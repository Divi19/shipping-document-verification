"""Human review queue endpoints: list escalated cases, open one, record a decision.

This is the seam the review interface talks to. A package holds everything a
reviewer needs in one response - the original email, both documents, the
fields in question with their evidence and confidence, the escalation reason,
the processing history and the report as it stands.
"""

import collections
import mimetypes
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints

from app.config import data_dir, resolve_within
from app.pipeline import (
    CaseOutcome,
    CaseRecord,
    DocumentRead,
    DocumentSide,
    FieldComparison,
    FieldName,
    FinalReport,
    ReviewAction,
    ReviewConflict,
    ReviewDecision,
    ReviewError,
    ReviewPriority,
    ReviewReason,
    ReviewStatus,
    ReviewTeam,
    ReviewTicket,
    StageAttempt,
    ValueCorrection,
    allowed_actions,
    apply_decision,
    build_report,
    review_queue,
)
from app.pipeline.store import CaseStore

from .cases import get_store, load_email

router = APIRouter(prefix="/review-queue", tags=["review"])

ReviewerName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]


class ReviewQueueItem(BaseModel):
    """One queued case, with enough to choose what to open next."""

    email_id: str
    subject: str
    status: ReviewStatus
    priority: ReviewPriority
    team: ReviewTeam
    reason: ReviewReason | None
    summary: str
    questionable_fields: list[FieldName]
    outcome: CaseOutcome
    opened_at: datetime
    last_decision: ReviewDecision | None


class ReviewQueueCounts(BaseModel):
    """How many tickets are in each status."""

    pending: int = 0
    awaiting_information: int = 0
    resolved: int = 0


class ReviewQueue(BaseModel):
    """The queue, most urgent first, with counts across every status."""

    counts: ReviewQueueCounts
    items: list[ReviewQueueItem]


class ReviewEmail(BaseModel):
    """The original email record."""

    email_id: str
    from_address: str
    subject: str
    body: str
    attachments: list[str]


class ReviewPackage(BaseModel):
    """Everything a reviewer needs to decide one case."""

    email: ReviewEmail
    ticket: ReviewTicket
    allowed_actions: list[ReviewAction]
    automated_outcome: CaseOutcome
    automated_review_reason: ReviewReason | None
    documents: list[DocumentRead]
    comparisons: list[FieldComparison]
    attempts: list[StageAttempt]
    report: FinalReport


class CorrectionRequest(BaseModel):
    """A value the reviewer read from one of the documents."""

    field: FieldName
    side: DocumentSide
    value: str = Field(min_length=1, max_length=500)


class DecisionRequest(BaseModel):
    """A reviewer's decision on a queued case."""

    reviewer: ReviewerName
    action: ReviewAction
    note: str | None = Field(default=None, max_length=2000)
    corrections: list[CorrectionRequest] = Field(default_factory=list, max_length=14)


def _queued_case(email_id: str, store: CaseStore) -> tuple[CaseRecord, ReviewTicket]:
    case = store.get(email_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case not processed: {email_id}")
    if case.review is None:
        raise HTTPException(status_code=404, detail=f"{email_id} is not in the review queue")
    return case, case.review


def _package(case: CaseRecord, ticket: ReviewTicket) -> ReviewPackage:
    email = load_email(case.email_id)
    return ReviewPackage(
        email=ReviewEmail(
            email_id=email.email_id,
            from_address=email.from_address,
            subject=email.subject,
            body=email.body,
            attachments=[attachment.filename for attachment in email.attachments],
        ),
        ticket=ticket,
        allowed_actions=allowed_actions(case),
        automated_outcome=case.outcome,
        automated_review_reason=case.review_reason,
        documents=case.documents,
        comparisons=case.comparisons,
        attempts=case.attempts,
        report=build_report(case),
    )


@router.get("", response_model=ReviewQueue)
def list_review_queue(
    status: ReviewStatus | None = None,
    store: CaseStore = Depends(get_store),
) -> ReviewQueue:
    """List queued cases, most urgent first, optionally in one status."""
    queue = review_queue(store.list())
    tally = collections.Counter(ticket.status for _, ticket in queue)
    counts = ReviewQueueCounts(
        pending=tally[ReviewStatus.PENDING],
        awaiting_information=tally[ReviewStatus.AWAITING_INFORMATION],
        resolved=tally[ReviewStatus.RESOLVED],
    )
    items = [
        ReviewQueueItem(
            email_id=case.email_id,
            subject=case.subject,
            status=ticket.status,
            priority=ticket.priority,
            team=ticket.team,
            reason=ticket.reason,
            summary=ticket.summary,
            questionable_fields=ticket.questionable_fields,
            outcome=case.final_outcome,
            opened_at=ticket.opened_at,
            last_decision=ticket.decisions[-1] if ticket.decisions else None,
        )
        for case, ticket in queue
        if status is None or ticket.status is status
    ]
    return ReviewQueue(counts=counts, items=items)


@router.get("/{email_id}", response_model=ReviewPackage)
def get_review_package(email_id: str, store: CaseStore = Depends(get_store)) -> ReviewPackage:
    """Return the complete review package for one queued case."""
    return _package(*_queued_case(email_id, store))


@router.post("/{email_id}/decision", response_model=ReviewPackage)
def record_decision(
    email_id: str,
    request: DecisionRequest,
    store: CaseStore = Depends(get_store),
) -> ReviewPackage:
    """Record a reviewer's decision and return the updated package and report.

    A decision the case cannot accept is refused whole: 409 when the case is
    not open for review, 422 when the decision itself is invalid.
    """
    case, _ = _queued_case(email_id, store)
    decision = ReviewDecision(
        reviewer=request.reviewer,
        action=request.action,
        note=request.note,
        corrections=[
            ValueCorrection(field=item.field, side=item.side, value=item.value)
            for item in request.corrections
        ],
    )
    try:
        case = store.save(apply_decision(case, decision))
    except ReviewConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    assert case.review is not None
    return _package(case, case.review)


@router.get("/{email_id}/attachments/{filename}", response_class=FileResponse)
def get_attachment(email_id: str, filename: str) -> FileResponse:
    """Serve one of the email's original attachments, so a reviewer can read the source.

    Only files the email itself references are served, and only from inside
    the dataset directory.
    """
    email = load_email(email_id)
    attachment = next((item for item in email.attachments if item.filename == filename), None)
    if attachment is None:
        raise HTTPException(status_code=404, detail=f"{email_id} has no attachment {filename}")
    try:
        path = resolve_within(data_dir(), attachment.path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Attachment not found") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{filename} is not on disk")
    media_type, _ = mimetypes.guess_type(filename)
    return FileResponse(
        path,
        media_type=media_type or "application/octet-stream",
        filename=filename,
        content_disposition_type="inline",
    )
