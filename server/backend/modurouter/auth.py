import hashlib
import hmac
import secrets
from datetime import timedelta

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from joserfc.errors import JoseError
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .billing import admission_lock
from .config import get_settings
from .db import get_db, utcnow
from .errors import AppError
from .models import LoginSession, LoginThrottle, User

router = APIRouter()
settings = get_settings()
COOKIE = "modurouter_session"
oauth = OAuth()
oauth.register("google", client_id=settings.google_client_id,
    client_secret=settings.google_client_secret.get_secret_value(),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"})


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(token: str) -> str:
    return hmac.new(settings.session_secret.get_secret_value().encode(),
                    ("csrf:" + token).encode(), hashlib.sha256).hexdigest()


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise AppError("AUTH_REQUIRED", "로그인이 필요합니다.", 401)
    session = await db.scalar(select(LoginSession).where(LoginSession.token_hash == digest(token),
        LoginSession.revoked_at.is_(None), LoginSession.expires_at > utcnow()))
    user = await db.get(User, session.user_id) if session else None
    if not user or user.deleted_at:
        raise AppError("SESSION_EXPIRED", "로그인이 만료되었습니다. 다시 로그인해 주세요.", 401)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        supplied = request.headers.get("X-CSRF-Token", "")
        if request.headers.get("Origin") != settings.web_origin or not supplied or not hmac.compare_digest(digest(supplied), session.csrf_hash):
            raise AppError("CSRF_INVALID", "요청을 확인할 수 없습니다. 화면을 새로고침해 주세요.", 403)
    request.state.login_session = session
    request.state.csrf = csrf_token(token)
    return user


def is_admin(user: User) -> bool:
    return settings.admin_configured and user.google_sub == "admin:" + settings.admin_username


async def current_admin(user: User = Depends(current_user)) -> User:
    if not is_admin(user):
        raise AppError("ADMIN_REQUIRED", "관리자 권한이 필요합니다.", 403)
    return user


@router.get("/auth/google/start")
async def google_start(request: Request):
    if not settings.google_configured:
        raise AppError("AUTH_NOT_CONFIGURED", "Google 로그인을 준비 중입니다.", 503)
    return await oauth.google.authorize_redirect(request,
        settings.api_public_url + "/auth/google/callback", nonce=secrets.token_urlsafe(32))


@router.get("/auth/google/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    if not settings.google_configured:
        raise AppError("AUTH_NOT_CONFIGURED", "Google 로그인을 준비 중입니다.", 503)
    try:
        token = await oauth.google.authorize_access_token(request)
        info = token["userinfo"]
        if not info.get("sub") or not info.get("email_verified"):
            raise ValueError("Unverified identity")
    except (OAuthError, JoseError, ValueError, KeyError):
        request.session.clear()
        return RedirectResponse(settings.web_origin + "/?auth_error=1", status_code=303)
    user = await db.scalar(select(User).where(User.google_sub == info["sub"]))
    if user is None:
        user = User(google_sub=info["sub"], email=info.get("email", ""),
                    display_name=info.get("name", "사용자")[:255])
        db.add(user)
        await db.flush()
    if user.deleted_at:
        request.session.clear()
        return RedirectResponse(settings.web_origin + "/?auth_error=account_deleted", status_code=303)
    response = RedirectResponse(settings.web_origin, status_code=303)
    return await start_session(request, db, user, response)


async def start_session(request: Request, db: AsyncSession, user: User, response: Response):
    previous = request.cookies.get(COOKIE)
    if previous:
        session = await db.scalar(select(LoginSession).where(LoginSession.token_hash == digest(previous)))
        if session:
            session.revoked_at = utcnow()
    raw_session = secrets.token_urlsafe(48)
    db.add(LoginSession(user_id=user.id, token_hash=digest(raw_session),
        csrf_hash=digest(csrf_token(raw_session)), expires_at=utcnow() + timedelta(days=settings.session_days)))
    await db.commit()
    request.session.clear()
    response.set_cookie(COOKIE, raw_session,
        max_age=None if user.google_sub.startswith("guest:") else settings.session_days * 86400,
        httponly=True, secure=settings.environment == "production", samesite="lax", path="/")
    return response


@router.post("/auth/guest")
async def guest_start(request: Request, db: AsyncSession = Depends(get_db)):
    if request.headers.get("Origin") != settings.web_origin:
        raise AppError("CSRF_INVALID", "요청을 확인할 수 없습니다.", 403)
    previous = request.cookies.get(COOKIE)
    if previous:
        session = await db.scalar(select(LoginSession).where(
            LoginSession.token_hash == digest(previous), LoginSession.revoked_at.is_(None),
            LoginSession.expires_at > utcnow()))
        user = await db.get(User, session.user_id) if session else None
        if user and not user.deleted_at:
            return {"started": True}
    user = User(google_sub="guest:" + secrets.token_urlsafe(32), email="", display_name="비로그인 사용자")
    db.add(user)
    await db.flush()
    return await start_session(request, db, user, JSONResponse({"started": True}))


@router.get("/v1/me")
async def me(request: Request, user: User = Depends(current_user)):
    return {"id": user.id, "display_name": user.display_name, "email": user.email,
            "guest": user.google_sub.startswith("guest:"), "admin": is_admin(user),
            "csrf_token": request.state.csrf}


class AdminCredentials(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: SecretStr = Field(min_length=1, max_length=1024)


@router.post("/auth/admin")
async def admin_start(credentials: AdminCredentials, request: Request, db: AsyncSession = Depends(get_db)):
    if request.headers.get("Origin") != settings.web_origin:
        raise AppError("CSRF_INVALID", "요청을 확인할 수 없습니다.", 403)
    if not settings.admin_configured:
        raise AppError("AUTH_NOT_CONFIGURED", "관리자 로그인을 준비 중입니다.", 503)
    # Use the server-resolved peer, never raw forwarding headers.
    throttle_id = digest("admin:" + (request.client.host if request.client else "unknown"))
    await admission_lock(db)
    now = utcnow()
    await db.execute(delete(LoginThrottle).where(LoginThrottle.window_started_at < now - timedelta(minutes=5)))
    throttle = await db.get(LoginThrottle, throttle_id)
    if throttle is not None and throttle.failures >= 10:
        raise AppError("LOGIN_RATE_LIMITED", "로그인 시도가 너무 많습니다. 5분 후 다시 시도해 주세요.", 429)
    valid_username = hmac.compare_digest(digest(credentials.username), digest(settings.admin_username))
    valid_password = hmac.compare_digest(digest(credentials.password.get_secret_value()),
                                         digest(settings.admin_password.get_secret_value()))
    if not (valid_username and valid_password):
        if throttle is None:
            throttle = LoginThrottle(id=throttle_id, failures=0, window_started_at=now)
            db.add(throttle)
        throttle.failures += 1
        await db.commit()
        raise AppError("LOGIN_INVALID", "아이디 또는 비밀번호가 올바르지 않습니다.", 401)
    if throttle is not None:
        await db.delete(throttle)
    subject = "admin:" + settings.admin_username
    user = await db.scalar(select(User).where(User.google_sub == subject))
    if user is None:
        user = User(google_sub=subject, email="", display_name=settings.admin_username)
        db.add(user)
        await db.flush()
    if user.deleted_at:
        raise AppError("ACCOUNT_DELETED", "삭제한 계정입니다.", 403)
    return await start_session(request, db, user, JSONResponse({"started": True}))


@router.post("/auth/logout")
async def logout(request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    request.state.login_session.revoked_at = utcnow()
    await db.commit()
    response = JSONResponse({"logged_out": True})
    response.delete_cookie(COOKIE, path="/", secure=settings.environment == "production", httponly=True, samesite="lax")
    return response
