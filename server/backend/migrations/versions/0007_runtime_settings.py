"""Persist administrator-managed non-secret routing policy."""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("runtime_settings",
        sa.Column("key", sa.String(32), primary_key=True),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table("runtime_settings")
