"""Document extractors package."""

from typing import Any

from .base import (
    ContentType,
    DocumentExtractor,
    ExtractedContent,
    ExtractionError,
    Image,
    IngestionStatus,
    Table,
)
from .docx_extractor import DocxExtractor
from .pdf_extractor import PDFExtractor
from .text_extractor import TextExtractor
from .xlsx_extractor import XLSXExtractor

__all__ = [
    "ContentType",
    "ExtractionError",
    "DocumentExtractor",
    "ExtractedContent",
    "IngestionStatus",
    "Table",
    "Image",
    "TextExtractor",
    "XLSXExtractor",
    "DocxExtractor",
    "PDFExtractor",
]


def get_extractor(content_type: ContentType, **kwargs: Any) -> DocumentExtractor:
    """Factory function to get the appropriate extractor for a content type."""
    extractors: dict[ContentType, type[DocumentExtractor]] = {
        ContentType.PDF: PDFExtractor,
        ContentType.DOCX: DocxExtractor,
        ContentType.XLSX: XLSXExtractor,
        ContentType.TEXT: TextExtractor,
    }

    extractor_class = extractors.get(content_type)
    if not extractor_class:
        raise ValueError(f"No extractor available for content type: {content_type}")

    return extractor_class(**kwargs)
