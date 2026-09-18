from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, new_id, timestamp, utcnow

Money = Numeric(20, 10)
ContentText = Text().with_variant(MEDIUMTEXT(), "mysql", "mariadb")


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    google_sub: Mapped[str] = mapped_column(String(255), unique=True)
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(timestamp, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(timestamp)
    paid_blocked: Mapped[bool] = mapped_column(Boolean, default=False)


class LoginThrottle(Base):
    __tablename__ = "login_throttles"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_started_at: Mapped[datetime] = mapped_column(timestamp, default=utcnow)


class LoginSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(timestamp)
    revoked_at: Mapped[datetime | None] = mapped_column(timestamp)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversation_user_updated", "user_id", "updated_at", "id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(160), default="새 대화")
    explanation_mode: Mapped[str] = mapped_column(String(20), default="standard")
    created_at: Mapped[datetime] = mapped_column(timestamp, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(timestamp, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(timestamp)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="accepted", index=True)
    selected_model: Mapped[str | None] = mapped_column(String(255))
    selected_provider: Mapped[str | None] = mapped_column(String(32))
    routing: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    context_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    quota_date: Mapped[date] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(timestamp, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(timestamp)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(ContentText, default="")
    status: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(timestamp, default=utcnow)


class GenerationAttempt(Base):
    __tablename__ = "generation_attempts"
    __table_args__ = (UniqueConstraint("run_id", "attempt_no"), UniqueConstraint("provider_code", "generation_id"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    provider_code: Mapped[str] = mapped_column(String(32), default="openrouter")
    generation_id: Mapped[str | None] = mapped_column(String(255))
    model_id: Mapped[str] = mapped_column(String(255))
    actual_model: Mapped[str | None] = mapped_column(String(255))
    actual_provider: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), default="reserved")
    reserved_usd: Mapped[Decimal] = mapped_column(Money)
    actual_usd: Mapped[Decimal | None] = mapped_column(Money)
    price_data: Mapped[dict | None] = mapped_column(JSON)
    usage_data: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(timestamp, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(timestamp)


class ProviderModel(Base):
    __tablename__ = "provider_models"
    __table_args__ = (UniqueConstraint("provider_code", "model_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_code: Mapped[str] = mapped_column(String(32), default="openrouter")
    model_id: Mapped[str] = mapped_column(String(255))
    context_length: Mapped[int] = mapped_column(Integer)
    capabilities: Mapped[dict] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    quality_status: Mapped[str] = mapped_column(String(24), default="unreviewed")


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    __table_args__ = (UniqueConstraint("batch_id", "model_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(String(36), index=True)
    model_key: Mapped[str] = mapped_column(ForeignKey("provider_models.id"))
    input_per_m: Mapped[Decimal] = mapped_column(Money)
    output_per_m: Mapped[Decimal] = mapped_column(Money)
    request_price: Mapped[Decimal] = mapped_column(Money)
    fetched_at: Mapped[datetime] = mapped_column(timestamp, default=utcnow)
    raw: Mapped[dict] = mapped_column(JSON)


class SyncState(Base):
    __tablename__ = "sync_state"
    provider_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    active_batch_id: Mapped[str | None] = mapped_column(String(36))
    last_success_at: Mapped[datetime | None] = mapped_column(timestamp)
    last_attempt_at: Mapped[datetime | None] = mapped_column(timestamp)
    error_code: Mapped[str | None] = mapped_column(String(64))


class QuotaBucket(Base):
    __tablename__ = "quota_buckets"
    __table_args__ = (UniqueConstraint("scope", "scope_id", "quota_date"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[str] = mapped_column(String(36))
    quota_date: Mapped[date] = mapped_column(Date)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    reserved_usd: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    spent_usd: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    limit_usd: Mapped[Decimal | None] = mapped_column(Money)


class UsageLedger(Base):
    __tablename__ = "usage_ledger"
    __table_args__ = (UniqueConstraint("provider_code", "generation_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("generation_attempts.id"), unique=True)
    provider_code: Mapped[str] = mapped_column(String(32), default="openrouter")
    generation_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Money)
    cost_source: Mapped[str | None] = mapped_column(String(24))
    settled_at: Mapped[datetime | None] = mapped_column(timestamp)


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    extraction_status: Mapped[str] = mapped_column(String(24), default="queued")
    extracted_text: Mapped[str | None] = mapped_column(ContentText)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(timestamp, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(timestamp)


class ToolRun(Base):
    __tablename__ = "tool_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(32))
    sources: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24))
    latency_ms: Mapped[int] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    lease_until: Mapped[datetime | None] = mapped_column(timestamp)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(timestamp, default=utcnow)


class RuntimeLock(Base):
    """A stable mutex row for cross-process admission and bucket creation."""
    __tablename__ = "runtime_locks"
    name: Mapped[str] = mapped_column(String(64), primary_key=True)


class SpeechRequest(Base):
    __tablename__ = "speech_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    quota_date: Mapped[date] = mapped_column(Date)
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    created_at: Mapped[datetime] = mapped_column(timestamp, default=utcnow)


for table in Base.metadata.tables.values():
    table.dialect_options["mysql"]["engine"] = "InnoDB"
    table.dialect_options["mysql"]["charset"] = "utf8mb4"
    table.dialect_options["mysql"]["collate"] = "utf8mb4_bin"


class RuntimeSettings(Base):
    __tablename__ = "runtime_settings"
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    values: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(timestamp, default=utcnow)
