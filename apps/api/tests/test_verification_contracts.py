"""Tests for Box 6 verification and Box 7 normalization contracts."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.extraction import (
    ComparisonField,
    DocumentRole,
    EvidenceReference,
    ExtractionMethod,
    FieldCandidate,
    TextSpanLocator,
)
from app.models.verification import (
    CandidateAssessment,
    DocumentNormalizationResult,
    DocumentVerificationResult,
    FieldVerificationResult,
    NormalizationFailure,
    NormalizationIssue,
    NormalizationRule,
    NormalizationStep,
    NormalizedDocument,
    NormalizedField,
    NormalizedIntegerValue,
    NormalizedTextValue,
    NormalizedWeightKgValue,
    VerificationIssue,
    VerificationOutcome,
    VerifiedField,
    VerifiedNormalizedPair,
)


def _candidate(
    field: ComparisonField,
    *,
    role: DocumentRole = DocumentRole.SHIPPING_INSTRUCTION,
    filename: str = "sample_si.txt",
    raw_value: str = "Example Trading Ltd",
) -> FieldCandidate:
    source_text = f"Field: {raw_value}"
    return FieldCandidate(
        field=field,
        document_role=role,
        raw_label="Field",
        raw_value=raw_value,
        evidence=[
            EvidenceReference(
                source_filename=filename,
                locator=TextSpanLocator(start=0, end=len(source_text)),
                source_text=source_text,
            )
        ],
        extraction_method=ExtractionMethod.LABEL_MAP,
        confidence=0.95,
    )


def _verified_field(
    field: ComparisonField,
    *,
    role: DocumentRole = DocumentRole.SHIPPING_INSTRUCTION,
    filename: str = "sample_si.txt",
    raw_value: str = "Example Trading Ltd",
) -> VerifiedField:
    candidate = _candidate(field, role=role, filename=filename, raw_value=raw_value)
    return VerifiedField(
        field=field,
        selected=CandidateAssessment(
            candidate=candidate,
            outcome=VerificationOutcome.VERIFIED,
        ),
    )


def _normalized_field(
    field: ComparisonField,
    *,
    role: DocumentRole,
    filename: str,
) -> NormalizedField:
    normalized: NormalizedTextValue | NormalizedIntegerValue | NormalizedWeightKgValue
    if field == ComparisonField.CONTAINER_COUNT:
        raw_value = "3"
        normalized = NormalizedIntegerValue(value=3)
    elif field == ComparisonField.GROSS_WEIGHT_KG:
        raw_value = "22000 kg"
        normalized = NormalizedWeightKgValue(value=Decimal("22000"))
    else:
        raw_value = f"normalized {field.value}"
        normalized = NormalizedTextValue(value=raw_value)
    return NormalizedField(
        field=field,
        verified=_verified_field(field, role=role, filename=filename, raw_value=raw_value),
        normalized=normalized,
    )


def _complete_document(role: DocumentRole, filename: str) -> NormalizedDocument:
    return NormalizedDocument(
        document_role=role,
        source_filename=filename,
        fields=[
            _normalized_field(field, role=role, filename=filename) for field in ComparisonField
        ],
    )


def test_unverified_candidate_requires_an_explicit_issue() -> None:
    candidate = _candidate(ComparisonField.SHIPPER)

    with pytest.raises(ValidationError, match="at least one issue"):
        CandidateAssessment(candidate=candidate, outcome=VerificationOutcome.UNCERTAIN)


def test_verified_selection_retains_conflicting_alternative() -> None:
    selected = CandidateAssessment(
        candidate=_candidate(ComparisonField.GROSS_WEIGHT_KG, raw_value="22000 KG"),
        outcome=VerificationOutcome.VERIFIED,
    )
    conflicting = CandidateAssessment(
        candidate=_candidate(ComparisonField.GROSS_WEIGHT_KG, raw_value="23000 KG"),
        outcome=VerificationOutcome.REJECTED,
        issues=[VerificationIssue.CONFLICTING_CANDIDATES],
    )

    verified = VerifiedField(
        field=ComparisonField.GROSS_WEIGHT_KG,
        selected=selected,
        alternatives=[conflicting],
    )

    assert verified.alternatives == [conflicting]


def test_unresolved_field_requires_an_issue() -> None:
    with pytest.raises(ValidationError, match="at least one issue"):
        FieldVerificationResult(field=ComparisonField.SHIPPER)


def test_document_verification_covers_all_seven_fields() -> None:
    with pytest.raises(ValidationError, match="all required fields"):
        DocumentVerificationResult(
            document_role=DocumentRole.SHIPPING_INSTRUCTION,
            source_filename="sample_si.txt",
            fields=[
                FieldVerificationResult(
                    field=ComparisonField.SHIPPER,
                    issues=[VerificationIssue.MISSING_CANDIDATE],
                )
            ],
        )


def test_normalization_preserves_an_auditable_transformation_trail() -> None:
    normalized = NormalizedField(
        field=ComparisonField.GROSS_WEIGHT_KG,
        verified=_verified_field(
            ComparisonField.GROSS_WEIGHT_KG,
            raw_value="22,000 KG",
        ),
        normalized=NormalizedWeightKgValue(value=Decimal("22000")),
        transformations=[
            NormalizationStep(
                rule=NormalizationRule.PARSE_WEIGHT,
                before="22,000 KG",
                after="22000 kg",
            )
        ],
    )

    assert normalized.comparison_text == "22000 kg"
    assert normalized.verified.selected.candidate.raw_value == "22,000 KG"


def test_changed_value_without_transformation_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must record"):
        NormalizedField(
            field=ComparisonField.SHIPPER,
            verified=_verified_field(ComparisonField.SHIPPER, raw_value="Example Trading"),
            normalized=NormalizedTextValue(value="EXAMPLE TRADING"),
        )


def test_field_requires_its_correct_normalized_type() -> None:
    with pytest.raises(ValidationError, match="invalid normalized value type"):
        NormalizedField(
            field=ComparisonField.CONTAINER_COUNT,
            verified=_verified_field(ComparisonField.CONTAINER_COUNT, raw_value="3"),
            normalized=NormalizedTextValue(value="3"),
        )


def test_normalized_document_rejects_duplicate_fields() -> None:
    field = _normalized_field(
        ComparisonField.SHIPPER,
        role=DocumentRole.SHIPPING_INSTRUCTION,
        filename="sample_si.txt",
    )

    with pytest.raises(ValidationError, match="must be unique"):
        NormalizedDocument(
            document_role=DocumentRole.SHIPPING_INSTRUCTION,
            source_filename="sample_si.txt",
            fields=[field, field],
        )


def test_normalization_result_requires_all_fields_to_have_an_outcome() -> None:
    document = NormalizedDocument(
        document_role=DocumentRole.SHIPPING_INSTRUCTION,
        source_filename="sample_si.txt",
        fields=[],
    )

    with pytest.raises(ValidationError, match="all required fields"):
        DocumentNormalizationResult(
            document=document,
            failures=[
                NormalizationFailure(
                    field=ComparisonField.SHIPPER,
                    issue=NormalizationIssue.MISSING_VERIFIED_FIELD,
                    message="Shipper was not verified.",
                )
            ],
        )


def test_verified_pair_requires_all_seven_fields() -> None:
    incomplete_si = NormalizedDocument(
        document_role=DocumentRole.SHIPPING_INSTRUCTION,
        source_filename="sample_si.txt",
        fields=[],
    )
    complete_bl = _complete_document(DocumentRole.BILL_OF_LADING, "sample_bl.txt")

    with pytest.raises(ValidationError, match="missing required fields"):
        VerifiedNormalizedPair(
            shipping_instruction=incomplete_si,
            bill_of_lading=complete_bl,
        )


def test_complete_verified_pair_is_ready_for_comparison() -> None:
    pair = VerifiedNormalizedPair(
        shipping_instruction=_complete_document(DocumentRole.SHIPPING_INSTRUCTION, "sample_si.txt"),
        bill_of_lading=_complete_document(DocumentRole.BILL_OF_LADING, "sample_bl.txt"),
    )

    assert set(pair.shipping_instruction.field_map()) == set(ComparisonField)
    assert set(pair.bill_of_lading.field_map()) == set(ComparisonField)
