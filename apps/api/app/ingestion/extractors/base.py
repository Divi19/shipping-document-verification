"""Base classes and interfaces for document extractors."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ContentType(StrEnum):
    """Supported document content types."""

    PDF = "application/pdf"
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    TEXT = "text/plain"
    UNKNOWN = "application/octet-stream"


class IngestionStatus(StrEnum):
    """Outcome of converting an attachment into readable document content."""

    SUCCESS = "success"
    UNREADABLE = "unreadable"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


@dataclass
class Table:
    """Represents an extracted table."""

    headers: list[str]
    rows: list[list[str]]
    sheet_name: str | None = None
    page_number: int | None = None

    def to_markdown(self) -> str:
        """Convert table to GitHub-flavored markdown."""
        if not self.headers and not self.rows:
            return ""

        # Use headers if available, otherwise use first row as headers
        if self.headers:
            header_row = self.headers
            data_rows = self.rows
        elif self.rows:
            header_row = self.rows[0]
            data_rows = self.rows[1:]
        else:
            return ""

        # Escape pipe characters in cells
        def escape_cell(cell: str) -> str:
            return str(cell).replace("|", "\\|").replace("\n", " ")

        header_escaped = [escape_cell(h) for h in header_row]
        separator = ["---"] * len(header_escaped)

        lines = [
            "| " + " | ".join(header_escaped) + " |",
            "| " + " | ".join(separator) + " |",
        ]

        for row in data_rows:
            row_escaped = [escape_cell(cell) for cell in row]
            # Pad row to match header length
            while len(row_escaped) < len(header_escaped):
                row_escaped.append("")
            lines.append("| " + " | ".join(row_escaped[: len(header_escaped)]) + " |")

        return "\n".join(lines)


@dataclass
class Image:
    """Represents an extracted image with optional OCR text."""

    data: bytes
    mime_type: str
    alt_text: str | None = None
    page_number: int | None = None
    caption: str | None = None


@dataclass
class ExtractedContent:
    """Container for extracted document content."""

    text: str = ""
    tables: list[Table] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    content_type: ContentType = ContentType.UNKNOWN
    source_filename: str = ""
    status: IngestionStatus = IngestionStatus.SUCCESS
    diagnostics: list[str] = field(default_factory=list)

    def has_meaningful_text(self, min_chars: int = 100) -> bool:
        """Check if extracted text is substantial enough."""
        return len(self.text.strip()) >= min_chars

    def text_ratio(self) -> float:
        """Estimate text-to-content ratio (rough heuristic)."""
        total_content = len(self.text) + sum(len(t.to_markdown()) for t in self.tables)
        if total_content == 0:
            return 0.0
        return len(self.text) / total_content


class DocumentExtractor(ABC):
    """Base interface for document extractors."""

    supported_types: list[ContentType] = []

    @abstractmethod
    def extract(self, file_path: Path) -> ExtractedContent:
        """Extract content from a file path."""
        pass

    @abstractmethod
    def extract_bytes(self, content: bytes, filename: str) -> ExtractedContent:
        """Extract content from raw bytes."""
        pass

    def can_handle(self, content_type: ContentType) -> bool:
        """Check if this extractor can handle the given content type."""
        return content_type in self.supported_types

    @classmethod
    def from_filename(cls, filename: str) -> ContentType:
        """Determine content type from filename."""
        suffix = Path(filename).suffix.lower()
        mapping = {
            ".pdf": ContentType.PDF,
            ".doc": ContentType.DOCX,
            ".docx": ContentType.DOCX,
            ".xlsx": ContentType.XLSX,
            ".xls": ContentType.XLSX,
            ".txt": ContentType.TEXT,
            ".md": ContentType.TEXT,
            ".csv": ContentType.TEXT,
            ".rtf": ContentType.TEXT,
        }
        return mapping.get(suffix, ContentType.UNKNOWN)

    @classmethod
    def from_bytes(cls, content: bytes, filename: str = "") -> ContentType:
        """Fallback detector when the file extension is missing or unreliable."""
        detected = cls.from_filename(filename)
        if detected != ContentType.UNKNOWN:
            return detected

        if content.startswith(b"%PDF"):
            return ContentType.PDF

        if content.startswith(b"PK"):
            try:
                import io
                import zipfile

                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    names = set(archive.namelist())
                    if any(name.startswith("word/") for name in names):
                        return ContentType.DOCX
                    if any(name.startswith("xl/") for name in names):
                        return ContentType.XLSX
            except Exception:
                pass

        if content and all(byte in b"\t\n\r\x20" or 32 <= byte < 127 for byte in content[:512]):
            return ContentType.TEXT

        return ContentType.UNKNOWN
