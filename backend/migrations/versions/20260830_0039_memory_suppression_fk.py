"""Allow memory row cleanup when suppression tombstones remain."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260830_0039"
down_revision: str | None = "20260830_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "memory_suppressions_memory_id_fkey",
        "memory_suppressions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "memory_suppressions_memory_id_fkey",
        "memory_suppressions",
        "long_term_memories",
        ["memory_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "memory_suppressions_memory_id_fkey",
        "memory_suppressions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "memory_suppressions_memory_id_fkey",
        "memory_suppressions",
        "long_term_memories",
        ["memory_id"],
        ["id"],
    )
