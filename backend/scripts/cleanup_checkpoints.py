"""Delete LangGraph checkpoints for old terminal Runs.

Run from ``backend``. The command is intentionally explicit instead of deleting
checkpoints in the request path; operations can schedule it at a low frequency.
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text

from laoshiren.config.settings import get_settings
from laoshiren.infrastructure.persistence.checkpoints import PostgresCheckpointLifecycle
from laoshiren.infrastructure.persistence.database import Database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--apply", action="store_true", help="Delete instead of dry-run.")
    return parser.parse_args()


async def run(*, retention_days: int, batch_size: int, apply: bool) -> int:
    if retention_days <= 0 or batch_size <= 0:
        raise ValueError("Retention days and batch size must be positive.")
    settings = get_settings()
    database = Database(settings.database_url)
    checkpoints = PostgresCheckpointLifecycle(settings.database_url)
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    try:
        async with database.engine.connect() as connection:
            rows = await connection.execute(
                text(
                    """
                    SELECT id FROM agent_runs
                    WHERE status IN ('COMPLETED', 'FAILED', 'CANCELLED')
                      AND completed_at < :cutoff
                    ORDER BY completed_at, id
                    LIMIT :batch_size
                    """
                ),
                {"cutoff": cutoff, "batch_size": batch_size},
            )
            run_ids = [UUID(str(value)) for value in rows.scalars()]
        if apply and run_ids:
            saver = await checkpoints.start()
            for run_id in run_ids:
                await saver.adelete_thread(str(run_id))
        print(f"checkpoint_candidates={len(run_ids)} applied={apply}")
        return len(run_ids)
    finally:
        await checkpoints.stop()
        await database.dispose()


if __name__ == "__main__":
    arguments = parse_args()
    asyncio.run(
        run(
            retention_days=arguments.retention_days,
            batch_size=arguments.batch_size,
            apply=arguments.apply,
        )
    )
