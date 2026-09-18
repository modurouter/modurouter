"""Remember the requested routing policy and selected provider."""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("runs", sa.Column("routing", sa.JSON(), nullable=True))
    op.add_column("runs", sa.Column("selected_provider", sa.String(32), nullable=True))


def downgrade():
    op.drop_column("runs", "selected_provider")
    op.drop_column("runs", "routing")
