from contextlib import AbstractAsyncContextManager
from types import TracebackType

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.engine import make_url


def to_psycopg_url(database_url: str) -> str:
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise ValueError("LangGraph checkpoints require PostgreSQL.")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


class PostgresCheckpointLifecycle:
    """Owns the checkpointer connection independently from business SQLAlchemy sessions."""

    def __init__(self, database_url: str) -> None:
        self._connection_url = to_psycopg_url(database_url)
        self._context: AbstractAsyncContextManager[AsyncPostgresSaver] | None = None
        self._saver: AsyncPostgresSaver | None = None

    @property
    def saver(self) -> AsyncPostgresSaver:
        if self._saver is None:
            raise RuntimeError("Checkpoint lifecycle has not been started.")
        return self._saver

    async def start(self) -> AsyncPostgresSaver:
        if self._saver is not None:
            return self._saver
        context = AsyncPostgresSaver.from_conn_string(self._connection_url)
        saver = await context.__aenter__()
        try:
            await saver.setup()
        except BaseException:
            await context.__aexit__(None, None, None)
            raise
        self._context = context
        self._saver = saver
        return saver

    async def stop(self) -> None:
        context = self._context
        self._context = None
        self._saver = None
        if context is not None:
            await context.__aexit__(None, None, None)

    async def __aenter__(self) -> AsyncPostgresSaver:
        return await self.start()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.stop()
