"""Persist request tariffs and usage for provider-specific accounting."""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("generation_attempts", sa.Column("price_data", sa.JSON(), nullable=True))
    op.add_column("generation_attempts", sa.Column("usage_data", sa.JSON(), nullable=True))
    op.add_column("usage_ledger", sa.Column("cost_source", sa.String(24), nullable=True))


def downgrade():
    op.drop_column("usage_ledger", "cost_source")
    op.drop_column("generation_attempts", "usage_data")
    op.drop_column("generation_attempts", "price_data")
