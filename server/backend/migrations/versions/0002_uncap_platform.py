"""Keep platform spending totals without a platform dollar limit."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("quota_buckets", "limit_usd",
                    existing_type=sa.Numeric(precision=20, scale=10), nullable=True)


def downgrade():
    op.execute("UPDATE quota_buckets SET limit_usd = 0 WHERE limit_usd IS NULL")
    op.alter_column("quota_buckets", "limit_usd",
                    existing_type=sa.Numeric(precision=20, scale=10), nullable=False)
