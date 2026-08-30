import asyncio
import hashlib
from collections.abc import AsyncIterator
from pathlib import Path


class LocalObjectStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _resolve(self, object_key: str) -> Path:
        target = (self._root / object_key).resolve()
        if self._root not in target.parents:
            raise ValueError("Invalid object key.")
        return target

    async def put(self, *, object_key: str, chunks: AsyncIterator[bytes]) -> tuple[int, str]:
        target = self._resolve(object_key)
        temporary = target.with_suffix(f"{target.suffix}.uploading")
        await asyncio.to_thread(temporary.parent.mkdir, parents=True, exist_ok=True)
        size = 0
        digest = hashlib.sha256()
        try:
            with temporary.open("wb") as output:
                async for chunk in chunks:
                    await asyncio.to_thread(output.write, chunk)
                    digest.update(chunk)
                    size += len(chunk)
            await asyncio.to_thread(temporary.replace, target)
        except Exception:
            await asyncio.to_thread(temporary.unlink, missing_ok=True)
            raise
        return size, digest.hexdigest()

    async def delete(self, *, object_key: str) -> None:
        await asyncio.to_thread(self._resolve(object_key).unlink, missing_ok=True)

    async def read(self, *, object_key: str) -> bytes:
        return await asyncio.to_thread(self._resolve(object_key).read_bytes)

    async def list_object_keys(self) -> list[str]:
        def _walk() -> list[str]:
            if not self._root.exists():
                return []
            keys: list[str] = []
            for path in self._root.rglob("*"):
                if not path.is_file():
                    continue
                if path.name.endswith(".uploading"):
                    continue
                keys.append(path.relative_to(self._root).as_posix())
            return keys

        return await asyncio.to_thread(_walk)
