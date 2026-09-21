"""Email data models."""

from enum import StrEnum

from pydantic import BaseModel


class EmailAttachment(BaseModel):
    """Email attachment reference."""

    path: str
    filename: str
    content_type: str | None = None


class ParsedEmail(BaseModel):
    """Parsed email with extracted header fields."""

    email_id: str
    from_address: str
    from_name: str | None = None
    subject: str
    body: str
    attachments: list[EmailAttachment]
    thread_id: str | None = None
    in_reply_to: str | None = None
    references: str | None = None
    date: str | None = None


class EmailCategory(StrEnum):
    """Email classification categories."""

    BL_COMPARISON = "BL_COMPARISON"
    SI_REQUEST = "SI_REQUEST"
    INVOICE_QUERY = "INVOICE_QUERY"
    GENERAL = "GENERAL"
    SPAM = "SPAM"


class DecidedBy(StrEnum):
    """Which mechanism produced a decision."""

    RULE = "rule"
    LLM = "llm"


class ClassifiedEmail(BaseModel):
    """Email with classification result.

    ``confidence`` records how specific the matched rule is. It is a triage
    signal for reviewers, never evidence: the pipeline decides certainty from
    checks on extracted values, not from a self-reported score.
    """

    email_id: str
    category: EmailCategory
    confidence: float
    reasoning: str
    decided_by: DecidedBy = DecidedBy.RULE
