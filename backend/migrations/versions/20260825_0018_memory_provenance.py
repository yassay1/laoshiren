"""Persist Run and Message provenance for formed memories."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0018"
down_revision: str | None = "20260825_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("long_term_memories", sa.Column("provenance_run_id", sa.Uuid()))
    op.add_column(
        "long_term_memories",
        sa.Column(
            "source_message_ids",
            postgresql.ARRAY(sa.Uuid()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("long_term_memories", "source_message_ids")
    op.drop_column("long_term_memories", "provenance_run_id")
