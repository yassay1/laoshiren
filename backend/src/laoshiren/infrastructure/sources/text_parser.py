import asyncio
from io import BytesIO
from pathlib import PurePath

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from laoshiren.application.sources.ports import SourceParsingError


class TextSourceParser:
    """First-pass parser for UTF text, Markdown and text-based PDF files."""

    def __init__(
        self,
        *,
        max_extracted_characters: int = 200_000,
        max_pdf_pages: int = 200,
        max_pdf_page_characters: int = 20_000,
    ) -> None:
        if min(
            max_extracted_characters, max_pdf_pages, max_pdf_page_characters
        ) <= 0:
            raise ValueError("Source parser limits must be positive.")
        self._max_extracted_characters = max_extracted_characters
        self._max_pdf_pages = max_pdf_pages
        self._max_pdf_page_characters = max_pdf_page_characters

    async def parse(self, *, filename: str, mime_type: str, content: bytes) -> str:
        del mime_type
        extension = PurePath(filename).suffix.lower()
        try:
            if extension in {".txt", ".md"}:
                text = content.decode("utf-8-sig")
            elif extension == ".pdf":
                text = await asyncio.to_thread(self._parse_pdf, content)
            else:
                raise SourceParsingError("No parser is available for this Source type.")
        except (UnicodeError, PdfReadError) as exception:
            raise SourceParsingError("Source text extraction failed.") from exception
        normalized = "\n".join(line.rstrip() for line in text.splitlines()).strip()
        if not normalized:
            raise SourceParsingError("Source contains no extractable text.")
        return normalized[: self._max_extracted_characters]

    def _parse_pdf(self, content: bytes) -> str:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise SourceParsingError("Encrypted PDF Sources are not supported.")
        if len(reader.pages) > self._max_pdf_pages:
            raise SourceParsingError("PDF exceeds the configured page limit.")
        parts: list[str] = []
        remaining = self._max_extracted_characters
        for page in reader.pages:
            if remaining <= 0:
                break
            page_text = (page.extract_text() or "")[: self._max_pdf_page_characters]
            parts.append(page_text[:remaining])
            remaining -= len(parts[-1])
        return "\n\n".join(parts)
