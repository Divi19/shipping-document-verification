from typing import Annotated

from fastapi import Depends, FastAPI, File, UploadFile
from pydantic import BaseModel, Field

from app.agents.email_classifier.classifier import EmailClassifier
from app.ingestion.extractors import IngestionStatus
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


# Document ingestion models
class IngestTextRequest(BaseModel):
    """Request model for text ingestion."""

    text: str
    filename: str = "input.txt"


class IngestResponse(BaseModel):
    """Response model for document ingestion."""

    markdown: str
    metadata: dict[str, object]
    tables_count: int
    images_count: int
    status: IngestionStatus
    diagnostics: list[str] = Field(default_factory=list)


def get_ingestion_service() -> DocumentIngestionService:
    """Dependency for getting document ingestion service."""
    return get_document_service()


IngestionServiceDependency = Annotated[
    DocumentIngestionService,
    Depends(get_ingestion_service),
]


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse()


@app.post("/classify", response_model=list[ClassifiedEmail], tags=["classification"])
def classify_emails(inbox_path: str = "sdoc-data") -> list[ClassifiedEmail]:
    """Classify all emails in the inbox."""
    parser = EmailParser(f"{inbox_path}/inbox")
    emails = parser.parse_all()
    classifier = EmailClassifier()
    return classifier.classify_batch(emails)


@app.get("/classify/{email_id}", response_model=ClassifiedEmail, tags=["classification"])
def classify_email(email_id: str, inbox_path: str = "sdoc-data") -> ClassifiedEmail:
    """Classify a single email by ID."""
    from pathlib import Path

    parser = EmailParser(f"{inbox_path}/inbox")
    email = parser.parse_file(Path(f"{inbox_path}/inbox/{email_id}.json"))
    classifier = EmailClassifier()
    return classifier.classify(email)


# Document Ingestion Endpoints
@app.post("/ingest/document", response_model=IngestResponse, tags=["ingestion"])
async def ingest_document(
    file: Annotated[UploadFile, File()],
    service: IngestionServiceDependency,
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
        status=result.status,
        diagnostics=result.diagnostics,
    )


@app.post("/ingest/text", response_model=IngestResponse, tags=["ingestion"])
async def ingest_text(
    request: IngestTextRequest,
    service: IngestionServiceDependency,
) -> IngestResponse:
    """
    Ingest plain text (copy-paste) and return structured markdown.

    Useful for pasting email content, shipping instructions, etc.
    """
    result = service.ingest_text(request.text, request.filename)

    return IngestResponse(
        markdown=result.content,
        metadata=result.metadata,
        tables_count=len(result.tables),
        images_count=len(result.images),
        status=result.status,
        diagnostics=result.diagnostics,
    )


@app.post(
    "/ingest/email-attachments/{email_id}",
    response_model=dict[str, IngestResponse],
    tags=["ingestion"],
)
async def ingest_email_attachments(
    email_id: str,
    service: IngestionServiceDependency,
    inbox_path: str = "sdoc-data",
) -> dict[str, IngestResponse]:
    """
    Ingest all attachments for a specific email.

    Returns a dict mapping attachment filename to ingestion result.
    """
    from pathlib import Path

    parser = EmailParser(f"{inbox_path}/inbox", document_service=service)
    email = parser.parse_file(Path(f"{inbox_path}/inbox/{email_id}.json"))

    results = {}
    for attachment in email.attachments:
        try:
            result = parser.extract_attachment_content(attachment)
            results[attachment.filename] = IngestResponse(
                markdown=result.content,
                metadata=result.metadata,
                tables_count=len(result.tables),
                images_count=len(result.images),
                status=result.status,
                diagnostics=result.diagnostics,
            )
        except Exception as e:
            results[attachment.filename] = IngestResponse(
                markdown=f"[Error: {e}]",
                metadata={"error": str(e)},
                tables_count=0,
                images_count=0,
                status=IngestionStatus.FAILED,
                diagnostics=[f"{type(e).__name__}: {e}"],
            )

    return results


@app.get("/ingest/cache/stats", tags=["ingestion"])
def get_cache_stats(
    service: IngestionServiceDependency,
) -> dict[str, object]:
    """Get document ingestion cache statistics."""
    return service.get_cache_stats()


@app.delete("/ingest/cache", tags=["ingestion"])
def clear_cache(service: IngestionServiceDependency) -> dict[str, int]:
    """Clear document ingestion cache."""
    cleared = service.clear_cache()
    return {"cleared_entries": cleared}
