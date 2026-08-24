from io import BytesIO

import pytest
from pypdf import PdfWriter

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


async def test_pdf_page_limit_is_enforced_before_extraction() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    content = BytesIO()
    writer.write(content)
    parser = TextSourceParser(max_pdf_pages=1)

    with pytest.raises(SourceParsingError, match="page limit"):
        await parser.parse(
            filename="too-many-pages.pdf",
            mime_type="application/pdf",
            content=content.getvalue(),
        )


async def test_text_extraction_character_limit_is_enforced() -> None:
    parser = TextSourceParser(max_extracted_characters=5)

    text = await parser.parse(
        filename="large.txt", mime_type="text/plain", content=b"123456789"
    )

    assert text == "12345"
