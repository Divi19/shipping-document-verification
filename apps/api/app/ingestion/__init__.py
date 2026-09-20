"""Document ingestion module."""

from app.ingestion.parser import EmailParser
from app.ingestion.service import (
    DocumentIngestionService,
    DocumentIngestionConfig,
    get_document_service,
)
from app.ingestion.markdown_builder import MarkdownBuilder, MarkdownDocument, build_simple_markdown
from app.ingestion.extractors import (
    ContentType,
    DocumentExtractor,
    ExtractedContent,
    Table,
    Image,
    TextExtractor,
    XLSXExtractor,
    DocxExtractor,
    PDFExtractor,
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