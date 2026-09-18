"""Operator recovery after investigating a reservation overrun."""
import argparse
import asyncio

from sqlalchemy import func, select

from .billing import ACTIVE, admission_lock
from .db import Session
from .errors import AppError
from .models import GenerationAttempt, Run, User


async def clear_paid_block(db, user_id: str):
    async with db.begin():
        await admission_lock(db)
        user = await db.get(User, user_id, with_for_update=True)
        if user is None or user.deleted_at:
            raise AppError("NOT_FOUND", "사용자를 찾을 수 없습니다.", 404)
        active = await db.scalar(select(func.count()).select_from(Run).where(
            Run.user_id == user_id, Run.status.in_(ACTIVE)))
        pending = await db.scalar(select(func.count()).select_from(GenerationAttempt).join(Run).where(
            Run.user_id == user_id, GenerationAttempt.status != "settled"))
        if active or pending:
            raise AppError("BUDGET_REVIEW_PENDING", "진행 중인 답변과 미정산 비용을 먼저 확인해 주세요.", 409)
        user.paid_blocked = False


async def main():
    parser = argparse.ArgumentParser(description="Clear a paid block after reviewing prices and settled charges")
    parser.add_argument("user_id")
    parser.add_argument("--reviewed", action="store_true", required=True,
                        help="Confirm the overrun and current model prices have been reviewed")
    args = parser.parse_args()
    async with Session() as db:
        await clear_paid_block(db, args.user_id)
    print("Paid block cleared. Daily spending and request limits are unchanged.")


if __name__ == "__main__":
    asyncio.run(main())
