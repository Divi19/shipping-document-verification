"""High-level document ingestion service."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from .extractors import (
    ContentType,
    DocumentExtractor,
    ExtractedContent,
    get_extractor,
)
from .extractors.base import DocumentExtractor as BaseExtractor
from .cache import DocumentCache, get_cache
from .markdown_builder import MarkdownBuilder, MarkdownDocument, build_simple_markdown

logger = logging.getLogger(__name__)


class DocumentIngestionConfig:
    """Configuration for document ingestion service."""

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        cache_size_gb: float = 1.0,
        vision_fallback_threshold: float = 0.3,
        enable_vision_fallback: bool = True,
        max_concurrent: int = 4,
        request_timeout: int = 30,
    ):
        self.gemini_api_key = gemini_api_key
        self.cache_dir = cache_dir or Path(".cache/document_ingestion")
        self.cache_size_gb = cache_size_gb
        self.vision_fallback_threshold = vision_fallback_threshold
        self.enable_vision_fallback = enable_vision_fallback
        self.max_concurrent = max_concurrent
        self.request_timeout = request_timeout


class DocumentIngestionService:
    """Main service for document ingestion."""

    def __init__(self, config: Optional[DocumentIngestionConfig] = None):
        self.config = config or DocumentIngestionConfig()
        self._cache: Optional[DocumentCache] = None
        self._executor = ThreadPoolExecutor(max_workers=self.config.max_concurrent)
        self._extractors: dict[ContentType, BaseExtractor] = {}

    def ingest(
        self,
        source: str | bytes | bytearray | Path | object,
        filename: Optional[str] = None,
        content_type: Optional[ContentType | str] = None,
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
            self._cache = get_cache(self.config.cache_dir, self.config.cache_size_gb)
        return self._cache

    def _get_extractor(self, content_type: ContentType) -> BaseExtractor:
        """Get or create extractor for content type."""
        if content_type not in self._extractors:
            if content_type == ContentType.PDF:
                self._extractors[content_type] = get_extractor(
                    content_type,
                    gemini_api_key=self.config.gemini_api_key,
                    vision_fallback_threshold=self.config.vision_fallback_threshold,
                    enable_vision_fallback=self.config.enable_vision_fallback,
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
        # Detect content type
        content_type = BaseExtractor.from_bytes(content, filename)
        if content_type == ContentType.UNKNOWN:
            content_type = ContentType.TEXT
        logger.info(f"Ingesting {filename} as {content_type.value}")

        # Check cache first
        extractor = self._get_extractor(content_type)
        extractor_name = extractor.__class__.__name__

        cached = self.cache.get(
            content,
            extractor_name,
            vision_fallback_threshold=self.config.vision_fallback_threshold,
            enable_vision_fallback=self.config.enable_vision_fallback,
        )
        if cached:
            logger.info(f"Cache hit for {filename}")
            return build_simple_markdown(cached)

        # Extract content
        extracted = extractor.extract_bytes(content, filename)
        # Keep a record of which reader produced this text. Extractors that
        # choose between strategies (Docling, vision) set their own value.
        extracted.metadata.setdefault("extractor", extractor_name)
        # The filename travels with the content so evidence can name its source.
        extracted.metadata.setdefault("source_filename", extracted.source_filename or filename)

        # Cache result
        self.cache.set(
            content,
            extractor_name,
            extracted,
            vision_fallback_threshold=self.config.vision_fallback_threshold,
            enable_vision_fallback=self.config.enable_vision_fallback,
        )

        # Build markdown
        return build_simple_markdown(extracted)

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
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self.ingest_file, file_path)

    async def ingest_bytes_async(self, content: bytes, filename: str) -> MarkdownDocument:
        """Async version of ingest_bytes."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self.ingest_bytes, content, filename)

    async def ingest_multiple_async(self, files: list[tuple[bytes, str]]) -> list[MarkdownDocument]:
        """Ingest multiple documents concurrently."""
        tasks = [self.ingest_bytes_async(content, filename) for content, filename in files]
        return await asyncio.gather(*tasks)

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        return self.cache.stats()

    def clear_cache(self) -> int:
        """Clear the cache."""
        return self.cache.clear()

    def shutdown(self):
        """Shutdown the service."""
        self._executor.shutdown(wait=True)
        if self._cache:
            self._cache.close()


# Global service instance (for FastAPI dependency injection)
_service_instance: Optional[DocumentIngestionService] = None


def get_document_service(config: Optional[DocumentIngestionConfig] = None) -> DocumentIngestionService:
    """Get or create global document ingestion service."""
    global _service_instance
    if _service_instance is None:
        _service_instance = DocumentIngestionService(config)
    return _service_instance


def set_document_service(service: DocumentIngestionService):
    """Set global document ingestion service (for testing)."""
    global _service_instance
    _service_instance = service


def ingest_document(
    source: str | bytes | bytearray | Path | object,
    filename: Optional[str] = None,
    config: Optional[DocumentIngestionConfig] = None,
) -> MarkdownDocument:
    """Convenience helper for the rest of the pipeline."""
    return get_document_service(config).ingest(source, filename=filename)
