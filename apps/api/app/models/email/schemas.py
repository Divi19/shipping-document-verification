"""Email data models."""

from enum import Enum
from pydantic import BaseModel
from typing import Optional


class EmailAttachment(BaseModel):
    """Email attachment reference."""
    path: str
    filename: str
    content_type: Optional[str] = None


class ParsedEmail(BaseModel):
    """Parsed email with extracted header fields."""
    email_id: str
    from_address: str
    from_name: Optional[str] = None
    subject: str
    body: str
    attachments: list[EmailAttachment]
    thread_id: Optional[str] = None
    in_reply_to: Optional[str] = None
    references: Optional[str] = None
    date: Optional[str] = None


class EmailCategory(str, Enum):
    """Email classification categories."""
    BL_COMPARISON = "BL_COMPARISON"
    SI_REQUEST = "SI_REQUEST"
    INVOICE_QUERY = "INVOICE_QUERY"
    GENERAL = "GENERAL"
    SPAM = "SPAM"


class DecidedBy(str, Enum):
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