import base64
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio
from authlib.integrations.starlette_client import OAuth
from fastapi.responses import RedirectResponse
from joserfc import jwt
from joserfc.jwk import generate_key
from modurouter.auth import COOKIE, csrf_token, digest
from modurouter.config import get_settings
from modurouter.db import get_db, utcnow
from modurouter.main import app
from modurouter.models import Conversation, LoginSession, User
from pydantic import SecretStr


@pytest.mark.parametrize("value", [{}, None, ["invalid", "id"], ["2026-01-01", {}],
                                    ["2026-01-01T00:00:00+00:00", "id"]])
async def test_invalid_cursor_is_a_client_error(identities, value):
    cursor = base64.urlsafe_b64encode(json.dumps(value).encode()).decode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 cookies={COOKIE: "owner-token"}) as client:
        response = await client.get("/v1/conversations", params={"cursor": cursor})
        assert response.status_code == 422
        assert response.json()["code"] == "CURSOR_INVALID"


async def test_google_callback_uses_configured_api_origin(monkeypatch):
    from modurouter import auth

    monkeypatch.setattr(auth.settings, "google_client_id", "test-client")
    monkeypatch.setattr(auth.settings, "google_client_secret", SecretStr("test-secret"))
    monkeypatch.setattr(auth.settings, "api_public_url", "https://api.example.test")
    observed = {}

    async def authorize_redirect(request, redirect_uri, nonce):
        observed["redirect_uri"] = redirect_uri
        observed["nonce"] = nonce
        return RedirectResponse("https://accounts.google.com/")

    monkeypatch.setattr(auth.oauth.google, "authorize_redirect", authorize_redirect)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 follow_redirects=False) as client:
        response = await client.get("/auth/google/start")
    assert response.status_code == 307
    assert observed["redirect_uri"] == "https://api.example.test/auth/google/callback"
    assert len(observed["nonce"]) >= 32


async def test_browser_origin_has_credentialed_api_preflight():
    origin = get_settings().web_origin
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options("/v1/me", headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-csrf-token, content-type",
        })
        assert response.status_code == 200
        assert response.headers["Access-Control-Allow-Origin"] == origin
        assert response.headers["Access-Control-Allow-Credentials"] == "true"
        denied = await client.options("/v1/me", headers={
            "Origin": "https://untrusted.example.test",
            "Access-Control-Request-Method": "POST",
        })
        assert "Access-Control-Allow-Origin" not in denied.headers


async def test_google_oidc_start_has_state_nonce_pkce_and_rejects_bad_state(monkeypatch):
    from modurouter import auth

    monkeypatch.setattr(auth.settings, "google_client_id", "test-client")
    monkeypatch.setattr(auth.settings, "google_client_secret", SecretStr("test-secret"))
    oauth = OAuth()
    oauth.register("google", client_id="test-client", client_secret="test-secret",
                   authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                   access_token_url="https://oauth2.googleapis.com/token",
                   client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"})
    monkeypatch.setattr(auth, "oauth", oauth)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 follow_redirects=False) as client:
        start = await client.get("/auth/google/start")
        assert start.status_code == 302
        query = parse_qs(urlsplit(start.headers["location"]).query)
        assert query["redirect_uri"] == [get_settings().api_public_url + "/auth/google/callback"]
        assert query["scope"] == ["openid email profile"]
        assert query["state"][0] and query["nonce"][0]
        assert query["code_challenge_method"] == ["S256"]
        assert query["code_challenge"][0]
        assert "modurouter_oauth=" in start.headers["set-cookie"]
        failed = await client.get("/auth/google/callback?code=fake&state=wrong")
        assert failed.status_code == 303
        assert failed.headers["location"] == get_settings().web_origin + "/?auth_error=1"


async def test_google_signed_callback_issues_host_only_session(identities, monkeypatch):
    import time

    from modurouter import auth

    monkeypatch.setattr(auth.settings, "google_client_id", "test-client")
    monkeypatch.setattr(auth.settings, "google_client_secret", SecretStr("test-secret"))
    key = generate_key("RSA", 2048, auto_kid=True)
    oauth = OAuth()
    oauth.register("google", client_id="test-client", client_secret="test-secret",
                   authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                   access_token_url="https://oauth2.googleapis.com/token",
                   client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"})
    oauth.google.server_metadata.update({"issuer": "https://accounts.google.com",
                                         "id_token_signing_alg_values_supported": ["RS256"],
                                         "jwks": {"keys": [key.as_dict()]}})
    monkeypatch.setattr(auth, "oauth", oauth)
    token_value = None
    exchanged = {}

    async def fetch_access_token(**kwargs):
        exchanged.update(kwargs)
        return {"id_token": token_value, "access_token": "test-access"}

    monkeypatch.setattr(oauth.google, "fetch_access_token", fetch_access_token)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 follow_redirects=False) as client:
        start = await client.get("/auth/google/start")
        query = parse_qs(urlsplit(start.headers["location"]).query)
        now = int(time.time())
        token_value = jwt.encode({"alg": "RS256", "kid": key.kid},
                                 {"iss": "https://accounts.google.com", "sub": "verified-google-user",
                                  "aud": "test-client", "exp": now + 600, "iat": now,
                                  "nonce": query["nonce"][0], "email": "verified@example.test",
                                  "email_verified": True, "name": "검증된 사용자"}, key)
        callback = await client.get("/auth/google/callback",
                                    params={"code": "test-code", "state": query["state"][0]})
        assert callback.status_code == 303
        assert callback.headers["location"] == get_settings().web_origin
        assert "modurouter_session=" in callback.headers["set-cookie"]
        assert "domain=" not in callback.headers["set-cookie"].lower()
        assert "httponly" in callback.headers["set-cookie"].lower()
        assert "code_verifier" in exchanged
        assert exchanged["redirect_uri"] == get_settings().api_public_url + "/auth/google/callback"
        me = await client.get("/v1/me")
        assert me.status_code == 200
        assert me.json()["display_name"] == "검증된 사용자"

    rogue = generate_key("RSA", 2048)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 follow_redirects=False) as client:
        start = await client.get("/auth/google/start")
        query = parse_qs(urlsplit(start.headers["location"]).query)
        token_value = jwt.encode({"alg": "RS256", "kid": key.kid},
                                 {"iss": "https://accounts.google.com", "sub": "forged-google-user",
                                  "aud": "test-client", "exp": now + 600, "iat": now,
                                  "nonce": query["nonce"][0], "email_verified": True}, rogue)
        failed = await client.get("/auth/google/callback",
                                  params={"code": "test-code", "state": query["state"][0]})
        assert failed.status_code == 303
        assert failed.headers["location"] == get_settings().web_origin + "/?auth_error=1"
        assert (await client.get("/v1/me")).status_code == 401


@pytest_asyncio.fixture
async def identities(database):
    async with database.begin() as db:
        owner = User(google_sub="owner", email="owner@example.test", display_name="소유자")
        stranger = User(google_sub="stranger", email="stranger@example.test", display_name="다른 사용자")
        db.add_all([owner, stranger])
        await db.flush()
        conversation = Conversation(user_id=owner.id, title="비공개 대화")
        db.add(conversation)
        for user, token in ((owner, "owner-token"), (stranger, "stranger-token")):
            db.add(LoginSession(user_id=user.id, token_hash=digest(token), csrf_hash=digest(csrf_token(token)),
                                expires_at=utcnow() + timedelta(days=1)))
        await db.flush()
        identifier = conversation.id
    async def override():
        async with database() as db:
            yield db
    app.dependency_overrides[get_db] = override
    yield identifier
    app.dependency_overrides.clear()


async def test_ownership_and_csrf(identities):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set(COOKIE, "stranger-token")
        response = await client.get(f"/v1/conversations/{identities}")
        assert response.status_code == 404
        client.cookies.set(COOKIE, "owner-token")
        assert (await client.get(f"/v1/conversations/{identities}")).status_code == 200
        assert (await client.delete(f"/v1/conversations/{identities}")).status_code == 403
        headers = {"Origin": get_settings().web_origin, "X-CSRF-Token": csrf_token("owner-token")}
        assert (await client.delete(f"/v1/conversations/{identities}", headers=headers)).status_code == 200
        assert (await client.get(f"/v1/conversations/{identities}")).status_code == 404


async def test_logout_revokes_session(identities):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set(COOKIE, "owner-token")
        response = await client.post("/auth/logout", headers={"Origin": get_settings().web_origin,
            "X-CSRF-Token": csrf_token("owner-token")})
        assert response.status_code == 200
        client.cookies.set(COOKIE, "owner-token")
        assert (await client.get("/v1/me")).status_code == 401


async def test_guest_session_features_isolation_and_reuse(identities, monkeypatch, tmp_path):
    from modurouter import files
    monkeypatch.setattr(files.settings, "upload_directory", tmp_path)
    origin = {"Origin": get_settings().web_origin}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/v1/me")).status_code == 401
        assert (await client.post("/auth/guest")).status_code == 403
        assert (await client.post("/auth/guest", headers={"Origin": "https://evil.test"})).status_code == 403
        started = await client.post("/auth/guest", headers=origin)
        assert started.status_code == 200
        cookie = started.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie
        assert "max-age=" not in cookie and "expires=" not in cookie
        user = (await client.get("/v1/me")).json()
        assert user["guest"] is True
        headers = {**origin, "X-CSRF-Token": user["csrf_token"]}
        assert (await client.post("/v1/conversations", json={}, headers=origin)).status_code == 403
        conversation = await client.post("/v1/conversations", json={"title": "비로그인 대화"}, headers=headers)
        assert conversation.status_code == 200
        cid = conversation.json()["id"]
        assert (await client.get("/v1/usage")).json()["shared_guest_quota"] is True
        assert (await client.get(f"/v1/conversations/{identities}")).status_code == 404
        uploaded = await client.post("/v1/attachments", data={"conversation_id": cid},
            files={"file": ("note.txt", b"guest attachment", "text/plain")}, headers=headers)
        assert uploaded.status_code == 200
        previous = client.cookies.get(COOKIE)
        assert (await client.post("/auth/guest", headers=origin)).status_code == 200
        assert client.cookies.get(COOKIE) == previous
        assert (await client.get("/v1/me")).json()["id"] == user["id"]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as other:
            await other.post("/auth/guest", headers=origin)
            assert (await other.get("/v1/me")).json()["id"] != user["id"]
            assert (await other.get(f"/v1/conversations/{cid}")).status_code == 404
            assert (await other.get(f"/v1/attachments/{uploaded.json()['id']}")).status_code == 404
        assert (await client.delete("/v1/me", headers=headers)).status_code == 200
        assert (await client.get("/v1/me")).status_code == 401
        await client.post("/auth/guest", headers=origin)
        assert (await client.get("/v1/me")).json()["id"] != user["id"]


async def test_guest_can_sign_in_as_admin_without_guest_downgrade(identities, admin_credentials):
    origin = {"Origin": get_settings().web_origin}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/auth/guest", headers=origin)
        previous = client.cookies.get(COOKIE)
        assert (await client.post("/auth/admin", json=admin_credentials, headers=origin)).status_code == 200
        member = (await client.get("/v1/me")).json()
        assert member["guest"] is False
        assert (await client.post("/auth/guest", headers=origin)).status_code == 200
        assert (await client.get("/v1/me")).json()["id"] == member["id"]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                    cookies={COOKIE: previous}) as old:
            assert (await old.get("/v1/me")).status_code == 401


async def test_expired_session_denied(identities, database):
    from sqlalchemy import select
    async with database.begin() as db:
        row = await db.scalar(select(LoginSession).where(LoginSession.token_hash == digest('owner-token')))
        row.expires_at = utcnow() - timedelta(seconds=1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
        cookies={COOKIE: 'owner-token'}) as client:
        assert (await client.get('/v1/me')).status_code == 401


@pytest.fixture
def admin_credentials(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_username", "test-admin")
    monkeypatch.setattr(settings, "admin_password", SecretStr("test-password"))
    return {"username": "test-admin", "password": "test-password"}


async def test_admin_login_has_member_features_and_persistent_identity(identities, admin_credentials, monkeypatch, tmp_path):
    from modurouter import files
    monkeypatch.setattr(files.settings, "upload_directory", tmp_path)
    origin = {"Origin": get_settings().web_origin}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        login = await client.post("/auth/admin", json=admin_credentials, headers=origin)
        assert login.status_code == 200
        cookie = login.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie and "max-age=" in cookie
        user = (await client.get("/v1/me")).json()
        assert not user["guest"] and user["display_name"] == admin_credentials["username"]
        headers = {**origin, "X-CSRF-Token": user["csrf_token"]}
        assert (await client.post("/v1/conversations", json={})).status_code == 403
        conversation = await client.post("/v1/conversations", json={"title": "관리자 회원 대화"}, headers=headers)
        assert conversation.status_code == 200
        cid = conversation.json()["id"]
        assert (await client.get("/v1/usage")).json()["shared_guest_quota"] is False
        assert (await client.get("/v1/models/status")).status_code == 200
        assert (await client.get(f"/v1/conversations/{identities}")).status_code == 404
        uploaded = await client.post("/v1/attachments", data={"conversation_id": cid},
            files={"file": ("note.txt", b"member attachment", "text/plain")}, headers=headers)
        assert uploaded.status_code == 200
        previous = client.cookies.get(COOKIE)
        assert (await client.post("/auth/admin", json=admin_credentials, headers=origin)).status_code == 200
        assert client.cookies.get(COOKIE) != previous
        user_again = (await client.get("/v1/me")).json()
        assert user_again["id"] == user["id"]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                    cookies={COOKIE: previous}) as old:
            assert (await old.get("/v1/me")).status_code == 401
        assert (await client.get(f"/v1/conversations/{cid}")).status_code == 200
        assert (await client.post("/auth/logout", headers={**origin, "X-CSRF-Token": user_again["csrf_token"]})).status_code == 200
        assert (await client.get("/v1/me")).status_code == 401
        assert (await client.post("/auth/admin", json=admin_credentials, headers=origin)).status_code == 200
        assert (await client.get("/v1/me")).json()["id"] == user["id"]


async def test_admin_login_validation_origin_and_throttling(identities, database, admin_credentials):
    from modurouter.models import LoginThrottle
    from sqlalchemy import select
    origin = {"Origin": get_settings().web_origin}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/auth/admin", json=admin_credentials)).status_code == 403
        assert (await client.post("/auth/admin", json=admin_credentials, headers={"Origin":"https://evil.test"})).status_code == 403
        assert (await client.post("/auth/admin", json={}, headers=origin)).status_code == 422
        wrong = {**admin_credentials, "password": "wrong-password"}
        for _ in range(10):
            result = await client.post("/auth/admin", json=wrong, headers=origin)
            assert result.status_code == 401 and "set-cookie" not in result.headers
        assert (await client.post("/auth/admin", json=wrong, headers=origin)).status_code == 429
        assert (await client.get("/v1/me")).status_code == 401
        assert (await client.post("/auth/admin", json=admin_credentials, headers=origin)).status_code == 429
        assert (await client.post("/auth/admin", json=admin_credentials,
            headers={**origin, "X-Forwarded-For": "203.0.113.99"})).status_code == 429
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("203.0.113.2", 1234)),
                                     base_url="http://test") as other:
            assert (await other.post("/auth/admin", json=admin_credentials, headers=origin)).status_code == 200
        async with database.begin() as db:
            (await db.scalar(select(LoginThrottle))).window_started_at = utcnow() - timedelta(minutes=6)
        assert (await client.post("/auth/admin", json=wrong, headers=origin)).status_code == 401
        assert (await client.post("/auth/admin", json=admin_credentials, headers=origin)).status_code == 200


async def test_admin_unconfigured_fails_closed(identities, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_password", SecretStr(""))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/auth/admin", json={"username":"someone", "password":"some-password"},
                                     headers={"Origin":get_settings().web_origin})
        assert response.status_code == 503


async def test_account_deletion_erases_content_and_revokes(identities, database):
    from modurouter.models import Attachment
    from sqlalchemy import select
    async with database.begin() as db:
        owner = await db.scalar(select(User).where(User.google_sub == 'owner'))
        identifier = owner.id
        db.add(Attachment(user_id=identifier, conversation_id=identities, filename='private.txt',
            storage_key=f'{identifier}/example', mime_type='text/plain', size_bytes=7,
            extraction_status='ready', extracted_text='private', expires_at=utcnow()+timedelta(days=1)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
        cookies={COOKIE: 'owner-token'}) as client:
        response = await client.delete('/v1/me', headers={'Origin':get_settings().web_origin,
            'X-CSRF-Token':csrf_token('owner-token')})
        assert response.status_code == 200
        client.cookies.set(COOKIE, 'owner-token')
        assert (await client.get('/v1/me')).status_code == 401
    async with database() as db:
        owner = await db.get(User, identifier)
        assert owner.email == '' and owner.google_sub.startswith('deleted:') and owner.deleted_at
        assert (await db.get(Conversation, identities)).deleted_at
        attachment = await db.scalar(select(Attachment))
        assert attachment.extracted_text is None and attachment.extraction_status == 'expired'


async def test_upload_mime_size_and_owner_enforced(identities, database, monkeypatch, tmp_path):
    from modurouter import files
    monkeypatch.setattr(files.settings, 'upload_directory', tmp_path)
    monkeypatch.setattr(files.settings, 'max_upload_bytes', 128)
    headers = {'Origin':get_settings().web_origin,'X-CSRF-Token':csrf_token('owner-token')}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
        cookies={COOKIE:'owner-token'}, headers=headers) as client:
        mismatch = await client.post('/v1/attachments', data={'conversation_id':identities},
            files={'file':('fake.png',b'plain text instead of an image','image/png')})
        assert mismatch.status_code == 422 and mismatch.json()['code'] == 'FILE_TYPE_MISMATCH'
        oversized = await client.post('/v1/attachments', data={'conversation_id':identities},
            files={'file':('big.txt',b'a'*129,'text/plain')})
        assert oversized.status_code == 413
        uploaded = await client.post('/v1/attachments', data={'conversation_id':identities},
            files={'file':('note.txt',b'hello library','text/plain')})
        assert uploaded.status_code == 200
        aid = uploaded.json()['id']
        client.cookies.set(COOKIE, 'stranger-token')
        assert (await client.get('/v1/attachments/'+aid)).status_code == 404
        client.cookies.set(COOKIE, 'owner-token')
        assert (await client.delete('/v1/attachments/'+aid)).status_code == 200
        assert (await client.get('/v1/attachments/'+aid)).json()['status'] == 'expired'


async def test_deleted_guest_late_settlement_releases_shared_reservation(database):
    from decimal import Decimal

    from modurouter.billing import admission_lock, admit_run, mark_pending, reserve, settle
    from modurouter.models import QuotaBucket, Run
    from sqlalchemy import select

    settings = get_settings()
    async with database.begin() as db:
        user = User(google_sub="guest:historical", email="", display_name="게스트")
        db.add(user)
        await db.flush()
        conversation = Conversation(user_id=user.id, title="과거 대화")
        db.add(conversation)
        await db.flush()
        await admission_lock(db)
        day = await admit_run(db, user.id, settings)
        run = Run(user_id=user.id, conversation_id=conversation.id, idempotency_key="pending-delete",
                  request_hash="0" * 64, quota_date=day, status="accepted")
        db.add(run)
        await db.flush()
        uid, rid = user.id, run.id
    async with database() as db:
        attempt = await reserve(db, rid, "test/model", Decimal(".01"), settings)
        aid = attempt.id
        await mark_pending(db, aid, "gen-deleted-guest")
    async with database.begin() as db:
        (await db.get(Run, rid)).status = "cancelled"
        user = await db.get(User, uid)
        user.google_sub = "deleted:guest:historical"
        user.deleted_at = utcnow()
    async with database() as db:
        await settle(db, aid, Decimal(".005"), 20, 10, "gen-deleted-guest", settings)
        shared = await db.scalar(select(QuotaBucket).where(QuotaBucket.scope == "guest"))
        assert shared.reserved_usd == 0 and shared.spent_usd == Decimal(".005")


@pytest.mark.parametrize("content", [b'{"question":"summary"}', b'<html><body>A textual document</body></html>'])
async def test_structured_txt_is_accepted_as_inert_text(identities, monkeypatch, tmp_path, content):
    from modurouter import files
    monkeypatch.setattr(files.settings, "upload_directory", tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
            cookies={COOKIE: "owner-token"}, headers={"Origin": get_settings().web_origin,
            "X-CSRF-Token": csrf_token("owner-token")}) as client:
        result = await client.post("/v1/attachments", data={"conversation_id": identities},
            files={"file": ("document.txt", content, "text/plain")})
        assert result.status_code == 200
