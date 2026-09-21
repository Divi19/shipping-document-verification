"""Deterministic, traceable normalisation.

Two documents describe the same shipment with different wording: `Port of
Loading` against `Load Port`, `Gross Wt (kgs) (毛重 KGS)` against a bare Excel
number, `6 x 40'HC` against `6`. Normalisation exists to remove exactly those
harmless differences - never to make two genuinely different values look equal.

Every transformation here is explicit and reversible in the report: the raw
value stays on the FieldValue alongside the normalised one.
"""

import re

# Placeholders the documents use for "not filled in yet". These are missing
# values, not discrepancies - they must escalate, never compare.
MISSING_MARKERS = frozenset({"", "-", "--", "N/A", "NA", "N.A.", "TBA", "TBD", "???", "?", "NIL"})

_CJK = re.compile(r"[\u3000-\u9fff\uff00-\uffef]+")
_PARENTHETICAL = re.compile(r"\([^)]*\)")
_UNDERSCORE_RUN = re.compile(r"_{2,}")
_NON_ALNUM = re.compile(r"[^A-Z0-9 ]+")
_SPACES = re.compile(r"\s+")

# Company suffixes written inconsistently across documents.
_SUFFIX_FIXES = (
    (re.compile(r"\bPTE\.?\s*LTD\.?\b"), "PTE LTD"),
    (re.compile(r"\bCO\.?,?\s*LTD\.?\b"), "CO LTD"),
    (re.compile(r"\bSDN\.?\s*BHD\.?\b"), "SDN BHD"),
    (re.compile(r"\bLIMITED\b"), "LTD"),
    (re.compile(r"\bINCORPORATED\b"), "INC"),
)

_CONTAINER_COUNT = re.compile(r"(\d+)\s*(?:x|\*)\s*\d{2}'?\s*[A-Z]{2,4}", re.IGNORECASE)
_NUMBER = re.compile(r"\d[\d,. ]*\d|\d")


def strip_cjk(text: str) -> str:
    """Drop CJK runs; the Word BLs label fields bilingually."""
    return _CJK.sub(" ", text)


def is_missing(value: str | None) -> bool:
    """True when the document left the field blank or used a placeholder."""
    if value is None:
        return True
    cleaned = _UNDERSCORE_RUN.sub("", strip_cjk(value)).strip()
    cleaned = cleaned.strip("_.- ")
    return cleaned.upper() in MISSING_MARKERS


def normalize_whitespace(value: str) -> str:
    """Collapse runs of whitespace; used when storing a raw value for display."""
    return _SPACES.sub(" ", value).strip()


def normalize_label(label: str) -> str:
    """Reduce a field label to a comparable key.

    ``Consignee (Non-Negotiable)`` -> ``consignee``;
    ``Gross Wt (kgs) (毛重 KGS)`` -> ``gross wt``.
    """
    text = strip_cjk(label)
    text = _PARENTHETICAL.sub(" ", text)
    text = text.replace(".", " ")
    text = _NON_ALNUM.sub(" ", text.upper())
    return _SPACES.sub(" ", text).strip().lower()


def normalize_party(value: str) -> str:
    """Normalise a company name for comparison."""
    text = strip_cjk(value).upper()
    text = _PARENTHETICAL.sub(" ", text)
    for pattern, replacement in _SUFFIX_FIXES:
        text = pattern.sub(replacement, text)
    text = _NON_ALNUM.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def normalize_place(value: str) -> str:
    """Normalise a port name.

    Trailing UN/LOCODEs and country qualifiers are formatting, not content:
    ``NANTONG, CHINA (CNNTG)`` and ``NANTONG, CHINA`` are the same port.
    """
    text = strip_cjk(value).upper()
    text = _PARENTHETICAL.sub(" ", text)
    text = _NON_ALNUM.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def parse_container_count(value: str) -> int | None:
    """Read a container count from ``6 x 40'HC``, ``12 X 20'FCL`` or ``6``."""
    text = strip_cjk(value)
    match = _CONTAINER_COUNT.search(text)
    if match:
        return int(match.group(1))
    digits = re.fullmatch(r"\s*(\d+)\s*", text.replace(",", ""))
    return int(digits.group(1)) if digits else None


def parse_weight_kg(value: str) -> float | None:
    """Read a gross weight in kilograms.

    Handles ``131,058 KG``, ``131058``, ``243,588`` and ``138 MT`` (converted),
    which is why the unit is inspected rather than assumed.
    """
    text = strip_cjk(value).upper().replace("\u00a0", " ")
    match = _NUMBER.search(text)
    if not match:
        return None
    number = match.group(0).replace(",", "").replace(" ", "")
    if number.count(".") > 1:
        return None
    try:
        amount = float(number)
    except ValueError:
        return None
    tail = text[match.end() :]
    if re.search(r"\bMT\b|\bTONNES?\b|\bMETRIC TONS?\b", tail):
        amount *= 1000
    return amount


def format_number(amount: float) -> str:
    """Render a parsed number without trailing ``.0`` noise."""
    return str(int(amount)) if amount.is_integer() else f"{amount:g}"


def party_names_agree(first: str, second: str) -> bool:
    """Whether two party values name the same party.

    Layouts differ in how much of the block belongs to the field: a Word BL
    keeps the name and its address in one cell, while the matching Excel SI
    holds the name alone. When one value is the other followed by address
    text, that is a layout difference, not a change of party - an amended
    party replaces the name outright, so it never shares this prefix.
    """
    if first == second:
        return True
    shorter, longer = sorted((first, second), key=len)
    if len(shorter) < 6:
        return False
    return longer.startswith(f"{shorter} ")
