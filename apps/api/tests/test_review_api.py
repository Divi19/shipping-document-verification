"""Review queue endpoints, exercised against a temporary dataset."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.cases import get_pipeline, get_store
from app.api.cases import router as cases_router
from app.api.review import router as review_router
from app.pipeline import Pipeline
from app.pipeline.readers import PlainTextReader
from app.pipeline.store import InMemoryCaseStore
from tests.test_pipeline import BL_TEXT, SI_TEXT
from tests.test_review import BL_WEIGHT_TBA

EMAILS: dict[str, dict[str, Any]] = {
    "email_004": {
        "subject": "REQUEST BL DRAFT _ PO 26067",
        "body": "Attached are the SI and draft BL. Please check and confirm.",
        "files": {"SI": SI_TEXT, "BL": BL_TEXT},
    },
    "email_506": {
        "subject": (
            "RE_ AFRT - LONG BEACH_US - EVER(EGLV433335384951) - 5RSG-19787 - 5250071809"
            " - EAST BRIGHT FZ-LLC - OA_CFR"
        ),
        "body": (
            "Dear Team,\n\nPlease compare the SI and draft BL for 070500263211 and confirm "
            "(attachments appear to have been dropped). Thank you."
        ),
        "files": {},
    },
    "email_516": {
        "subject": "TO CONFIRM DOCS _ 5RVN-23924",
        "body": "Attached are the SI and draft BL. Please check.",
        "files": {"SI": SI_TEXT, "BL": BL_WEIGHT_TBA},
    },
}


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    (tmp_path / "inbox").mkdir()
    (tmp_path / "attachments").mkdir()
    for email_id, spec in EMAILS.items():
        attachments = []
        for role, text in spec["files"].items():
            name = f"attachments/{email_id}_{role}.txt"
            (tmp_path / name).write_text(text, encoding="utf-8")
            attachments.append(name)
        record = {
            "email_id": email_id,
            "from": "docs@vitalsolutions.sg",
            "subject": spec["subject"],
            "body": spec["body"],
            "attachments": attachments,
        }
        (tmp_path / "inbox" / f"{email_id}.json").write_text(json.dumps(record))
    (tmp_path / "secret.txt").write_text("outside the attachments", encoding="utf-8")
    return tmp_path


@pytest.fixture
def client(dataset: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SDOC_DATA_DIR", str(dataset))
    app = FastAPI()
    app.include_router(cases_router)
    app.include_router(review_router)
    store = InMemoryCaseStore()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_pipeline] = lambda: Pipeline(
        dataset_root=dataset, readers=(PlainTextReader(),)
    )
    with TestClient(app) as test_client:
        yield test_client


def correct_weight(client: TestClient, value: str = "131,058 KG") -> Any:
    return client.post(
        "/review-queue/email_516/decision",
        json={
            "reviewer": "Ops reviewer",
            "action": "corrected",
            "note": "Read from the draft BL.",
            "corrections": [{"field": "gross_weight_kg", "side": "bl", "value": value}],
        },
    )


def test_processing_the_inbox_fills_the_queue_once(client: TestClient) -> None:
    first = client.post("/cases/run-inbox").json()
    assert first["processed"] == 3
    assert first["skipped"] == 0
    assert first["queued_for_review"] == 2
    assert first["outcomes"] == {"mismatch": 1, "needs_review": 2}

    second = client.post("/cases/run-inbox").json()
    assert second["processed"] == 0
    assert second["skipped"] == 3


def test_the_queue_lists_escalations_with_counts(client: TestClient) -> None:
    client.post("/cases/run-inbox")

    queue = client.get("/review-queue").json()

    assert queue["counts"] == {"pending": 2, "awaiting_information": 0, "resolved": 0}
    ids = [item["email_id"] for item in queue["items"]]
    assert sorted(ids) == ["email_506", "email_516"]  # the clean mismatch is not queued
    item = next(item for item in queue["items"] if item["email_id"] == "email_516")
    assert item["subject"] == EMAILS["email_516"]["subject"]
    assert item["reason"] == "missing_value"
    assert item["team"] == "field_verification"
    assert item["questionable_fields"] == ["gross_weight_kg"]
    assert item["last_decision"] is None

    resolved = client.get("/review-queue", params={"status": "resolved"}).json()
    assert resolved["items"] == []
    assert resolved["counts"]["pending"] == 2


def test_the_package_holds_everything_a_reviewer_needs(client: TestClient) -> None:
    client.post("/cases/run-inbox")

    package = client.get("/review-queue/email_516").json()

    assert package["email"]["body"] == EMAILS["email_516"]["body"]
    assert package["email"]["attachments"] == ["email_516_SI.txt", "email_516_BL.txt"]
    assert [doc["role"] for doc in package["documents"]] == [
        "shipping_instruction",
        "bill_of_lading",
    ]
    assert "SHIPPING INSTRUCTION" in package["documents"][0]["text"]
    assert package["ticket"]["reason"] == "missing_value"
    assert "confirmed" not in package["allowed_actions"]
    assert len(package["comparisons"]) == 7
    weight = next(c for c in package["comparisons"] if c["field"] == "gross_weight_kg")
    assert weight["si"]["evidence"]["source"] == "email_516_SI.txt"
    assert weight["si"]["confidence"] is not None
    assert any(attempt["stage"] == "triage" for attempt in package["attempts"])
    assert package["report"]["review_status"] == "pending"


def test_a_correction_updates_the_report_and_the_queue(client: TestClient) -> None:
    client.post("/cases/run-inbox")

    response = correct_weight(client)

    assert response.status_code == 200
    package = response.json()
    assert package["ticket"]["status"] == "resolved"
    assert package["allowed_actions"] == []
    assert package["automated_outcome"] == "needs_review"
    assert package["report"]["outcome"] == "verified"
    assert package["report"]["processing_status"] == "complete"

    assert client.get("/cases/email_516/report").json()["outcome"] == "verified"
    assert client.get("/cases/email_516/submission").json()["status"] == "OK"
    counts = client.get("/review-queue").json()["counts"]
    assert counts == {"pending": 1, "awaiting_information": 0, "resolved": 1}
    summary = next(row for row in client.get("/cases").json() if row["email_id"] == "email_516")
    assert summary["reviewed"] is True
    assert summary["review_status"] == "resolved"


def test_a_request_for_information_moves_the_case_to_waiting(client: TestClient) -> None:
    client.post("/cases/run-inbox")

    response = client.post(
        "/review-queue/email_506/decision",
        json={
            "reviewer": "Ops reviewer",
            "action": "information_requested",
            "note": "Asked the sender to attach the SI and draft BL again.",
        },
    )

    assert response.status_code == 200
    assert response.json()["ticket"]["status"] == "awaiting_information"
    item = client.get("/review-queue", params={"status": "awaiting_information"}).json()
    assert [row["email_id"] for row in item["items"]] == ["email_506"]
    assert item["items"][0]["last_decision"]["action"] == "information_requested"


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"reviewer": "  ", "action": "unable_to_verify", "note": "x"}, None),
        ({"reviewer": "Ops", "action": "unable_to_verify"}, "note is required"),
        ({"reviewer": "Ops", "action": "confirmed"}, "no complete result to confirm"),
        (
            {
                "reviewer": "Ops",
                "action": "corrected",
                "corrections": [{"field": "gross_weight_kg", "side": "bl", "value": "TBA"}],
            },
            "not a usable value",
        ),
    ],
)
def test_an_invalid_decision_is_refused_whole(
    client: TestClient, payload: dict[str, Any], detail: str | None
) -> None:
    client.post("/cases/run-inbox")

    response = client.post("/review-queue/email_516/decision", json=payload)

    assert response.status_code == 422
    if detail is not None:
        assert detail in response.json()["detail"]
    package = client.get("/review-queue/email_516").json()
    assert package["ticket"]["decisions"] == []


def test_a_resolved_case_is_a_conflict(client: TestClient) -> None:
    client.post("/cases/run-inbox")
    correct_weight(client)

    response = correct_weight(client, "131,000 KG")

    assert response.status_code == 409
    assert "already resolved" in response.json()["detail"]


def test_cases_outside_the_queue_are_not_found(client: TestClient) -> None:
    client.post("/cases/run-inbox")

    assert client.get("/review-queue/email_004").status_code == 404  # clean mismatch
    assert client.get("/review-queue/email_999").status_code == 404
    assert correct_weight(client).status_code == 200
    assert client.post("/review-queue/email_004/decision", json={}).status_code == 422


def test_retrying_a_case_keeps_the_human_decision(client: TestClient) -> None:
    client.post("/cases/run-inbox")
    correct_weight(client)

    assert client.post("/cases/email_516/run").status_code == 200

    package = client.get("/review-queue/email_516").json()
    assert package["ticket"]["status"] == "resolved"
    assert len(package["ticket"]["decisions"]) == 1
    assert package["report"]["outcome"] == "verified"
    stages = [attempt["stage"] for attempt in package["attempts"]]
    assert "reprocess" in stages
    assert stages.count("classify") == 2


def test_an_attachment_is_served_only_for_its_own_email(client: TestClient) -> None:
    response = client.get("/review-queue/email_516/attachments/email_516_BL.txt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["content-disposition"].startswith("inline")
    assert "BILL OF LADING" in response.text

    assert client.get("/review-queue/email_516/attachments/email_004_BL.txt").status_code == 404
    assert client.get("/review-queue/email_516/attachments/..%2Fsecret.txt").status_code == 404
    assert client.get("/review-queue/..%2Fsecret/attachments/secret.txt").status_code in {
        404,
        422,
    }
