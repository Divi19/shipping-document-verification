"""Load email records from the participant bundle.

Deliberately dependency-free (stdlib + Pydantic): the pipeline, its tests and
the scoring harness must run on a machine that has not installed the document
extraction extras. ``EmailParser`` remains the route for anything that also
needs attachment content.
"""

import json
from collections.abc import Iterator
from pathlib import Path

from app.models.email.schemas import EmailAttachment, ParsedEmail


def parse_email(record: dict[str, object]) -> ParsedEmail:
    """Build a ParsedEmail from one inbox JSON record."""
    attachments = [
        EmailAttachment(path=str(path), filename=str(path).rsplit("/", 1)[-1])
        for path in list(record.get("attachments") or [])
    ]
    return ParsedEmail(
        email_id=str(record["email_id"]),
        from_address=str(record.get("from", "")),
        subject=str(record.get("subject", "")),
        body=str(record.get("body", "")),
        attachments=attachments,
    )


def iter_emails(dataset_root: Path) -> Iterator[ParsedEmail]:
    """Yield every email record in ``dataset_root/inbox``, in id order."""
    inbox = Path(dataset_root) / "inbox"
    if not inbox.is_dir():
        raise FileNotFoundError(
            f"No inbox directory at {inbox}. Extract the participant bundle there, "
            "or point SDOC_DATA_DIR at it."
        )
    for path in sorted(inbox.glob("email_*.json")):
        yield parse_email(json.loads(path.read_text(encoding="utf-8")))


def load_emails(dataset_root: Path) -> list[ParsedEmail]:
    """Read the whole inbox."""
    return list(iter_emails(dataset_root))
