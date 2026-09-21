"""Bridge the orchestrator to the verified Boxes 5, 6, and 7 pipeline."""

from pathlib import Path

from app.field_extraction import TextFieldExtractor
from app.ingestion.extractors import ContentType, ExtractedContent, IngestionStatus
from app.models.extraction import (
    ComparisonField,
    PageRegionLocator,
    TableCellLocator,
    TextSpanLocator,
)
from app.models.extraction import DocumentRole as ExtractionDocumentRole
from app.normalization import DocumentNormalizer
from app.verification import TextEvidenceVerifier

from .fields import PARTY_FIELDS
from .fields import extract_fields as legacy_extract_fields
from .models import DocumentRead, Evidence, FieldName, FieldValue
from .normalize import (
    format_number,
    normalize_party,
    normalize_place,
    parse_container_count,
    parse_weight_kg,
)


def extract_verified_fields(document: DocumentRead) -> dict[FieldName, FieldValue]:
    """Extract, verify, and normalize fields for the orchestration layer.

    TXT and PDF documents use the shared Box 5 -> 6 -> 7 implementation. The
    teammate extractor remains as a compatibility fallback for Word and Excel
    until those structured table formats have equivalent evidence adapters.
    """
    content_type = _content_type(document.filename)
    if content_type not in {ContentType.TEXT, ContentType.PDF}:
        return legacy_extract_fields(document.text, document.filename)

    source = ExtractedContent(
        text=document.text,
        content_type=content_type,
        source_filename=document.filename,
        status=IngestionStatus.SUCCESS,
        metadata={"extractor": document.reader},
    )
    role = ExtractionDocumentRole(document.role.value)
    candidates = TextFieldExtractor().extract(source, role)
    verified = TextEvidenceVerifier().verify(source, candidates)
    normalized = DocumentNormalizer().normalize(verified)

    normalized_fields = normalized.document.field_map()
    failures = {failure.field.value: failure.message for failure in normalized.failures}
    results: dict[FieldName, FieldValue] = {}
    for field in FieldName:
        shared_field = normalized_fields.get(ComparisonField(field.value))
        if shared_field is None:
            results[field] = FieldValue(
                field=field,
                note=failures.get(field.value, "not extracted"),
            )
            continue

        candidate = shared_field.verified.selected.candidate
        evidence = candidate.evidence[0]
        raw, comparison_value = _orchestration_values(
            field,
            candidate.raw_value,
            shared_field.comparison_text,
        )
        results[field] = FieldValue(
            field=field,
            raw=raw,
            normalized=comparison_value,
            confidence=candidate.confidence,
            evidence=Evidence(
                source=evidence.source_filename,
                locator=_format_locator(evidence.locator),
                snippet=evidence.source_text,
            ),
        )
    return results


def _orchestration_values(field: FieldName, raw: str, normalized: str) -> tuple[str, str]:
    """Translate typed Box 7 values into the orchestrator's string contract."""
    if field in PARTY_FIELDS:
        primary_name = next((line.strip() for line in raw.splitlines() if line.strip()), raw)
        return primary_name, normalize_party(normalized)
    if field in {FieldName.PORT_OF_LOADING, FieldName.PORT_OF_DISCHARGE}:
        return raw, normalize_place(normalized)
    if field is FieldName.CONTAINER_COUNT:
        count = parse_container_count(normalized)
        return raw, str(count) if count is not None else normalized
    if field is FieldName.GROSS_WEIGHT_KG:
        amount = parse_weight_kg(normalized)
        return raw, format_number(amount) if amount is not None else normalized
    return raw, normalized


def _content_type(filename: str) -> ContentType:
    return {
        ".txt": ContentType.TEXT,
        ".md": ContentType.TEXT,
        ".csv": ContentType.TEXT,
        ".pdf": ContentType.PDF,
    }.get(Path(filename).suffix.casefold(), ContentType.UNKNOWN)


def _format_locator(locator: TextSpanLocator | TableCellLocator | PageRegionLocator) -> str:
    if isinstance(locator, TextSpanLocator):
        return (
            f"characters {locator.start}-{locator.end}; "
            f"lines {locator.line_start}-{locator.line_end}"
        )
    if isinstance(locator, TableCellLocator):
        return (
            f"table {locator.table_index}; row {locator.row_index}; column {locator.column_index}"
        )
    if isinstance(locator, PageRegionLocator):
        return f"page {locator.page_number}; region {locator.bounding_box}"
    return str(locator)
