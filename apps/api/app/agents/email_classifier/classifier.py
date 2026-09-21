"""Email classification: deterministic rules first, LLM only for the remainder.

Rule order matters and is verified in tests:

1. attachments at all            -> BL_COMPARISON (only comparison requests carry files)
2. known spam sender domain      -> SPAM
3. spam wording, no shipment ref -> SPAM
4. SI request wording            -> SI_REQUEST
5. internal broadcast/bot mail   -> GENERAL
6. comparison wording or code    -> BL_COMPARISON
7. billing wording               -> INVOICE_QUERY
8. anything left                 -> LLM fallback, else GENERAL

`confidence` expresses how specific the matched rule is, not a probability.
Nothing downstream may treat it as evidence; the pipeline derives certainty
from checks on the extracted values instead.
"""

from typing import Protocol

from app.models.email.schemas import ClassifiedEmail, DecidedBy, EmailCategory, ParsedEmail

from . import rules


class CategoryOracle(Protocol):
    """An LLM (or any other judge) consulted when no rule matches."""

    def classify(self, email: ParsedEmail) -> tuple[EmailCategory, str] | None:
        """Return a category and its justification, or None to abstain."""


class EmailClassifier:
    """Classify emails into the five required categories."""

    def __init__(self, oracle: CategoryOracle | None = None) -> None:
        self.oracle = oracle

    def classify(self, email: ParsedEmail) -> ClassifiedEmail:
        """Classify a single email."""
        subject = rules.strip_reply_prefix(email.subject)
        sender = email.from_address.lower()

        # 1. In this inbox, attachments only ever accompany a comparison request.
        #    An SI without its BL is still a comparison request - one whose BL is
        #    missing - so it must reach the pipeline and escalate there.
        if email.attachments:
            return self._decided(
                email,
                EmailCategory.BL_COMPARISON,
                0.99,
                "Carries document attachments",
            )

        # 2/3. Spam: sender domain is decisive, wording alone is not (real
        #      billing threads also say "invoice payment").
        if rules.SPAM_SENDER.search(sender):
            return self._decided(email, EmailCategory.SPAM, 0.99, "Known spam sender domain")
        if rules.SPAM_WORDING.search(subject) and not rules.SHIPMENT_REFERENCE.search(subject):
            return self._decided(
                email,
                EmailCategory.SPAM,
                0.90,
                "Spam wording with no shipment reference",
            )

        # 4. SI requests, before the broadcast check: an SI request from an
        #    internal address is still an SI request.
        if rules.SI_REQUEST_SUBJECT.search(subject) or rules.SI_CODED_SUBJECT.match(subject):
            return self._decided(email, EmailCategory.SI_REQUEST, 0.95, "SI request subject")

        # 5. Reports, reminders and RPA notices. "Pending BL Release" and
        #    "Submit SI & AED" are broadcasts, not requests, despite the wording.
        if rules.INTERNAL_BROADCAST_SENDER.match(sender) or rules.BROADCAST_SUBJECT.search(subject):
            return self._decided(email, EmailCategory.GENERAL, 0.90, "Internal broadcast or notice")

        # 6. Comparison requests with no attachment yet ("please send the draft
        #    BL for checking"). Still a comparison request; the pipeline reports
        #    it as awaiting documents rather than comparing nothing.
        if rules.COMPARISON_SUBJECT.search(subject) or (
            rules.COMPARISON_CODED_SUBJECT.match(subject) and "(" in subject
        ):
            return self._decided(
                email,
                EmailCategory.BL_COMPARISON,
                0.90,
                "Document comparison subject",
            )

        # 7. Billing and charge queries.
        if rules.INVOICE_SUBJECT.search(subject):
            return self._decided(email, EmailCategory.INVOICE_QUERY, 0.85, "Billing subject")

        # 8. Nothing matched - ask the model rather than guessing a category.
        if self.oracle is not None:
            verdict = self.oracle.classify(email)
            if verdict is not None:
                category, reasoning = verdict
                return ClassifiedEmail(
                    email_id=email.email_id,
                    category=category,
                    confidence=0.6,
                    reasoning=reasoning,
                    decided_by=DecidedBy.LLM,
                )

        return self._decided(email, EmailCategory.GENERAL, 0.50, "No rule matched; default")

    def classify_batch(self, emails: list[ParsedEmail]) -> list[ClassifiedEmail]:
        """Classify multiple emails."""
        return [self.classify(email) for email in emails]

    @staticmethod
    def _decided(
        email: ParsedEmail,
        category: EmailCategory,
        confidence: float,
        reasoning: str,
    ) -> ClassifiedEmail:
        return ClassifiedEmail(
            email_id=email.email_id,
            category=category,
            confidence=confidence,
            reasoning=reasoning,
            decided_by=DecidedBy.RULE,
        )
