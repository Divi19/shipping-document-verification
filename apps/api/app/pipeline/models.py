"""The shared case record: every stage reads and writes this object.

One email produces one :class:`CaseRecord`. It carries the classification, the
documents that were read, the seven extracted fields with their evidence, the
comparison, the outcome, and the full attempt history - so a reviewer (and the
report) can always see why the system concluded what it did.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.email.schemas import EmailCategory


def _now() -> datetime:
    return datetime.now(UTC)


class FieldName(StrEnum):
    """The seven fields compared between the SI and the draft BL."""

    SHIPPER = "shipper"
    CONSIGNEE = "consignee"
    NOTIFY_PARTY = "notify_party"
    PORT_OF_LOADING = "port_of_loading"
    PORT_OF_DISCHARGE = "port_of_discharge"
    CONTAINER_COUNT = "container_count"
    GROSS_WEIGHT_KG = "gross_weight_kg"


COMPARED_FIELDS: tuple[FieldName, ...] = tuple(FieldName)


class DocumentRole(StrEnum):
    """What a document turned out to be once it was read."""

    SHIPPING_INSTRUCTION = "shipping_instruction"
    BILL_OF_LADING = "bill_of_lading"
    OTHER = "other"
    UNKNOWN = "unknown"


class ReviewReason(StrEnum):
    """Why a case could not be decided automatically."""

    WRONG_DOC_TYPE = "wrong_doc_type"
    MISSING_ATTACHMENT = "missing_attachment"
    UNREADABLE = "unreadable"
    MISSING_VALUE = "missing_value"


class CaseOutcome(StrEnum):
    """The internal outcome - richer than the three submission statuses.

    ``AWAITING_DOCUMENTS`` is deliberately distinct from ``VERIFIED``: a request
    to send a draft BL has nothing to compare yet, and the interface must never
    present that as "all seven fields checked".
    """

    VERIFIED = "verified"
    MISMATCH = "mismatch"
    NEEDS_REVIEW = "needs_review"
    AWAITING_DOCUMENTS = "awaiting_documents"
    NOT_APPLICABLE = "not_applicable"


class Evidence(BaseModel):
    """Where a value came from, so a reviewer can check it in seconds."""

    source: str
    locator: str
    snippet: str


class FieldValue(BaseModel):
    """One extracted field, with what was read and how it was normalised."""

    field: FieldName
    raw: str | None = None
    normalized: str | None = None
    evidence: Evidence | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    note: str | None = None

    @property
    def is_present(self) -> bool:
        """True when a usable value was found (a blank or `N/A` is not one)."""
        return self.normalized is not None


class DocumentRead(BaseModel):
    """The result of reading one attachment."""

    path: str
    filename: str
    reader: str
    readable: bool
    role: DocumentRole = DocumentRole.UNKNOWN
    text: str = ""
    failure: str | None = None


class FieldComparison(BaseModel):
    """SI against BL for a single field."""

    field: FieldName
    si: FieldValue
    bl: FieldValue
    matches: bool | None = None  # None: not decidable from what was read
    note: str | None = None

    @property
    def is_defect(self) -> bool:
        return self.matches is False


class StageAttempt(BaseModel):
    """One attempt at one stage, kept even when it failed."""

    stage: str
    attempt: int
    ok: bool
    detail: str
    at: datetime = Field(default_factory=_now)


class ReviewAction(StrEnum):
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    UNABLE_TO_VERIFY = "unable_to_verify"


class ReviewDecision(BaseModel):
    """What a human decided about an escalated case."""

    reviewer: str
    action: ReviewAction
    note: str | None = None
    corrected_fields: list[FieldName] = Field(default_factory=list)
    at: datetime = Field(default_factory=_now)


class CaseRecord(BaseModel):
    """Everything known about one email."""

    email_id: str
    category: EmailCategory
    outcome: CaseOutcome
    review_reason: ReviewReason | None = None
    documents: list[DocumentRead] = Field(default_factory=list)
    comparisons: list[FieldComparison] = Field(default_factory=list)
    attempts: list[StageAttempt] = Field(default_factory=list)
    classification_reasoning: str = ""
    review: ReviewDecision | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @property
    def defect_fields(self) -> list[FieldName]:
        """Fields that differ - only meaningful for a completed comparison."""
        if self.outcome is not CaseOutcome.MISMATCH:
            return []
        return [c.field for c in self.comparisons if c.is_defect]

    def record_attempt(self, stage: str, ok: bool, detail: str) -> None:
        attempt = sum(1 for a in self.attempts if a.stage == stage) + 1
        self.attempts.append(StageAttempt(stage=stage, attempt=attempt, ok=ok, detail=detail))
        self.updated_at = _now()

    def document(self, role: DocumentRole) -> DocumentRead | None:
        """Return the first document read as ``role``, if any."""
        return next((d for d in self.documents if d.role is role), None)
