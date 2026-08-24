import asyncio
import sys
from collections.abc import Callable


def pytest_asyncio_loop_factories() -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
    if sys.platform == "win32":
        return {"windows-selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}
