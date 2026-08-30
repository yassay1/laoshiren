"""Add keyed PROFILE Memory version chains."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0013"
down_revision: str | None = "20260825_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("long_term_memories", sa.Column("profile_key", sa.String(100)))
    op.add_column("long_term_memories", sa.Column("supersedes_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_memories_supersedes",
        "long_term_memories",
        "long_term_memories",
        ["supersedes_id"],
        ["id"],
    )
    op.create_index(
        "uq_memories_active_profile_key",
        "long_term_memories",
        ["user_id", "profile_key"],
        unique=True,
        postgresql_where=sa.text(
            "memory_type = 'PROFILE' AND status = 'ACTIVE' AND profile_key IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_memories_active_profile_key", table_name="long_term_memories")
    op.drop_constraint("fk_memories_supersedes", "long_term_memories", type_="foreignkey")
    op.drop_column("long_term_memories", "supersedes_id")
    op.drop_column("long_term_memories", "profile_key")
