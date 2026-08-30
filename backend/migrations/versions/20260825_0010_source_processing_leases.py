"""Add durable Source processing claims and retry schedule."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0010"
down_revision: str | None = "20260824_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("processing_claim_owner", sa.String(200)))
    op.add_column("sources", sa.Column("processing_lease_expires_at", sa.DateTime(timezone=True)))
    op.add_column("sources", sa.Column("processing_heartbeat_at", sa.DateTime(timezone=True)))
    op.add_column(
        "sources",
        sa.Column(
            "processing_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column("sources", sa.Column("next_processing_attempt_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_sources_processing_claim",
        "sources",
        ["processing_status", "next_processing_attempt_at", "processing_lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sources_processing_claim", table_name="sources")
    op.drop_column("sources", "next_processing_attempt_at")
    op.drop_column("sources", "processing_attempt_count")
    op.drop_column("sources", "processing_heartbeat_at")
    op.drop_column("sources", "processing_lease_expires_at")
    op.drop_column("sources", "processing_claim_owner")
