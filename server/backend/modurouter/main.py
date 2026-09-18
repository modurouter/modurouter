import logging
import secrets
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

from . import admin, auth, conversations, files, harness, speech
from .billing import ACTIVE, usage_summary
from .config import get_settings
from .db import Session, engine, get_db, utcnow
from .document_formats import FORMATS
from .errors import AppError
from .models import Attachment, Conversation, Job, LoginSession, Message, Run, User
from .router import RoutingPreference, candidates, model_catalog
from .router import model_status as provider_model_status
from .runtime_config import effective_settings

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("modurouter")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with Session.begin() as db:
        interrupted = list((await db.scalars(select(Run.id).where(Run.status.in_(ACTIVE)))).all())
        if interrupted:
            await db.execute(update(Run).where(Run.id.in_(interrupted)).values(
                status="interrupted", error_code="SERVER_RESTARTED", finished_at=utcnow()))
            await db.execute(update(Message).where(Message.run_id.in_(interrupted),
                Message.role == "assistant").values(status="interrupted"))
    yield
    await engine.dispose()


app = FastAPI(title="Modurouter API", version="0.1.0", lifespan=lifespan,
              docs_url=None if settings.environment == "production" else "/docs")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret.get_secret_value() or secrets.token_hex(32),
                   session_cookie="modurouter_oauth", max_age=600, same_site="lax",
                   https_only=settings.environment == "production")
app.add_middleware(CORSMiddleware, allow_origins=[settings.web_origin], allow_credentials=True,
                   allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"])


@app.middleware("http")
async def safe_headers(request: Request, call_next):
    started = time.monotonic()
    request_id = str(uuid4())
    request.state.request_id = request_id
    try:
        response = await call_next(request)
    except Exception as exc:
        # Tracebacks from DB drivers may contain SQL parameters, including user text.
        logger.error("request_failed request_id=%s exception=%s", request_id, type(exc).__name__)
        response = JSONResponse(AppError("SERVICE_UNAVAILABLE", "서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.", 503, True).payload(), status_code=503)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    logger.info("request_completed request_id=%s method=%s status=%s latency_ms=%s",
                request_id, request.method, response.status_code, int((time.monotonic() - started) * 1000))
    return response


@app.exception_handler(AppError)
async def app_error(request: Request, exc: AppError):
    return JSONResponse(exc.payload(), status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(AppError("INPUT_INVALID", "입력 내용을 확인해 주세요.").payload(), status_code=422)


@app.get("/health/live")
async def live():
    return {"status": "ok"}


@app.get("/health/ready")
async def ready(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        config = await effective_settings(db, settings)
        await candidates(db, config, 1, routing=RoutingPreference(**config.default_routing))
    except AppError as exc:
        return JSONResponse({"status": "not_ready", "code": exc.code}, status_code=503)
    except Exception as exc:
        logger.warning("readiness_failed exception=%s", type(exc).__name__)
        return JSONResponse({"status": "not_ready", "code": "DATABASE_UNAVAILABLE"}, status_code=503)
    return {"status": "ready"}


@app.get("/v1/config")
async def public_config(db: AsyncSession = Depends(get_db)):
    config = await effective_settings(db, settings)
    return {"google_login_available": settings.google_configured, "admin_login_available": settings.admin_configured, "max_attachment_bytes": settings.max_upload_bytes,
            "max_attachments": 3, "attachment_extensions": sorted(FORMATS), "search_default": "auto",
            "stt_available": "openai" in config.configured_providers,
            "stt_model": speech.MODEL, "stt_max_seconds": speech.MAX_SECONDS,
            "voice_notice": "녹음한 음성은 OpenAI로 전송되어 글로 변환됩니다. 한 번에 최대 10분입니다."}


@app.get("/v1/usage")
async def usage(user: User = Depends(auth.current_user), db: AsyncSession = Depends(get_db)):
    return await usage_summary(db, user.id, await effective_settings(db, settings))


@app.get("/v1/models")
async def available_models(user: User = Depends(auth.current_user), db: AsyncSession = Depends(get_db)):
    return await model_catalog(db, await effective_settings(db, settings))


@app.get("/v1/models/status")
async def model_status(user: User = Depends(auth.current_user), db: AsyncSession = Depends(get_db)):
    return await provider_model_status(db, await effective_settings(db, settings))


@app.delete("/v1/me")
async def delete_account(user: User = Depends(auth.current_user), db: AsyncSession = Depends(get_db)):
    await db.commit()
    await harness.admission_lock(db)
    rows = (await db.scalars(select(Conversation).where(Conversation.user_id == user.id,
        Conversation.deleted_at.is_(None)))).all()
    for row in rows:
        await conversations.erase_conversation(db, row)
    for session in (await db.scalars(select(LoginSession).where(LoginSession.user_id == user.id))).all():
        session.revoked_at = utcnow()
    for attachment in (await db.scalars(select(Attachment).where(Attachment.user_id == user.id))).all():
        attachment.extracted_text = None
        attachment.filename = "삭제한 파일"
        attachment.extraction_status = "expired"
        db.add(Job(type="delete_file", payload={"storage_key": attachment.storage_key}))
    user.google_sub = ("deleted:guest:" if user.google_sub.startswith("guest:") else "deleted:") + str(uuid4())
    user.email = ""
    user.display_name = "삭제한 계정"
    user.deleted_at = utcnow()
    await db.commit()
    response = JSONResponse({"deleted": True})
    response.delete_cookie(auth.COOKIE, path="/", secure=settings.environment == "production", httponly=True, samesite="lax")
    return response


app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(files.router)
app.include_router(harness.router)

app.include_router(speech.router)
