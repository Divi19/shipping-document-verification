"""High-level document ingestion service."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .cache import DocumentCache
from .extractors import (
    ContentType,
    ExtractedContent,
    IngestionStatus,
    get_extractor,
)
from .extractors.base import DocumentExtractor as BaseExtractor
from .markdown_builder import MarkdownBuilder, MarkdownDocument

logger = logging.getLogger(__name__)


class DocumentIngestionConfig:
    """Configuration for document ingestion service."""

    def __init__(
        self,
        gemini_api_key: str | None = None,
        gemini_model: str = "gemini-2.5-flash-lite",
        cache_dir: Path | None = None,
        cache_size_gb: float = 1.0,
        vision_fallback_threshold: float = 0.3,
        enable_vision_fallback: bool = True,
        enable_local_ocr: bool = True,
        ocr_render_scale: float = 2.0,
        max_pdf_pages: int = 20,
        max_pdf_bytes: int = 25 * 1024 * 1024,
        max_concurrent: int = 4,
        request_timeout: int = 30,
    ):
        self.gemini_api_key = gemini_api_key
        self.gemini_model = gemini_model
        self.cache_dir = cache_dir or Path(".cache/document_ingestion")
        self.cache_size_gb = cache_size_gb
        self.vision_fallback_threshold = vision_fallback_threshold
        self.enable_vision_fallback = enable_vision_fallback
        self.enable_local_ocr = enable_local_ocr
        self.ocr_render_scale = ocr_render_scale
        self.max_pdf_pages = max_pdf_pages
        self.max_pdf_bytes = max_pdf_bytes
        self.max_concurrent = max_concurrent
        self.request_timeout = request_timeout


class DocumentIngestionService:
    """Main service for document ingestion."""

    def __init__(self, config: DocumentIngestionConfig | None = None):
        self.config = config or DocumentIngestionConfig()
        self._cache: DocumentCache | None = None
        self._executor = ThreadPoolExecutor(max_workers=self.config.max_concurrent)
        self._extractors: dict[ContentType, BaseExtractor] = {}

    def ingest(
        self,
        source: str | bytes | bytearray | Path | object,
        filename: str | None = None,
    ) -> MarkdownDocument:
        """Simple public entry point for any supported document input.

        Accepts raw text, file paths, bytes, or file-like objects and routes them to the
        correct extractor without forcing callers to know the internal document type system.
        """
        if isinstance(source, Path):
            return self.ingest_file(source)

        if isinstance(source, str):
            candidate_path = Path(source)
            if candidate_path.exists() and candidate_path.is_file():
                return self.ingest_file(candidate_path)
            return self.ingest_text(source, filename or "input.txt")

        if isinstance(source, (bytes, bytearray)):
            return self.ingest_bytes(bytes(source), filename or "document.bin")

        if hasattr(source, "read"):
            data = source.read()
            if isinstance(data, str):
                return self.ingest_text(data, filename or "input.txt")
            return self.ingest_bytes(data, filename or "document.bin")

        raise TypeError(
            "Unsupported ingestion source. Pass a file path, text string, bytes, "
            "or a readable file-like object."
        )

    __call__ = ingest

    @property
    def cache(self) -> DocumentCache:
        """Get or create cache instance."""
        if self._cache is None:
            self._cache = DocumentCache(self.config.cache_dir, self.config.cache_size_gb)
        return self._cache

    def _get_extractor(self, content_type: ContentType) -> BaseExtractor:
        """Get or create extractor for content type."""
        if content_type not in self._extractors:
            if content_type == ContentType.PDF:
                self._extractors[content_type] = get_extractor(
                    content_type,
                    gemini_api_key=self.config.gemini_api_key,
                    gemini_model=self.config.gemini_model,
                    vision_fallback_threshold=self.config.vision_fallback_threshold,
                    enable_vision_fallback=self.config.enable_vision_fallback,
                    enable_local_ocr=self.config.enable_local_ocr,
                    ocr_render_scale=self.config.ocr_render_scale,
                    max_pdf_pages=self.config.max_pdf_pages,
                    max_pdf_bytes=self.config.max_pdf_bytes,
                )
            else:
                self._extractors[content_type] = get_extractor(content_type)
        return self._extractors[content_type]

    def ingest_file(self, file_path: Path) -> MarkdownDocument:
        """
        Ingest a document from file path.

        Args:
            file_path: Path to the document file

        Returns:
            MarkdownDocument with extracted content
        """
        content = file_path.read_bytes()
        return self.ingest_bytes(content, file_path.name)

    def ingest_bytes(self, content: bytes, filename: str) -> MarkdownDocument:
        """
        Ingest a document from raw bytes.

        Args:
            content: Raw document bytes
            filename: Original filename (used for type detection)

        Returns:
            MarkdownDocument with extracted content
        """
        extracted = self.extract_bytes(content, filename)
        return MarkdownBuilder(include_images=False).build(extracted)

    def extract_bytes(self, content: bytes, filename: str) -> ExtractedContent:
        """Extract structured content without flattening it to Markdown."""
        content_type = BaseExtractor.from_bytes(content, filename)
        if content_type == ContentType.UNKNOWN:
            return ExtractedContent(
                content_type=ContentType.UNKNOWN,
                source_filename=filename,
                status=IngestionStatus.UNSUPPORTED,
                diagnostics=["The attachment type is not supported."],
            )
        logger.info("Ingesting %s as %s", filename, content_type.value)

        # Check cache first
        extractor = self._get_extractor(content_type)
        extractor_name = extractor.__class__.__name__

        cached = self.cache.get(
            content,
            extractor_name,
            vision_fallback_threshold=self.config.vision_fallback_threshold,
            enable_vision_fallback=self.config.enable_vision_fallback,
            enable_local_ocr=self.config.enable_local_ocr,
            ocr_render_scale=self.config.ocr_render_scale,
            max_pdf_pages=self.config.max_pdf_pages,
            max_pdf_bytes=self.config.max_pdf_bytes,
        )
        if cached:
            logger.info("Cache hit for %s", filename)
            return cached

        try:
            extracted = extractor.extract_bytes(content, filename)
        except Exception as exc:
            logger.exception("Document extraction failed for %s", filename)
            extracted = ExtractedContent(
                content_type=content_type,
                source_filename=filename,
                status=IngestionStatus.FAILED,
                diagnostics=[f"{type(exc).__name__}: {exc}"],
            )

        if (
            extracted.status == IngestionStatus.SUCCESS
            and not extracted.text.strip()
            and not extracted.tables
        ):
            extracted.status = IngestionStatus.UNREADABLE
            extracted.diagnostics.append("No readable text or tables were extracted.")

        # Cache result
        self.cache.set(
            content,
            extractor_name,
            extracted,
            vision_fallback_threshold=self.config.vision_fallback_threshold,
            enable_vision_fallback=self.config.enable_vision_fallback,
            enable_local_ocr=self.config.enable_local_ocr,
            ocr_render_scale=self.config.ocr_render_scale,
            max_pdf_pages=self.config.max_pdf_pages,
            max_pdf_bytes=self.config.max_pdf_bytes,
        )

        return extracted

    def ingest_text(self, text: str, filename: str = "input.txt") -> MarkdownDocument:
        """
        Ingest plain text (copy-paste).

        Args:
            text: Plain text content
            filename: Optional filename for context

        Returns:
            MarkdownDocument with the text content
        """
        content = text.encode("utf-8")
        return self.ingest_bytes(content, filename)

    async def ingest_file_async(self, file_path: Path) -> MarkdownDocument:
        """Async version of ingest_file."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self.ingest_file, file_path)

    async def ingest_bytes_async(self, content: bytes, filename: str) -> MarkdownDocument:
        """Async version of ingest_bytes."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self.ingest_bytes, content, filename)

    async def ingest_multiple_async(self, files: list[tuple[bytes, str]]) -> list[MarkdownDocument]:
        """Ingest multiple documents concurrently."""
        tasks = [self.ingest_bytes_async(content, filename) for content, filename in files]
        return await asyncio.gather(*tasks)

    def get_cache_stats(self) -> dict[str, object]:
        """Get cache statistics."""
        return self.cache.stats()

    def clear_cache(self) -> int:
        """Clear the cache."""
        return self.cache.clear()

    def shutdown(self) -> None:
        """Shutdown the service."""
        self._executor.shutdown(wait=True)
        for extractor in self._extractors.values():
            close = getattr(extractor, "close", None)
            if callable(close):
                close()
        if self._cache:
            self._cache.close()


# Global service instance (for FastAPI dependency injection)
_service_instance: DocumentIngestionService | None = None


def get_document_service(
    config: DocumentIngestionConfig | None = None,
) -> DocumentIngestionService:
    """Get or create global document ingestion service."""
    global _service_instance
    if _service_instance is None:
        _service_instance = DocumentIngestionService(config)
    return _service_instance


def set_document_service(service: DocumentIngestionService) -> None:
    """Set global document ingestion service (for testing)."""
    global _service_instance
    _service_instance = service


def ingest_document(
    source: str | bytes | bytearray | Path | object,
    filename: str | None = None,
    config: DocumentIngestionConfig | None = None,
) -> MarkdownDocument:
    """Convenience helper for the rest of the pipeline."""
    return get_document_service(config).ingest(source, filename=filename)
