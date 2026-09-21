"""Contracts for evidence verification and typed normalization."""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.models.extraction import (
    ALL_COMPARISON_FIELDS,
    ComparisonField,
    ContractModel,
    DocumentRole,
    FieldCandidate,
)


class VerificationOutcome(StrEnum):
    """Decision made about one extraction candidate."""

    VERIFIED = "verified"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"


class VerificationIssue(StrEnum):
    """Reason a candidate or document could not be trusted."""

    EVIDENCE_NOT_FOUND = "evidence_not_found"
    CONFLICTING_CANDIDATES = "conflicting_candidates"
    MISSING_CANDIDATE = "missing_candidate"
    LOW_CONFIDENCE = "low_confidence"
    ROLE_MISMATCH = "role_mismatch"
    LIKELY_OCR_ERROR = "likely_ocr_error"
    SHIPMENT_MISMATCH = "shipment_mismatch"


class CandidateAssessment(ContractModel):
    """Box 6 verification decision for one field candidate."""

    candidate: FieldCandidate
    outcome: VerificationOutcome
    issues: list[VerificationIssue] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_issues(self) -> Self:
        """Require issues only when the candidate is not verified."""
        if self.outcome == VerificationOutcome.VERIFIED and self.issues:
            raise ValueError("a verified candidate cannot have verification issues")
        if self.outcome != VerificationOutcome.VERIFIED and not self.issues:
            raise ValueError("an unverified candidate must identify at least one issue")
        return self


class VerifiedField(ContractModel):
    """The selected verified candidate plus retained alternatives."""

    field: ComparisonField
    selected: CandidateAssessment
    alternatives: list[CandidateAssessment] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        """Require a verified selection and field-aligned alternatives."""
        if self.selected.outcome != VerificationOutcome.VERIFIED:
            raise ValueError("the selected candidate must be verified")
        assessments = [self.selected, *self.alternatives]
        if any(item.candidate.field != self.field for item in assessments):
            raise ValueError("all assessments must describe the verified field")
        return self


class FieldVerificationResult(ContractModel):
    """Box 6 result for one required field, including unresolved outcomes."""

    field: ComparisonField
    assessments: list[CandidateAssessment] = Field(default_factory=list)
    verified_field: VerifiedField | None = None
    issues: list[VerificationIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        """Require either one verified selection or explicit unresolved issues."""
        if any(item.candidate.field != self.field for item in self.assessments):
            raise ValueError("all assessments must describe the result field")
        if self.verified_field is None:
            if not self.issues:
                raise ValueError("an unresolved field must identify at least one issue")
            return self

        if self.verified_field.field != self.field:
            raise ValueError("verified field does not match the result field")
        if self.issues:
            raise ValueError("a resolved field cannot have unresolved issues")
        represented = [
            self.verified_field.selected,
            *self.verified_field.alternatives,
        ]
        if len(represented) != len(self.assessments) or any(
            item not in self.assessments for item in represented
        ):
            raise ValueError("verified selection must retain every candidate assessment")
        return self


class DocumentVerificationResult(ContractModel):
    """Complete Box 6 evidence decision for one document."""

    document_role: DocumentRole
    source_filename: str = Field(min_length=1)
    fields: list[FieldVerificationResult]
    diagnostics: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        """Require exactly one result for each of the seven fields."""
        field_names = [item.field for item in self.fields]
        if len(field_names) != len(set(field_names)):
            raise ValueError("verification result fields must be unique")
        if set(field_names) != ALL_COMPARISON_FIELDS:
            raise ValueError("verification result must cover all required fields")
        for result in self.fields:
            for assessment in result.assessments:
                candidate = assessment.candidate
                if candidate.document_role != self.document_role:
                    raise ValueError("candidate role does not match the verified document")
                if any(
                    evidence.source_filename != self.source_filename
                    for evidence in candidate.evidence
                ):
                    raise ValueError("candidate evidence does not match the verified document")
        return self

    def verified_fields(self) -> list[VerifiedField]:
        """Return fields that passed evidence and consistency verification."""
        return [item.verified_field for item in self.fields if item.verified_field is not None]

    def unresolved_fields(self) -> list[ComparisonField]:
        """Return fields that require missing-value or uncertainty handling."""
        return [item.field for item in self.fields if item.verified_field is None]


class NormalizationRule(StrEnum):
    """Approved deterministic transformations recorded by Box 7."""

    UNICODE_NFKC = "unicode_nfkc"
    TRIM_WHITESPACE = "trim_whitespace"
    COLLAPSE_WHITESPACE = "collapse_whitespace"
    NORMALIZE_CASE = "normalize_case"
    NORMALIZE_PUNCTUATION = "normalize_punctuation"
    NORMALIZE_LEGAL_SUFFIX = "normalize_legal_suffix"
    SELECT_PRIMARY_ENTITY = "select_primary_entity"
    PARSE_CONTAINER_COUNT = "parse_container_count"
    PARSE_WEIGHT = "parse_weight"
    CONVERT_WEIGHT_TO_KG = "convert_weight_to_kg"


class NormalizationStep(ContractModel):
    """One auditable before-and-after normalization operation."""

    rule: NormalizationRule
    before: str
    after: str


class NormalizedTextValue(ContractModel):
    """Normalized value for party and port fields."""

    kind: Literal["text"] = "text"
    value: str = Field(min_length=1)


class NormalizedIntegerValue(ContractModel):
    """Normalized positive container count."""

    kind: Literal["integer"] = "integer"
    value: int = Field(gt=0)


class NormalizedWeightKgValue(ContractModel):
    """Normalized positive gross weight expressed in kilograms."""

    kind: Literal["weight_kg"] = "weight_kg"
    value: Decimal = Field(gt=0)
    unit: Literal["kg"] = "kg"


NormalizedValue = Annotated[
    NormalizedTextValue | NormalizedIntegerValue | NormalizedWeightKgValue,
    Field(discriminator="kind"),
]


class NormalizedField(ContractModel):
    """Verified source field and its typed deterministic comparison value."""

    field: ComparisonField
    verified: VerifiedField
    normalized: NormalizedValue
    transformations: list[NormalizationStep] = Field(default_factory=list)

    @property
    def comparison_text(self) -> str:
        """Return the canonical string recorded by transformation steps."""
        if isinstance(self.normalized, NormalizedWeightKgValue):
            return f"{self.normalized.value} kg"
        return str(self.normalized.value)

    @model_validator(mode="after")
    def validate_normalization(self) -> Self:
        """Enforce field types and a continuous transformation audit trail."""
        if self.verified.field != self.field:
            raise ValueError("verified source field does not match normalized field")

        invalid_type = (
            self.field == ComparisonField.CONTAINER_COUNT
            and not isinstance(self.normalized, NormalizedIntegerValue)
        ) or (
            self.field == ComparisonField.GROSS_WEIGHT_KG
            and not isinstance(self.normalized, NormalizedWeightKgValue)
        )
        text_fields = ALL_COMPARISON_FIELDS - {
            ComparisonField.CONTAINER_COUNT,
            ComparisonField.GROSS_WEIGHT_KG,
        }
        invalid_type = invalid_type or (
            self.field in text_fields and not isinstance(self.normalized, NormalizedTextValue)
        )
        if invalid_type:
            raise ValueError(f"{self.field.value} has an invalid normalized value type")

        raw_value = self.verified.selected.candidate.raw_value
        if not self.transformations:
            if raw_value != self.comparison_text:
                raise ValueError("changed values must record normalization transformations")
            return self

        if self.transformations[0].before != raw_value:
            raise ValueError("normalization trail must start with the raw value")
        for previous, current in zip(self.transformations, self.transformations[1:], strict=False):
            if previous.after != current.before:
                raise ValueError("normalization transformations must form a continuous trail")
        if self.transformations[-1].after != self.comparison_text:
            raise ValueError("normalization trail must end with the comparison value")
        return self


class NormalizedDocument(ContractModel):
    """Verified normalized fields belonging to one document."""

    document_role: DocumentRole
    source_filename: str = Field(min_length=1)
    fields: list[NormalizedField] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        """Require unique fields sourced from this document and role."""
        field_names = [item.field for item in self.fields]
        if len(field_names) != len(set(field_names)):
            raise ValueError("normalized document fields must be unique")
        for item in self.fields:
            candidate = item.verified.selected.candidate
            if candidate.document_role != self.document_role:
                raise ValueError("normalized field role does not match its document")
            if any(
                evidence.source_filename != self.source_filename for evidence in candidate.evidence
            ):
                raise ValueError("normalized field evidence must reference its document")
        return self

    def field_map(self) -> dict[ComparisonField, NormalizedField]:
        """Return normalized fields keyed by their comparison name."""
        return {item.field: item for item in self.fields}


class VerifiedNormalizedPair(ContractModel):
    """Complete SI and BL inputs accepted by deterministic comparison."""

    shipping_instruction: NormalizedDocument
    bill_of_lading: NormalizedDocument

    @model_validator(mode="after")
    def validate_pair(self) -> Self:
        """Require correctly assigned documents with all seven fields."""
        if self.shipping_instruction.document_role != DocumentRole.SHIPPING_INSTRUCTION:
            raise ValueError("shipping_instruction must have the SI document role")
        if self.bill_of_lading.document_role != DocumentRole.BILL_OF_LADING:
            raise ValueError("bill_of_lading must have the BL document role")

        for document in (self.shipping_instruction, self.bill_of_lading):
            present = set(document.field_map())
            if present != ALL_COMPARISON_FIELDS:
                missing = sorted(field.value for field in ALL_COMPARISON_FIELDS - present)
                raise ValueError(f"normalized document is missing required fields: {missing}")
        return self
