"""Email ingestion and parsing with document extraction."""

import json
import logging
import re
from pathlib import Path

from app.ingestion.extractors import IngestionStatus
from app.ingestion.markdown_builder import MarkdownDocument
from app.ingestion.service import DocumentIngestionService, get_document_service
from app.models.email.schemas import EmailAttachment, ParsedEmail

logger = logging.getLogger(__name__)


class EmailParser:
    """Parse raw email JSON into structured ParsedEmail with document extraction."""

    def __init__(
        self,
        inbox_dir: str,
        document_service: DocumentIngestionService | None = None,
        attachments_base_dir: str | None = None,
    ) -> None:
        self.inbox_dir = Path(inbox_dir)
        self.document_service = document_service or get_document_service()
        self.attachments_base_dir = (
            Path(attachments_base_dir) if attachments_base_dir else self.inbox_dir.parent
        )

    def parse_all(self) -> list[ParsedEmail]:
        """Parse all emails in the inbox directory."""
        emails = []
        for path in sorted(self.inbox_dir.glob("email_*.json")):
            emails.append(self.parse_file(path))
        return emails

    def parse_file(self, path: Path) -> ParsedEmail:
        """Parse a single email JSON file."""
        data = json.loads(path.read_text())
        return self.parse_dict(data)

    def parse_dict(self, data: dict[str, object]) -> ParsedEmail:
        """Parse email from dictionary."""
        email_id = str(data["email_id"])
        from_raw = str(data.get("from", ""))
        from_name, from_address = self._parse_from(from_raw)
        subject = str(data.get("subject", ""))
        body = str(data.get("body", ""))
        attachment_data = data.get("attachments", [])
        attachment_paths = (
            [str(path) for path in attachment_data] if isinstance(attachment_data, list) else []
        )
        attachments = self._parse_attachments(attachment_paths)

        return ParsedEmail(
            email_id=email_id,
            from_address=from_address,
            from_name=from_name,
            subject=subject,
            body=body,
            attachments=attachments,
        )

    def _parse_from(self, from_raw: str) -> tuple[str | None, str]:
        """Parse 'From' header into name and address."""
        match = re.match(r"^(.+?)\s*<(.+?)>$", from_raw)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        if "@" in from_raw:
            return None, from_raw.strip()
        return from_raw.strip(), ""

    def _parse_attachments(self, attachment_paths: list[str]) -> list[EmailAttachment]:
        """Parse attachment paths into EmailAttachment objects."""
        attachments = []
        for path in attachment_paths:
            filename = Path(path).name
            content_type = self._guess_content_type(filename)
            attachments.append(
                EmailAttachment(
                    path=path,
                    filename=filename,
                    content_type=content_type,
                )
            )
        return attachments

    def _guess_content_type(self, filename: str) -> str:
        """Guess MIME type from filename."""
        suffix = Path(filename).suffix.lower()
        types = {
            ".txt": "text/plain",
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        return types.get(suffix, "application/octet-stream")

    def extract_attachment_content(self, attachment: EmailAttachment) -> MarkdownDocument:
        """
        Extract and parse attachment content to markdown.

        Args:
            attachment: EmailAttachment to extract

        Returns:
            MarkdownDocument with extracted content
        """
        return self.document_service.ingest_file(self._resolve_attachment_path(attachment))

    def _resolve_attachment_path(self, attachment: EmailAttachment) -> Path:
        """Resolve an attachment inside the configured data directory."""
        base_dir = self.attachments_base_dir.resolve()
        candidates = [base_dir / attachment.path, base_dir / attachment.filename]

        for candidate in candidates:
            resolved = candidate.resolve()
            if not resolved.is_relative_to(base_dir):
                continue
            if resolved.is_file():
                return resolved

        raise FileNotFoundError(f"Attachment not found: {attachment.path}")

    def extract_all_attachments(self, email: ParsedEmail) -> dict[str, MarkdownDocument]:
        """
        Extract content from all attachments in an email.

        Args:
            email: ParsedEmail with attachments

        Returns:
            Dict mapping attachment filename to MarkdownDocument
        """
        results = {}
        for attachment in email.attachments:
            try:
                results[attachment.filename] = self.extract_attachment_content(attachment)
            except Exception as e:
                logger.warning("Failed to extract %s: %s", attachment.filename, e)
                results[attachment.filename] = MarkdownDocument(
                    content=f"[Error extracting {attachment.filename}: {e}]",
                    metadata={"error": str(e)},
                    source_filename=attachment.filename,
                    status=IngestionStatus.FAILED,
                    diagnostics=[f"{type(e).__name__}: {e}"],
                )
        return results
