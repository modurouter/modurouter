"""Store the full bounded Unicode response and extracted document text."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import MEDIUMTEXT

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    for table, column, nullable in (("messages", "content", False),
                                    ("attachments", "extracted_text", True)):
        op.alter_column(table, column, existing_type=sa.Text(),
                        type_=MEDIUMTEXT(), existing_nullable=nullable)


def downgrade():
    raise RuntimeError("Narrowing content columns could discard saved text")
