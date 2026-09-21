"""Case endpoints: run the pipeline, read a case, record a review decision.

This is the seam the review interface talks to. Responses are the pipeline's
own Pydantic models, so the generated TypeScript contracts stay in step with
the backend automatically.

The router deliberately avoids importing the document ingestion package at
module level, so the API surface is testable without the extraction extras.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.composition import build_pipeline
from app.config import data_dir
from app.pipeline import CaseOutcome, CaseRecord, Pipeline, ReviewAction, submission_entry
from app.pipeline.inbox import parse_email
from app.pipeline.models import FieldName, ReviewDecision
from app.pipeline.store import CaseStore, InMemoryCaseStore, apply_review
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


class ReviewRequest(BaseModel):
    """A reviewer's decision on an escalated case."""

    reviewer: str
    action: ReviewAction
    note: str | None = None
    corrected_fields: list[FieldName] = Field(default_factory=list)


class CaseSummary(BaseModel):
    """List-view row: enough to triage without loading every document."""

    email_id: str
    category: str
    outcome: CaseOutcome
    review_reason: str | None
    defect_fields: list[FieldName]
    reviewed: bool


def _summary(case: CaseRecord) -> CaseSummary:
    return CaseSummary(
        email_id=case.email_id,
        category=case.category.value,
        outcome=case.outcome,
        review_reason=case.review_reason.value if case.review_reason else None,
        defect_fields=case.defect_fields,
        reviewed=case.review is not None,
    )


def _email_path(email_id: str) -> Path:
    if not EMAIL_ID_PATTERN.match(email_id):
        raise HTTPException(status_code=422, detail="Invalid email_id")
    path = data_dir() / "inbox" / f"{email_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Unknown email_id: {email_id}")
    return path


@router.post("/{email_id}/run", response_model=CaseRecord)
def run_case(
    email_id: str,
    pipeline: Pipeline = Depends(get_pipeline),
    store: CaseStore = Depends(get_store),
) -> CaseRecord:
    """Process one email and store the result, whatever the outcome.

    A case that needs review is saved here too, with its reason and evidence,
    so it appears in the queue immediately rather than after a human replies.
    """
    record = json.loads(_email_path(email_id).read_text(encoding="utf-8"))
    return store.save(pipeline.run(parse_email(record)))


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


@router.post("/{email_id}/review", response_model=CaseRecord)
def review_case(
    email_id: str,
    request: ReviewRequest,
    store: CaseStore = Depends(get_store),
) -> CaseRecord:
    """Record a reviewer's decision and update the stored case."""
    case = store.get(email_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case not processed: {email_id}")

    decision = ReviewDecision(
        reviewer=request.reviewer,
        action=request.action,
        note=request.note,
        corrected_fields=request.corrected_fields,
    )
    return store.save(apply_review(case, decision))
