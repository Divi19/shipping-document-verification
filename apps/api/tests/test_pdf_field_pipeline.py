"""End-to-end PDF coverage across ingestion, extraction, verification, and normalization."""

import pytest

from app.config import resolve_data_dir
from app.field_extraction import TextFieldExtractor
from app.ingestion.extractors import ContentType, ExtractedContent
from app.ingestion.extractors.pdf_extractor import PDFExtractor, TesseractOcrEngine
from app.models.extraction import ComparisonField, DocumentRole, ExtractionMethod
from app.normalization import DocumentNormalizer
from app.verification import TextEvidenceVerifier


def test_native_participant_pdf_completes_boxes_five_through_seven() -> None:
    path = resolve_data_dir() / "attachments" / "email_059_SI.pdf"
    if not path.exists():
        pytest.skip("Participant bundle is not available")

    document = PDFExtractor(
        enable_vision_fallback=False,
        enable_local_ocr=False,
    ).extract(path)
    candidates = TextFieldExtractor().extract(document, DocumentRole.SHIPPING_INSTRUCTION)
    verified = TextEvidenceVerifier().verify(document, candidates)
    normalized = DocumentNormalizer().normalize(verified)

    assert {candidate.field for candidate in candidates.candidates} == set(ComparisonField)
    assert candidates.diagnostics == []
    assert verified.unresolved_fields() == []
    assert normalized.is_complete
    values = {
        field: item.comparison_text for field, item in normalized.document.field_map().items()
    }
    assert values == {
        ComparisonField.SHIPPER: "APRIL FINE PAPER TRADING",
        ComparisonField.CONSIGNEE: "BALL & DOGGETT AUSTRALIA PTY LTD",
        ComparisonField.NOTIFY_PARTY: "PACIFIC OFFICE (M) SDN BHD",
        ComparisonField.PORT_OF_LOADING: "BUATAN, INDONESIA",
        ComparisonField.PORT_OF_DISCHARGE: "FREMANTLE, AUSTRALIA",
        ComparisonField.CONTAINER_COUNT: "6",
        ComparisonField.GROSS_WEIGHT_KG: "131322 kg",
    }


def test_ocr_pdf_candidates_retain_method_and_bounded_confidence() -> None:
    document = ExtractedContent(
        text=(
            "Shipper: Example Trading Ltd\n"
            "Consignee: Example Imports Ltd\n"
            "Notify Party: Example Logistics Ltd\n"
            "Port of Loading: Singapore\n"
            "Port of Discharge: Rotterdam\n"
            "Containers: 2 x 40HC\n"
            "Gross Weight: 44,000 KG\n"
        ),
        content_type=ContentType.PDF,
        source_filename="scan.pdf",
        metadata={"extractor": "tesseract", "ocr_average_confidence": 91.25},
    )

    candidates = TextFieldExtractor().extract(document, DocumentRole.SHIPPING_INSTRUCTION)
    verified = TextEvidenceVerifier().verify(document, candidates)

    assert len(candidates.candidates) == 7
    assert all(item.extraction_method == ExtractionMethod.OCR for item in candidates.candidates)
    assert all(item.confidence == 0.9125 for item in candidates.candidates)
    assert verified.unresolved_fields() == []


def test_pdf_column_layout_without_colons_is_supported() -> None:
    document = ExtractedContent(
        text=(
            "Shipper                       Example Trading Ltd\n"
            "Gross Weight                  8,500 KG"
        ),
        content_type=ContentType.PDF,
        source_filename="layout.pdf",
    )

    candidates = TextFieldExtractor().extract(document, DocumentRole.SHIPPING_INSTRUCTION)

    values = {item.field: item.raw_value for item in candidates.candidates}
    assert values[ComparisonField.SHIPPER] == "Example Trading Ltd"
    assert values[ComparisonField.GROSS_WEIGHT_KG] == "8,500 KG"


def test_scanned_participant_pdf_completes_with_tesseract_and_levenshtein() -> None:
    path = resolve_data_dir() / "attachments" / "email_512_SI.pdf"
    if not path.exists():
        pytest.skip("Participant bundle is not available")
    if not TesseractOcrEngine().is_available():
        pytest.skip("Tesseract is not installed")

    extractor = PDFExtractor(enable_vision_fallback=False)
    document = extractor._extract_with_local_ocr(path.read_bytes(), path.name)
    candidates = TextFieldExtractor().extract(document, DocumentRole.SHIPPING_INSTRUCTION)
    verified = TextEvidenceVerifier().verify(document, candidates)
    normalized = DocumentNormalizer().normalize(verified)

    assert document.metadata["extractor"] == "tesseract"
    assert {candidate.field for candidate in candidates.candidates} == set(ComparisonField)
    assert any(
        candidate.extraction_method == ExtractionMethod.LEVENSHTEIN_LABEL
        for candidate in candidates.candidates
    )
    assert verified.unresolved_fields() == []
    assert normalized.is_complete
