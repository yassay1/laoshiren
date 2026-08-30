"""Add soft-deletion tombstones for Things and Sources."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0035"
down_revision: str | None = "20260830_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("things", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_things_user_deleted", "things", ["user_id", "deleted_at"])
    op.add_column("sources", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_sources_user_deleted", "sources", ["user_id", "deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_sources_user_deleted", table_name="sources")
    op.drop_column("sources", "deleted_at")
    op.drop_index("ix_things_user_deleted", table_name="things")
    op.drop_column("things", "deleted_at")
