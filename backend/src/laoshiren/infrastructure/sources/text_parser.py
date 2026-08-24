import asyncio
from io import BytesIO
from multiprocessing import get_context
from multiprocessing.connection import Connection
from pathlib import PurePath
from typing import cast

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from laoshiren.application.sources.ports import SourceParsingError

type PdfWorkerResult = tuple[bool, str]


def _extract_pdf_text(
    content: bytes,
    *,
    max_pages: int,
    max_page_characters: int,
    max_characters: int,
) -> str:
    reader = PdfReader(BytesIO(content))
    if reader.is_encrypted:
        raise SourceParsingError("Encrypted PDF Sources are not supported.")
    if len(reader.pages) > max_pages:
        raise SourceParsingError("PDF exceeds the configured page limit.")
    parts: list[str] = []
    remaining = max_characters
    for page in reader.pages:
        if remaining <= 0:
            break
        page_text = (page.extract_text() or "")[:max_page_characters]
        parts.append(page_text[:remaining])
        remaining -= len(parts[-1])
    return "\n\n".join(parts)


def _pdf_worker(
    connection: Connection,
    content: bytes,
    max_pages: int,
    max_page_characters: int,
    max_characters: int,
) -> None:
    """Process entry point: return sanitized data and never propagate child exceptions."""
    try:
        text = _extract_pdf_text(
            content,
            max_pages=max_pages,
            max_page_characters=max_page_characters,
            max_characters=max_characters,
        )
        result: PdfWorkerResult = (True, text)
    except SourceParsingError as exception:
        result = (False, str(exception))
    except (PdfReadError, UnicodeError):
        result = (False, "Source text extraction failed.")
    except BaseException:
        result = (False, "PDF parser process failed.")
    try:
        connection.send(result)
    finally:
        connection.close()


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
                text = await self._parse_pdf_isolated(content)
            else:
                raise SourceParsingError("No parser is available for this Source type.")
        except (UnicodeError, PdfReadError) as exception:
            raise SourceParsingError("Source text extraction failed.") from exception
        normalized = "\n".join(line.rstrip() for line in text.splitlines()).strip()
        if not normalized:
            raise SourceParsingError("Source contains no extractable text.")
        return normalized[: self._max_extracted_characters]

    async def _parse_pdf_isolated(self, content: bytes) -> str:
        context = get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=_pdf_worker,
            args=(
                sender,
                content,
                self._max_pdf_pages,
                self._max_pdf_page_characters,
                self._max_extracted_characters,
            ),
            name="source-pdf-parser",
            daemon=True,
        )
        process.start()
        sender.close()
        try:
            while True:
                if receiver.poll():
                    succeeded, payload = cast(PdfWorkerResult, receiver.recv())
                    if not succeeded:
                        raise SourceParsingError(payload)
                    return payload
                if not process.is_alive():
                    raise SourceParsingError("PDF parser process exited without a result.")
                await asyncio.sleep(0.01)
        finally:
            receiver.close()
            if process.is_alive():
                process.terminate()
            await asyncio.to_thread(process.join, 1.0)
            if process.is_alive():
                process.kill()
                await asyncio.to_thread(process.join, 1.0)
