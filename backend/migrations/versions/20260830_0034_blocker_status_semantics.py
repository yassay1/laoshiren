"""Freeze Blocker status to OPEN and RESOLVED."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260830_0034"
down_revision: str | None = "20260830_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE blocker_status RENAME TO blocker_status_legacy")
    op.execute("CREATE TYPE blocker_status AS ENUM ('OPEN', 'RESOLVED')")
    op.execute(
        "ALTER TABLE blockers ALTER COLUMN status TYPE blocker_status USING "
        "(CASE WHEN status::text = 'OPEN' THEN 'OPEN' ELSE 'RESOLVED' END)::blocker_status"
    )
    op.execute("DROP TYPE blocker_status_legacy")


def downgrade() -> None:
    op.execute("ALTER TYPE blocker_status ADD VALUE IF NOT EXISTS 'IGNORED'")
