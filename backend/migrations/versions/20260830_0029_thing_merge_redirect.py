"""Add canonical Thing merge redirect."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260830_0029"
down_revision: str | None = "20260830_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "things",
        sa.Column(
            "merged_into_thing_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("things.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_things_merged_into", "things", ["merged_into_thing_id"])


def downgrade() -> None:
    op.drop_index("ix_things_merged_into", table_name="things")
    op.drop_column("things", "merged_into_thing_id")
