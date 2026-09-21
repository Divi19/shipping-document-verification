"""Regression tests for actionable email classification."""

from app.agents.email_classifier.classifier import EmailClassifier
from app.models.email.schemas import EmailAttachment, EmailCategory, ParsedEmail


def _email(
    *,
    body: str,
    attachments: tuple[str, ...],
    email_id: str = "test_email",
) -> ParsedEmail:
    return ParsedEmail(
        email_id=email_id,
        from_address="docs@example.com",
        subject="Document request",
        body=body,
        attachments=[
            EmailAttachment(path=f"attachments/{name}", filename=name) for name in attachments
        ],
    )


def test_both_si_and_bl_attachments_are_comparison() -> None:
    result = EmailClassifier().classify(
        _email(body="Please review the documents.", attachments=("job_si.txt", "job_bl.txt"))
    )

    assert result.category is EmailCategory.BL_COMPARISON
    assert result.reasoning == "Has both SI and BL attachments"


def test_missing_bl_stays_comparison_when_request_is_explicit() -> None:
    result = EmailClassifier().classify(
        _email(
            email_id="email_507",
            body=(
                "Please compare the SI and draft BL for I756178688 and confirm "
                "(the draft BL is still missing)."
            ),
            attachments=("email_507_SI.txt",),
        )
    )

    assert result.category is EmailCategory.BL_COMPARISON
    assert result.reasoning == "Explicit SI-to-BL comparison request"


def test_check_bl_against_si_is_comparison() -> None:
    result = EmailClassifier().classify(
        _email(
            body="Please check the draft BL against the SI and report any discrepancy.",
            attachments=("draft_si.txt",),
        )
    )

    assert result.category is EmailCategory.BL_COMPARISON


def test_ordinary_si_with_future_bl_request_remains_si_request() -> None:
    result = EmailClassifier().classify(
        _email(
            body=(
                "Please find the shipping instruction attached. "
                "Please revert with the draft BL once available."
            ),
            attachments=("shipping_SI.txt",),
        )
    )

    assert result.category is EmailCategory.SI_REQUEST
    assert result.reasoning == "Has SI attachment only"


def test_attachment_role_detection_is_case_insensitive() -> None:
    result = EmailClassifier().classify(
        _email(body="Please review.", attachments=("shipment_si.txt", "shipment_bl.txt"))
    )

    assert result.category is EmailCategory.BL_COMPARISON
