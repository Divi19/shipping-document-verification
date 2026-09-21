"""Case endpoints, exercised against a temporary dataset."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.cases import get_pipeline, get_store, router
from app.pipeline import CaseOutcome, Pipeline
from app.pipeline.store import InMemoryCaseStore
from tests.test_pipeline import BL_TEXT, SI_TEXT

COMPARISON_EMAIL = {
    "email_id": "email_004",
    "from": "docs@vitalsolutions.sg",
    "subject": "REQUEST BL DRAFT _ PO 26067_ COATED IVORY BOARD__138MT",
    "body": "Attached are the SI and draft BL for OC 5ALT-01226. Please check and confirm.",
    "attachments": ["attachments/email_004_SI.txt", "attachments/email_004_BL.txt"],
}


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    (tmp_path / "inbox").mkdir()
    (tmp_path / "attachments").mkdir()
    (tmp_path / "inbox" / "email_004.json").write_text(json.dumps(COMPARISON_EMAIL))
    (tmp_path / "attachments" / "email_004_SI.txt").write_text(SI_TEXT, encoding="utf-8")
    (tmp_path / "attachments" / "email_004_BL.txt").write_text(BL_TEXT, encoding="utf-8")
    return tmp_path


@pytest.fixture
def client(dataset: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SDOC_DATA_DIR", str(dataset))
    app = FastAPI()
    app.include_router(router)
    store = InMemoryCaseStore()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_pipeline] = lambda: Pipeline(dataset_root=dataset)
    with TestClient(app) as test_client:
        yield test_client


def test_running_a_case_returns_the_record_with_evidence(client: TestClient) -> None:
    response = client.post("/cases/email_004/run")
    assert response.status_code == 200
    case = response.json()
    assert case["outcome"] == CaseOutcome.MISMATCH.value

    consignee = next(c for c in case["comparisons"] if c["field"] == "consignee")
    assert consignee["matches"] is False
    assert consignee["si"]["raw"] == "EAST BRIGHT FZ-LLC"
    assert consignee["bl"]["raw"] == "UAB NOVAKOPA"
    assert consignee["si"]["evidence"]["source"] == "email_004_SI.txt"
    assert "EAST BRIGHT FZ-LLC" in consignee["si"]["evidence"]["snippet"]


def test_available_cases_and_complete_report_are_exposed(client: TestClient) -> None:
    available = client.get("/cases/available")
    assert available.status_code == 200
    assert available.json() == [
        {
            "email_id": "email_004",
            "subject": COMPARISON_EMAIL["subject"],
            "attachment_count": 2,
            "attachment_names": ["email_004_SI.txt", "email_004_BL.txt"],
        }
    ]

    response = client.post("/cases/email_004/run-report")
    assert response.status_code == 200
    report = response.json()
    assert report["processing_status"] == "complete"
    assert report["match_status"] == "mismatch"
    assert report["quality_gate"]["status"] == "pass"
    assert len(report["comparisons"]) == 7
    assert len(report["evidence_summary"]) == 7

    stored = client.get("/cases/email_004/report")
    assert stored.status_code == 200
    assert stored.json() == report


def test_case_is_stored_and_listed(client: TestClient) -> None:
    client.post("/cases/email_004/run")

    listed = client.get("/cases").json()
    assert [row["email_id"] for row in listed] == ["email_004"]
    assert listed[0]["defect_fields"] == ["consignee", "notify_party"]
    assert listed[0]["review_status"] == "not_required"  # a clean mismatch is not queued
    assert listed[0]["reviewed"] is False

    assert client.get("/cases", params={"outcome": "verified"}).json() == []
    assert len(client.get("/cases", params={"outcome": "mismatch"}).json()) == 1


def test_submission_entry_matches_the_evaluation_shape(client: TestClient) -> None:
    client.post("/cases/email_004/run")
    entry = client.get("/cases/email_004/submission").json()
    assert entry == {
        "category": "BL_COMPARISON",
        "status": "MISMATCH",
        "review_reason": None,
        "has_defect": True,
        "defect_fields": ["consignee", "notify_party"],
    }


def test_unknown_email_is_a_404(client: TestClient) -> None:
    assert client.post("/cases/email_999/run").status_code == 404


def test_malformed_email_id_is_rejected(client: TestClient) -> None:
    assert client.post("/cases/..%2F..%2Fsecret/run").status_code in {404, 422}


def test_unprocessed_case_is_a_404(client: TestClient) -> None:
    assert client.get("/cases/email_004").status_code == 404
