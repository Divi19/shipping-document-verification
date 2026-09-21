"""Tests for deterministic typed document normalization."""

from decimal import Decimal
from pathlib import Path

from app.field_extraction import TextFieldExtractor
from app.ingestion.extractors import TextExtractor
from app.models.extraction import ComparisonField, DocumentRole
from app.models.verification import (
    DocumentNormalizationResult,
    NormalizationIssue,
    NormalizationRule,
    NormalizedIntegerValue,
    NormalizedTextValue,
    NormalizedWeightKgValue,
)
from app.normalization import DocumentNormalizer, normalize_verified_document
from app.verification import TextEvidenceVerifier

CORPUS_DIR = Path(__file__).parent / "fixtures" / "txt_extraction"


def _normalize(
    text: str,
    role: DocumentRole = DocumentRole.SHIPPING_INSTRUCTION,
) -> DocumentNormalizationResult:
    document = TextExtractor().extract_bytes(text.encode(), "sample.txt")
    extracted = TextFieldExtractor().extract(document, role)
    verified = TextEvidenceVerifier().verify(document, extracted)
    return normalize_verified_document(verified)


def test_party_normalization_selects_primary_entity_and_preserves_source() -> None:
    result = _normalize(
        "Shipper:\n"
        "April Fine Paper Trading Co., Ltd.\n"
        "On behalf of Seaside Holdings Pte Ltd\n"
        "77 Harbor Road\n"
    )
    shipper = result.document.field_map()[ComparisonField.SHIPPER]

    assert isinstance(shipper.normalized, NormalizedTextValue)
    assert shipper.normalized.value == "APRIL FINE PAPER TRADING CO LTD"
    assert shipper.verified.selected.candidate.raw_value.endswith("77 Harbor Road")
    assert [step.rule for step in shipper.transformations] == [
        NormalizationRule.SELECT_PRIMARY_ENTITY,
        NormalizationRule.NORMALIZE_CASE,
        NormalizationRule.NORMALIZE_LEGAL_SUFFIX,
        NormalizationRule.COLLAPSE_WHITESPACE,
    ]


def test_notify_reference_resolves_to_normalized_consignee() -> None:
    result = _normalize("Consignee: Northstar Imports LLC\nNotify Party: Same as Consignee\n")
    fields = result.document.field_map()
    notify = fields[ComparisonField.NOTIFY_PARTY]

    assert notify.comparison_text == fields[ComparisonField.CONSIGNEE].comparison_text
    assert notify.transformations[-1].rule == NormalizationRule.RESOLVE_PARTY_REFERENCE


def test_container_count_is_a_typed_integer() -> None:
    result = _normalize("No. of Containers: 3 x 40'HC\n")
    container = result.document.field_map()[ComparisonField.CONTAINER_COUNT]

    assert isinstance(container.normalized, NormalizedIntegerValue)
    assert container.normalized.value == 3
    assert container.comparison_text == "3"


def test_kg_weight_is_parsed_without_float_rounding() -> None:
    result = _normalize("Gross Weight: 66,000.25 KG\n")
    weight = result.document.field_map()[ComparisonField.GROSS_WEIGHT_KG]

    assert isinstance(weight.normalized, NormalizedWeightKgValue)
    assert weight.normalized.value == Decimal("66000.25")
    assert weight.comparison_text == "66000.25 kg"


def test_metric_tonnes_are_converted_to_kilograms() -> None:
    result = _normalize("Gross Weight: 66.5 MT\n")
    weight = result.document.field_map()[ComparisonField.GROSS_WEIGHT_KG]

    assert isinstance(weight.normalized, NormalizedWeightKgValue)
    assert weight.normalized.value == Decimal("66500")
    assert weight.transformations[-1].rule == NormalizationRule.CONVERT_WEIGHT_TO_KG


def test_weight_unit_can_be_supplied_by_the_raw_label() -> None:
    result = _normalize("Gross Wt (kgs): 66000\n")
    weight = result.document.field_map()[ComparisonField.GROSS_WEIGHT_KG]

    assert weight.comparison_text == "66000 kg"


def test_unverified_and_unparseable_fields_have_explicit_failures() -> None:
    result = _normalize("Gross Weight: 66000\n")
    failures = {failure.field: failure for failure in result.failures}

    assert failures[ComparisonField.SHIPPER].issue == (NormalizationIssue.MISSING_VERIFIED_FIELD)
    assert failures[ComparisonField.GROSS_WEIGHT_KG].issue == (
        NormalizationIssue.UNSUPPORTED_VALUE_FORMAT
    )
    assert result.is_complete is False


def test_canonical_si_and_label_variant_bl_normalize_equivalently() -> None:
    si = _normalize((CORPUS_DIR / "canonical_si.txt").read_text())
    bl = _normalize(
        (CORPUS_DIR / "label_variants_bl.txt").read_text(),
        DocumentRole.BILL_OF_LADING,
    )

    assert si.is_complete
    assert bl.is_complete
    assert {field: value.comparison_text for field, value in si.document.field_map().items()} == {
        field: value.comparison_text for field, value in bl.document.field_map().items()
    }


def test_document_normalizer_class_matches_convenience_function() -> None:
    text = "Container Count: 3\n"
    document = TextExtractor().extract_bytes(text.encode(), "sample.txt")
    extracted = TextFieldExtractor().extract(document, DocumentRole.SHIPPING_INSTRUCTION)
    verified = TextEvidenceVerifier().verify(document, extracted)

    direct = DocumentNormalizer().normalize(verified)
    convenient = normalize_verified_document(verified)

    assert direct == convenient
