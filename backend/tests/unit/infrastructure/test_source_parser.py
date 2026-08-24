import pytest

from laoshiren.application.sources.ports import SourceParsingError
from laoshiren.infrastructure.sources.text_parser import TextSourceParser

pytestmark = pytest.mark.asyncio


async def test_text_and_markdown_are_decoded_and_normalized() -> None:
    parser = TextSourceParser()

    text = await parser.parse(
        filename="notes.md",
        mime_type="text/markdown",
        content="\ufeff# 标题  \n\n正文\n".encode(),
    )

    assert text == "# 标题\n\n正文"


async def test_empty_text_source_is_rejected() -> None:
    parser = TextSourceParser()

    with pytest.raises(SourceParsingError, match="no extractable text"):
        await parser.parse(filename="empty.txt", mime_type="text/plain", content=b"  \n")
