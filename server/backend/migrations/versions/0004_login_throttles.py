"""Persist password login throttling across API restarts and workers."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("login_throttles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table("login_throttles")
