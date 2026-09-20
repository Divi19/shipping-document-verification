"""Decide what a document actually is, after reading it.

A filename cannot answer this: in the supplied data a file named
``email_501_BL.txt`` contains a Commercial Invoice, and the SI in the PDF and
Excel pairs is titled ``BILL OF LADING INSTRUCTION`` / ``BL INSTRUCTION``.
Matching on "bill of lading" alone therefore labels the SI as the BL and the
whole comparison runs backwards - so "instruction" is decisive here.
"""

import re

from .models import DocumentRead, DocumentRole
from .normalize import strip_cjk

# Checked in order. The first pattern that matches the document header wins.
_ROLE_PATTERNS: tuple[tuple[re.Pattern[str], DocumentRole], ...] = (
    (
        re.compile(
            r"\b(shipping instruction|bl instruction|b/?l instruction"
            r"|bill of lading instruction)\b",
            re.IGNORECASE,
        ),
        DocumentRole.SHIPPING_INSTRUCTION,
    ),
    (
        re.compile(
            r"\b(commercial invoice|packing list|certificate of origin"
            r"|debit note|credit note)\b",
            re.IGNORECASE,
        ),
        DocumentRole.OTHER,
    ),
    (
        re.compile(r"\b(bill of lading|b/?l draft|draft b/?l|sea ?waybill)\b", re.IGNORECASE),
        DocumentRole.BILL_OF_LADING,
    ),
)

# Only the top of the document decides its identity; "B/L No." appears inside
# an SI and must not turn it into a bill of lading.
HEADER_LINES = 12


def document_header(text: str) -> str:
    """The first few non-empty lines, where the document names itself."""
    lines = [line.strip() for line in strip_cjk(text).splitlines() if line.strip()]
    return "\n".join(lines[:HEADER_LINES])


def detect_role(text: str) -> DocumentRole:
    """Classify a document from its header."""
    header = document_header(text)
    if not header:
        return DocumentRole.UNKNOWN
    for pattern, role in _ROLE_PATTERNS:
        if pattern.search(header):
            return role
    return DocumentRole.UNKNOWN


def is_readable(text: str, minimum_characters: int = 40) -> bool:
    """Whether a reader produced usable text.

    An empty file, a truncated PDF and an image-only scan all arrive here as
    (almost) no text. That is an escalation, never an empty comparison.
    """
    return len(text.strip()) >= minimum_characters


def describe(document: DocumentRead) -> str:
    """One line for the review package and the audit trail."""
    if not document.readable:
        return f"{document.filename}: unreadable ({document.failure or 'no text extracted'})"
    return f"{document.filename}: {document.role.value} via {document.reader}"
