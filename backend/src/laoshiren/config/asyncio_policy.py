import asyncio
import sys


def configure_asyncio_policy() -> None:
    """Use the event loop required by psycopg async connections on Windows."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
