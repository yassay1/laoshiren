"""Add Notification outbox claims and retry scheduling."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0011"
down_revision: str | None = "20260825_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notification_outbox", sa.Column("claim_owner", sa.String(200)))
    op.add_column(
        "notification_outbox", sa.Column("lease_expires_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "notification_outbox", sa.Column("next_attempt_at", sa.DateTime(timezone=True))
    )
    op.create_index(
        "ix_notification_outbox_dispatch",
        "notification_outbox",
        ["status", "next_attempt_at", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_outbox_dispatch", table_name="notification_outbox")
    op.drop_column("notification_outbox", "next_attempt_at")
    op.drop_column("notification_outbox", "lease_expires_at")
    op.drop_column("notification_outbox", "claim_owner")
