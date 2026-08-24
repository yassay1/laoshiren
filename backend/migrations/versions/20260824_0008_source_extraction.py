"""Add durable Source extraction results."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0008"
down_revision: str | None = "20260824_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("extracted_text", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("processing_error", sa.String(100), nullable=True))
    op.add_column(
        "sources", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("sources", "processed_at")
    op.drop_column("sources", "processing_error")
    op.drop_column("sources", "extracted_text")
