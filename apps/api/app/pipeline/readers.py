"""Readers turn a file into text. One reader per format, chosen by type.

A cascade that tries plain text first and falls back to a parser is the wrong
shape here: decoding a PDF or an .xlsx as text yields plausible-looking
garbage instead of a clean failure. The reader is selected from the detected
file type, and a *different* reader is only tried when the chosen one fails.

Readers raise :class:`ReaderError` on failure. Returning empty text silently is
never acceptable: an unreadable document has to reach the review queue.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

TEXT_SUFFIXES = frozenset({".txt", ".md", ".csv"})
BINARY_SUFFIXES = frozenset({".pdf", ".docx", ".doc", ".xlsx", ".xls"})


class ReaderError(RuntimeError):
    """A reader could not produce usable text from a file."""


def strip_front_matter(text: str) -> str:
    """Drop a leading ``---`` metadata block so it never counts as content."""
    if not text.startswith("---"):
        return text
    _, separator, body = text.partition("\n---")
    return body if separator else text


@runtime_checkable
class DocumentReader(Protocol):
    """Anything that can turn a file into text.

    Document-format work plugs in here: implement this protocol and the
    orchestrator will use it without further changes.
    """

    name: str

    def can_read(self, path: Path) -> bool:
        """Whether this reader handles the file's type."""

    def read(self, path: Path) -> str:
        """Return the document's text, or raise :class:`ReaderError`."""


class PlainTextReader:
    """Read .txt/.md/.csv, refusing anything that is not really text."""

    name = "plain-text"

    def can_read(self, path: Path) -> bool:
        return path.suffix.lower() in TEXT_SUFFIXES

    def read(self, path: Path) -> str:
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ReaderError(f"cannot open {path.name}: {exc}") from exc
        if data.startswith(b"%PDF") or data[:2] == b"PK":
            raise ReaderError(f"{path.name} is a binary document with a text extension")
        text = data.decode("utf-8", errors="replace")
        if not text.strip():
            raise ReaderError(f"{path.name} is empty")
        return text


class IngestionServiceReader:
    """Adapter onto the document ingestion service (PDF/Word/Excel).

    Imported lazily so the pipeline, its tests and the scoring harness keep
    running on a machine without the heavier extraction dependencies.
    """

    name = "ingestion-service"

    def can_read(self, path: Path) -> bool:
        return path.suffix.lower() in BINARY_SUFFIXES

    def read(self, path: Path) -> str:
        try:
            from app.ingestion.service import get_document_service
        except ImportError as exc:  # pragma: no cover - depends on optional extras
            raise ReaderError(f"ingestion service unavailable: {exc}") from exc

        try:
            document = get_document_service().ingest_file(path)
        except Exception as exc:  # noqa: BLE001 - any reader failure is a ReaderError
            raise ReaderError(f"{path.name}: {exc}") from exc

        # The service reports a failed extraction in metadata and still returns a
        # document whose body is only the metadata header. That is a failure, and
        # it must not reach the pipeline looking like a readable document.
        failure = document.metadata.get("error")
        if failure:
            raise ReaderError(f"{path.name}: {failure}")

        status = getattr(document, "status", None)
        if status is not None and status != "success":
            detail = "; ".join(getattr(document, "diagnostics", [])) or str(status)
            raise ReaderError(f"{path.name}: {detail}")

        if not strip_front_matter(document.content).strip():
            raise ReaderError(f"{path.name}: no text extracted (scan or damaged file)")
        return document.content


def default_readers() -> tuple[DocumentReader, ...]:
    """The readers used unless a caller supplies its own set."""
    return (PlainTextReader(), IngestionServiceReader())


def readers_for(path: Path, readers: Sequence[DocumentReader]) -> list[DocumentReader]:
    """Readers that handle this file's type, in preference order."""
    return [reader for reader in readers if reader.can_read(path)]
