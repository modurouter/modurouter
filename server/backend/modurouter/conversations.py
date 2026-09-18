import base64
import json
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import current_user
from .billing import ACTIVE, admission_lock
from .db import get_db, utcnow
from .errors import AppError
from .models import Attachment, Conversation, Job, Message, Run, ToolRun, User

router = APIRouter(prefix="/v1/conversations")


class ConversationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="새 대화", min_length=1, max_length=160)


async def owned_conversation(db: AsyncSession, user_id: str, conversation_id: str):
    row = await db.scalar(select(Conversation).join(User).where(Conversation.id == conversation_id,
        Conversation.user_id == user_id, Conversation.deleted_at.is_(None), User.deleted_at.is_(None)))
    if row is None:
        raise AppError("NOT_FOUND", "대화를 찾을 수 없습니다.", 404)
    return row


def summary(row: Conversation):
    return {"id": row.id, "title": row.title, "updated_at": row.updated_at.isoformat() + "Z"}


@router.post("")
async def create(body: ConversationInput, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await db.commit()
    await admission_lock(db)
    await db.refresh(user)
    if user.deleted_at:
        raise AppError("SESSION_EXPIRED", "로그인이 만료되었습니다. 다시 로그인해 주세요.", 401)
    row = Conversation(user_id=user.id, title=body.title)
    db.add(row)
    await db.commit()
    return summary(row)


@router.get("")
async def listing(cursor: str | None = Query(None, max_length=512), limit: int = Query(30, ge=1, le=100),
                  user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    query = select(Conversation).where(Conversation.user_id == user.id, Conversation.deleted_at.is_(None))
    if cursor:
        try:
            value = json.loads(base64.urlsafe_b64decode(cursor))
            if not isinstance(value, list) or len(value) != 2:
                raise ValueError
            when = datetime.fromisoformat(value[0])
            if when.tzinfo is not None:
                raise ValueError
            if not isinstance(value[1], str):
                raise ValueError
            identifier = str(UUID(value[1]))
        except (ValueError, TypeError, IndexError):
            raise AppError("CURSOR_INVALID", "대화 목록 위치가 올바르지 않습니다.") from None
        query = query.where(or_(Conversation.updated_at < when,
            and_(Conversation.updated_at == when, Conversation.id < identifier)))
    rows = (await db.scalars(query.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(limit + 1))).all()
    next_cursor = None
    if len(rows) > limit:
        row = rows[limit - 1]
        next_cursor = base64.urlsafe_b64encode(json.dumps([row.updated_at.isoformat(), row.id]).encode()).decode()
    return {"items": [summary(row) for row in rows[:limit]], "next_cursor": next_cursor}


@router.get("/{conversation_id}")
async def detail(conversation_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    row = await owned_conversation(db, user.id, conversation_id)
    messages = (await db.scalars(select(Message).where(Message.conversation_id == row.id).order_by(Message.created_at, Message.id))).all()
    return {**summary(row), "messages": [{"id": m.id, "run_id": m.run_id, "role": m.role,
            "content": m.content, "status": m.status} for m in messages]}


async def erase_conversation(db: AsyncSession, row: Conversation):
    running = (await db.scalars(select(Run).where(Run.conversation_id == row.id, Run.status.in_(ACTIVE)))).all()
    if running:
        raise AppError("RUN_ACTIVE", "답변을 중단한 뒤 대화를 삭제해 주세요.", 409, True)
    row.deleted_at = utcnow()
    row.title = "삭제한 대화"
    run_ids = select(Run.id).where(Run.conversation_id == row.id)
    for tool in (await db.scalars(select(ToolRun).where(ToolRun.run_id.in_(run_ids)))).all():
        tool.sources = []
    for message in (await db.scalars(select(Message).where(Message.conversation_id == row.id))).all():
        message.content = ""
    for attachment in (await db.scalars(select(Attachment).where(Attachment.conversation_id == row.id))).all():
        attachment.extracted_text = None
        attachment.filename = "삭제한 파일"
        attachment.extraction_status = "expired"
        db.add(Job(type="delete_file", payload={"storage_key": attachment.storage_key}))


@router.delete("/{conversation_id}")
async def remove(conversation_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await db.commit()
    await admission_lock(db)
    row = await owned_conversation(db, user.id, conversation_id)
    await erase_conversation(db, row)
    await db.commit()
    return {"deleted": True}
