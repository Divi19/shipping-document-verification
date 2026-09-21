"""Turn what the pipeline found into one outcome, by an explicit rule order.

Order matters, and each rule answers a different question:

1. Not a comparison request                  -> NOT_APPLICABLE
2. No documents, none claimed to be attached -> AWAITING_DOCUMENTS
3. No documents, but the sender says they
   attached them (or says they went missing) -> NEEDS_REVIEW / missing_attachment
4. A document could not be read              -> NEEDS_REVIEW / unreadable
5. A document is the wrong kind entirely     -> NEEDS_REVIEW / wrong_doc_type
6. One of the pair is absent                 -> NEEDS_REVIEW / missing_attachment
7. A required value is blank or contradictory-> NEEDS_REVIEW / missing_value
8. Every field compared and at least one
   differs                                   -> MISMATCH
9. Every field compared and all agree        -> VERIFIED

Rules 2 and 3 are the same situation to a filename-based check and completely
different to the operator: "please send the draft BL for checking" has nothing
to compare yet, while "please compare the SI and draft BL (attachments appear
to have been dropped)" is a request whose documents went astray.
"""

import re

from app.models.email.schemas import EmailCategory

from .compare import differing_fields, undecided_fields
from .models import CaseOutcome, DocumentRead, DocumentRole, FieldComparison, ReviewReason

# The external-sender banner mentions "attachments" in every message that
# carries it, so it is removed before any claim about attachments is read.
_BANNER = re.compile(
    r"WARNING:.*?originated outside.*?(?:\r?\n|$)|please exercise caution.*?(?:\r?\n|$)",
    re.IGNORECASE | re.DOTALL,
)

_ASSERTS_ATTACHED = re.compile(
    r"attached (?:are|is|herewith|please find)"
    r"|please find attached"
    r"|attached (?:si|bl|are the si)"
    r"|please compare the si and (?:the )?draft bl"
    r"|attachments?[^.\n]*(?:dropped|missing|not attach)"
    r"|(?:draft bl|bl)[^.\n]*still missing"
    r"|enclosed (?:are|is|herewith)",
    re.IGNORECASE,
)


def strip_banner(body: str) -> str:
    """Remove the external-sender warning so it cannot be read as a claim."""
    return _BANNER.sub(" ", body)


def asserts_documents_attached(body: str) -> bool:
    """Whether the sender says the documents are (or should be) attached."""
    return bool(_ASSERTS_ATTACHED.search(strip_banner(body)))


def decide(
    category: EmailCategory,
    body: str,
    documents: list[DocumentRead],
    comparisons: list[FieldComparison],
) -> tuple[CaseOutcome, ReviewReason | None]:
    """Apply the rule order above."""
    if category is not EmailCategory.BL_COMPARISON:
        return CaseOutcome.NOT_APPLICABLE, None

    if not documents:
        if asserts_documents_attached(body):
            return CaseOutcome.NEEDS_REVIEW, ReviewReason.MISSING_ATTACHMENT
        return CaseOutcome.AWAITING_DOCUMENTS, None

    if any(not document.readable for document in documents):
        return CaseOutcome.NEEDS_REVIEW, ReviewReason.UNREADABLE

    if any(document.role is DocumentRole.OTHER for document in documents):
        return CaseOutcome.NEEDS_REVIEW, ReviewReason.WRONG_DOC_TYPE

    roles = {document.role for document in documents}
    if not {DocumentRole.SHIPPING_INSTRUCTION, DocumentRole.BILL_OF_LADING} <= roles:
        # Either only one of the pair arrived, or one document does not identify
        # itself; a reviewer decides which, with both files in front of them.
        return CaseOutcome.NEEDS_REVIEW, ReviewReason.MISSING_ATTACHMENT

    if not comparisons or undecided_fields(comparisons):
        return CaseOutcome.NEEDS_REVIEW, ReviewReason.MISSING_VALUE

    if differing_fields(comparisons):
        return CaseOutcome.MISMATCH, None

    return CaseOutcome.VERIFIED, None
