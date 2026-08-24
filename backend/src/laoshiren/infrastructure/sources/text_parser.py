import asyncio
from io import BytesIO
from pathlib import PurePath

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from laoshiren.application.sources.ports import SourceParsingError


class TextSourceParser:
    """First-pass parser for UTF text, Markdown and text-based PDF files."""

    def __init__(self, *, max_extracted_characters: int = 200_000) -> None:
        self._max_extracted_characters = max_extracted_characters

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

    @staticmethod
    def _parse_pdf(content: bytes) -> str:
        reader = PdfReader(BytesIO(content))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
