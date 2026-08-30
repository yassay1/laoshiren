"""Add memory_suppressions tombstones for forget suppression."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0038"
down_revision: str | None = "20260830_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_suppressions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["memory_id"], ["long_term_memories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "content_fingerprint",
            name="uq_memory_suppressions_user_fingerprint",
        ),
    )
    op.create_index(
        "ix_memory_suppressions_user_created",
        "memory_suppressions",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_suppressions_user_created", table_name="memory_suppressions")
    op.drop_table("memory_suppressions")
