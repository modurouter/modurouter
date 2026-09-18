import asyncio
import json
import logging
import sys
import time
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import or_, select

from .billing import settle
from .config import get_settings
from .db import Session, utcnow
from .files import storage_path
from .models import Attachment, GenerationAttempt, Job, SyncState
from .providers import create_adapters, usage_cost
from .router import sync_models

settings = get_settings()
logger = logging.getLogger("modurouter.worker")


async def claim_job():
    async with Session.begin() as db:
        job = await db.scalar(select(Job).where(or_(Job.status == "queued",
            (Job.status == "running") & (Job.lease_until < utcnow()))).order_by(Job.created_at)
            .with_for_update(skip_locked=True).limit(1))
        if job is None:
            return None
        if job.attempts >= 3:
            job.status = "failed"
            logger.warning("job_exhausted job_id=%s kind=%s attempts=%s", job.id, job.type, job.attempts)
            if job.type == "extract":
                attachment = await db.get(Attachment, job.payload["attachment_id"])
                if attachment and attachment.extraction_status != "expired":
                    attachment.extraction_status = "failed"
                    attachment.error_code = "WORKER_INTERRUPTED"
            return None
        job.status = "running"
        job.attempts += 1
        job.lease_until = utcnow() + timedelta(seconds=90)
        return job.id, job.type, job.payload, job.created_at, job.attempts


async def process_extraction(identifier: str):
    async with Session.begin() as db:
        attachment = await db.get(Attachment, identifier, with_for_update=True)
        if not attachment or attachment.expires_at <= utcnow() or attachment.extraction_status == "expired":
            return
        attachment.extraction_status = "pending"
        key, mime = attachment.storage_key, attachment.mime_type
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "modurouter.extract",
        str(storage_path(key)), mime, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
        result = json.loads(stdout) if process.returncode == 0 else {"error": "EXTRACTION_FAILED"}
    except TimeoutError:
        process.kill()
        await process.wait()
        result = {"error": "EXTRACTION_TIMEOUT"}
    except asyncio.CancelledError:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    except (ValueError, UnicodeError):
        result = {"error": "EXTRACTION_FAILED"}
    async with Session.begin() as db:
        attachment = await db.get(Attachment, identifier, with_for_update=True)
        if not attachment or attachment.expires_at <= utcnow() or attachment.extraction_status == "expired":
            return
        attachment.extraction_status = "failed" if "error" in result else "ready"
        attachment.error_code = result.get("error")
        attachment.extracted_text = result.get("text")
        attachment.truncated = result.get("truncated", False)
        attachment.retryable = result.get("error") in ("EXTRACTION_TIMEOUT", "OCR_TIMEOUT")


async def expire_files():
    async with Session.begin() as db:
        rows = (await db.scalars(select(Attachment).where(Attachment.expires_at <= utcnow(),
            Attachment.extraction_status != "expired").limit(100))).all()
        for row in rows:
            row.extraction_status = "expired"
            row.extracted_text = None
            db.add(Job(type="delete_file", payload={"storage_key": row.storage_key}))


async def reconcile(adapters):
    async with Session() as db:
        attempts = (await db.scalars(select(GenerationAttempt).where(
            GenerationAttempt.status.in_(["pending", "reserved"]),
            GenerationAttempt.provider_code.in_(adapters),
            or_(GenerationAttempt.usage_data.is_not(None),
                GenerationAttempt.provider_code.in_(("openrouter", "zenmux"))
                & GenerationAttempt.generation_id.is_not(None)),
            GenerationAttempt.created_at < utcnow() - timedelta(minutes=2)).limit(50))).all()
    for attempt in attempts:
        try:
            cost = usage_cost(attempt.provider_code, attempt.usage_data, attempt.price_data or {})
            if cost is not None:
                async with Session() as db:
                    await settle(db, attempt.id, cost[0], attempt.usage_data.get("prompt_tokens"),
                                 attempt.usage_data.get("completion_tokens"), attempt.generation_id, settings, cost[1])
                continue
            if not attempt.generation_id:
                continue
            usage = await adapters[attempt.provider_code].get_generation_usage(attempt.generation_id)
            if usage.get("total_cost") is not None:
                async with Session() as db:
                    await settle(db, attempt.id, Decimal(str(usage["total_cost"])),
                        usage.get("native_tokens_prompt"), usage.get("native_tokens_completion"),
                        attempt.generation_id, settings)
        except Exception:
            logger.warning("usage_reconciliation_pending attempt_id=%s", attempt.id)


async def sync_due(adapters):
    for provider, adapter in adapters.items():
        async with Session() as db:
            state = await db.get(SyncState, provider)
            due = not state or not state.last_attempt_at or (utcnow() - state.last_attempt_at).total_seconds() >= settings.price_refresh_seconds
        if due:
            try:
                async with Session() as db:
                    count = await sync_models(db, adapter, settings)
                    logger.info("model_sync_completed provider=%s count=%s", provider, count)
            except Exception:
                logger.warning("model_sync_failed provider=%s", provider)


async def maintenance(adapters):
    last_reconcile = None
    while True:
        await sync_due(adapters)
        await expire_files()
        if last_reconcile is None or (utcnow() - last_reconcile).total_seconds() >= 60:
            await reconcile(adapters)
            last_reconcile = utcnow()
        await asyncio.sleep(5)


async def jobs():
    while True:
        claimed = await claim_job()
        if claimed is None:
            await asyncio.sleep(1)
            continue
        identifier, kind, payload, created_at, attempts = claimed
        queue_age_ms = int((utcnow() - created_at).total_seconds() * 1000)
        started = time.monotonic()
        try:
            if kind == "extract":
                await process_extraction(payload["attachment_id"])
            elif kind == "delete_file":
                await asyncio.to_thread(storage_path(payload["storage_key"]).unlink, missing_ok=True)
            else:
                raise ValueError("Unknown job type")
            async with Session.begin() as db:
                job = await db.get(Job, identifier)
                job.status = "completed"
                job.lease_until = None
            logger.info("job_completed job_id=%s kind=%s attempts=%s queue_age_ms=%s latency_ms=%s",
                identifier, kind, attempts, queue_age_ms, int((time.monotonic() - started) * 1000))
        except Exception as exc:
            logger.warning("job_failed job_id=%s kind=%s attempts=%s exception=%s queue_age_ms=%s latency_ms=%s",
                identifier, kind, attempts, type(exc).__name__, queue_age_ms,
                int((time.monotonic() - started) * 1000))
            # Keep the lease until expiry to avoid a tight retry loop.


async def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    adapters = create_adapters(settings)
    try:
        while True:
            try:
                async with asyncio.TaskGroup() as group:
                    group.create_task(maintenance(adapters))
                    group.create_task(jobs())
            except ExceptionGroup:
                logger.warning("worker_dependency_unavailable retry_seconds=3")
                await asyncio.sleep(3)
    finally:
        await asyncio.gather(*(adapter.close() for adapter in adapters.values()))


if __name__ == "__main__":
    asyncio.run(main())
