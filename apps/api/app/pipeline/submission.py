"""Render case records into the evaluation submission shape.

The submission has three statuses; the pipeline has five outcomes. The mapping
is deliberate and documented, because one row of it is a genuine divergence
between the product and the scoreboard:

    VERIFIED            -> OK
    MISMATCH            -> MISMATCH
    NEEDS_REVIEW        -> NEEDS_REVIEW
    NOT_APPLICABLE      -> OK      (non-comparison mail carries no comparison)
    AWAITING_DOCUMENTS  -> OK      (see below)

A comparison request whose documents have not been sent yet is scored ``OK`` by
the organisers' dataset, but nothing was compared. The interface keeps showing
"awaiting documents"; only this adapter flattens it, so no reviewer is ever
told that seven fields were verified when none were read.
"""

import json
from collections.abc import Iterable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import TypedDict

from .models import CaseOutcome, CaseRecord


class SubmissionStatus(StrEnum):
    OK = "OK"
    MISMATCH = "MISMATCH"
    NEEDS_REVIEW = "NEEDS_REVIEW"


OUTCOME_TO_STATUS: dict[CaseOutcome, SubmissionStatus] = {
    CaseOutcome.VERIFIED: SubmissionStatus.OK,
    CaseOutcome.MISMATCH: SubmissionStatus.MISMATCH,
    CaseOutcome.NEEDS_REVIEW: SubmissionStatus.NEEDS_REVIEW,
    CaseOutcome.NOT_APPLICABLE: SubmissionStatus.OK,
    CaseOutcome.AWAITING_DOCUMENTS: SubmissionStatus.OK,
}


class SubmissionEntry(TypedDict):
    category: str
    status: str
    review_reason: str | None
    has_defect: bool
    defect_fields: list[str]


def submission_entry(case: CaseRecord) -> SubmissionEntry:
    """Render one case."""
    submission_status = OUTCOME_TO_STATUS[case.outcome]
    defects = [field.value for field in case.defect_fields]
    return {
        "category": case.category.value,
        "status": submission_status.value,
        "review_reason": case.review_reason.value if case.review_reason else None,
        "has_defect": submission_status is SubmissionStatus.MISMATCH,
        "defect_fields": defects,
    }


def build_submission(cases: Iterable[CaseRecord]) -> dict[str, SubmissionEntry]:
    """Render every case, keyed by email id."""
    return {case.email_id: submission_entry(case) for case in cases}


def write_submission(cases: Sequence[CaseRecord], path: Path) -> Path:
    """Write the submission JSON and return where it landed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_submission(cases), indent=2), encoding="utf-8")
    return path
