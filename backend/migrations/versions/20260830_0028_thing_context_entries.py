"""Add current soft-state Thing context entries."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260830_0028"
down_revision: str | None = "20260830_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "thing_context_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "thing_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("things.id"), nullable=False
        ),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_thing_context_entries_thing_updated",
        "thing_context_entries",
        ["thing_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_thing_context_entries_thing_updated", table_name="thing_context_entries")
    op.drop_table("thing_context_entries")
