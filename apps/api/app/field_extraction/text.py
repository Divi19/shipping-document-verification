"""Deterministic required-field extraction from plain-text documents."""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from app.ingestion.extractors import ContentType, ExtractedContent, IngestionStatus
from app.models.extraction import (
    ALL_COMPARISON_FIELDS,
    ComparisonField,
    DocumentFieldCandidates,
    DocumentRole,
    EvidenceReference,
    ExtractionMethod,
    FieldCandidate,
    TextSpanLocator,
)

from .semantic import SemanticFieldFallback

FIELD_LABELS: dict[ComparisonField, tuple[str, ...]] = {
    ComparisonField.SHIPPER: (
        "Shipper",
        "Shipper/Exporter",
        "Shipper (Principal or Seller)",
        "Exporter",
    ),
    ComparisonField.CONSIGNEE: (
        "Consignee",
        "Consignee (Non-Negotiable)",
        "To the Order of",
    ),
    ComparisonField.NOTIFY_PARTY: (
        "Notify Party",
        "Notify Party/Intermediate Consignee",
        "Notify",
    ),
    ComparisonField.PORT_OF_LOADING: (
        "Port of Loading",
        "Port of Loading (POL)",
        "Load Port",
        "POL",
    ),
    ComparisonField.PORT_OF_DISCHARGE: (
        "Port of Discharge",
        "Port of Discharge (POD)",
        "Discharge Port",
        "POD",
    ),
    ComparisonField.CONTAINER_COUNT: (
        "Container Count",
        "Total Containers",
        "No. of Containers",
        "No. of Containers or Packages",
        "Containers",
    ),
    ComparisonField.GROSS_WEIGHT_KG: (
        "Gross Weight",
        "Gross Weight (KG)",
        "Gross Wt (kgs)",
        "Gross Weight毛重(KGS)",
        "Total Gross Weight",
        "Total Gross Wt (kgs)",
    ),
}

PARTY_FIELDS = {
    ComparisonField.SHIPPER,
    ComparisonField.CONSIGNEE,
    ComparisonField.NOTIFY_PARTY,
}

PLACEHOLDER_VALUES = {
    "",
    "-",
    "N/A",
    "NA",
    "NONE",
    "NOT PROVIDED",
    "TBC",
    "TBD",
    "UNKNOWN",
}


@dataclass(frozen=True)
class _TextLine:
    """One source line with half-open character offsets."""

    body: str
    start: int
    end: int
    number: int


@dataclass(frozen=True)
class _LabelMatch:
    """Recognized field label and its inline value."""

    field: ComparisonField
    raw_label: str
    inline_value: str
    label_start: int
    extraction_method: ExtractionMethod | None = None
    confidence_ceiling: float | None = None


def _compile_label_pattern() -> re.Pattern[str]:
    aliases = sorted(
        (alias for labels in FIELD_LABELS.values() for alias in labels),
        key=len,
        reverse=True,
    )
    # A unit qualifier may follow any label - "TOTAL Gross Weight (KG):" as well
    # as the listed "Gross Weight (KG)". Without this the longest alias that
    # fits ("Total Gross Weight") matched, the space after it counted as the
    # separator, and "(KG): 131,322 KG" became an unparseable value.
    #
    # PDF text layers also glue a Title Case label straight onto an UPPER CASE
    # value: "Notify Party/Intermediate ConsigneeNAGAPPA EXPORTS". With no
    # separator the long alias could not match, the short "Notify" did, and the
    # value became "Party/Intermediate ConsigneeNAGAPPA EXPORTS" - a false
    # mismatch. A lowercase-to-uppercase boundary is accepted as a separator.
    # It is matched case-sensitively; case-insensitive, it would split any word.
    return re.compile(
        rf"^(?P<indent>\s*)(?P<label>{'|'.join(re.escape(alias) for alias in aliases)})"
        r"(?P<unit>\s*\(\s*(?:KGS?|MTS?|TONS?)\s*\))?"
        r"(?:\s*:\s*|\s+|(?-i:(?<=[a-z])(?=[A-Z])))(?P<value>.*?)\s*$",
        re.IGNORECASE,
    )


LABEL_PATTERN = _compile_label_pattern()
LABEL_TO_FIELD = {
    alias.casefold(): field for field, aliases in FIELD_LABELS.items() for alias in aliases
}
FUZZY_DELIMITED_LABEL_PATTERN = re.compile(
    r"^(?P<indent>\s*)(?P<label>[^:\n]{4,40}?)[.:]\s+(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
GENERIC_LABEL_PATTERN = re.compile(r"^\s*[^:\n]{1,80}:\s*")
# A trailing weight-unit qualifier on a label, spaced or glued: "(KG)", "(kgs)".
UNIT_QUALIFIER_PATTERN = re.compile(r"\s*\(\s*(?:KGS?|MTS?|TONS?)\s*\)\s*$", re.IGNORECASE)
DECORATED_PLACEHOLDER_PATTERN = re.compile(
    r"^(?:_+|\?+|-+)(?:\s*(?:KG|KGS|MT|MTS|TONS?))?$",
    re.IGNORECASE,
)


class TextFieldExtractor:
    """Extract Box 5 candidates from ingested plain text or PDF text layers."""

    confidence = 0.98

    def __init__(self, semantic_fallback: SemanticFieldFallback | None = None) -> None:
        self.semantic_fallback = semantic_fallback

    def extract(
        self,
        document: ExtractedContent,
        document_role: DocumentRole,
    ) -> DocumentFieldCandidates:
        """Extract candidates from the structured ingestion result."""
        if document.content_type not in {ContentType.TEXT, ContentType.PDF}:
            raise ValueError(
                "TextFieldExtractor only accepts text/plain or application/pdf documents"
            )
        if not document.source_filename:
            raise ValueError("source_filename is required for extraction evidence")
        if document.status != IngestionStatus.SUCCESS:
            diagnostics = [
                f"Document ingestion status is {document.status.value}; field extraction skipped.",
                *document.diagnostics,
            ]
            return DocumentFieldCandidates(
                document_role=document_role,
                source_filename=document.source_filename,
                diagnostics=diagnostics,
            )
        method = ExtractionMethod.LABEL_MAP
        confidence = self.confidence
        if document.metadata.get("extractor") == "tesseract":
            method = ExtractionMethod.OCR
            average = document.metadata.get("ocr_average_confidence")
            if isinstance(average, int | float):
                confidence = min(self.confidence, max(0.0, float(average) / 100))
        return self.extract_text(
            document.text,
            document.source_filename,
            document_role,
            extraction_method=method,
            confidence=confidence,
        )

    def extract_text(
        self,
        text: str,
        source_filename: str,
        document_role: DocumentRole,
        *,
        extraction_method: ExtractionMethod = ExtractionMethod.LABEL_MAP,
        confidence: float | None = None,
    ) -> DocumentFieldCandidates:
        """Extract candidates with exact text evidence and source-order retention."""
        if not source_filename:
            raise ValueError("source_filename is required for extraction evidence")

        lines = self._split_lines(text)
        candidates: list[FieldCandidate] = []
        for index, line in enumerate(lines):
            match = self._match_label(line)
            if match is None:
                continue

            raw_value, evidence_end, line_end = self._read_value(lines, index, match)
            if self._is_placeholder(raw_value):
                continue

            evidence_start = line.start + match.label_start
            source_text = text[evidence_start:evidence_end]
            candidates.append(
                FieldCandidate(
                    field=match.field,
                    document_role=document_role,
                    raw_label=match.raw_label,
                    raw_value=raw_value,
                    evidence=[
                        EvidenceReference(
                            source_filename=source_filename,
                            locator=TextSpanLocator(
                                start=evidence_start,
                                end=evidence_end,
                                line_start=line.number,
                                line_end=line_end,
                            ),
                            source_text=source_text,
                        )
                    ],
                    extraction_method=match.extraction_method or extraction_method,
                    confidence=self._candidate_confidence(match, confidence),
                )
            )

        diagnostics = self._build_diagnostics(candidates)
        deterministic = DocumentFieldCandidates(
            document_role=document_role,
            source_filename=source_filename,
            candidates=candidates,
            diagnostics=diagnostics,
        )
        if self.semantic_fallback is None:
            return deterministic
        return self.semantic_fallback.augment(text, deterministic)

    def close(self) -> None:
        """Release optional semantic-provider resources."""
        if self.semantic_fallback is not None:
            self.semantic_fallback.close()

    @staticmethod
    def _split_lines(text: str) -> list[_TextLine]:
        lines: list[_TextLine] = []
        offset = 0
        for number, source_line in enumerate(text.splitlines(keepends=True), start=1):
            body = source_line.rstrip("\r\n")
            lines.append(
                _TextLine(
                    body=body,
                    start=offset,
                    end=offset + len(body),
                    number=number,
                )
            )
            offset += len(source_line)
        if text and not lines:
            lines.append(_TextLine(body=text, start=0, end=len(text), number=1))
        return lines

    @staticmethod
    def _match_label(line: _TextLine) -> _LabelMatch | None:
        match = LABEL_PATTERN.match(line.body)
        if match is not None:
            alias = match.group("label")
            # Keep the unit on the label: the weight normaliser reads it when
            # the value itself carries no unit.
            raw_label = alias + (match.group("unit") or "")
            return _LabelMatch(
                field=LABEL_TO_FIELD[alias.casefold()],
                raw_label=raw_label,
                inline_value=match.group("value").strip(),
                label_start=len(match.group("indent")),
            )
        fuzzy = FUZZY_DELIMITED_LABEL_PATTERN.match(line.body)
        if fuzzy is None:
            return None
        fuzzy_result = TextFieldExtractor._closest_label(fuzzy.group("label"))
        if fuzzy_result is None:
            return None
        field, similarity = fuzzy_result
        return _LabelMatch(
            field=field,
            raw_label=fuzzy.group("label").strip(),
            inline_value=fuzzy.group("value").strip(),
            label_start=len(fuzzy.group("indent")),
            extraction_method=ExtractionMethod.LEVENSHTEIN_LABEL,
            confidence_ceiling=similarity * 0.95,
        )

    def _candidate_confidence(
        self,
        match: _LabelMatch,
        document_confidence: float | None,
    ) -> float:
        confidence = self.confidence if document_confidence is None else document_confidence
        if match.confidence_ceiling is not None:
            return min(confidence, match.confidence_ceiling)
        return confidence

    @staticmethod
    def _closest_label(raw_label: str) -> tuple[ComparisonField, float] | None:
        # A unit qualifier is not part of the label's identity. Left in, a glued
        # "(KGS)" on "TOTAL Gross Weightss(KGS)" added three edits and pushed a
        # recognisable label past the distance limit; stripped on both sides,
        # the comparison is between the words that actually name the field.
        candidate = TextFieldExtractor._normalize_label(UNIT_QUALIFIER_PATTERN.sub("", raw_label))
        if len(candidate) < 6:
            return None
        matches: list[tuple[float, int, ComparisonField]] = []
        for field, aliases in FIELD_LABELS.items():
            for alias in aliases:
                normalized_alias = TextFieldExtractor._normalize_label(
                    UNIT_QUALIFIER_PATTERN.sub("", alias)
                )
                distance = TextFieldExtractor._levenshtein_distance(candidate, normalized_alias)
                similarity = 1 - distance / max(len(candidate), len(normalized_alias))
                matches.append((similarity, -distance, field))
        best_similarity, negated_distance, best_field = max(matches, key=lambda item: item[:2])
        if best_similarity < 0.88 or -negated_distance > 2:
            return None
        return best_field, best_similarity

    @staticmethod
    def _normalize_label(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        return "".join(character for character in normalized if character.isalnum())

    @staticmethod
    def _levenshtein_distance(left: str, right: str) -> int:
        if len(left) < len(right):
            left, right = right, left
        previous = list(range(len(right) + 1))
        for left_index, left_character in enumerate(left, start=1):
            current = [left_index]
            for right_index, right_character in enumerate(right, start=1):
                current.append(
                    min(
                        current[-1] + 1,
                        previous[right_index] + 1,
                        previous[right_index - 1] + (left_character != right_character),
                    )
                )
            previous = current
        return previous[-1]

    def _read_value(
        self,
        lines: list[_TextLine],
        index: int,
        match: _LabelMatch,
    ) -> tuple[str, int, int]:
        line = lines[index]
        values = [match.inline_value] if match.inline_value else []
        evidence_end = line.end
        line_end = line.number

        if match.field not in PARTY_FIELDS:
            return "\n".join(values), evidence_end, line_end

        for continuation in lines[index + 1 :]:
            if not continuation.body.strip() or self._match_label(continuation) is not None:
                break
            if match.inline_value and not continuation.body[:1].isspace():
                break
            if not match.inline_value and GENERIC_LABEL_PATTERN.match(continuation.body):
                break

            values.append(continuation.body.strip())
            evidence_end = continuation.end
            line_end = continuation.number

        return "\n".join(values), evidence_end, line_end

    @staticmethod
    def _is_placeholder(value: str) -> bool:
        stripped = value.strip()
        return (
            stripped.upper() in PLACEHOLDER_VALUES
            or DECORATED_PLACEHOLDER_PATTERN.fullmatch(stripped) is not None
        )

    @staticmethod
    def _build_diagnostics(candidates: list[FieldCandidate]) -> list[str]:
        counts = Counter(candidate.field for candidate in candidates)
        diagnostics = [
            f"No candidate extracted for {field.value}."
            for field in sorted(ALL_COMPARISON_FIELDS - set(counts), key=lambda item: item.value)
        ]
        diagnostics.extend(
            f"Multiple candidates extracted for {field.value}: {count}."
            for field, count in sorted(counts.items(), key=lambda item: item[0].value)
            if count > 1
        )
        diagnostics.extend(
            f"Levenshtein label recovery mapped {candidate.raw_label!r} to {candidate.field.value}."
            for candidate in candidates
            if candidate.extraction_method == ExtractionMethod.LEVENSHTEIN_LABEL
        )
        return diagnostics


def extract_text_fields(
    document: ExtractedContent,
    document_role: DocumentRole,
    semantic_fallback: SemanticFieldFallback | None = None,
) -> DocumentFieldCandidates:
    """Convenience boundary between document ingestion and Box 5."""
    return TextFieldExtractor(semantic_fallback).extract(document, document_role)
