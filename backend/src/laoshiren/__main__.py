import asyncio
import sys

import uvicorn

from laoshiren.config.asyncio_policy import configure_asyncio_policy


def main() -> None:
    configure_asyncio_policy()
    config = uvicorn.Config("laoshiren.main:app", host="127.0.0.1", port=8000, loop="none")
    server = uvicorn.Server(config)
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(server.serve())
        return
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
