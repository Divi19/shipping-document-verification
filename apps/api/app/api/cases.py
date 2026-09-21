"""Case endpoints: run the pipeline over one email or the whole inbox, read a case.

Responses are the pipeline's own Pydantic models, so the generated TypeScript
contracts stay in step with the backend automatically. Review decisions live in
``app.api.review``.

The router deliberately avoids importing the document ingestion package at
module level, so the API surface is testable without the extraction extras.
"""

import collections
import json
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.composition import build_pipeline
from app.config import data_dir
from app.models.email.schemas import ParsedEmail
from app.pipeline import (
    CaseOutcome,
    CaseRecord,
    FinalReport,
    Pipeline,
    ReviewStatus,
    build_report,
    reprocess,
    submission_entry,
)
from app.pipeline.inbox import iter_emails, parse_email
from app.pipeline.models import FieldName
from app.pipeline.store import CaseStore, InMemoryCaseStore
from app.pipeline.submission import SubmissionEntry

router = APIRouter(prefix="/cases", tags=["cases"])

EMAIL_ID_PATTERN = re.compile(r"^email_\d{1,6}$")


@lru_cache(maxsize=1)
def get_store() -> CaseStore:
    """The process-wide case store (swap for Supabase without touching routes)."""
    return InMemoryCaseStore()


@lru_cache(maxsize=1)
def get_pipeline() -> Pipeline:
    """The configured pipeline, with AI attached when a key is present."""
    return build_pipeline()


class CaseSummary(BaseModel):
    """List-view row: enough to triage without loading every document."""

    email_id: str
    category: str
    outcome: CaseOutcome
    review_reason: str | None
    defect_fields: list[FieldName]
    review_status: ReviewStatus
    reviewed: bool  # at least one human decision is on record


class InboxRun(BaseModel):
    """What one pass over the inbox did."""

    processed: int
    skipped: int
    outcomes: dict[str, int] = Field(default_factory=dict)
    queued_for_review: int


class AvailableCase(BaseModel):
    """An inbox item that can be run from the local demonstration UI."""

    email_id: str
    subject: str
    attachment_count: int
    attachment_names: list[str]


def _summary(case: CaseRecord) -> CaseSummary:
    return CaseSummary(
        email_id=case.email_id,
        category=case.category.value,
        outcome=case.outcome,
        review_reason=case.review_reason.value if case.review_reason else None,
        defect_fields=case.defect_fields,
        review_status=case.review_status,
        reviewed=bool(case.review and case.review.decisions),
    )


def _email_path(email_id: str) -> Path:
    if not EMAIL_ID_PATTERN.match(email_id):
        raise HTTPException(status_code=422, detail="Invalid email_id")
    path = data_dir() / "inbox" / f"{email_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Unknown email_id: {email_id}")
    return path


def load_email(email_id: str) -> ParsedEmail:
    """Load one inbox record, or raise 404/422 for an unknown or malformed id."""
    record = json.loads(_email_path(email_id).read_text(encoding="utf-8"))
    return parse_email(record)


def _process(email: ParsedEmail, pipeline: Pipeline, store: CaseStore) -> CaseRecord:
    """Run one email and store it, keeping history from any earlier run."""
    return store.save(reprocess(store.get(email.email_id), pipeline.run(email)))


@router.get("/available", response_model=list[AvailableCase])
def available_cases() -> list[AvailableCase]:
    """List inbox records that can exercise the complete pipeline."""
    available: list[AvailableCase] = []
    for path in sorted((data_dir() / "inbox").glob("email_*.json")):
        email = parse_email(json.loads(path.read_text(encoding="utf-8")))
        available.append(
            AvailableCase(
                email_id=email.email_id,
                subject=email.subject,
                attachment_count=len(email.attachments),
                attachment_names=[item.filename for item in email.attachments],
            )
        )
    return available


@router.post("/{email_id}/run", response_model=CaseRecord)
def run_case(
    email_id: str,
    pipeline: Pipeline = Depends(get_pipeline),
    store: CaseStore = Depends(get_store),
) -> CaseRecord:
    """Process one email and store the result, whatever the outcome.

    A case that needs review is saved here too, with its reason and evidence,
    so it appears in the queue immediately rather than after a human replies.
    Running a case again is the controlled retry: earlier attempts and any
    human decision stay on the record.
    """
    return _process(load_email(email_id), pipeline, store)


@router.post("/run-inbox", response_model=InboxRun)
def run_inbox(
    pipeline: Pipeline = Depends(get_pipeline),
    store: CaseStore = Depends(get_store),
) -> InboxRun:
    """Process every inbox email not processed yet, and fill the review queue.

    Cases already in the store are skipped, so a second pass duplicates no work
    and does not call a configured model again. Use ``/cases/{id}/run`` to
    retry one case.
    """
    outcomes: collections.Counter[str] = collections.Counter()
    processed = skipped = 0
    for email in iter_emails(data_dir()):
        if store.get(email.email_id) is not None:
            skipped += 1
            continue
        case = _process(email, pipeline, store)
        outcomes[case.outcome.value] += 1
        processed += 1
    queued = sum(
        1
        for case in store.list()
        if case.review_status in {ReviewStatus.PENDING, ReviewStatus.AWAITING_INFORMATION}
    )
    return InboxRun(
        processed=processed,
        skipped=skipped,
        outcomes=dict(outcomes),
        queued_for_review=queued,
    )


@router.post("/{email_id}/run-report", response_model=FinalReport)
def run_case_report(
    email_id: str,
    pipeline: Pipeline = Depends(get_pipeline),
    store: CaseStore = Depends(get_store),
) -> FinalReport:
    """Run classification through reporting and return the complete final result."""
    return build_report(_process(load_email(email_id), pipeline, store))


@router.get("/{email_id}/report", response_model=FinalReport)
def get_case_report(email_id: str, store: CaseStore = Depends(get_store)) -> FinalReport:
    """Render a previously processed case without rerunning the pipeline."""
    case = store.get(email_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case not processed: {email_id}")
    return build_report(case)


@router.get("/{email_id}", response_model=CaseRecord)
def get_case(email_id: str, store: CaseStore = Depends(get_store)) -> CaseRecord:
    """Return a processed case with its evidence and attempt history."""
    case = store.get(email_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case not processed: {email_id}")
    return case


@router.get("", response_model=list[CaseSummary])
def list_cases(
    outcome: CaseOutcome | None = Query(default=None),
    store: CaseStore = Depends(get_store),
) -> list[CaseSummary]:
    """List processed cases, optionally filtered by outcome."""
    return [_summary(case) for case in store.list(outcome)]


@router.get("/{email_id}/submission", response_model=dict)
def case_submission_entry(email_id: str, store: CaseStore = Depends(get_store)) -> SubmissionEntry:
    """The evaluation-shaped entry for one case."""
    case = store.get(email_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case not processed: {email_id}")
    return submission_entry(case)
