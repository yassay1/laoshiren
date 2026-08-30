"""Freeze Thing and Task lifecycle enum values."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260830_0030"
down_revision: str | None = "20260830_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE thing_status RENAME TO thing_status_legacy")
    op.execute("CREATE TYPE thing_status AS ENUM ('ACTIVE', 'COMPLETED', 'CANCELLED')")
    op.execute(
        "ALTER TABLE things ALTER COLUMN status TYPE thing_status USING "
        "(CASE WHEN status::text IN ('COMPLETED', 'CANCELLED') THEN status::text "
        "ELSE 'ACTIVE' END)::thing_status"
    )
    op.execute("DROP TYPE thing_status_legacy")
    op.execute("ALTER TYPE task_status RENAME TO task_status_legacy")
    op.execute("CREATE TYPE task_status AS ENUM ('TODO', 'DONE', 'CANCELLED')")
    op.execute(
        "ALTER TABLE tasks ALTER COLUMN status TYPE task_status USING "
        "(CASE WHEN status::text IN ('DONE', 'CANCELLED') THEN status::text "
        "ELSE 'TODO' END)::task_status"
    )
    op.execute("DROP TYPE task_status_legacy")


def downgrade() -> None:
    op.execute("ALTER TYPE thing_status ADD VALUE IF NOT EXISTS 'PLANNING'")
    op.execute("ALTER TYPE thing_status ADD VALUE IF NOT EXISTS 'BLOCKED'")
    op.execute("ALTER TYPE thing_status ADD VALUE IF NOT EXISTS 'WAITING'")
    op.execute("ALTER TYPE thing_status ADD VALUE IF NOT EXISTS 'PAUSED'")
    op.execute("ALTER TYPE thing_status ADD VALUE IF NOT EXISTS 'ARCHIVED'")
    op.execute("ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'IN_PROGRESS'")
    op.execute("ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'WAITING'")
    op.execute("ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'BLOCKED'")
