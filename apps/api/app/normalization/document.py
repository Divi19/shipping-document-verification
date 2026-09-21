"""Deterministic typed normalization for verified document fields."""

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.models.extraction import ComparisonField
from app.models.verification import (
    DocumentNormalizationResult,
    DocumentVerificationResult,
    NormalizationFailure,
    NormalizationIssue,
    NormalizationRule,
    NormalizationStep,
    NormalizedDocument,
    NormalizedField,
    NormalizedIntegerValue,
    NormalizedTextValue,
    NormalizedWeightKgValue,
    VerifiedField,
)

PARTY_FIELDS = {
    ComparisonField.SHIPPER,
    ComparisonField.CONSIGNEE,
    ComparisonField.NOTIFY_PARTY,
}
PORT_FIELDS = {
    ComparisonField.PORT_OF_LOADING,
    ComparisonField.PORT_OF_DISCHARGE,
}
CONSIGNEE_REFERENCES = {
    "AS PER CONSIGNEE",
    "SAME AS CONSIGNEE",
}
CONTAINER_PATTERN = re.compile(
    r"^(?P<count>\d[\d,]*)(?=\s*(?:[x×]\s*\d|containers?\b|$))",
    re.IGNORECASE,
)
WEIGHT_PATTERN = re.compile(
    r"^(?P<amount>\d[\d,\s]*(?:\.\d+)?)\s*"
    r"(?P<unit>kg|kgs|kilograms?|mt|mts|metric\s+tons?|tonnes?)?$",
    re.IGNORECASE,
)


class _NormalizationError(ValueError):
    """Internal typed failure converted to a contract result."""

    def __init__(self, issue: NormalizationIssue, message: str) -> None:
        super().__init__(message)
        self.issue = issue


@dataclass
class _TransformationTrail:
    """Build a continuous before-and-after transformation history."""

    current: str
    steps: list[NormalizationStep] = field(default_factory=list)

    def apply(self, rule: NormalizationRule, value: str) -> None:
        """Record only transformations that materially change the value."""
        if value == self.current:
            return
        self.steps.append(
            NormalizationStep(
                rule=rule,
                before=self.current,
                after=value,
            )
        )
        self.current = value


class DocumentNormalizer:
    """Normalize verified Box 6 fields without changing their evidence."""

    def normalize(
        self,
        verified: DocumentVerificationResult,
    ) -> DocumentNormalizationResult:
        """Return one normalized or failed outcome for every required field."""
        normalized_fields: list[NormalizedField] = []
        failures: list[NormalizationFailure] = []
        normalized_by_field: dict[ComparisonField, NormalizedField] = {}
        verification_by_field = {item.field: item for item in verified.fields}

        for field_name in ComparisonField:
            field_result = verification_by_field[field_name]
            if field_result.verified_field is None:
                issues = ", ".join(issue.value for issue in field_result.issues)
                failures.append(
                    NormalizationFailure(
                        field=field_name,
                        issue=NormalizationIssue.MISSING_VERIFIED_FIELD,
                        message=f"Field did not pass verification: {issues}.",
                    )
                )
                continue

            try:
                normalized = self._normalize_field(
                    field_result.verified_field,
                    normalized_by_field,
                )
            except _NormalizationError as exc:
                failures.append(
                    NormalizationFailure(
                        field=field_name,
                        issue=exc.issue,
                        message=str(exc),
                    )
                )
                continue
            normalized_fields.append(normalized)
            normalized_by_field[field_name] = normalized

        return DocumentNormalizationResult(
            document=NormalizedDocument(
                document_role=verified.document_role,
                source_filename=verified.source_filename,
                fields=normalized_fields,
            ),
            failures=failures,
        )

    def _normalize_field(
        self,
        verified: VerifiedField,
        normalized_by_field: dict[ComparisonField, NormalizedField],
    ) -> NormalizedField:
        field_name = verified.field
        if field_name in PARTY_FIELDS:
            return self._normalize_party(verified, normalized_by_field)
        if field_name in PORT_FIELDS:
            return self._normalize_port(verified)
        if field_name == ComparisonField.CONTAINER_COUNT:
            return self._normalize_container_count(verified)
        if field_name == ComparisonField.GROSS_WEIGHT_KG:
            return self._normalize_weight(verified)
        raise _NormalizationError(
            NormalizationIssue.UNSUPPORTED_VALUE_FORMAT,
            f"No normalization strategy exists for {field_name.value}.",
        )

    def _normalize_party(
        self,
        verified: VerifiedField,
        normalized_by_field: dict[ComparisonField, NormalizedField],
    ) -> NormalizedField:
        trail = self._base_text_trail(verified)
        lines = [line.strip() for line in trail.current.splitlines() if line.strip()]
        if not lines:
            raise _NormalizationError(
                NormalizationIssue.UNSUPPORTED_VALUE_FORMAT,
                f"{verified.field.value} has no primary entity name.",
            )
        trail.apply(NormalizationRule.SELECT_PRIMARY_ENTITY, lines[0])
        trail.apply(NormalizationRule.NORMALIZE_CASE, trail.current.upper())
        trail.apply(
            NormalizationRule.NORMALIZE_LEGAL_SUFFIX,
            re.sub(r"[.,]+", " ", trail.current),
        )
        trail.apply(
            NormalizationRule.COLLAPSE_WHITESPACE,
            " ".join(trail.current.split()),
        )

        if verified.field == ComparisonField.NOTIFY_PARTY and trail.current in CONSIGNEE_REFERENCES:
            consignee = normalized_by_field.get(ComparisonField.CONSIGNEE)
            if consignee is None:
                raise _NormalizationError(
                    NormalizationIssue.MISSING_REFERENCE_TARGET,
                    "Notify party references a consignee that was not normalized.",
                )
            trail.apply(
                NormalizationRule.RESOLVE_PARTY_REFERENCE,
                consignee.comparison_text,
            )

        return NormalizedField(
            field=verified.field,
            verified=verified,
            normalized=NormalizedTextValue(value=trail.current),
            transformations=trail.steps,
        )

    def _normalize_port(self, verified: VerifiedField) -> NormalizedField:
        trail = self._base_text_trail(verified)
        trail.apply(NormalizationRule.NORMALIZE_CASE, trail.current.upper())
        trail.apply(
            NormalizationRule.NORMALIZE_PUNCTUATION,
            re.sub(r"\s*,\s*", ", ", trail.current),
        )
        trail.apply(
            NormalizationRule.COLLAPSE_WHITESPACE,
            " ".join(trail.current.split()),
        )
        return NormalizedField(
            field=verified.field,
            verified=verified,
            normalized=NormalizedTextValue(value=trail.current),
            transformations=trail.steps,
        )

    def _normalize_container_count(self, verified: VerifiedField) -> NormalizedField:
        trail = self._base_text_trail(verified)
        match = CONTAINER_PATTERN.match(trail.current)
        if match is None:
            raise _NormalizationError(
                NormalizationIssue.UNSUPPORTED_VALUE_FORMAT,
                f"Unsupported container count: {trail.current!r}.",
            )
        count = int(match.group("count").replace(",", ""))
        if count <= 0:
            raise _NormalizationError(
                NormalizationIssue.UNSUPPORTED_VALUE_FORMAT,
                "Container count must be positive.",
            )
        trail.apply(NormalizationRule.PARSE_CONTAINER_COUNT, str(count))
        return NormalizedField(
            field=verified.field,
            verified=verified,
            normalized=NormalizedIntegerValue(value=count),
            transformations=trail.steps,
        )

    def _normalize_weight(self, verified: VerifiedField) -> NormalizedField:
        trail = self._base_text_trail(verified)
        match = WEIGHT_PATTERN.fullmatch(trail.current)
        if match is None:
            raise _NormalizationError(
                NormalizationIssue.UNSUPPORTED_VALUE_FORMAT,
                f"Unsupported gross weight: {trail.current!r}.",
            )
        try:
            amount = Decimal(match.group("amount").replace(",", "").replace(" ", ""))
        except InvalidOperation as exc:
            raise _NormalizationError(
                NormalizationIssue.UNSUPPORTED_VALUE_FORMAT,
                f"Unsupported gross weight: {trail.current!r}.",
            ) from exc
        if amount <= 0:
            raise _NormalizationError(
                NormalizationIssue.UNSUPPORTED_VALUE_FORMAT,
                "Gross weight must be positive.",
            )

        unit = self._weight_unit(match.group("unit"), verified.selected.candidate.raw_label)
        if unit is None:
            raise _NormalizationError(
                NormalizationIssue.UNSUPPORTED_VALUE_FORMAT,
                "Gross weight has no supported unit in its value or label.",
            )

        amount = self._canonical_decimal(amount)
        trail.apply(
            NormalizationRule.PARSE_WEIGHT,
            f"{self._format_decimal(amount)} {unit}",
        )
        if unit == "mt":
            amount = self._canonical_decimal(amount * Decimal(1000))
            trail.apply(
                NormalizationRule.CONVERT_WEIGHT_TO_KG,
                f"{self._format_decimal(amount)} kg",
            )
        return NormalizedField(
            field=verified.field,
            verified=verified,
            normalized=NormalizedWeightKgValue(value=amount),
            transformations=trail.steps,
        )

    @staticmethod
    def _base_text_trail(verified: VerifiedField) -> _TransformationTrail:
        trail = _TransformationTrail(verified.selected.candidate.raw_value)
        trail.apply(
            NormalizationRule.UNICODE_NFKC,
            unicodedata.normalize("NFKC", trail.current),
        )
        trail.apply(NormalizationRule.TRIM_WHITESPACE, trail.current.strip())
        return trail

    @staticmethod
    def _weight_unit(raw_unit: str | None, raw_label: str) -> str | None:
        value = (raw_unit or "").casefold().replace(" ", "")
        if value in {"kg", "kgs", "kilogram", "kilograms"}:
            return "kg"
        if value in {"mt", "mts", "metricton", "metrictons", "tonne", "tonnes"}:
            return "mt"
        if raw_unit is None and "kg" in raw_label.casefold():
            return "kg"
        return None

    @staticmethod
    def _canonical_decimal(value: Decimal) -> Decimal:
        return Decimal(DocumentNormalizer._format_decimal(value))

    @staticmethod
    def _format_decimal(value: Decimal) -> str:
        formatted = format(value, "f")
        if "." in formatted:
            formatted = formatted.rstrip("0").rstrip(".")
        return formatted


def normalize_verified_document(
    verified: DocumentVerificationResult,
) -> DocumentNormalizationResult:
    """Convenience boundary between Box 6 verification and Box 7."""
    return DocumentNormalizer().normalize(verified)
