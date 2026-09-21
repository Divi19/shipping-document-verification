"""Document ingestion module."""

from app.ingestion.extractors import (
    ContentType,
    DocumentExtractor,
    DocxExtractor,
    ExtractedContent,
    Image,
    PDFExtractor,
    Table,
    TextExtractor,
    XLSXExtractor,
)
from app.ingestion.markdown_builder import MarkdownBuilder, MarkdownDocument, build_simple_markdown
from app.ingestion.parser import EmailParser
from app.ingestion.service import (
    DocumentIngestionConfig,
    DocumentIngestionService,
    get_document_service,
)

__all__ = [
    "EmailParser",
    "DocumentIngestionService",
    "DocumentIngestionConfig",
    "get_document_service",
    "MarkdownBuilder",
    "MarkdownDocument",
    "build_simple_markdown",
    "ContentType",
    "DocumentExtractor",
    "ExtractedContent",
    "Table",
    "Image",
    "TextExtractor",
    "XLSXExtractor",
    "DocxExtractor",
    "PDFExtractor",
]
