from fastapi import FastAPI

from app.models.health import HealthResponse
from app.models.email.schemas import ClassifiedEmail
from app.ingestion.parser import EmailParser
from app.agents.email_classifier.classifier import EmailClassifier

app = FastAPI(
    title="Shipping Document Verification API",
    version="0.1.0",
)


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