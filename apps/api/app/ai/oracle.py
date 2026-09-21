"""Model-backed classification for the email no rule could place.

The rules settle the inbox's recognised shapes. This handles the rest - a
reworded request, a new subject convention - instead of quietly filing it as
GENERAL. The answer is constrained to the five categories and rejected if it
is anything else.
"""

import logging

from app.models.email.schemas import EmailCategory, ParsedEmail

from .client import LlmClient

logger = logging.getLogger(__name__)

MAX_BODY_CHARS = 1500

PROMPT = """You are triaging a shipping operations inbox.

Classify the email into exactly one category:
- BL_COMPARISON: asks for a draft Bill of Lading to be checked against a
  Shipping Instruction, or sends those documents for checking, or chases a
  draft BL for checking.
- SI_REQUEST: asks for a Shipping Instruction to be prepared or sent.
- INVOICE_QUERY: about invoices, billing, freight or other charges.
- GENERAL: operational notices, reports, reminders, internal announcements.
- SPAM: unsolicited or fraudulent mail.

From: {sender}
Subject: {subject}
Body:
{body}

Reply with JSON only:
{{"category": "<one of the five>", "reason": "<short justification>"}}"""


class LlmCategoryOracle:
    """Consulted by EmailClassifier only when no rule matched."""

    def __init__(self, client: LlmClient) -> None:
        self.client = client

    def classify(self, email: ParsedEmail) -> tuple[EmailCategory, str] | None:
        """Return a category and its justification, or None to abstain."""
        prompt = PROMPT.format(
            sender=email.from_address,
            subject=email.subject,
            body=email.body[:MAX_BODY_CHARS],
        )
        answer = self.client.generate_json(prompt)
        if not answer:
            return None

        raw = str(answer.get("category", "")).strip().upper()
        try:
            category = EmailCategory(raw)
        except ValueError:
            # An answer outside the five categories is not an answer.
            logger.warning("Model returned an unknown category for %s: %r", email.email_id, raw)
            return None

        reason = str(answer.get("reason", "")).strip() or "no reason given"
        return category, f"model ({self.client.name}): {reason}"
