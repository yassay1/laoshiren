"""Add explicit RunEvent visibility and schema version."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0023"
down_revision: str | None = "20260830_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "run_events",
        sa.Column(
            "visibility",
            sa.String(length=30),
            server_default="CLIENT",
            nullable=False,
        ),
    )
    op.add_column(
        "run_events",
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("run_events", "schema_version")
    op.drop_column("run_events", "visibility")
