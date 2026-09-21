"""Tests for Box 5 extraction and evidence contracts."""

import pytest
from pydantic import ValidationError

from app.models.extraction import (
    BoundingBox,
    ComparisonField,
    DocumentFieldCandidates,
    DocumentRole,
    EvidenceReference,
    ExtractionMethod,
    FieldCandidate,
    PageRegionLocator,
    TableCellLocator,
    TextSpanLocator,
)


def _candidate(
    *,
    field: ComparisonField = ComparisonField.SHIPPER,
    role: DocumentRole = DocumentRole.SHIPPING_INSTRUCTION,
    filename: str = "sample_si.txt",
) -> FieldCandidate:
    return FieldCandidate(
        field=field,
        document_role=role,
        raw_label="Shipper",
        raw_value="Example Trading Pte Ltd",
        evidence=[
            EvidenceReference(
                source_filename=filename,
                locator=TextSpanLocator(start=0, end=36, line_start=1, line_end=1),
                source_text="Shipper: Example Trading Pte Ltd",
            )
        ],
        extraction_method=ExtractionMethod.LABEL_MAP,
        confidence=0.98,
    )


def test_candidate_preserves_raw_value_and_text_evidence() -> None:
    candidate = _candidate()

    assert candidate.raw_value == "Example Trading Pte Ltd"
    assert candidate.evidence[0].locator.kind == "text_span"
    assert candidate.confidence == 0.98


def test_locator_union_supports_tables_and_page_regions() -> None:
    table_evidence = EvidenceReference(
        source_filename="sample.xlsx",
        locator=TableCellLocator(table_index=0, row_index=2, column_index=1, sheet_name="SI"),
        source_text="22,000 KG",
    )
    page_evidence = EvidenceReference(
        source_filename="sample.pdf",
        locator=PageRegionLocator(
            page_number=1,
            bounding_box=BoundingBox(x0=10, y0=20, x1=120, y1=40),
        ),
        source_text="GROSS WEIGHT 22,000 KG",
    )

    assert table_evidence.locator.kind == "table_cell"
    assert page_evidence.locator.kind == "page_region"


def test_multiple_candidates_are_retained_for_later_verification() -> None:
    first = _candidate(field=ComparisonField.SHIPPER)
    second = first.model_copy(update={"raw_value": "Conflicting Trading Ltd"})
    document = DocumentFieldCandidates(
        document_role=DocumentRole.SHIPPING_INSTRUCTION,
        source_filename="sample_si.txt",
        candidates=[first, second],
    )

    assert document.candidates_for(ComparisonField.SHIPPER) == [first, second]


def test_document_rejects_evidence_from_another_source() -> None:
    candidate = _candidate(filename="other.txt")

    with pytest.raises(ValidationError, match="source document"):
        DocumentFieldCandidates(
            document_role=DocumentRole.SHIPPING_INSTRUCTION,
            source_filename="sample_si.txt",
            candidates=[candidate],
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"raw_value": "   "}, "raw_value"),
        ({"confidence": 1.1}, "less than or equal to 1"),
        ({"evidence": []}, "at least 1 item"),
    ],
)
def test_candidate_rejects_untrustworthy_shapes(changes: dict[str, object], message: str) -> None:
    data = _candidate().model_dump()
    data.update(changes)

    with pytest.raises(ValidationError, match=message):
        FieldCandidate.model_validate(data)


def test_text_span_requires_ordered_offsets() -> None:
    with pytest.raises(ValidationError, match="greater than start"):
        TextSpanLocator(start=10, end=5)
