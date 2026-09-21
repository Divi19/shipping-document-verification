"""Model-assisted field extraction, accepted only on verified evidence.

Deterministic extraction matches known labels. When a document words a field in
a way the synonym table has never seen, that field comes back missing and the
case escalates - correct, but a person then has to read the document to find
something that was plainly there.

This asks the model for the missing fields only, and requires it to quote the
line it read them from. Three checks run before anything is believed:

1. the quoted line must actually occur in the document;
2. the value must occur inside that quoted line;
3. the value must survive the same normalisation as any other value.

A proposal that fails any of them is discarded and the field stays missing, so
the case escalates as it would have. The model can therefore only ever recover
a field it can point to - it cannot invent one.
"""

import logging
import re
from collections.abc import Sequence

from app.pipeline.fields import normalize_value
from app.pipeline.models import Evidence, FieldName, FieldValue
from app.pipeline.normalize import is_missing, normalize_whitespace

from .client import LlmClient

logger = logging.getLogger(__name__)

MAX_DOCUMENT_CHARS = 6000

PROMPT = """You are reading a shipping document and extracting specific fields.

Document ({source}):
---
{document}
---

Find these fields: {fields}

Rules:
- Use only what is written in the document above.
- Quote the exact line you read each value from, character for character.
- If a field is not in the document, or is blank, omit it entirely.
- Never guess and never infer a value from another field.

Reply with JSON only:
{{"<field>": {{"value": "<the value>", "evidence": "<the exact line>"}}}}"""


def _appears_in(needle: str, haystack: str) -> bool:
    """Whitespace- and case-insensitive containment check."""
    squeeze = re.compile(r"\s+")
    return squeeze.sub(" ", needle).strip().lower() in squeeze.sub(" ", haystack).strip().lower()


def _locate(line: str, document: str) -> str:
    """Report which line of the document the evidence came from."""
    target = re.sub(r"\s+", " ", line).strip().lower()
    for number, candidate in enumerate(document.splitlines(), start=1):
        if re.sub(r"\s+", " ", candidate).strip().lower() == target:
            return f"line {number}"
    return "quoted text"


class LlmFieldResolver:
    """Recover fields deterministic extraction could not find."""

    def __init__(self, client: LlmClient, max_document_chars: int = MAX_DOCUMENT_CHARS) -> None:
        self.client = client
        self.max_document_chars = max_document_chars

    def resolve(
        self, text: str, source: str, missing: Sequence[FieldName]
    ) -> dict[FieldName, FieldValue]:
        """Return only the fields the model proposed *and* evidence supports."""
        if not missing or not text.strip():
            return {}

        answer = self.client.generate_json(
            PROMPT.format(
                source=source,
                document=text[: self.max_document_chars],
                fields=", ".join(field.value for field in missing),
            )
        )
        if not answer:
            return {}

        resolved: dict[FieldName, FieldValue] = {}
        for field in missing:
            proposal = answer.get(field.value)
            if not isinstance(proposal, dict):
                continue

            value = str(proposal.get("value", "")).strip()
            evidence = str(proposal.get("evidence", "")).strip()
            if not value or not evidence or is_missing(value):
                continue

            if not _appears_in(evidence, text):
                logger.warning("%s: quoted evidence is not in %s", field.value, source)
                continue
            if not _appears_in(value, evidence):
                logger.warning(
                    "%s: value is not inside its own evidence in %s", field.value, source
                )
                continue

            normalized = normalize_value(field, value)
            if normalized is None:
                continue

            resolved[field] = FieldValue(
                field=field,
                raw=normalize_whitespace(value),
                normalized=normalized,
                evidence=Evidence(
                    source=source,
                    locator=_locate(evidence, text),
                    snippet=normalize_whitespace(evidence),
                ),
                note=f"recovered by model ({self.client.name}); evidence verified in the document",
            )

        return resolved
