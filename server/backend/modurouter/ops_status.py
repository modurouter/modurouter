"""Read-only aggregate operations snapshot without user content or credentials."""

import asyncio
import json
from decimal import Decimal

from sqlalchemy import func, select

from .billing import quota_day
from .config import get_settings
from .db import Session, utcnow
from .models import GenerationAttempt, Job, QuotaBucket
from .router import model_status


def age_seconds(now, value):
    return max(0, int((now - value).total_seconds())) if value else None


async def snapshot():
    settings = get_settings()
    now = utcnow()
    day = quota_day()
    async with Session() as db:
        prices = await model_status(db, settings)
        bucket = await db.scalar(select(QuotaBucket).where(
            QuotaBucket.scope == "platform", QuotaBucket.scope_id == "global",
            QuotaBucket.quota_date == day))
        pending = (await db.execute(select(func.count(), func.min(GenerationAttempt.created_at)).where(
            GenerationAttempt.status.in_(("pending", "reserved"))))).one()
        missing_id = await db.scalar(select(func.count()).select_from(GenerationAttempt).where(
            GenerationAttempt.status.in_(("pending", "reserved")),
            GenerationAttempt.generation_id.is_(None)))
        job_counts = dict((await db.execute(select(Job.status, func.count()).group_by(Job.status))).all())
        oldest_queued = await db.scalar(select(func.min(Job.created_at)).where(Job.status == "queued"))
    spent = bucket.spent_usd if bucket else Decimal(0)
    reserved = bucket.reserved_usd if bucket else Decimal(0)
    return {
        "price": prices,
        "platform": {"quota_date": day.isoformat(), "limit_usd": None,
                     "spent_usd": str(spent), "reserved_usd": str(reserved),
                     "remaining_usd": None},
        "pending_attempts": {"count": pending[0], "without_generation_id": missing_id,
                             "oldest_age_seconds": age_seconds(now, pending[1])},
        "jobs": {"queued": job_counts.get("queued", 0), "running": job_counts.get("running", 0),
                 "failed": job_counts.get("failed", 0),
                 "oldest_queued_age_seconds": age_seconds(now, oldest_queued)},
    }


def main():
    print(json.dumps(asyncio.run(snapshot()), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
