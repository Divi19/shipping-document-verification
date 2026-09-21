"""PDF extractor with Docling (local) and Gemini Vision (fallback)."""

import base64
import logging
import os
from pathlib import Path
from typing import Any

import google.generativeai as genai

from .base import (
    ContentType,
    DocumentExtractor,
    ExtractedContent,
    ExtractionError,
    Image,
    Table,
)

logger = logging.getLogger(__name__)

# Overridable so the model can be moved on without a code change. The legacy
# google.generativeai package is deprecated; migrating to google-genai is
# tracked separately, but the model id here must stay current either way.
DEFAULT_VISION_MODEL = os.environ.get("GEMINI_VISION_MODEL", "gemini-2.0-flash")

# Try to import docling, but make it optional
try:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter

    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False
    DocumentConverter = None
    InputFormat = None
    PdfPipelineOptions = None


class PDFExtractor(DocumentExtractor):
    """Extractor for PDF documents with hybrid local/cloud approach."""

    supported_types = [ContentType.PDF]

    def __init__(
        self,
        gemini_api_key: str | None = None,
        vision_fallback_threshold: float = 0.3,
        enable_vision_fallback: bool = True,
        vision_model: str | None = None,
    ):
        """
        Initialize PDF extractor.

        Args:
            gemini_api_key: API key for Gemini Vision (required for fallback)
            vision_fallback_threshold: Minimum text ratio before triggering vision fallback
            enable_vision_fallback: Whether to use Gemini Vision as fallback
        """
        self.gemini_api_key = gemini_api_key
        self.vision_fallback_threshold = vision_fallback_threshold
        self.enable_vision_fallback = enable_vision_fallback and gemini_api_key is not None
        self._docling_converter: Any = None
        self._gemini_model: Any = None
        self.vision_model = vision_model or DEFAULT_VISION_MODEL

        if self.enable_vision_fallback:
            genai.configure(api_key=gemini_api_key)  # type: ignore[attr-defined]
            self._gemini_model = genai.GenerativeModel(  # type: ignore[attr-defined]
                self.vision_model
            )

    def _get_docling_converter(self) -> Any:
        """Lazy initialization of Docling converter."""
        if not DOCLING_AVAILABLE:
            raise RuntimeError("Docling not installed. Install with: pip install docling")

        if self._docling_converter is None:
            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_ocr = True
            pipeline_options.do_table_structure = True
            pipeline_options.table_structure_options.do_cell_matching = True

            self._docling_converter = DocumentConverter(
                format_options={InputFormat.PDF: pipeline_options}
            )
        return self._docling_converter

    def extract(self, file_path: Path) -> ExtractedContent:
        """Extract content from a PDF file."""
        content = file_path.read_bytes()
        return self.extract_bytes(content, file_path.name)

    def extract_bytes(self, content: bytes, filename: str) -> ExtractedContent:
        """Extract content from raw bytes."""
        # Try Docling first (local, fast)
        if DOCLING_AVAILABLE:
            try:
                result = self._extract_with_docling(content, filename)
                # Check if extraction is good enough
                if self._is_extraction_sufficient(result):
                    return result
                logger.info(
                    f"Docling extraction insufficient for {filename}, trying vision fallback"
                )
            except Exception as e:
                logger.warning(f"Docling extraction failed for {filename}: {e}")

        # Fallback to Gemini Vision
        if self.enable_vision_fallback:
            try:
                return self._extract_with_gemini_vision(content, filename)
            except Exception as e:
                logger.error(f"Gemini Vision extraction failed for {filename}: {e}")

        # Nothing could read this file. Raise rather than returning an empty
        # document, so it reaches the review queue as "unreadable" instead of
        # looking like a PDF with no fields in it.
        raise ExtractionError(
            f"{filename}: no extraction method could read this PDF "
            f"(Docling available: {DOCLING_AVAILABLE}, "
            f"vision fallback: {self.enable_vision_fallback})"
        )

    def _extract_with_docling(self, content: bytes, filename: str) -> ExtractedContent:
        """Extract using Docling (local)."""
        converter = self._get_docling_converter()

        # Write to temp file for Docling (it needs a file path)
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            result = converter.convert(tmp_path)
            doc = result.document

            # Export to markdown
            markdown_text = doc.export_to_markdown()

            # Extract tables from Docling document
            tables = self._extract_tables_from_docling(doc)

            # Extract images (Docling doesn't easily expose images, but we can note their presence)
            images: list[Image] = []

            return ExtractedContent(
                text=markdown_text,
                tables=tables,
                images=images,
                content_type=ContentType.PDF,
                source_filename=filename,
                metadata={
                    "extractor": "docling",
                    "page_count": len(doc.pages) if hasattr(doc, "pages") else 0,
                },
            )
        finally:
            # Clean up temp file
            import contextlib
            import os

            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

    def _extract_tables_from_docling(self, doc: Any) -> list[Table]:
        """Extract tables from Docling document."""
        tables = []

        # Docling stores tables in the document structure
        # This is a simplified extraction - actual implementation depends on Docling version
        try:
            for table in doc.tables:
                # Convert Docling table to our Table format
                headers = []
                rows = []

                # Docling table structure varies by version
                if hasattr(table, "data") and hasattr(table.data, "grid"):
                    grid = table.data.grid
                    if grid:
                        headers = [str(cell.text) for cell in grid[0]] if grid else []
                        rows = [[str(cell.text) for cell in row] for row in grid[1:]]

                if headers or rows:
                    tables.append(
                        Table(
                            headers=headers,
                            rows=rows,
                            page_number=getattr(table, "page_number", None),
                        )
                    )
        except Exception as e:
            logger.warning(f"Failed to extract tables from Docling: {e}")

        return tables

    def _is_extraction_sufficient(self, content: ExtractedContent) -> bool:
        """Check if local extraction yielded enough content."""
        if not content.has_meaningful_text(min_chars=50):
            return False
        # If we have tables, that's usually good
        if content.tables:
            return True
        # Check text ratio
        return content.text_ratio() >= self.vision_fallback_threshold

    def _extract_with_gemini_vision(self, content: bytes, filename: str) -> ExtractedContent:
        """Extract using Gemini Vision API (handles image-only PDFs and complex tables)."""
        if not self._gemini_model:
            raise RuntimeError("Gemini model not initialized")

        # Convert PDF to images (one per page) for vision processing
        images_data = self._pdf_to_images(content)

        if not images_data:
            return ExtractedContent(
                text="",
                content_type=ContentType.PDF,
                source_filename=filename,
                metadata={"extractor": "gemini-vision", "error": "No images generated from PDF"},
            )

        # Process each page with vision
        all_text = []
        all_tables = []

        for i, img_data in enumerate(images_data):
            page_result = self._process_page_with_vision(img_data, i + 1)
            if page_result["text"]:
                all_text.append(f"## Page {i + 1}\n\n{page_result['text']}")
            all_tables.extend(page_result["tables"])

        return ExtractedContent(
            text="\n\n".join(all_text),
            tables=all_tables,
            images=[
                Image(data=img, mime_type="image/png", page_number=i + 1)
                for i, img in enumerate(images_data)
            ],
            content_type=ContentType.PDF,
            source_filename=filename,
            metadata={"extractor": "gemini-vision", "page_count": len(images_data)},
        )

    def _pdf_to_images(self, content: bytes) -> list[bytes]:
        """Convert PDF pages to PNG images for vision processing."""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.warning("PyMuPDF not installed, cannot convert PDF to images for vision")
            return []

        images = []
        doc = fitz.open(stream=content, filetype="pdf")

        for page_num in range(len(doc)):
            page = doc[page_num]
            # Render at 2x resolution for better OCR
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            images.append(img_bytes)

        doc.close()
        return images

    def _process_page_with_vision(self, image_bytes: bytes, page_number: int) -> dict[str, Any]:
        """Process a single page image with Gemini Vision."""
        # Encode image as base64
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        prompt = """Extract all text content from this shipping/document page.
Pay special attention to:
1. Tables - extract them as structured data with headers and rows
2. Key-value pairs (like "Bill of Lading No: ABC123")
3. Any shipping/logistics document fields

Return the result as JSON with:
{
  "text": "markdown formatted text content",
  "tables": [
    {"headers": ["col1", "col2"], "rows": [["val1", "val2"], ["val3", "val4"]]}
  ]
}"""

        model = self._gemini_model
        if model is None:  # pragma: no cover - guarded by the caller
            raise ExtractionError("Gemini model not initialised")

        response = model.generate_content([prompt, {"mime_type": "image/png", "data": image_b64}])

        # Parse JSON response
        import json

        try:
            result = json.loads(response.text)
            tables = [
                Table(headers=t.get("headers", []), rows=t.get("rows", []), page_number=page_number)
                for t in result.get("tables", [])
            ]
            return {"text": result.get("text", ""), "tables": tables}
        except json.JSONDecodeError:
            # Fallback: treat as plain text
            return {"text": response.text, "tables": []}
