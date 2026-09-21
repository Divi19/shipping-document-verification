"""API coverage for the local document-pipeline test workbench."""

import httpx
import pytest

from app.config import resolve_data_dir
from app.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_upload_runs_complete_text_pipeline() -> None:
    content = "\n".join(
        [
            "Shipper: Example Trading Ltd",
            "Consignee: Example Imports Ltd",
            "Notify Party: Example Logistics Ltd",
            "Port of Loading: Singapore",
            "Port of Discharge: Rotterdam",
            "Container Count: 2",
            "Gross Weight: 44,000 KG",
        ]
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/pipeline/document",
            params={"document_role": "shipping_instruction"},
            files={"file": ("sample_si.txt", content, "text/plain")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ingestion"]["status"] == "success"
    assert len(body["candidates"]["candidates"]) == 7
    assert all(field["verified_field"] for field in body["verification"]["fields"])
    assert body["normalization"]["failures"] == []
    assert len(body["normalization"]["document"]["fields"]) == 7


@pytest.mark.anyio
async def test_pipeline_samples_endpoint_is_available() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/pipeline/samples")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.anyio
async def test_native_pdf_sample_runs_through_all_document_stages() -> None:
    if not (resolve_data_dir() / "attachments" / "email_059_SI.pdf").exists():
        pytest.skip("Participant bundle is not available")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/pipeline/sample/email_059_SI.pdf",
            params={"document_role": "shipping_instruction"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ingestion"]["extractor"] == "pypdf"
    assert len(body["candidates"]["candidates"]) == 7
    assert body["normalization"]["failures"] == []
