"""Add primary deadline projection and integrity constraint."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0002"
down_revision: str | None = "20260823_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("things", sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_thing_dates_primary_kind",
        "thing_dates",
        ["thing_id", "kind"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )


def downgrade() -> None:
    op.drop_index("uq_thing_dates_primary_kind", table_name="thing_dates")
    op.drop_column("things", "deadline_at")
