"""Tests for email and attachment path resolution."""

from pathlib import Path

from app.ingestion.parser import EmailParser
from app.ingestion.service import DocumentIngestionConfig, DocumentIngestionService
from app.models.email.schemas import EmailAttachment


def test_attachment_paths_resolve_from_bundle_root(tmp_path: Path) -> None:
    data_dir = tmp_path / "bundle"
    inbox_dir = data_dir / "inbox"
    attachments_dir = data_dir / "attachments"
    inbox_dir.mkdir(parents=True)
    attachments_dir.mkdir()
    attachment_path = attachments_dir / "email_001_SI.txt"
    attachment_path.write_text("Shipper: Example Trading")
    service = DocumentIngestionService(
        DocumentIngestionConfig(
            cache_dir=tmp_path / "cache",
            enable_vision_fallback=False,
        )
    )

    try:
        parser = EmailParser(str(inbox_dir), document_service=service)
        result = parser.extract_attachment_content(
            EmailAttachment(
                path="attachments/email_001_SI.txt",
                filename="email_001_SI.txt",
                content_type="text/plain",
            )
        )
    finally:
        service.shutdown()

    assert "Shipper: Example Trading" in result.content


def test_attachment_path_cannot_escape_data_directory(tmp_path: Path) -> None:
    data_dir = tmp_path / "bundle"
    inbox_dir = data_dir / "inbox"
    inbox_dir.mkdir(parents=True)
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("not part of the bundle")
    parser = EmailParser(str(inbox_dir))

    attachment = EmailAttachment(
        path="../../outside.txt",
        filename="outside.txt",
        content_type="text/plain",
    )

    try:
        parser.extract_attachment_content(attachment)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Escaping attachment path was accepted")
