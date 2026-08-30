"""Freeze ThingDate type, precision, and label semantics."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0033"
down_revision: str | None = "20260830_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("thing_dates", sa.Column("label", sa.String(length=200), nullable=True))
    op.execute("UPDATE thing_dates SET label = kind WHERE label IS NULL")
    op.execute("CREATE TYPE thing_date_type AS ENUM ('DEADLINE', 'EVENT', 'MILESTONE')")
    op.execute(
        "ALTER TABLE thing_dates ALTER COLUMN kind TYPE thing_date_type USING "
        "(CASE WHEN upper(kind) IN ('EVENT', 'MILESTONE') THEN upper(kind) "
        "ELSE 'DEADLINE' END)::thing_date_type"
    )
    op.execute("ALTER TYPE date_precision RENAME TO date_precision_legacy")
    op.execute("CREATE TYPE date_precision AS ENUM ('DATE_TIME', 'DATE', 'MONTH')")
    op.execute(
        "ALTER TABLE thing_dates ALTER COLUMN precision TYPE date_precision USING "
        "(CASE WHEN precision::text = 'DATE' THEN 'DATE' ELSE 'DATE_TIME' END)::date_precision"
    )
    op.execute("DROP TYPE date_precision_legacy")


def downgrade() -> None:
    op.execute("ALTER TYPE date_precision RENAME TO date_precision_v22")
    op.execute("CREATE TYPE date_precision AS ENUM ('DATE', 'DATETIME')")
    op.execute(
        "ALTER TABLE thing_dates ALTER COLUMN precision TYPE date_precision USING "
        "(CASE WHEN precision::text = 'DATE' THEN 'DATE' ELSE 'DATETIME' END)::date_precision"
    )
    op.execute("DROP TYPE date_precision_v22")
    op.execute("ALTER TABLE thing_dates ALTER COLUMN kind TYPE varchar(80) USING kind::text")
    op.execute("DROP TYPE thing_date_type")
    op.drop_column("thing_dates", "label")
