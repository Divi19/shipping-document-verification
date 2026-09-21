"""Email ingestion and parsing with document extraction."""

import json
import re
from pathlib import Path
from typing import Optional

from app.models.email.schemas import ParsedEmail, EmailAttachment
from app.ingestion.service import get_document_service, DocumentIngestionService
from app.ingestion.markdown_builder import MarkdownDocument


class EmailParser:
    """Parse raw email JSON into structured ParsedEmail with document extraction."""

    def __init__(
        self,
        inbox_dir: str,
        document_service: Optional[DocumentIngestionService] = None,
        attachments_base_dir: Optional[str] = None,
    ):
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

    def parse_dict(self, data: dict) -> ParsedEmail:
        """Parse email from dictionary."""
        email_id = data["email_id"]
        from_raw = data.get("from", "")
        from_name, from_address = self._parse_from(from_raw)
        subject = data.get("subject", "")
        body = data.get("body", "")
        attachments = self._parse_attachments(data.get("attachments", []))

        return ParsedEmail(
            email_id=email_id,
            from_address=from_address,
            from_name=from_name,
            subject=subject,
            body=body,
            attachments=attachments,
        )

    def _parse_from(self, from_raw: str) -> tuple[Optional[str], str]:
        """Parse 'From' header into name and address."""
        match = re.match(r'^(.+?)\s*<(.+?)>$', from_raw)
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
            attachments.append(EmailAttachment(
                path=path,
                filename=filename,
                content_type=content_type,
            ))
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
        # Attachment paths in the email records are relative to the dataset
        # root and already include the "attachments/" prefix, so join from the
        # root rather than from the attachments directory itself.
        full_path = self.attachments_base_dir / attachment.path
        if not full_path.exists():
            full_path = self.attachments_base_dir / Path(attachment.path).name

        if not full_path.exists():
            raise FileNotFoundError(f"Attachment not found: {attachment.path}")

        return self.document_service.ingest_file(full_path)

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
                # Log error but continue with other attachments
                import logging
                logging.getLogger(__name__).warning(
                    f"Failed to extract {attachment.filename}: {e}"
                )
                results[attachment.filename] = MarkdownDocument(
                    content=f"[Error extracting {attachment.filename}: {e}]",
                    metadata={"error": str(e)},
                )
        return results