"""Rule-based email classifier."""

import re
from app.models.email.schemas import ParsedEmail, EmailCategory, ClassifiedEmail


class EmailClassifier:
    """Classify emails using rule-based logic."""

    SPAM_PATTERNS = [
        r"increase your shipping revenue",
        r"one weird trick",
    ]

    # More specific invoice patterns - only clear invoice queries
    INVOICE_PATTERNS = [
        r"request to cancel invoice",
        r"invoice payment",
        r"bank details",
    ]

    SI_REQUEST_PATTERNS = [
        r"\brequest si\b",
        r"\bsi needed\b",
        r"\bsi request\b",
        r"\bcust si\b",
        r"shipping instruction",
    ]

    BL_PATTERNS = [
        r"draft bl",
        r"request bl",
        r"pending bl",
        r"amend bl",
        r"bill of lading",
        r"outstanding bl",
    ]

    # Broader invoice terms - only if no SI/BL patterns match
    BROAD_INVOICE_PATTERNS = [
        r"\binvoice\b",
        r"total freight",
        r"mill d&d charges",
        r"rak billing",
        r"telex release charges",
        r"local charges",
        r"\bbilling\b",
        r"payment",
    ]

    def classify(self, email: ParsedEmail) -> ClassifiedEmail:
        """Classify a single email."""
        subject = email.subject.lower()
        body = email.body.lower()
        text = f"{subject} {body}"
        has_si_att = any("SI" in a.filename for a in email.attachments)
        has_bl_att = any("BL" in a.filename for a in email.attachments)

        # Rule 1: Both SI and BL attachments -> BL_COMPARISON
        if has_si_att and has_bl_att:
            return ClassifiedEmail(
                email_id=email.email_id,
                category=EmailCategory.BL_COMPARISON,
                confidence=0.99,
                reasoning="Has both SI and BL attachments",
            )

        # Rule 2: Only SI attachment -> SI_REQUEST
        if has_si_att and not has_bl_att:
            return ClassifiedEmail(
                email_id=email.email_id,
                category=EmailCategory.SI_REQUEST,
                confidence=0.95,
                reasoning="Has SI attachment only",
            )

        # Rule 3: Spam patterns
        for pattern in self.SPAM_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return ClassifiedEmail(
                    email_id=email.email_id,
                    category=EmailCategory.SPAM,
                    confidence=0.99,
                    reasoning=f"Matches spam pattern: {pattern}",
                )

        # Rule 4: SI request patterns (no attachment) - check BEFORE invoice
        for pattern in self.SI_REQUEST_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return ClassifiedEmail(
                    email_id=email.email_id,
                    category=EmailCategory.SI_REQUEST,
                    confidence=0.85,
                    reasoning=f"Matches SI request pattern: {pattern}",
                )

        # Rule 5: BL patterns (no attachment) - check BEFORE invoice
        for pattern in self.BL_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return ClassifiedEmail(
                    email_id=email.email_id,
                    category=EmailCategory.GENERAL,
                    confidence=0.80,
                    reasoning=f"Matches BL pattern: {pattern}",
                )

        # Rule 6: Specific invoice patterns
        for pattern in self.INVOICE_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return ClassifiedEmail(
                    email_id=email.email_id,
                    category=EmailCategory.INVOICE_QUERY,
                    confidence=0.90,
                    reasoning=f"Matches invoice pattern: {pattern}",
                )

        # Rule 7: Broad invoice patterns (lower confidence)
        for pattern in self.BROAD_INVOICE_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return ClassifiedEmail(
                    email_id=email.email_id,
                    category=EmailCategory.INVOICE_QUERY,
                    confidence=0.75,
                    reasoning=f"Matches broad invoice pattern: {pattern}",
                )

        # Default: GENERAL
        return ClassifiedEmail(
            email_id=email.email_id,
            category=EmailCategory.GENERAL,
            confidence=0.70,
            reasoning="No specific pattern matched",
        )

    def classify_batch(self, emails: list[ParsedEmail]) -> list[ClassifiedEmail]:
        """Classify multiple emails."""
        return [self.classify(email) for email in emails]