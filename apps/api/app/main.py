from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.agents.email_classifier.classifier import EmailClassifier
from app.api import cases_router
from app.config import resolve_data_dir
from app.field_extraction import TextFieldExtractor, gemini_semantic_fallback_from_env
from app.ingestion.extractors import ContentType, IngestionStatus
from app.ingestion.parser import EmailParser
from app.ingestion.service import (
    DocumentIngestionService,
    get_document_service,
)
from app.models.email.schemas import ClassifiedEmail
from app.models.extraction import DocumentFieldCandidates, DocumentRole
from app.models.health import HealthResponse
from app.models.verification import DocumentNormalizationResult, DocumentVerificationResult
from app.normalization import DocumentNormalizer
from app.verification import TextEvidenceVerifier

app = FastAPI(
    title="Shipping Document Verification API",
    version="0.1.0",
)
app.include_router(cases_router)


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


class PipelineIngestionResult(BaseModel):
    """Document ingestion details displayed by the local test workbench."""

    filename: str
    content_type: ContentType
    status: IngestionStatus
    extractor: str | None = None
    extracted_text: str
    metadata: dict[str, object]
    diagnostics: list[str] = Field(default_factory=list)


class DocumentPipelineResponse(BaseModel):
    """Observable results for Boxes 5, 6, and 7 for one document."""

    ingestion: PipelineIngestionResult
    candidates: DocumentFieldCandidates | None = None
    verification: DocumentVerificationResult | None = None
    normalization: DocumentNormalizationResult | None = None


class PipelineSample(BaseModel):
    """One participant attachment available to the local test workbench."""

    filename: str
    document_role: DocumentRole
    content_type: ContentType


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


def _run_document_pipeline(
    content: bytes,
    filename: str,
    document_role: DocumentRole,
    service: DocumentIngestionService,
) -> DocumentPipelineResponse:
    """Run one attachment through ingestion and the implemented document stages."""
    document = service.extract_bytes(content, filename)
    ingestion = PipelineIngestionResult(
        filename=filename,
        content_type=document.content_type,
        status=document.status,
        extractor=(
            str(document.metadata["extractor"])
            if document.metadata.get("extractor") is not None
            else None
        ),
        extracted_text=document.text,
        metadata=document.metadata,
        diagnostics=document.diagnostics,
    )
    if document.status != IngestionStatus.SUCCESS:
        return DocumentPipelineResponse(ingestion=ingestion)
    if document.content_type not in {ContentType.TEXT, ContentType.PDF}:
        ingestion.diagnostics.append("Boxes 5–7 currently accept text and PDF documents only.")
        return DocumentPipelineResponse(ingestion=ingestion)

    field_extractor = TextFieldExtractor(gemini_semantic_fallback_from_env())
    try:
        candidates = field_extractor.extract(document, document_role)
    finally:
        field_extractor.close()
    verification = TextEvidenceVerifier().verify(document, candidates)
    normalization = DocumentNormalizer().normalize(verification)
    return DocumentPipelineResponse(
        ingestion=ingestion,
        candidates=candidates,
        verification=verification,
        normalization=normalization,
    )


def _sample_path(filename: str) -> tuple[Path, ContentType]:
    """Resolve a testable sample without permitting paths outside the attachment bundle."""
    if filename != Path(filename).name:
        raise HTTPException(status_code=400, detail="Invalid sample filename")
    path = (resolve_data_dir() / "attachments" / filename).resolve()
    attachments = (resolve_data_dir() / "attachments").resolve()
    if not path.is_relative_to(attachments) or not path.is_file():
        raise HTTPException(status_code=404, detail="Sample attachment not found")
    detected = {
        ".txt": ContentType.TEXT,
        ".pdf": ContentType.PDF,
    }.get(path.suffix.casefold())
    if detected is None:
        raise HTTPException(status_code=400, detail="Only TXT and PDF samples are testable")
    return path, detected


@app.get("/pipeline/samples", response_model=list[PipelineSample], tags=["pipeline"])
def list_pipeline_samples() -> list[PipelineSample]:
    """List included TXT/PDF participant attachments that can exercise Boxes 5–7."""
    attachments = resolve_data_dir() / "attachments"
    if not attachments.is_dir():
        return []
    samples: list[PipelineSample] = []
    for path in sorted(attachments.iterdir()):
        content_type = {
            ".txt": ContentType.TEXT,
            ".pdf": ContentType.PDF,
        }.get(path.suffix.casefold())
        if not path.is_file() or content_type is None:
            continue
        role = (
            DocumentRole.SHIPPING_INSTRUCTION
            if "_SI." in path.name.upper()
            else DocumentRole.BILL_OF_LADING
        )
        samples.append(
            PipelineSample(
                filename=path.name,
                document_role=role,
                content_type=content_type,
            )
        )
    return samples


@app.post(
    "/pipeline/document",
    response_model=DocumentPipelineResponse,
    tags=["pipeline"],
)
async def run_uploaded_document_pipeline(
    file: Annotated[UploadFile, File()],
    document_role: DocumentRole,
    service: IngestionServiceDependency,
) -> DocumentPipelineResponse:
    """Run an uploaded TXT/PDF through ingestion and Boxes 5–7."""
    filename = file.filename or "document.bin"
    return _run_document_pipeline(await file.read(), filename, document_role, service)


@app.post(
    "/pipeline/sample/{filename}",
    response_model=DocumentPipelineResponse,
    tags=["pipeline"],
)
def run_sample_document_pipeline(
    filename: str,
    document_role: DocumentRole,
    service: IngestionServiceDependency,
) -> DocumentPipelineResponse:
    """Run one bundled participant attachment through ingestion and Boxes 5–7."""
    path, _ = _sample_path(filename)
    return _run_document_pipeline(path.read_bytes(), filename, document_role, service)


@app.post("/classify", response_model=list[ClassifiedEmail], tags=["classification"])
def classify_emails(inbox_path: str | None = None) -> list[ClassifiedEmail]:
    """Classify all emails in the inbox."""
    parser = EmailParser(str(resolve_data_dir(inbox_path) / "inbox"))
    emails = parser.parse_all()
    classifier = EmailClassifier()
    return classifier.classify_batch(emails)


@app.get("/classify/{email_id}", response_model=ClassifiedEmail, tags=["classification"])
def classify_email(email_id: str, inbox_path: str | None = None) -> ClassifiedEmail:
    """Classify a single email by ID."""
    inbox_dir = resolve_data_dir(inbox_path) / "inbox"
    parser = EmailParser(str(inbox_dir))
    email = parser.parse_file(inbox_dir / f"{email_id}.json")
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
    inbox_path: str | None = None,
) -> dict[str, IngestResponse]:
    """
    Ingest all attachments for a specific email.

    Returns a dict mapping attachment filename to ingestion result.
    """
    inbox_dir = resolve_data_dir(inbox_path) / "inbox"
    parser = EmailParser(str(inbox_dir), document_service=service)
    email = parser.parse_file(inbox_dir / f"{email_id}.json")

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
