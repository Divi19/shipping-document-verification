"""Persistence behavior for the human-review case store."""

from pathlib import Path

from app.models.email.schemas import EmailCategory
from app.pipeline.models import (
    CaseOutcome,
    CaseRecord,
    ReviewAction,
    ReviewResolution,
    ReviewStatus,
)
from app.pipeline.review import triage
from app.pipeline.store import JsonCaseStore


def review_case(email_id: str = "email_059") -> CaseRecord:
    case = CaseRecord(
        email_id=email_id,
        category=EmailCategory.BL_COMPARISON,
        outcome=CaseOutcome.NEEDS_REVIEW,
    )
    case.review = triage(case)
    return case


def test_json_store_survives_reconstruction(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    JsonCaseStore(path).save(review_case())

    restored = JsonCaseStore(path).get("email_059")

    assert restored is not None
    assert restored.outcome is CaseOutcome.NEEDS_REVIEW
    assert restored.review_status is ReviewStatus.PENDING


def test_json_store_filters_on_final_outcome(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    store = JsonCaseStore(path)
    verified = review_case("email_060")
    assert verified.review is not None
    verified.review.resolution = ReviewResolution(
        outcome=CaseOutcome.VERIFIED,
        action=ReviewAction.CONFIRMED,
        reviewer="Ops reviewer",
    )
    store.save(verified)

    assert [case.email_id for case in store.list(CaseOutcome.VERIFIED)] == ["email_060"]
    assert store.list(CaseOutcome.NEEDS_REVIEW) == []
