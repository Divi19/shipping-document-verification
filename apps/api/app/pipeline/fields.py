"""Locate the seven comparison fields in a document and keep the evidence.

Input is whatever the reader produced for a document: plain text for .txt,
markdown (with tables) for .xlsx/.docx/.pdf. Three shapes are recognised,
because the supplied documents use all three:

* ``Consignee (Non-Negotiable): EAST BRIGHT FZ-LLC``  - plain text SI/BL
* ``| Load Port | SINGAPORE |``                       - spreadsheet markdown
* a bilingual label line followed by ``243,588``      - Word label above value

Every value carries an :class:`Evidence` record naming the file, the line it
came from and the text as written, so a reviewer never has to take the
pipeline's word for it.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from .models import Evidence, FieldName, FieldValue
from .normalize import (
    format_number,
    is_missing,
    normalize_label,
    normalize_party,
    normalize_place,
    normalize_whitespace,
    parse_container_count,
    parse_weight_kg,
)

# Labels are matched after normalize_label(), which lowercases, drops CJK runs
# and removes parentheticals: "Port of Loading (POL)" arrives here as
# "port of loading". Add synonyms as new document layouts appear.
LABEL_SYNONYMS: dict[FieldName, frozenset[str]] = {
    FieldName.SHIPPER: frozenset({"shipper", "shipper exporter", "exporter", "shipper seller"}),
    FieldName.CONSIGNEE: frozenset({"consignee", "to the order of", "order of", "consigned to"}),
    FieldName.NOTIFY_PARTY: frozenset(
        {
            "notify",
            "notify party",
            "notify address",
            "notify party intermediate consignee",
        }
    ),
    FieldName.PORT_OF_LOADING: frozenset(
        {"port of loading", "load port", "loading port", "pol", "port of load"}
    ),
    FieldName.PORT_OF_DISCHARGE: frozenset(
        {"port of discharge", "discharge port", "pod", "port of delivery"}
    ),
    FieldName.CONTAINER_COUNT: frozenset(
        {
            "container count",
            "total containers",
            "no of containers",
            "no of containers or packages",
            "number of containers",
            "containers",
            "container qty",
        }
    ),
    FieldName.GROSS_WEIGHT_KG: frozenset(
        {
            "gross weight",
            "gross wt",
            "total gross weight",
            "total gross wt",
            "gross weight kg",
            "gross wt kgs",
        }
    ),
}

_LABEL_LOOKUP: dict[str, FieldName] = {
    label: field for field, labels in LABEL_SYNONYMS.items() for label in labels
}

PARTY_FIELDS = (FieldName.SHIPPER, FieldName.CONSIGNEE, FieldName.NOTIFY_PARTY)
PLACE_FIELDS = (FieldName.PORT_OF_LOADING, FieldName.PORT_OF_DISCHARGE)


@dataclass(frozen=True)
class Candidate:
    """A label/value pair found in a document."""

    field: FieldName
    label: str
    value: str
    line_number: int
    snippet: str


def match_field(label: str) -> FieldName | None:
    """Map a document label onto one of the seven fields, if it is one."""
    return _LABEL_LOOKUP.get(normalize_label(label))


# A table cell escapes a literal pipe as "\|"; only unescaped pipes separate
# cells. Splitting on every pipe truncated any value containing one.
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def _split_markdown_row(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    cells = [
        cell.strip().replace("\\|", "|") for cell in _UNESCAPED_PIPE.split(stripped.strip("|"))
    ]
    if len(cells) < 2 or set("".join(cells)) <= {"-", " "}:
        return None
    value = next((cell for cell in cells[1:] if cell), "")
    return cells[0], value


def _split_colon(line: str) -> tuple[str, str] | None:
    if ":" not in line:
        return None
    label, _, value = line.partition(":")
    return label, value


def iter_candidates(text: str) -> Iterator[Candidate]:
    """Yield every label/value pair in the document that names one of the seven."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue

        pair = _split_markdown_row(line) or _split_colon(line)
        if pair is not None:
            label, value = pair
            field = match_field(label)
            if field is not None:
                # A label written as "Label: <nothing>" or "| Label |  |" states
                # that the field is blank. Reading the next line instead would
                # import a neighbouring field's value - the SI that leaves
                # "No. of Containers or Packages:" empty must stay empty.
                yield Candidate(field, label.strip(), value.strip(), index + 1, line.strip())
            continue

        # A bare label line (Word documents put the value in the next paragraph).
        field = match_field(line)
        if field is not None:
            following = _next_value(lines, index)
            if following:
                yield Candidate(field, line.strip(), following, index + 1, line.strip())


def _next_value(lines: list[str], index: int) -> str:
    """Return the next non-empty line, unless it is itself a field label."""
    for candidate in lines[index + 1 : index + 3]:
        text = candidate.strip()
        if not text:
            continue
        row = _split_markdown_row(candidate)
        if row is not None:
            return row[1]
        if match_field(text) is not None:
            return ""
        return text.lstrip("|").strip()
    return ""


def _normalize_for(field: FieldName, value: str) -> str | None:
    """Apply the normalisation appropriate to the field's type."""
    if not value.strip():
        return None
    if field in PARTY_FIELDS:
        # Party blocks continue onto address lines; the name identifies the party.
        return normalize_party(value.splitlines()[0]) or None
    if field in PLACE_FIELDS:
        return normalize_place(value) or None
    if field is FieldName.CONTAINER_COUNT:
        count = parse_container_count(value)
        return str(count) if count is not None else None
    weight = parse_weight_kg(value)
    return format_number(weight) if weight is not None else None


def _choose(field: FieldName, candidates: list[Candidate]) -> FieldValue:
    """Pick one value for a field, refusing to guess between contradictions."""
    if field is FieldName.GROSS_WEIGHT_KG:
        # A container table lists a weight per container and a total; the
        # shipment's gross weight is the total, never one row of it.
        totals = [c for c in candidates if "total" in normalize_label(c.label)]
        if totals:
            candidates = totals

    resolved = [(c, _normalize_for(field, c.value)) for c in candidates]
    usable = [(c, n) for c, n in resolved if n is not None and not is_missing(c.value)]

    if not usable:
        first = candidates[0]
        return FieldValue(
            field=field,
            raw=normalize_whitespace(first.value),
            evidence=_evidence(first),
            note="value is blank or a placeholder",
        )

    distinct = {normalized for _, normalized in usable}
    chosen, normalized = usable[0]
    if len(distinct) > 1:
        # Two different readings of the same field inside one document: report
        # the conflict instead of silently preferring one of them.
        return FieldValue(
            field=field,
            raw=normalize_whitespace(chosen.value),
            evidence=_evidence(chosen),
            note=f"conflicting values in the same document: {sorted(distinct)}",
        )

    return FieldValue(
        field=field,
        raw=normalize_whitespace(chosen.value),
        normalized=normalized,
        evidence=_evidence(chosen),
    )


def _evidence(candidate: Candidate, source: str = "") -> Evidence:
    return Evidence(
        source=source,
        locator=f"line {candidate.line_number}",
        snippet=candidate.snippet,
    )


def extract_fields(text: str, source: str) -> dict[FieldName, FieldValue]:
    """Extract all seven fields from one document's text."""
    grouped: dict[FieldName, list[Candidate]] = {}
    for candidate in iter_candidates(text):
        grouped.setdefault(candidate.field, []).append(candidate)

    extracted: dict[FieldName, FieldValue] = {}
    for field in FieldName:
        candidates = grouped.get(field)
        if not candidates:
            extracted[field] = FieldValue(field=field, note="label not found in document")
            continue
        value = _choose(field, candidates)
        if value.evidence is not None:
            value.evidence.source = source
        extracted[field] = value
    return extracted
