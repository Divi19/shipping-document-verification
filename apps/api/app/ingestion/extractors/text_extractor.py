"""Plain text and markdown extractor."""

from pathlib import Path

from .base import ContentType, DocumentExtractor, ExtractedContent


class TextExtractor(DocumentExtractor):
    """Extractor for plain text files and markdown."""

    supported_types = [ContentType.TEXT]

    def extract(self, file_path: Path) -> ExtractedContent:
        """Extract text from a file."""
        text = file_path.read_text(encoding="utf-8", errors="replace")
        return ExtractedContent(
            text=text,
            content_type=ContentType.TEXT,
            source_filename=file_path.name,
            metadata={"source": "file", "size": file_path.stat().st_size},
        )

    def extract_bytes(self, content: bytes, filename: str) -> ExtractedContent:
        """Extract text from raw bytes."""
        text = content.decode("utf-8", errors="replace")
        return ExtractedContent(
            text=text,
            content_type=ContentType.TEXT,
            source_filename=filename,
            metadata={"source": "bytes", "size": len(content)},
        )
