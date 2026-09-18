import io
import wave
from decimal import Decimal

import httpx
import pytest
from modurouter import speech
from modurouter.config import Settings
from modurouter.errors import AppError
from modurouter.models import Base, QuotaBucket, RuntimeLock, RuntimeSettings, SpeechRequest, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def wav(seconds=1, rate=16000):
    data = io.BytesIO()
    with wave.open(data, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b"\0\0" * int(rate * seconds))
    return data.getvalue()


def test_audio_duration_and_format_are_verified():
    assert speech.validate_audio(wav(600)) == 600
    for data in (wav(601), wav(0.1), wav(1, 8000), wav()[:-10], b"not audio"):
        with pytest.raises(AppError):
            speech.validate_audio(data)


def test_usage_is_not_assumed_free():
    assert speech.transcription_cost({}) is None
    assert speech.transcription_cost({"output_tokens": 5, "input_token_details": {"audio_tokens": -1, "text_tokens": 0}}) is None
    assert speech.transcription_cost({"output_tokens": 20, "input_token_details": {"audio_tokens": 100, "text_tokens": 0}}) == Decimal("0.000225")


@pytest.mark.parametrize("outcome", ["success", "long_success", "rejected", "timeout", "over_budget"])
async def test_transcription_billing_and_request(outcome, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[User.__table__, RuntimeLock.__table__, QuotaBucket.__table__, SpeechRequest.__table__, RuntimeSettings.__table__]))
    async with factory.begin() as db:
        db.add(User(id="test-user", google_sub="guest:test", email="", display_name="test"))
        db.add(RuntimeLock(name="admission"))
    settings = Settings(_env_file=None, openai_api_key="test-only", user_daily_budget_usd=0 if outcome == "over_budget" else 1)
    monkeypatch.setattr(speech, "get_settings", lambda: settings)
    monkeypatch.setattr(speech, "Session", factory)
    calls = []

    def reply(request):
        calls.append(request)
        assert request.url == "https://api.openai.com/v1/audio/transcriptions"
        assert request.headers["authorization"] == "Bearer test-only"
        assert b"gpt-4o-mini-transcribe" in request.content
        if outcome == "timeout":
            raise httpx.ReadTimeout("synthetic")
        if outcome == "rejected":
            return httpx.Response(429)
        return httpx.Response(200, json={"text": "안녕하세요", "usage": {"output_tokens": 20, "input_token_details": {"audio_tokens": 100, "text_tokens": 0}}})

    original = httpx.AsyncClient
    monkeypatch.setattr(speech.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(reply), **kwargs))

    class Request:
        async def stream(self):
            yield wav(241 if outcome == "long_success" else 1)

    async with factory() as db:
        user = await db.get(User, "test-user")
        if outcome in ("success", "long_success"):
            result = await speech.transcribe(Request(), user, db)
            assert result["text"] == ("안녕하세요 안녕하세요 안녕하세요" if outcome == "long_success" else "안녕하세요")
        else:
            with pytest.raises(AppError):
                await speech.transcribe(Request(), user, db)
    async with factory() as db:
        rows = (await db.scalars(select(QuotaBucket))).all()
        operations = (await db.scalars(select(SpeechRequest))).all()
        if outcome == "over_budget":
            assert not calls and not operations
        else:
            assert len(calls) == (3 if outcome == "long_success" else 1) and len(operations) == 1
            assert {r.scope for r in rows} == {"platform", "user", "guest"}
            for row in rows:
                assert row.request_count == 1
                assert row.reserved_usd == (speech.RESERVATION if outcome == "timeout" else 0)
                assert row.spent_usd == (Decimal("0.000675") if outcome == "long_success" else Decimal("0.000225") if outcome == "success" else 0)
    await engine.dispose()


def test_ten_minute_recording_is_split_without_dropping_frames():
    parts = list(speech.audio_parts(wav(600)))
    assert len(parts) == 5
    assert sum(speech.validate_audio(part) for part in parts) == 600
    assert all(speech.validate_audio(part) == 120 for part in parts)

@pytest.mark.parametrize('identity,request_count,allowed', [
    ('guest:limited', 2, False), ('member', 2, True), ('admin:operator', 100, True),
])
async def test_speech_uses_account_specific_request_limits(database, monkeypatch, identity, request_count, allowed):
    from modurouter.billing import quota_day
    settings = Settings(_env_file=None, openai_api_key='test', guest_daily_request_limit=2,
                        user_daily_request_limit=3, user_daily_budget_usd=1)
    monkeypatch.setattr(speech, 'get_settings', lambda: settings)
    monkeypatch.setattr(speech, 'Session', database)
    async with database.begin() as db:
        user = User(google_sub=identity, email='', display_name='test')
        db.add(user)
        await db.flush()
        identifier = user.id
        db.add(QuotaBucket(scope='user',scope_id=identifier,quota_date=quota_day(),request_count=request_count,
                           reserved_usd=0,spent_usd=0,limit_usd=1))
    calls = []
    def reply(request):
        calls.append(request)
        return httpx.Response(200,json={'text':'확인','usage':{'output_tokens':1,'input_token_details':{'audio_tokens':10,'text_tokens':0}}})
    original = httpx.AsyncClient
    monkeypatch.setattr(speech.httpx,'AsyncClient',lambda **kwargs: original(transport=httpx.MockTransport(reply),**kwargs))
    class Request:
        async def stream(self):
            yield wav()
    async with database() as db:
        user = await db.get(User,identifier)
        if allowed:
            assert (await speech.transcribe(Request(),user,db))['text'] == '확인'
        else:
            with pytest.raises(AppError) as error:
                await speech.transcribe(Request(),user,db)
            assert error.value.code == 'REQUEST_LIMIT'
    assert bool(calls) == allowed


async def test_speech_obeys_runtime_provider_disable(database, monkeypatch):
    from modurouter.runtime_config import RoutingPolicy
    settings = Settings(_env_file=None,openai_api_key='test')
    policy = RoutingPolicy.from_settings(settings).model_copy(update={'enabled_providers':[]})
    async with database.begin() as db:
        user = User(google_sub='member',email='',display_name='test')
        db.add(user)
        db.add(RuntimeSettings(key='routing',values=policy.model_dump(mode='json'),revision=1))
        await db.flush()
        identifier = user.id
    monkeypatch.setattr(speech,'get_settings',lambda:settings)
    async with database() as db:
        with pytest.raises(AppError) as error:
            await speech.transcribe(None,await db.get(User,identifier),db)
        assert error.value.code == 'STT_UNAVAILABLE'
