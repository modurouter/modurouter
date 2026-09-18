"""Persist learning studio progress and link coaching conversations."""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("learning_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("task_version", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("last_request", sa.String(64), nullable=True),
        sa.Column("last_hash", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "task_id", name="uq_learning_user_task"),
        sa.UniqueConstraint("conversation_id", name="uq_learning_sessions_conversation_id"))
    op.create_index("ix_learning_sessions_user_id", "learning_sessions", ["user_id"])


def downgrade():
    op.drop_table("learning_sessions")
