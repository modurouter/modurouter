"""Short, ordered database transactions. No provider I/O while holding locks."""
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .db import utcnow
from .errors import AppError
from .models import GenerationAttempt, QuotaBucket, Run, RuntimeLock, UsageLedger, User

ACTIVE = ("accepted", "preparing", "model", "tool", "streaming")
SEOUL = ZoneInfo("Asia/Seoul")
ZERO = Decimal(0)


def quota_day(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(SEOUL).date()


def next_reset() -> str:
    tomorrow = quota_day() + timedelta(days=1)
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=SEOUL).isoformat()


async def admission_lock(db: AsyncSession):
    lock = await db.scalar(select(RuntimeLock).where(RuntimeLock.name == "admission").with_for_update())
    if lock is None:
        raise AppError("SERVICE_UNAVAILABLE", "서비스를 준비 중입니다. 잠시 후 다시 시도해 주세요.", 503, True)


async def buckets(db: AsyncSession, user_id: str, day: date, settings: Settings):
    # Every caller takes the stable admission mutex before creating or locking buckets.
    result = []
    specs = [("platform", "global", None),
             ("user", user_id, settings.user_daily_budget_usd)]
    # Legacy guest buckets are needed only to reconcile charges from before
    # guest login was removed. Existing guest sessions cannot admit new runs.
    owner = await db.get(User, user_id)
    if owner and owner.google_sub.startswith(("guest:", "deleted:guest:")):
        specs.append(("guest", "shared", settings.user_daily_budget_usd))
    for scope, scope_id, limit in specs:
        row = await db.scalar(select(QuotaBucket).where(
            QuotaBucket.scope == scope, QuotaBucket.scope_id == scope_id,
            QuotaBucket.quota_date == day).with_for_update())
        if row is None:
            row = QuotaBucket(scope=scope, scope_id=scope_id, quota_date=day,
                              request_count=0, reserved_usd=ZERO, spent_usd=ZERO, limit_usd=limit)
            db.add(row)
            await db.flush()
        row.limit_usd = limit
        result.append(row)
    return result


async def admit_run(db: AsyncSession, user_id: str, settings: Settings) -> date:
    """Caller owns transaction, takes admission_lock and inserts Run before commit."""
    active = await db.scalar(select(func.count()).select_from(Run).where(Run.status.in_(ACTIVE)))
    own = await db.scalar(select(func.count()).select_from(Run).where(
        Run.status.in_(ACTIVE), Run.user_id == user_id))
    if own or active >= settings.platform_concurrency:
        raise AppError("CONCURRENCY_LIMIT", "진행 중인 답변이 있습니다. 잠시 후 다시 시도해 주세요.", 429, True)
    day = quota_day()
    rows = await buckets(db, user_id, day, settings)
    if any(row.request_count >= settings.user_daily_request_limit for row in rows if row.scope != "platform"):
        raise AppError("REQUEST_LIMIT", "오늘의 질문 횟수를 모두 사용했습니다.", 429)
    for row in rows:
        row.request_count += 1
    return day


async def reserve(db: AsyncSession, run_id: str, model_id: str, amount: Decimal,
                  settings: Settings, provider_code: str = "openrouter",
                  price_data: dict | None = None) -> GenerationAttempt:
    if not amount.is_finite() or amount < 0:
        raise ValueError("Invalid reservation")
    amount = amount.quantize(Decimal("0.0000000001"), rounding=ROUND_CEILING)
    async with db.begin():
        await admission_lock(db)
        run = await db.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run.status not in ACTIVE or run.cancel_requested:
            raise AppError("CANCELLED", "답변 생성을 중단했습니다.")
        count = await db.scalar(select(func.count()).select_from(GenerationAttempt).where(
            GenerationAttempt.run_id == run_id))
        if count >= settings.max_model_calls_per_run:
            raise AppError("MODEL_CALL_LIMIT", "답변에 필요한 처리 횟수 제한에 도달했습니다.")
        user = await db.get(User, run.user_id)
        if amount > 0 and user.paid_blocked:
            raise AppError("BUDGET_REVIEW_REQUIRED", "이전 사용 비용을 확인 중입니다.", 429)
        for row in await buckets(db, run.user_id, run.quota_date, settings):
            if row.limit_usd is not None and row.spent_usd + row.reserved_usd + amount > row.limit_usd:
                raise AppError("BUDGET_EXCEEDED", "오늘의 사용 한도에 도달했습니다.", 429)
            row.reserved_usd += amount
        attempt = GenerationAttempt(run_id=run_id, attempt_no=count + 1, model_id=model_id,
                                    reserved_usd=amount, provider_code=provider_code, price_data=price_data)
        db.add(attempt)
        await db.flush()
        db.add(UsageLedger(attempt_id=attempt.id, provider_code=provider_code))
    return attempt


async def settle(db: AsyncSession, attempt_id: str, cost: Decimal,
                 input_tokens: int | None, output_tokens: int | None, generation_id: str | None,
                 settings: Settings, cost_source: str = "provider") -> bool:
    if not cost.is_finite() or cost < 0:
        raise ValueError("Invalid provider cost")
    cost = cost.quantize(Decimal("0.0000000001"), rounding=ROUND_CEILING)
    if any(x is not None and x < 0 for x in (input_tokens, output_tokens)):
        raise ValueError("Invalid provider token count")
    async with db.begin():
        await admission_lock(db)
        attempt = await db.scalar(select(GenerationAttempt).where(
            GenerationAttempt.id == attempt_id).with_for_update())
        ledger = await db.scalar(select(UsageLedger).where(
            UsageLedger.attempt_id == attempt_id).with_for_update())
        if ledger.status == "settled":
            return False
        if generation_id:
            existing = await db.scalar(select(UsageLedger).where(
                UsageLedger.provider_code == attempt.provider_code, UsageLedger.generation_id == generation_id,
                UsageLedger.attempt_id != attempt_id))
            if existing:
                raise AppError("SETTLEMENT_CONFLICT", "사용 비용을 확인 중입니다.", 503)
        run = await db.get(Run, attempt.run_id)
        for row in await buckets(db, run.user_id, run.quota_date, settings):
            row.reserved_usd -= attempt.reserved_usd
            row.spent_usd += cost
        if cost > attempt.reserved_usd:
            user = await db.get(User, run.user_id)
            user.paid_blocked = True
        attempt.actual_usd = cost
        attempt.generation_id = generation_id or attempt.generation_id
        attempt.status = "settled"
        attempt.finished_at = utcnow()
        ledger.status = "settled"
        ledger.generation_id = generation_id
        ledger.cost_usd = cost
        ledger.cost_source = cost_source
        ledger.input_tokens = input_tokens
        ledger.output_tokens = output_tokens
        ledger.settled_at = utcnow()
    return True


async def mark_pending(db: AsyncSession, attempt_id: str, generation_id: str | None,
                       error_code: str | None = None):
    async with db.begin():
        await admission_lock(db)
        attempt = await db.get(GenerationAttempt, attempt_id, with_for_update=True)
        if attempt.status == "settled":
            return
        attempt.status = "pending"
        attempt.generation_id = generation_id
        attempt.error_code = error_code
        attempt.finished_at = utcnow()
        ledger = await db.scalar(select(UsageLedger).where(UsageLedger.attempt_id == attempt_id))
        ledger.generation_id = generation_id


async def usage_summary(db: AsyncSession, user_id: str, settings: Settings) -> dict:
    owner = await db.get(User, user_id)
    guest = owner.google_sub.startswith(("guest:", "deleted:guest:"))
    row = await db.scalar(select(QuotaBucket).where(QuotaBucket.scope == "user",
        QuotaBucket.scope_id == user_id, QuotaBucket.quota_date == quota_day()))
    if guest:
        row = await db.scalar(select(QuotaBucket).where(QuotaBucket.scope == "guest",
            QuotaBucket.scope_id == "shared", QuotaBucket.quota_date == quota_day()))
    spent = row.spent_usd if row else ZERO
    reserved = row.reserved_usd if row else ZERO
    return {"remaining_requests": max(0, settings.user_daily_request_limit - (row.request_count if row else 0)),
            "request_limit": settings.user_daily_request_limit, "spent_usd": str(spent),
            "reserved_usd": str(reserved), "limit_usd": str(settings.user_daily_budget_usd),
            "remaining_usd": str(max(ZERO, settings.user_daily_budget_usd - spent - reserved)),
            "resets_at": next_reset(), "shared_guest_quota": guest}
