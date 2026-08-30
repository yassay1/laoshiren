"""Converge durable RunEvent names and remove persisted ephemeral frames."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260830_0026"
down_revision: str | None = "20260830_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_VALUES = (
    "run.queued",
    "run.started",
    "assistant.started",
    "assistant.completed",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "hitl.requested",
    "run.waiting_for_user",
    "run.resumed",
    "run.completed",
    "run.failed",
    "run.cancelled",
)


def _create_type(values: tuple[str, ...]) -> None:
    quoted = ", ".join(f"'{value}'" for value in values)
    op.execute(f"CREATE TYPE run_event_type AS ENUM ({quoted})")


def upgrade() -> None:
    op.execute("ALTER TABLE run_events ALTER COLUMN event_type TYPE text USING event_type::text")
    op.execute("DELETE FROM run_events WHERE event_type IN ('assistant.delta', 'heartbeat')")
    op.execute(
        "UPDATE run_events SET event_type = 'assistant.completed' "
        "WHERE event_type = 'assistant.message'"
    )
    op.execute(
        "UPDATE run_events SET event_type = 'hitl.requested' "
        "WHERE event_type = 'interrupt.required'"
    )
    op.execute(
        "UPDATE run_events SET event_type = CASE "
        "WHEN data->>'status' = 'CANCELLED' THEN 'run.cancelled' "
        "WHEN data->>'phase' = 'resuming' THEN 'run.resumed' "
        "ELSE 'run.queued' END WHERE event_type = 'status.updated'"
    )
    op.execute("DROP TYPE run_event_type")
    _create_type(NEW_VALUES)
    op.execute(
        "ALTER TABLE run_events ALTER COLUMN event_type TYPE run_event_type "
        "USING event_type::run_event_type"
    )


def downgrade() -> None:
    old_values = (
        "run.started",
        "assistant.delta",
        "assistant.message",
        "tool.started",
        "tool.completed",
        "tool.failed",
        "status.updated",
        "interrupt.required",
        "run.completed",
        "run.failed",
        "heartbeat",
    )
    op.execute("ALTER TABLE run_events ALTER COLUMN event_type TYPE text USING event_type::text")
    op.execute(
        "UPDATE run_events SET event_type = 'assistant.message' "
        "WHERE event_type IN ('assistant.started', 'assistant.completed')"
    )
    op.execute(
        "UPDATE run_events SET event_type = 'interrupt.required' "
        "WHERE event_type IN ('hitl.requested', 'run.waiting_for_user')"
    )
    op.execute(
        "UPDATE run_events SET event_type = 'status.updated' "
        "WHERE event_type IN ('run.queued', 'run.resumed', 'run.cancelled')"
    )
    op.execute("DROP TYPE run_event_type")
    _create_type(old_values)
    op.execute(
        "ALTER TABLE run_events ALTER COLUMN event_type TYPE run_event_type "
        "USING event_type::run_event_type"
    )
