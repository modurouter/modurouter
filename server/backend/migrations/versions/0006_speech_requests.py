"""Bound and account OpenAI speech transcription separately from chat runs."""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("speech_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("quota_date", sa.Date(), nullable=False),
        sa.Column("reserved_usd", sa.Numeric(20, 10), nullable=False),
        sa.Column("cost_usd", sa.Numeric(20, 10), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_bin")
    op.create_index("ix_speech_requests_user_id", "speech_requests", ["user_id"])


def downgrade():
    op.drop_table("speech_requests")
