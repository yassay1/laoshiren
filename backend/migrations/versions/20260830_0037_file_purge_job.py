"""Add FILE_PURGE durable job kind."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260830_0037"
down_revision: str | None = "20260830_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE durable_job_kind ADD VALUE IF NOT EXISTS 'FILE_PURGE'")


def downgrade() -> None:
    raise NotImplementedError("PostgreSQL enum values cannot be removed safely.")
