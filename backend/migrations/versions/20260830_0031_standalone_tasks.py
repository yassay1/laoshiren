"""Allow standalone Tasks with direct user ownership."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260830_0031"
down_revision: str | None = "20260830_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(
        "UPDATE tasks SET user_id = things.user_id FROM things WHERE tasks.thing_id = things.id"
    )
    op.alter_column("tasks", "user_id", nullable=False)
    op.create_foreign_key("fk_tasks_user_id_users", "tasks", "users", ["user_id"], ["id"])
    op.alter_column("tasks", "thing_id", nullable=True)
    op.alter_column("state_mutations", "thing_id", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM state_mutations WHERE thing_id IS NULL")
    op.execute("DELETE FROM tasks WHERE thing_id IS NULL")
    op.alter_column("state_mutations", "thing_id", nullable=False)
    op.alter_column("tasks", "thing_id", nullable=False)
    op.drop_constraint("fk_tasks_user_id_users", "tasks", type_="foreignkey")
    op.drop_column("tasks", "user_id")
