import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from laoshiren.application.sources.dto import SourceProcessingJobDTO
from laoshiren.application.sources.ports import SourceParsingError
from laoshiren.application.sources.service import (
    SourceApplicationService,
    build_source_chunks,
)

pytestmark = pytest.mark.asyncio


class MemoryStorage:
    async def read(self, *, object_key: str) -> bytes:
        assert object_key == "source.pdf"
        return b"content"

    async def put(
        self, *, object_key: str, chunks: AsyncIterator[bytes]
    ) -> tuple[int, str]:
        raise AssertionError("not used")

    async def delete(self, *, object_key: str) -> None:
        raise AssertionError("not used")


class SlowParser:
    async def parse(self, *, filename: str, mime_type: str, content: bytes) -> str:
        await asyncio.sleep(1)
        return "too late"


async def test_claimed_source_parse_timeout_becomes_terminal_parse_error() -> None:
    service = SourceApplicationService(  # type: ignore[arg-type]
        lambda: None,
        MemoryStorage(),
        max_upload_bytes=1024,
        parser=SlowParser(),
        parse_timeout_seconds=0.001,
    )
    job = SourceProcessingJobDTO(
        id=uuid4(),
        user_id=uuid4(),
        title="source.pdf",
        mime_type="application/pdf",
        object_key="source.pdf",
        attempt_count=1,
    )

    with pytest.raises(SourceParsingError, match="time limit"):
        await service.extract_claimed_text(job)


async def test_source_chunks_have_stable_ordinals_offsets_and_overlap() -> None:
    source_id = uuid4()
    chunks = build_source_chunks(
        source_id=source_id,
        text="abcdefghij",
        chunk_characters=6,
        overlap=2,
    )

    assert [(item.ordinal, item.char_start, item.char_end) for item in chunks] == [
        (0, 0, 6),
        (1, 4, 10),
    ]
    assert [item.content for item in chunks] == ["abcdef", "efghij"]
    assert all(item.source_id == source_id for item in chunks)
