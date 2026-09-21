"""Tests for TXT evidence and candidate consistency verification."""

from app.field_extraction import TextFieldExtractor
from app.ingestion.extractors import ExtractedContent, TextExtractor
from app.models.extraction import ComparisonField, DocumentFieldCandidates, DocumentRole
from app.models.verification import VerificationIssue, VerificationOutcome
from app.verification import TextEvidenceVerifier, verify_text_candidates


def _extract(text: str) -> tuple[ExtractedContent, DocumentFieldCandidates]:
    document = TextExtractor().extract_bytes(text.encode(), "sample_si.txt")
    candidates = TextFieldExtractor().extract(document, DocumentRole.SHIPPING_INSTRUCTION)
    return document, candidates


def test_verifies_candidate_supported_by_exact_text_span() -> None:
    document, candidates = _extract("Shipper: Example Trading Ltd\n")

    result = verify_text_candidates(document, candidates)

    shipper = result.fields[0]
    assert shipper.field == ComparisonField.SHIPPER
    assert shipper.verified_field is not None
    assert shipper.verified_field.selected.outcome == VerificationOutcome.VERIFIED
    assert set(result.unresolved_fields()) == set(ComparisonField) - {ComparisonField.SHIPPER}


def test_rejects_candidate_when_cited_source_text_was_tampered() -> None:
    document, candidates = _extract("Shipper: Example Trading Ltd\n")
    evidence = candidates.candidates[0].evidence[0]
    candidates.candidates[0].evidence[0] = evidence.model_copy(
        update={"source_text": "Shipper: Different Company Ltd"}
    )

    result = TextEvidenceVerifier().verify(document, candidates)
    shipper = result.fields[0]

    assert shipper.verified_field is None
    assert shipper.issues == [VerificationIssue.EVIDENCE_NOT_FOUND]
    assert shipper.assessments[0].outcome == VerificationOutcome.REJECTED


def test_conflicting_supported_candidates_remain_unresolved() -> None:
    document, candidates = _extract("Gross Weight: 22,000 KG\nTotal Gross Weight: 23,000 KG\n")

    result = TextEvidenceVerifier().verify(document, candidates)
    weight = next(item for item in result.fields if item.field == ComparisonField.GROSS_WEIGHT_KG)

    assert weight.verified_field is None
    assert weight.issues == [VerificationIssue.CONFLICTING_CANDIDATES]
    assert [item.outcome for item in weight.assessments] == [
        VerificationOutcome.UNCERTAIN,
        VerificationOutcome.UNCERTAIN,
    ]


def test_identical_duplicate_values_are_retained_but_resolved() -> None:
    document, candidates = _extract("Gross Weight: 22,000 KG\nTotal Gross Weight: 22,000 KG\n")

    result = TextEvidenceVerifier().verify(document, candidates)
    weight = next(item for item in result.fields if item.field == ComparisonField.GROSS_WEIGHT_KG)

    assert weight.verified_field is not None
    assert len(weight.verified_field.alternatives) == 1
    assert weight.verified_field.alternatives[0].outcome == VerificationOutcome.VERIFIED


def test_low_confidence_candidate_is_uncertain() -> None:
    document, candidates = _extract("Shipper: Example Trading Ltd\n")
    candidates.candidates[0] = candidates.candidates[0].model_copy(update={"confidence": 0.5})

    result = TextEvidenceVerifier(minimum_confidence=0.8).verify(document, candidates)
    shipper = result.fields[0]

    assert shipper.verified_field is None
    assert shipper.issues == [VerificationIssue.LOW_CONFIDENCE]


def test_replacement_character_is_treated_as_likely_ocr_error() -> None:
    document, candidates = _extract("Shipper: Example Trad�ng Ltd\n")

    result = TextEvidenceVerifier().verify(document, candidates)
    shipper = result.fields[0]

    assert shipper.verified_field is None
    assert shipper.issues == [VerificationIssue.LIKELY_OCR_ERROR]


def test_complete_document_verifies_all_seven_fields() -> None:
    text = "\n".join(
        [
            "Shipper: Example Trading Ltd",
            "Consignee: Example Imports LLC",
            "Notify Party: Example Logistics LLC",
            "Port of Loading: Singapore",
            "Port of Discharge: Rotterdam",
            "Container Count: 3",
            "Gross Weight: 66,000 KG",
        ]
    )
    document, candidates = _extract(text)

    result = TextEvidenceVerifier().verify(document, candidates)

    assert result.unresolved_fields() == []
    assert len(result.verified_fields()) == 7
