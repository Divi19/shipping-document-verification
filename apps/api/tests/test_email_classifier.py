"""Classification rules, exercised with subjects taken from the supplied inbox."""

import pytest

from app.agents.email_classifier import EmailClassifier
from app.models.email.schemas import (
    ClassifiedEmail,
    DecidedBy,
    EmailAttachment,
    EmailCategory,
    ParsedEmail,
)


def make_email(
    subject: str,
    sender: str = "deswita_elvyani@aprilasia.com",
    body: str = "",
    attachments: list[str] | None = None,
    email_id: str = "email_001",
) -> ParsedEmail:
    return ParsedEmail(
        email_id=email_id,
        from_address=sender,
        subject=subject,
        body=body,
        attachments=[
            EmailAttachment(path=path, filename=path.rsplit("/", 1)[-1])
            for path in (attachments or [])
        ],
    )


def classify(**kwargs: object) -> ClassifiedEmail:
    return EmailClassifier().classify(make_email(**kwargs))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "subject",
    [
        "TO CONFIRM DOCS _ 5RVN-23924 _ HOCHIMINH CITY_VIETNAM _ BALL & DOGGETT",
        "RE_ TO CONFIRM DOCS _ 5RUS-79473 _ GDANSK_POLAND _ EAST BRIGHT FZ-LLC",
        "REQUEST BL DRAFT _ PO 26320_ PAPERONE DIGITAL COPIER PAPER__132MT",
        "RE_ Draft BL VISION 202 V.002 NANTONG - amend BL 041",
        "AFRT - LONG BEACH_US - ONE(SINF11325797) - 5ALT-99601 - HABRAS INTERNATIONAL",
    ],
)
def test_comparison_requests_without_attachments_are_routed(subject: str) -> None:
    """A request to send a draft BL is still a comparison case, not GENERAL."""
    assert classify(subject=subject).category == EmailCategory.BL_COMPARISON


def test_si_only_attachment_stays_a_comparison_request() -> None:
    """email_507 ships the SI alone; the missing BL must escalate downstream."""
    result = classify(
        subject="RE_ TO CONFIRM DOCS _ 5AKR-00230 _ KOPER_SLOVENIA",
        body="Please compare the SI and draft BL (the draft BL is still missing).",
        attachments=["attachments/email_507_SI.txt"],
    )
    assert result.category == EmailCategory.BL_COMPARISON


def test_invoice_named_attachment_still_routes_to_comparison() -> None:
    """email_501 attaches a Commercial Invoice named *_BL.txt - a doc-type issue
    for the pipeline to find by reading it, not a classification decision."""
    result = classify(
        subject="TO CONFIRM DOCS _ 5RSG-51522 _ SAVANNAH_US",
        attachments=["attachments/email_501_SI.txt", "attachments/email_501_BL.txt"],
    )
    assert result.category == EmailCategory.BL_COMPARISON


@pytest.mark.parametrize(
    "subject",
    [
        "REQUEST SI _ 5RFR-37631 _ GDANSK_POLAND _ AL GURG STATIONERY LLC _ SIJ1051834",
        "RE_ SI NEEDED_ 5APH-26773 _ UAB NOVAKOPA _ PO_25_2186 _ MERSIN",
        "CUST SI _ MEA _ 5RCY-52735 __ PO_25_5465",
        "SI - OOLU5310033092 - DIRECT(OOCL) - 5AAT-45299 - BUSAN_SOUTH KOREA - HOUSE BL",
    ],
)
def test_si_requests(subject: str) -> None:
    assert classify(subject=subject).category == EmailCategory.SI_REQUEST


def test_si_needed_is_matched_despite_trailing_underscore() -> None:
    """`SI NEEDED_ 5APH...` has no word boundary after "needed" - underscores are
    word characters, so a \b-terminated pattern silently misses 13 emails."""
    assert classify(subject="SI NEEDED_ 5RCY-63982 _ 3S PAPER").category == (
        EmailCategory.SI_REQUEST
    )


@pytest.mark.parametrize(
    ("subject", "sender"),
    [
        ("15_01_2026 - UPDATE SUMMARY LE HAVRE V.QI540A", "noreply@aprilasia.com"),
        ("daily Berthing Report - 14 JAN 2026", "hr@aprilasia.com"),
        ("_RPA_ India HSS SD Billing Process Completed", "rpa.bot@aprilasia.com"),
        ("Pending BL Release 03_01_2026", "rpa.bot@aprilasia.com"),
        ("_Reminder_Paper - Submit SI & AED_26-01-2026", "hr@aprilasia.com"),
        ("Delivery planning Jan 2026", "operations@aprilasia.com"),
    ],
)
def test_broadcasts_are_general(subject: str, sender: str) -> None:
    """Bot notices mention BL and SI but request nothing."""
    assert classify(subject=subject, sender=sender).category == EmailCategory.GENERAL


@pytest.mark.parametrize(
    "subject",
    [
        "REQUEST TO CANCEL INVOICE -5250071780 - ROXCEL TRADING GMBH - 5RUS-32611",
        "RE_ LOCAL CHARGES FOB - KARGOSMAR - 5RAE-75485 - TELEX RELEASE CHARGES",
        "Total Freight - INDIA - 5RSG-70551",
    ],
)
def test_invoice_queries(subject: str) -> None:
    assert classify(subject=subject, sender="chella.perumal@psabdp.com").category == (
        EmailCategory.INVOICE_QUERY
    )


@pytest.mark.parametrize(
    ("subject", "sender"),
    [
        ("Increase your shipping revenue with this ONE weird trick", "info@crypto-invest.net"),
        ("Bitcoin investment opportunity - guaranteed 300% returns", "admin@secure-mailbox.org"),
        ("URGENT: Your email storage is full - verify account", "support@webmail-verify.co"),
        ("Re: Invoice payment - kindly confirm your bank details", "admin@secure-mailbox.org"),
    ],
)
def test_spam(subject: str, sender: str) -> None:
    """Including the phishing mail that imitates a billing subject."""
    assert classify(subject=subject, sender=sender).category == EmailCategory.SPAM


def test_genuine_billing_thread_is_not_spam() -> None:
    """Spam wording plus a real shipment reference is business mail."""
    result = classify(
        subject="REQUEST TO CANCEL INVOICE -5250075462 - VITAL SOLUTIONS - 5RMY-25192",
        sender="docs@vitalsolutions.sg",
    )
    assert result.category == EmailCategory.INVOICE_QUERY


def test_rule_decisions_are_labelled() -> None:
    assert classify(subject="Total Freight - INDIA - 5RSG-70551").decided_by == DecidedBy.RULE


def test_oracle_is_consulted_only_when_no_rule_matches() -> None:
    calls: list[str] = []

    class Oracle:
        def classify(self, email: ParsedEmail) -> tuple[EmailCategory, str] | None:
            calls.append(email.email_id)
            return EmailCategory.GENERAL, "model decided"

    classifier = EmailClassifier(oracle=Oracle())

    matched = classifier.classify(make_email("CUST SI _ MEA _ 5RCY-52735", email_id="email_002"))
    assert matched.decided_by == DecidedBy.RULE
    assert calls == []

    unmatched = classifier.classify(make_email("Lunch tomorrow?", email_id="email_003"))
    assert unmatched.decided_by == DecidedBy.LLM
    assert unmatched.reasoning == "model decided"
    assert calls == ["email_003"]


def test_unmatched_email_defaults_to_general_without_an_oracle() -> None:
    result = classify(subject="Lunch tomorrow?")
    assert result.category == EmailCategory.GENERAL
    assert result.decided_by == DecidedBy.RULE
