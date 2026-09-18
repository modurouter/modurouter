"""Korean dictation through OpenAI, with existing shared daily budgets."""
import asyncio
import io
import wave
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import current_user
from .billing import admission_lock, buckets, daily_request_limit, quota_day
from .config import get_settings
from .db import Session, get_db
from .errors import AppError
from .models import SpeechRequest, User
from .runtime_config import effective_settings

router = APIRouter(prefix="/v1/audio")
MODEL = "gpt-4o-mini-transcribe"
MAX_SECONDS = 600
MAX_BYTES = MAX_SECONDS * 16000 * 2 + 44
CHUNK_SECONDS = 120
RESERVATION = Decimal("0.03")  # Conservative hold, not a quoted per-minute price.


def validate_audio(data: bytes) -> float:
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
                raise ValueError
            frames = audio.getnframes()
            duration = frames / 16000
            if not 0.3 <= duration <= MAX_SECONDS or len(audio.readframes(frames)) != frames * 2:
                raise ValueError
            return duration
    except (wave.Error, EOFError, ValueError):
        raise AppError("AUDIO_INVALID", "10분 이내의 음성을 다시 녹음해 주세요.") from None


def audio_parts(data: bytes):
    """Bound model output length without interrupting the user's recording."""
    with wave.open(io.BytesIO(data), "rb") as source:
        while frames := source.readframes(CHUNK_SECONDS * 16000):
            target = io.BytesIO()
            with wave.open(target, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(frames)
            yield target.getvalue()


def transcription_cost(usage: dict) -> Decimal | None:
    # Official mini-transcribe token tariffs, reviewed 2026-09-18.
    # https://developers.openai.com/api/docs/models/gpt-4o-mini-transcribe
    details = usage.get("input_token_details") or {}
    audio, text, output = details.get("audio_tokens"), details.get("text_tokens"), usage.get("output_tokens")
    if any(type(v) is not int or v < 0 for v in (audio, text, output)):
        return None
    return (Decimal(audio) * Decimal("1.25") + Decimal(text) * Decimal("1.25") + Decimal(output) * 5) / 1_000_000


async def settle_speech(identifier: str, cost: Decimal | None):
    if cost is None:
        return  # Unknown billing remains reserved, including uncertain network failures.
    settings = get_settings()
    async with Session.begin() as db:
        await admission_lock(db)
        settings = await effective_settings(db, settings)
        row = await db.get(SpeechRequest, identifier)
        if row.status != "pending":
            return
        for bucket in await buckets(db, row.user_id, row.quota_date, settings):
            bucket.reserved_usd -= row.reserved_usd
            bucket.spent_usd += cost
        row.cost_usd, row.status = cost, "settled"
        if cost > row.reserved_usd:
            (await db.get(User, row.user_id)).paid_blocked = True


@router.post("/transcriptions")
async def transcribe(request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    settings = await effective_settings(db, get_settings())
    if "openai" not in settings.configured_providers:
        raise AppError("STT_UNAVAILABLE", "음성 인식 서버 설정이 필요합니다.", 503)
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > MAX_BYTES:
            raise AppError("AUDIO_TOO_LARGE", "음성은 한 번에 10분까지 입력할 수 있어요.", 413)
    data = bytes(chunks)
    validate_audio(data)
    user_id = user.id
    await db.commit()
    async with db.begin():
        await admission_lock(db)
        await db.refresh(user)
        if user.paid_blocked or user.deleted_at:
            raise AppError("BUDGET_REVIEW_REQUIRED", "사용 상태를 확인한 뒤 다시 시도해 주세요.", 429)
        day = quota_day()
        rows = await buckets(db, user_id, day, settings)
        request_limit = daily_request_limit(user, settings)
        if request_limit is not None and any(r.scope != "platform" and r.request_count >= request_limit for r in rows):
            raise AppError("REQUEST_LIMIT", "오늘의 사용 횟수에 도달했어요.", 429)
        if any(r.limit_usd is not None and r.spent_usd + r.reserved_usd + RESERVATION > r.limit_usd for r in rows):
            raise AppError("BUDGET_EXCEEDED", "오늘의 사용 한도에 도달했어요.", 429)
        for row in rows:
            row.request_count += 1
            row.reserved_usd += RESERVATION
        operation = SpeechRequest(user_id=user_id, quota_date=day, reserved_usd=RESERVATION)
        db.add(operation)
        await db.flush()
        identifier = operation.id
    cost = Decimal(0)
    try:
        texts = []
        async with asyncio.timeout(300), httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as client:
            for part in audio_parts(data):
                # A request with an uncertain result keeps the entire reservation.
                known_cost = cost
                cost = None
                try:
                    response = await client.post("https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {settings.openai_api_key.get_secret_value()}"},
                        data={"model": MODEL, "language": "ko", "response_format": "json"},
                        files={"file": ("speech.wav", part, "audio/wav")})
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    cost = known_cost
                    raise
                if response.status_code >= 400:
                    cost = known_cost
                    raise AppError("STT_FAILED", "음성을 인식하지 못했어요. 잠시 후 다시 시도해 주세요.", 503)
                result = response.json()
                part_cost = transcription_cost(result.get("usage") or {})
                cost = known_cost + part_cost if known_cost is not None and part_cost is not None else None
                if not isinstance(result.get("text"), str):
                    raise AppError("STT_FAILED", "음성 인식 결과를 읽지 못했어요.", 503)
                texts.append(result["text"].strip())
        return {"text": " ".join(texts), "model": MODEL}
    except (httpx.ConnectError, httpx.ConnectTimeout):
        raise AppError("STT_UNAVAILABLE", "음성 인식 서버에 연결하지 못했어요.", 503) from None
    except (httpx.HTTPError, ValueError, TimeoutError):
        raise AppError("STT_FAILED", "음성 인식 연결이 끊겼어요. 잠시 후 다시 시도해 주세요.", 503) from None
    finally:
        settlement = asyncio.create_task(settle_speech(identifier, cost))
        try:
            await asyncio.shield(settlement)
        except asyncio.CancelledError:
            await settlement
            raise
