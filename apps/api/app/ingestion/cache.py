"""Caching layer for document ingestion."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import diskcache  # type: ignore[import-untyped]

from .extractors.base import ContentType, ExtractedContent, Image, IngestionStatus, Table

logger = logging.getLogger(__name__)


class DocumentCache:
    """Persistent cache for document extraction results."""

    def __init__(self, cache_dir: Path, max_size_gb: float = 1.0):
        """
        Initialize cache.

        Args:
            cache_dir: Directory to store cache files
            max_size_gb: Maximum cache size in GB
        """
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # diskcache uses bytes for size limit
        self.cache = diskcache.Cache(
            directory=str(cache_dir),
            size_limit=int(max_size_gb * 1024 * 1024 * 1024),
        )

    def _make_key(self, content_hash: str, extractor_name: str, config_hash: str) -> str:
        """Create a cache key from content hash, extractor, and config."""
        return f"{extractor_name}:{config_hash}:{content_hash}"

    def _hash_content(self, content: bytes) -> str:
        """Generate SHA256 hash of content."""
        return hashlib.sha256(content).hexdigest()

    def _hash_config(self, **config: object) -> str:
        """Generate hash of extraction configuration."""
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()[:16]

    @staticmethod
    def _deserialize(cached: dict[str, Any]) -> ExtractedContent:
        """Restore cached dictionaries to the structured ingestion dataclasses."""
        return ExtractedContent(
            text=str(cached.get("text", "")),
            tables=[Table(**table) for table in cached.get("tables", [])],
            images=[Image(**image) for image in cached.get("images", [])],
            metadata=dict(cached.get("metadata", {})),
            content_type=ContentType(cached.get("content_type", ContentType.UNKNOWN)),
            source_filename=str(cached.get("source_filename", "")),
            status=IngestionStatus(cached.get("status", IngestionStatus.SUCCESS)),
            diagnostics=list(cached.get("diagnostics", [])),
        )

    def get(
        self,
        content: bytes,
        extractor_name: str,
        **config: object,
    ) -> ExtractedContent | None:
        """Get cached extraction result if available."""
        content_hash = self._hash_content(content)
        config_hash = self._hash_config(**config)
        key = self._make_key(content_hash, extractor_name, config_hash)

        try:
            cached = self.cache.get(key)
            if cached:
                logger.debug(f"Cache hit for {extractor_name} ({content_hash[:8]})")
                return self._deserialize(cached)
        except Exception as e:
            logger.warning(f"Cache read error: {e}")

        return None

    def set(
        self,
        content: bytes,
        extractor_name: str,
        result: ExtractedContent,
        **config: object,
    ) -> None:
        """Cache extraction result."""
        content_hash = self._hash_content(content)
        config_hash = self._hash_config(**config)
        key = self._make_key(content_hash, extractor_name, config_hash)

        try:
            # Convert to dict for serialization
            cached_data = {
                "text": result.text,
                "tables": [
                    {
                        "headers": table.headers,
                        "rows": table.rows,
                        "sheet_name": table.sheet_name,
                        "page_number": table.page_number,
                    }
                    for table in result.tables
                ],
                "images": [
                    {
                        "data": image.data,
                        "mime_type": image.mime_type,
                        "alt_text": image.alt_text,
                        "page_number": image.page_number,
                        "caption": image.caption,
                    }
                    for image in result.images
                ],
                "metadata": result.metadata,
                "content_type": result.content_type.value,
                "source_filename": result.source_filename,
                "status": result.status.value,
                "diagnostics": result.diagnostics,
            }
            self.cache.set(key, cached_data)
            logger.debug(f"Cached result for {extractor_name} ({content_hash[:8]})")
        except Exception as e:
            logger.warning(f"Cache write error: {e}")

    def clear(self) -> int:
        """Clear all cache entries. Returns number of cleared entries."""
        count = len(self.cache)
        self.cache.clear()
        logger.info(f"Cleared {count} cache entries")
        return count

    def stats(self) -> dict[str, object]:
        """Get cache statistics."""
        return {
            "size_mb": self.cache.volume() / (1024 * 1024),
            "entry_count": len(self.cache),
            "directory": str(self.cache_dir),
        }

    def close(self) -> None:
        """Close cache connection."""
        self.cache.close()


# Global cache instance (initialized lazily)
_cache_instance: DocumentCache | None = None


def get_cache(cache_dir: Path | None = None, max_size_gb: float = 1.0) -> DocumentCache:
    """Get or create global cache instance."""
    global _cache_instance
    if _cache_instance is None:
        if cache_dir is None:
            cache_dir = Path(".cache/document_ingestion")
        _cache_instance = DocumentCache(cache_dir, max_size_gb)
    return _cache_instance
