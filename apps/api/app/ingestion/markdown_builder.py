"""Build structured markdown from extracted document content."""

import logging
from dataclasses import dataclass, field
from typing import Any

from .extractors.base import ExtractedContent, Image, Table

logger = logging.getLogger(__name__)


@dataclass
class MarkdownDocument:
    """Structured markdown document with metadata."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    tables: list[Table] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    # The file this content came from, so a citation can name its source.
    source_filename: str = ""

    def to_markdown(self) -> str:
        """Return full markdown content."""
        return self.content


class MarkdownBuilder:
    """Build well-structured markdown from extracted content."""

    def __init__(
        self,
        include_metadata: bool = True,
        include_tables: bool = True,
        include_images: bool = True,
        table_format: str = "github",  # github, simple
    ):
        self.include_metadata = include_metadata
        self.include_tables = include_tables
        self.include_images = include_images
        self.table_format = table_format

    def build(self, extracted: ExtractedContent) -> MarkdownDocument:
        """Build markdown document from extracted content."""
        parts = []

        # Add metadata header if enabled
        if self.include_metadata and extracted.metadata:
            parts.append(self._build_metadata_section(extracted))

        # Add main text content
        if extracted.text.strip():
            parts.append(extracted.text.strip())

        # Add tables section if enabled and tables exist
        if self.include_tables and extracted.tables:
            parts.append(self._build_tables_section(extracted.tables))

        # Add images section if enabled
        if self.include_images and extracted.images:
            parts.append(self._build_images_section(extracted.images))

        content = "\n\n".join(filter(None, parts))

        return MarkdownDocument(
            content=content,
            metadata=extracted.metadata,
            tables=extracted.tables,
            images=extracted.images,
            source_filename=extracted.source_filename,
        )

    def _build_metadata_section(self, extracted: ExtractedContent) -> str:
        """Build metadata header section."""
        lines = ["---"]
        lines.append(f"source_file: {extracted.source_filename}")
        lines.append(f"content_type: {extracted.content_type.value}")
        lines.append(f"extractor: {extracted.metadata.get('extractor', 'unknown')}")

        for key, value in extracted.metadata.items():
            if key not in ("extractor",):
                lines.append(f"{key}: {value}")

        lines.append("---")
        return "\n".join(lines)

    def _build_tables_section(self, tables: list[Table]) -> str:
        """Build tables section."""
        if not tables:
            return ""

        parts = ["## Extracted Tables"]

        for i, table in enumerate(tables):
            table_md = table.to_markdown()
            if table_md:
                if table.sheet_name:
                    parts.append(f"### Table {i + 1}: {table.sheet_name}")
                elif table.page_number:
                    parts.append(f"### Table {i + 1} (Page {table.page_number})")
                else:
                    parts.append(f"### Table {i + 1}")
                parts.append(table_md)

        return "\n\n".join(parts)

    def _build_images_section(self, images: list[Image]) -> str:
        """Build images section with references."""
        if not images:
            return ""

        parts = ["## Images"]

        for i, img in enumerate(images):
            alt = img.alt_text or f"Image {i + 1}"
            if img.page_number:
                alt += f" (Page {img.page_number})"
            if img.caption:
                alt += f" - {img.caption}"

            # Note: actual image data is not embedded in markdown
            # In a real implementation, you'd save images and reference them
            parts.append(f"![{alt}](image_{i + 1}.png)")

        return "\n\n".join(parts)


def build_simple_markdown(extracted: ExtractedContent) -> MarkdownDocument:
    """Convenience function for simple markdown output."""
    builder = MarkdownBuilder(
        include_metadata=True,
        include_tables=True,
        include_images=False,  # Skip images for simple text output
    )
    return builder.build(extracted)
