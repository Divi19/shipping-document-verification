"""Deterministic signals used to classify shipping-inbox email.

The patterns come from the subject conventions actually present in the APRIL
inbox: coded booking subjects, `TO CONFIRM DOCS` / `REQUEST BL DRAFT` threads,
`CUST SI` requests, billing queries, RPA broadcasts and consumer-grade spam.

Everything here is intentionally explicit and testable. Anything these rules
cannot decide is handed to the LLM fallback instead of being guessed.
"""

import re

# Senders that only ever emit internal broadcasts (reports, RPA notices, HR).
INTERNAL_BROADCAST_SENDER = re.compile(r"^(hr|noreply|no-reply|rpa\.bot|operations)@")

# Domains used by the phishing/marketing mail in the inbox.
SPAM_SENDER = re.compile(
    r"@(crypto-invest|secure-mailbox|webmail-verify|parcel-track|logistics-deals|prize-claims)\."
)

SPAM_WORDING = re.compile(
    r"weird trick|bitcoin|guaranteed \d+%|\d+% off|hot singles|storage is full"
    r"|undelivered messages|update your account|you have won|gift card|claim now"
    r"|avoid suspension|confirm your bank details",
    re.IGNORECASE,
)

# An operations reference (order code, PO, booking/BL number). Genuine business
# mail carries one; spam that imitates business subjects does not.
SHIPMENT_REFERENCE = re.compile(r"\b5[A-Z]{3}-\d{5}\b|\bPO[_ ]?\d|\b[A-Z]{4}\d{6,}\b")

BROADCAST_SUBJECT = re.compile(
    r"update summary|berthing report|_rpa_|_reminder_|time off|delivery planning"
    r"|miss connection|pending bl release",
    re.IGNORECASE,
)

SI_REQUEST_SUBJECT = re.compile(r"cust si\b|request si\b|si\s*needed", re.IGNORECASE)

# `SI - HLCUSIN975523149 - DIRECT(HAPAG) - ...`
SI_CODED_SUBJECT = re.compile(r"^si\s*-", re.IGNORECASE)

COMPARISON_SUBJECT = re.compile(
    r"to confirm docs|request bl draft|draft bl|amend bl", re.IGNORECASE
)

# Coded booking subjects: `AIE - PYEONGTAEK_SOUTH KOREA - MSC(MEDUUD032119) - ...`
COMPARISON_CODED_SUBJECT = re.compile(r"^(aie|afrt|afptme|afemy|afpt|aipl)\b", re.IGNORECASE)

INVOICE_SUBJECT = re.compile(
    r"invoice|billing|local charges|telex release|total freight|d ?& ?d|missing gr|freight",
    re.IGNORECASE,
)

# Leading Re:/Fw: markers, including the `RE_` form used by exported .msg files.
REPLY_PREFIX = re.compile(r"^((re|fw|fwd)[\s_:]+)+", re.IGNORECASE)


def strip_reply_prefix(subject: str) -> str:
    """Remove any chain of Re:/Fw: markers from the front of a subject."""
    return REPLY_PREFIX.sub("", subject.strip())
