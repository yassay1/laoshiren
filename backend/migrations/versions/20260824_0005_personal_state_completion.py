"""Add blocker, Thing relations and ThingDate versioning."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0005"
down_revision: str | None = "20260824_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    blocker_severity = postgresql.ENUM(
        "LOW", "MEDIUM", "HIGH", "CRITICAL", name="blocker_severity", create_type=False
    )
    blocker_status = postgresql.ENUM(
        "OPEN", "RESOLVED", "IGNORED", name="blocker_status", create_type=False
    )
    relation_type = postgresql.ENUM(
        "RELATED_TO", "DEPENDS_ON", "PART_OF", name="thing_relation_type", create_type=False
    )
    bind = op.get_bind()
    blocker_severity.create(bind, checkfirst=True)
    blocker_status.create(bind, checkfirst=True)
    relation_type.create(bind, checkfirst=True)
    op.add_column(
        "thing_dates", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_table(
        "blockers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thing_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", blocker_severity, nullable=False),
        sa.Column("status", blocker_status, nullable=False),
        sa.Column("blocked_since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["thing_id"], ["things.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_blockers_thing_status", "blockers", ["thing_id", "status"])
    op.create_table(
        "thing_relations",
        sa.Column("from_thing_id", sa.Uuid(), nullable=False),
        sa.Column("to_thing_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", relation_type, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("from_thing_id <> to_thing_id", name="ck_relation_not_self"),
        sa.ForeignKeyConstraint(["from_thing_id"], ["things.id"]),
        sa.ForeignKeyConstraint(["to_thing_id"], ["things.id"]),
        sa.PrimaryKeyConstraint("from_thing_id", "to_thing_id", "relation_type"),
    )


def downgrade() -> None:
    op.drop_table("thing_relations")
    op.drop_index("ix_blockers_thing_status", table_name="blockers")
    op.drop_table("blockers")
    op.drop_column("thing_dates", "version")
    for name in ("thing_relation_type", "blocker_status", "blocker_severity"):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
