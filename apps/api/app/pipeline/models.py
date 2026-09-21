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
    """What a reviewer can decide about a queued case."""

    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    INFORMATION_REQUESTED = "information_requested"
    UNABLE_TO_VERIFY = "unable_to_verify"


class ReviewStatus(StrEnum):
    """Where a case stands in the human review queue."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    AWAITING_INFORMATION = "awaiting_information"
    RESOLVED = "resolved"


class ReviewPriority(StrEnum):
    """How soon a reviewer should pick up a queued case."""

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class ReviewTeam(StrEnum):
    """Who owns a queued case."""

    DOCUMENT_INTAKE = "document_intake"  # the fix is obtaining the right, readable file
    FIELD_VERIFICATION = "field_verification"  # the fix is reading values from the source


class DocumentSide(StrEnum):
    """Which document of the pair a value belongs to."""

    SI = "si"
    BL = "bl"


class ValueCorrection(BaseModel):
    """One value a reviewer read from a source document."""

    field: FieldName
    side: DocumentSide
    value: str
    previous: str | None = None  # the extracted raw value this replaces


class ReviewDecision(BaseModel):
    """What a human decided about an escalated case."""

    reviewer: str
    action: ReviewAction
    note: str | None = None
    corrections: list[ValueCorrection] = Field(default_factory=list)
    at: datetime = Field(default_factory=_now)


class ReviewResolution(BaseModel):
    """The result a reviewer's decision produced.

    It sits beside the automated result and never replaces it on the record.
    """

    outcome: CaseOutcome
    review_reason: ReviewReason | None = None
    comparisons: list[FieldComparison] = Field(default_factory=list)
    action: ReviewAction
    reviewer: str
    at: datetime = Field(default_factory=_now)


class ReviewTicket(BaseModel):
    """A case in the human review queue: why it is there, who owns it, what was decided."""

    status: ReviewStatus = ReviewStatus.PENDING
    reason: ReviewReason | None = None
    failed_checks: list[str] = Field(default_factory=list)
    summary: str
    priority: ReviewPriority
    team: ReviewTeam
    questionable_fields: list[FieldName] = Field(default_factory=list)
    recommended_action: ReviewAction
    decisions: list[ReviewDecision] = Field(default_factory=list)
    resolution: ReviewResolution | None = None
    opened_at: datetime = Field(default_factory=_now)
    closed_at: datetime | None = None


class CaseRecord(BaseModel):
    """Everything known about one email.

    ``outcome``, ``review_reason`` and ``comparisons`` are the automated result.
    A reviewer's resolution is kept on ``review``; the ``final_*`` properties
    return whichever result currently stands.
    """

    email_id: str
    subject: str = ""
    category: EmailCategory
    outcome: CaseOutcome
    review_reason: ReviewReason | None = None
    documents: list[DocumentRead] = Field(default_factory=list)
    comparisons: list[FieldComparison] = Field(default_factory=list)
    attempts: list[StageAttempt] = Field(default_factory=list)
    classification_reasoning: str = ""
    review: ReviewTicket | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @property
    def defect_fields(self) -> list[FieldName]:
        """Fields that differ - only meaningful for a completed comparison."""
        if self.outcome is not CaseOutcome.MISMATCH:
            return []
        return [c.field for c in self.comparisons if c.is_defect]

    @property
    def resolution(self) -> ReviewResolution | None:
        """The reviewer's resolution, when the case has one."""
        return self.review.resolution if self.review is not None else None

    @property
    def final_outcome(self) -> CaseOutcome:
        """The reviewer's outcome when there is one, otherwise the automated one."""
        return self.resolution.outcome if self.resolution else self.outcome

    @property
    def final_review_reason(self) -> ReviewReason | None:
        """The review reason that goes with ``final_outcome``."""
        return self.resolution.review_reason if self.resolution else self.review_reason

    @property
    def final_comparisons(self) -> list[FieldComparison]:
        """The comparisons that go with ``final_outcome``."""
        return self.resolution.comparisons if self.resolution else self.comparisons

    @property
    def final_defect_fields(self) -> list[FieldName]:
        """Fields that differ in the result that currently stands."""
        if self.final_outcome is not CaseOutcome.MISMATCH:
            return []
        return [c.field for c in self.final_comparisons if c.is_defect]

    @property
    def review_status(self) -> ReviewStatus:
        """The queue status; a NEEDS_REVIEW case without a ticket still counts as pending."""
        if self.review is not None:
            return self.review.status
        if self.outcome is CaseOutcome.NEEDS_REVIEW:
            return ReviewStatus.PENDING
        return ReviewStatus.NOT_REQUIRED

    def record_attempt(self, stage: str, ok: bool, detail: str) -> None:
        attempt = sum(1 for a in self.attempts if a.stage == stage) + 1
        self.attempts.append(StageAttempt(stage=stage, attempt=attempt, ok=ok, detail=detail))
        self.updated_at = _now()

    def document(self, role: DocumentRole) -> DocumentRead | None:
        """Return the first document read as ``role``, if any."""
        return next((d for d in self.documents if d.role is role), None)
