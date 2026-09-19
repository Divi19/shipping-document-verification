"""Email ingestion and parsing."""

import json
import re
from pathlib import Path
from typing import Optional

from app.models.email.schemas import ParsedEmail, EmailAttachment


class EmailParser:
    """Parse raw email JSON into structured ParsedEmail."""

    def __init__(self, inbox_dir: str):
        self.inbox_dir = Path(inbox_dir)

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