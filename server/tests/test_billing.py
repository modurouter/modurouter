import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from modurouter.billing import (
    admission_lock,
    admit_run,
    mark_pending,
    quota_day,
    reserve,
    settle,
    usage_summary,
)
from modurouter.config import Settings
from modurouter.errors import AppError
from modurouter.models import Conversation, GenerationAttempt, QuotaBucket, Run, User
from sqlalchemy import select


async def seed(factory, settings, count=1):
    runs = []
    async with factory.begin() as db:
        for n in range(count):
            user = User(google_sub=str(n), email=f"{n}@example.test", display_name="테스트")
            db.add(user)
            await db.flush()
            conversation = Conversation(user_id=user.id)
            db.add(conversation)
            await db.flush()
            await admission_lock(db)
            day = await admit_run(db, user.id, settings)
            run = Run(user_id=user.id, conversation_id=conversation.id, idempotency_key="key",
                      request_hash="a" * 64, quota_date=day)
            db.add(run)
            await db.flush()
            runs.append(run)
    return runs


@pytest.mark.asyncio
async def test_concurrent_users_keep_platform_accounting_without_global_cap(database):
    config = Settings(_env_file=None, user_daily_budget_usd="1")
    runs = await seed(database, config, 2)
    async def attempt(run):
        async with database() as db:
            try:
                return await reserve(db, run.id, "test/model", Decimal("0.08"), config)
            except AppError as exc:
                return exc.code
    results = await asyncio.gather(*(attempt(r) for r in runs))
    accepted = [r for r in results if isinstance(r, GenerationAttempt)]
    assert len(accepted) == 2
    async with database() as db:
        for index, attempt in enumerate(accepted, start=1):
            assert await settle(db, attempt.id, Decimal("0.03"), 10, 10, f"gen-{index}", config)
            assert not await settle(db, attempt.id, Decimal("0.03"), 10, 10, f"gen-{index}", config)
        row = await db.scalar(select(QuotaBucket).where(QuotaBucket.scope == "platform"))
        assert row.limit_usd is None
        assert row.spent_usd == Decimal("0.06")
        assert row.reserved_usd == 0


async def test_unknown_cost_is_retained_and_overrun_blocks_paid_calls(database):
    config = Settings(_env_file=None, user_daily_budget_usd="1")
    run = (await seed(database, config))[0]
    async with database() as db:
        first = await reserve(db, run.id, "test/model", Decimal("0.02"), config)
        first_id = first.id
        await mark_pending(db, first.id, None, "STREAM_INTERRUPTED")
        row = await db.scalar(select(QuotaBucket).where(QuotaBucket.scope == "user"))
        assert row.reserved_usd == Decimal("0.02")
        await db.rollback()
        await settle(db, first_id, Decimal("0.03"), 1, 1, "gen-2", config)
        with pytest.raises(AppError, match="BUDGET_REVIEW_REQUIRED"):
            await reserve(db, run.id, "test/model", Decimal("0.01"), config)


async def test_same_user_concurrency_and_daily_request_limit(database):
    config = Settings(_env_file=None, user_daily_request_limit=1)
    run = (await seed(database, config))[0]
    async with database() as db:
        with pytest.raises(AppError, match="CONCURRENCY_LIMIT"):
            async with db.begin():
                await admission_lock(db)
                await admit_run(db, run.user_id, config)
        async with db.begin():
            row = await db.get(Run, run.id)
            row.status = "completed"
        with pytest.raises(AppError, match="REQUEST_LIMIT"):
            async with db.begin():
                await admission_lock(db)
                await admit_run(db, run.user_id, config)


def test_seoul_midnight_boundary():
    assert str(quota_day(datetime(2026, 9, 17, 14, 59, 59, tzinfo=UTC))) == "2026-09-17"
    assert str(quota_day(datetime(2026, 9, 17, 15, 0, tzinfo=UTC))) == "2026-09-18"


@pytest.mark.parametrize(("subject", "limit"), [("guest:test", 30), ("member", 50)])
async def test_role_request_limit_boundary(database, subject, limit):
    config = Settings(_env_file=None)
    async with database.begin() as db:
        user = User(google_sub=subject, email="", display_name="테스트")
        db.add(user)
        await db.flush()
        await admission_lock(db)
        summary = await usage_summary(db, user.id, config)
        assert summary["request_limit"] == summary["remaining_requests"] == limit
        for _ in range(limit - 1):
            await admit_run(db, user.id, config)
        assert (await usage_summary(db, user.id, config))["remaining_requests"] == 1
        await admit_run(db, user.id, config)
        assert (await usage_summary(db, user.id, config))["remaining_requests"] == 0
        with pytest.raises(AppError, match="REQUEST_LIMIT"):
            await admit_run(db, user.id, config)


async def test_admin_unlimited_requests_keep_usage_accounting(database):
    config = Settings(_env_file=None)
    async with database.begin() as db:
        user = User(google_sub="admin:test", email="", display_name="관리자")
        db.add(user)
        await db.flush()
        await admission_lock(db)
        initial = await usage_summary(db, user.id, config)
        assert initial["request_limit"] is None and initial["remaining_requests"] is None
        await admit_run(db, user.id, config)
        rows = (await db.scalars(select(QuotaBucket))).all()
        for row in rows:
            row.request_count = 10000
        await admit_run(db, user.id, config)
        assert all(row.request_count == 10001 for row in rows)
        summary = await usage_summary(db, user.id, config)
        assert summary["request_limit"] is None and summary["remaining_requests"] is None
        assert summary["shared_guest_quota"] is False


async def test_new_guest_session_cannot_reset_shared_request_limit(database):
    config = Settings(_env_file=None)
    async with database.begin() as db:
        users = [User(google_sub=f"guest:{index}", email="", display_name="비회원")
                 for index in range(2)]
        db.add_all(users)
        await db.flush()
        await admission_lock(db)
        for _ in range(30):
            await admit_run(db, users[0].id, config)
        summary = await usage_summary(db, users[1].id, config)
        assert summary["request_limit"] == 30 and summary["remaining_requests"] == 0
        with pytest.raises(AppError, match="REQUEST_LIMIT"):
            await admit_run(db, users[1].id, config)


async def test_review_recovery_requires_settled_inactive_runs(database):
    from modurouter.billing_review import clear_paid_block
    config = Settings(_env_file=None, user_daily_budget_usd="1")
    run = (await seed(database, config))[0]
    async with database() as db:
        attempt = await reserve(db, run.id, "test/model", Decimal(".01"), config)
        attempt_id = attempt.id
        await mark_pending(db, attempt_id, "review-gen")
        with pytest.raises(AppError, match="BUDGET_REVIEW_PENDING"):
            await clear_paid_block(db, run.user_id)
        await settle(db, attempt_id, Decimal(".02"), 1, 1, "review-gen", config)
        with pytest.raises(AppError, match="BUDGET_REVIEW_PENDING"):
            await clear_paid_block(db, run.user_id)
        async with db.begin():
            (await db.get(Run, run.id)).status = "completed"
        await clear_paid_block(db, run.user_id)
        assert not (await db.get(User, run.user_id)).paid_blocked
        row = await db.scalar(select(QuotaBucket).where(QuotaBucket.scope == "user"))
        assert row.spent_usd == Decimal(".02") and row.request_count == 1
