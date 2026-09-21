"""Tests for the bounded native and local-OCR PDF fallback chain."""

import io

import pytest
from PIL import Image as PILImage
from pypdf import PdfWriter

from app.config import resolve_data_dir
from app.ingestion.extractors import IngestionStatus
from app.ingestion.extractors.pdf_extractor import OcrPage, PDFExtractor


class _FakeOcrEngine:
    def is_available(self) -> bool:
        return True

    def extract(self, image: PILImage.Image, page_number: int) -> OcrPage:
        assert image.width > 0
        return OcrPage(
            text=(
                "Shipper: Example Trading Ltd\n"
                "Consignee: Example Buyer Ltd\n"
                "Gross Weight: 12,500 KG"
            ),
            words=[
                {
                    "text": "Shipper:",
                    "confidence": 96.5,
                    "left": 10,
                    "top": 12,
                    "width": 50,
                    "height": 12,
                    "page_number": page_number,
                }
            ],
        )


def _blank_pdf(page_count: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=200, height=200)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_image_only_pdf_falls_back_to_local_ocr_with_word_evidence() -> None:
    extractor = PDFExtractor(
        enable_vision_fallback=False,
        ocr_engine=_FakeOcrEngine(),
    )

    result = extractor.extract_bytes(_blank_pdf(), "scan.pdf")

    assert result.status == IngestionStatus.SUCCESS
    assert result.metadata["extractor"] == "tesseract"
    assert result.metadata["ocr_average_confidence"] == 96.5
    assert result.metadata["ocr_words"] == [
        {
            "text": "Shipper:",
            "confidence": 96.5,
            "left": 10,
            "top": 12,
            "width": 50,
            "height": 12,
            "page_number": 1,
        }
    ]
    assert any(item.startswith("Native PDF") for item in result.diagnostics)


def test_corrupt_pdf_returns_typed_unreadable_result() -> None:
    extractor = PDFExtractor(enable_vision_fallback=False, enable_local_ocr=False)

    result = extractor.extract_bytes(b"%PDF-1.5\ncorrupt", "corrupt.pdf")

    assert result.status == IngestionStatus.UNREADABLE
    assert result.text == ""
    assert any("Native PDF extraction failed" in item for item in result.diagnostics)


def test_page_limit_applies_to_native_and_rendered_paths() -> None:
    extractor = PDFExtractor(
        enable_vision_fallback=False,
        ocr_engine=_FakeOcrEngine(),
        max_pdf_pages=1,
    )

    result = extractor.extract_bytes(_blank_pdf(page_count=2), "too-many-pages.pdf")

    assert result.status == IngestionStatus.UNREADABLE
    assert sum("configured 1 pages" in item for item in result.diagnostics) == 2


def test_participant_pdf_uses_native_text_when_available() -> None:
    path = resolve_data_dir() / "attachments" / "email_059_SI.pdf"
    if not path.exists():
        pytest.skip("Participant bundle is not available")

    result = PDFExtractor(
        enable_vision_fallback=False,
        enable_local_ocr=False,
    ).extract(path)

    assert result.status == IngestionStatus.SUCCESS
    assert result.metadata == {"extractor": "pypdf", "page_count": 1}
    assert "APRIL FINE PAPER TRADING" in result.text
