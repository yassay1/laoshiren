import asyncio
from io import BytesIO
from multiprocessing import get_context
from multiprocessing.connection import Connection
from pathlib import PurePath
from typing import cast
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from laoshiren.application.sources.ports import (
    ParsedSourceContent,
    ParsedSourcePage,
    SourceParsingError,
)

type PdfWorkerResult = tuple[bool, str | list[str]]


def _extract_docx_text(content: bytes, *, max_uncompressed_bytes: int) -> str:
    try:
        with ZipFile(BytesIO(content)) as archive:
            try:
                info = archive.getinfo("word/document.xml")
            except KeyError as exception:
                raise SourceParsingError("DOCX document body is missing.") from exception
            if info.file_size > max_uncompressed_bytes:
                raise SourceParsingError("DOCX exceeds the configured extraction limit.")
            document = archive.read(info)
    except BadZipFile as exception:
        raise SourceParsingError("DOCX container is invalid.") from exception
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as exception:
        raise SourceParsingError("DOCX document XML is invalid.") from exception
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t"))
        if text.strip():
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _extract_pdf_pages(
    content: bytes,
    *,
    max_pages: int,
    max_page_characters: int,
    max_characters: int,
) -> list[str]:
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
    return parts


def _pdf_worker(
    connection: Connection,
    content: bytes,
    max_pages: int,
    max_page_characters: int,
    max_characters: int,
) -> None:
    """Process entry point: return sanitized data and never propagate child exceptions."""
    try:
        pages = _extract_pdf_pages(
            content,
            max_pages=max_pages,
            max_page_characters=max_page_characters,
            max_characters=max_characters,
        )
        result: PdfWorkerResult = (True, pages)
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
    """Bounded parser for UTF text, Markdown, text PDF and DOCX files."""

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

    async def parse(
        self, *, filename: str, mime_type: str, content: bytes
    ) -> ParsedSourceContent:
        del mime_type
        extension = PurePath(filename).suffix.lower()
        try:
            if extension in {".txt", ".md"}:
                raw_pages = [content.decode("utf-8-sig")]
                page_numbers: list[int | None] = [None]
            elif extension == ".pdf":
                raw_pages = await self._parse_pdf_isolated(content)
                page_numbers = list(range(1, len(raw_pages) + 1))
            elif extension == ".docx":
                raw_pages = [
                    _extract_docx_text(
                        content,
                        max_uncompressed_bytes=self._max_extracted_characters * 8,
                    )
                ]
                page_numbers = [None]
            else:
                raise SourceParsingError("No parser is available for this Source type.")
        except (UnicodeError, PdfReadError) as exception:
            raise SourceParsingError("Source text extraction failed.") from exception
        normalized_pages: list[ParsedSourcePage] = []
        remaining = self._max_extracted_characters
        for page_number, raw in zip(page_numbers, raw_pages, strict=True):
            separator_cost = 2 if normalized_pages else 0
            remaining -= separator_cost
            if remaining <= 0:
                break
            page_text = "\n".join(line.rstrip() for line in raw.splitlines()).strip()
            page_text = page_text[:remaining]
            if page_text:
                normalized_pages.append(
                    ParsedSourcePage(page_number=page_number, text=page_text)
                )
                remaining -= len(page_text)
        pages = tuple(normalized_pages)
        normalized = "\n\n".join(page.text for page in pages)
        if not normalized:
            raise SourceParsingError("Source contains no extractable text.")
        return ParsedSourceContent(
            text=normalized, pages=pages
        )

    async def _parse_pdf_isolated(self, content: bytes) -> list[str]:
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
                        raise SourceParsingError(str(payload))
                    if not isinstance(payload, list):
                        raise SourceParsingError("PDF parser returned invalid page data.")
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
