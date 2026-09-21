"""Unit tests for deterministic TXT field extraction."""

import pytest

from app.config import resolve_data_dir
from app.field_extraction import TextFieldExtractor, extract_text_fields
from app.ingestion.extractors import ContentType, ExtractedContent, IngestionStatus, TextExtractor
from app.models.extraction import (
    ComparisonField,
    DocumentRole,
    ExtractionMethod,
    TextSpanLocator,
)


def test_extracts_ingested_text_into_box_five_candidates() -> None:
    document = TextExtractor().extract_bytes(
        b"Shipper: Example Trading Ltd\nContainer Count: 3\n",
        "sample_si.txt",
    )

    result = extract_text_fields(document, DocumentRole.SHIPPING_INSTRUCTION)

    assert [candidate.field for candidate in result.candidates] == [
        ComparisonField.SHIPPER,
        ComparisonField.CONTAINER_COUNT,
    ]
    shipper = result.candidates[0]
    assert shipper.raw_label == "Shipper"
    assert shipper.raw_value == "Example Trading Ltd"
    assert shipper.extraction_method == ExtractionMethod.LABEL_MAP
    assert shipper.evidence[0].source_text == "Shipper: Example Trading Ltd"
    locator = shipper.evidence[0].locator
    assert isinstance(locator, TextSpanLocator)
    assert document.text[locator.start : locator.end] == shipper.evidence[0].source_text


def test_captures_multiline_party_block_as_one_candidate() -> None:
    text = (
        "Shipper:\n"
        "Example Paper Trading\n"
        "On behalf of Holding Company Ltd\n"
        "77 Harbor Road\n\n"
        "POD: Rotterdam\n"
    )

    result = TextFieldExtractor().extract_text(
        text,
        "multiline_si.txt",
        DocumentRole.SHIPPING_INSTRUCTION,
    )

    shipper = result.candidates_for(ComparisonField.SHIPPER)[0]
    assert shipper.raw_value == (
        "Example Paper Trading\nOn behalf of Holding Company Ltd\n77 Harbor Road"
    )
    assert shipper.evidence[0].source_text == text.split("\n\n", maxsplit=1)[0]
    locator = shipper.evidence[0].locator
    assert isinstance(locator, TextSpanLocator)
    assert locator.line_start == 1
    assert locator.line_end == 4


def test_retains_continuation_address_for_inline_party() -> None:
    text = "SHIPPER: Example Paper Ltd\n  77 Harbor Road; Singapore\nPOD: Rotterdam\n"

    result = TextFieldExtractor().extract_text(
        text,
        "address_bl.txt",
        DocumentRole.BILL_OF_LADING,
    )

    shipper = result.candidates_for(ComparisonField.SHIPPER)[0]
    assert shipper.raw_value == "Example Paper Ltd\n77 Harbor Road; Singapore"
    assert shipper.evidence[0].source_text == (
        "SHIPPER: Example Paper Ltd\n  77 Harbor Road; Singapore"
    )


def test_skips_blank_and_placeholder_values() -> None:
    text = "Shipper:\nConsignee: N/A\nNotify Party: -\nGross Weight: ____MT\nContainer Count: 2\n"

    result = TextFieldExtractor().extract_text(
        text,
        "missing_bl.txt",
        DocumentRole.BILL_OF_LADING,
    )

    assert [candidate.field for candidate in result.candidates] == [ComparisonField.CONTAINER_COUNT]
    assert "No candidate extracted for shipper." in result.diagnostics
    assert "No candidate extracted for consignee." in result.diagnostics
    assert "No candidate extracted for gross_weight_kg." in result.diagnostics


def test_retains_contradictory_values_and_reports_diagnostic() -> None:
    text = "Gross Weight: 22,000 KG\nTotal Gross Weight: 23,000 KG\n"

    result = TextFieldExtractor().extract_text(
        text,
        "conflict_bl.txt",
        DocumentRole.BILL_OF_LADING,
    )

    weights = result.candidates_for(ComparisonField.GROSS_WEIGHT_KG)
    assert [candidate.raw_value for candidate in weights] == ["22,000 KG", "23,000 KG"]
    assert "Multiple candidates extracted for gross_weight_kg: 2." in result.diagnostics


def test_skips_failed_ingestion_without_inventing_candidates() -> None:
    document = ExtractedContent(
        content_type=ContentType.TEXT,
        source_filename="failed.txt",
        status=IngestionStatus.UNREADABLE,
        diagnostics=["No readable text was extracted."],
    )

    result = TextFieldExtractor().extract(document, DocumentRole.SHIPPING_INSTRUCTION)

    assert result.candidates == []
    assert result.diagnostics == [
        "Document ingestion status is unreadable; field extraction skipped.",
        "No readable text was extracted.",
    ]


def test_accepts_pdf_text_document() -> None:
    document = ExtractedContent(
        text="Shipper: Example Trading Ltd",
        content_type=ContentType.PDF,
        source_filename="sample.pdf",
    )

    result = TextFieldExtractor().extract(document, DocumentRole.SHIPPING_INSTRUCTION)

    assert result.candidates[0].raw_value == "Example Trading Ltd"


@pytest.mark.parametrize(
    ("filename", "role"),
    [
        ("email_001_SI.txt", DocumentRole.SHIPPING_INSTRUCTION),
        ("email_001_BL.txt", DocumentRole.BILL_OF_LADING),
    ],
)
def test_participant_txt_examples_produce_all_seven_fields(
    filename: str, role: DocumentRole
) -> None:
    source_path = resolve_data_dir() / "attachments" / filename
    if not source_path.exists():
        pytest.skip("Participant bundle is not available")

    document = TextExtractor().extract(source_path)
    result = TextFieldExtractor().extract(document, role)

    assert {candidate.field for candidate in result.candidates} == set(ComparisonField)
    assert result.diagnostics == []
