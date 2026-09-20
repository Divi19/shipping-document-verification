import re
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.agents.email_classifier.classifier import EmailClassifier
from app.config import data_dir, inbox_dir, resolve_within
from app.ingestion.parser import EmailParser
from app.ingestion.service import (
    DocumentIngestionService,
    get_document_service,
)
from app.models.email.schemas import ClassifiedEmail
from app.models.health import HealthResponse

app = FastAPI(
    title="Shipping Document Verification API",
    version="0.1.0",
)

EMAIL_ID_PATTERN = re.compile(r"^email_\d{1,6}$")


# Document ingestion models
class IngestTextRequest(BaseModel):
    """Request model for text ingestion."""

    text: str
    filename: str | None = "input.txt"


class IngestResponse(BaseModel):
    """Response model for document ingestion."""

    markdown: str
    metadata: dict
    tables_count: int
    images_count: int


def get_ingestion_service() -> DocumentIngestionService:
    """Dependency for getting document ingestion service."""
    return get_document_service()


def email_record_path(email_id: str) -> Path:
    """Resolve an email record path, rejecting anything outside the inbox."""
    if not EMAIL_ID_PATTERN.match(email_id):
        raise HTTPException(status_code=422, detail="Invalid email_id")
    try:
        path = resolve_within(inbox_dir(), f"{email_id}.json")
    except ValueError as exc:  # pragma: no cover - defensive, pattern already blocks this
        raise HTTPException(status_code=422, detail="Invalid email_id") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Unknown email_id: {email_id}")
    return path


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse()


@app.post("/classify", response_model=list[ClassifiedEmail], tags=["classification"])
def classify_emails() -> list[ClassifiedEmail]:
    """Classify every email in the configured inbox."""
    parser = EmailParser(str(inbox_dir()))
    emails = parser.parse_all()
    classifier = EmailClassifier()
    return classifier.classify_batch(emails)


@app.get("/classify/{email_id}", response_model=ClassifiedEmail, tags=["classification"])
def classify_email(email_id: str) -> ClassifiedEmail:
    """Classify a single email by ID."""
    parser = EmailParser(str(inbox_dir()))
    email = parser.parse_file(email_record_path(email_id))
    classifier = EmailClassifier()
    return classifier.classify(email)


# Document Ingestion Endpoints
@app.post("/ingest/document", response_model=IngestResponse, tags=["ingestion"])
async def ingest_document(
    file: UploadFile = File(...),
    service: DocumentIngestionService = Depends(get_ingestion_service),
) -> IngestResponse:
    """
    Ingest a document file (PDF, DOCX, XLSX, TXT) and return structured markdown.

    Supports: PDF (including image-only), DOCX, XLSX, TXT, MD
    """
    content = await file.read()
    result = service.ingest_bytes(content, file.filename or "unknown")

    return IngestResponse(
        markdown=result.content,
        metadata=result.metadata,
        tables_count=len(result.tables),
        images_count=len(result.images),
    )


@app.post("/ingest/text", response_model=IngestResponse, tags=["ingestion"])
async def ingest_text(
    request: IngestTextRequest,
    service: DocumentIngestionService = Depends(get_ingestion_service),
) -> IngestResponse:
    """
    Ingest plain text (copy-paste) and return structured markdown.

    Useful for pasting email content, shipping instructions, etc.
    """
    result = service.ingest_text(request.text, request.filename or "input.txt")

    return IngestResponse(
        markdown=result.content,
        metadata=result.metadata,
        tables_count=len(result.tables),
        images_count=len(result.images),
    )


@app.post(
    "/ingest/email-attachments/{email_id}",
    response_model=dict[str, IngestResponse],
    tags=["ingestion"],
)
async def ingest_email_attachments(
    email_id: str,
    service: DocumentIngestionService = Depends(get_ingestion_service),
) -> dict[str, IngestResponse]:
    """
    Ingest all attachments for a specific email.

    Returns a dict mapping attachment filename to ingestion result.
    """
    parser = EmailParser(
        str(inbox_dir()),
        document_service=service,
        attachments_base_dir=str(data_dir()),
    )
    email = parser.parse_file(email_record_path(email_id))

    results: dict[str, IngestResponse] = {}
    for attachment in email.attachments:
        try:
            result = parser.extract_attachment_content(attachment)
            results[attachment.filename] = IngestResponse(
                markdown=result.content,
                metadata=result.metadata,
                tables_count=len(result.tables),
                images_count=len(result.images),
            )
        except Exception as exc:  # noqa: BLE001 - surfaced per attachment, never fatal
            results[attachment.filename] = IngestResponse(
                markdown=f"[Error: {exc}]",
                metadata={"error": str(exc)},
                tables_count=0,
                images_count=0,
            )

    return results


@app.get("/ingest/cache/stats", tags=["ingestion"])
def get_cache_stats(
    service: DocumentIngestionService = Depends(get_ingestion_service),
) -> dict:
    """Get document ingestion cache statistics."""
    return service.get_cache_stats()


@app.delete("/ingest/cache", tags=["ingestion"])
def clear_cache(
    service: DocumentIngestionService = Depends(get_ingestion_service),
) -> dict:
    """Clear document ingestion cache."""
    return {"cleared_entries": service.clear_cache()}
