"""Exception triage and the human review queue.

A case reaches a person when the pipeline cannot decide it (NEEDS_REVIEW), or
when a decided result fails the quality gate. Triage turns the case into a
ticket: the reason in plain words, the fields in question, who owns it and how
soon. The reviewer then confirms the result, corrects values, requests
information, or marks the case unable to verify.

Rules this module keeps:

* The automated result is never overwritten. A decision produces a resolution
  that sits beside it, and the report shows both.
* A corrected value goes through the same normalisation and comparison as an
  extracted one, so a correction is held to the rules extraction follows.
* Reprocessing never discards a human decision.

Priority, first match wins:

    high    a discrepancy is already confirmed on some field: the BL needs amending
    normal  the case cannot progress without a person
    low     the result is decided and only failed the quality gate

Team:

    document_intake      missing_attachment, wrong_doc_type, unreadable
    field_verification   missing_value and quality-gate failures
"""

from collections.abc import Iterable

from .compare import compare_documents, differing_fields, undecided_fields
from .documents import document_header
from .fields import normalize_value
from .models import (
    COMPARED_FIELDS,
    CaseOutcome,
    CaseRecord,
    DocumentRead,
    DocumentRole,
    DocumentSide,
    Evidence,
    FieldComparison,
    FieldName,
    FieldValue,
    ReviewAction,
    ReviewDecision,
    ReviewPriority,
    ReviewReason,
    ReviewResolution,
    ReviewStatus,
    ReviewTeam,
    ReviewTicket,
    StageAttempt,
    ValueCorrection,
)
from .normalize import is_missing, normalize_whitespace
from .reporting import MINIMUM_CONFIDENCE, check_quality

STAGE_TRIAGE = "triage"
STAGE_HUMAN_REVIEW = "human_review"
STAGE_REPROCESS = "reprocess"

# Cases where nothing could be compared: the fix is getting the right file.
BLOCKING_REASONS = frozenset(
    {ReviewReason.MISSING_ATTACHMENT, ReviewReason.WRONG_DOC_TYPE, ReviewReason.UNREADABLE}
)

RECOMMENDED_ACTIONS: dict[ReviewReason, ReviewAction] = {
    ReviewReason.MISSING_ATTACHMENT: ReviewAction.INFORMATION_REQUESTED,
    ReviewReason.WRONG_DOC_TYPE: ReviewAction.INFORMATION_REQUESTED,
    ReviewReason.UNREADABLE: ReviewAction.INFORMATION_REQUESTED,
    ReviewReason.MISSING_VALUE: ReviewAction.CORRECTED,
}

# A request or a closure without a written reason is not auditable.
NOTE_REQUIRED = frozenset({ReviewAction.INFORMATION_REQUESTED, ReviewAction.UNABLE_TO_VERIFY})

_STATUS_ORDER = {
    ReviewStatus.PENDING: 0,
    ReviewStatus.AWAITING_INFORMATION: 1,
    ReviewStatus.RESOLVED: 2,
    ReviewStatus.NOT_REQUIRED: 3,
}
_PRIORITY_ORDER = {ReviewPriority.HIGH: 0, ReviewPriority.NORMAL: 1, ReviewPriority.LOW: 2}
_SIDE_ROLES = {
    DocumentSide.SI: DocumentRole.SHIPPING_INSTRUCTION,
    DocumentSide.BL: DocumentRole.BILL_OF_LADING,
}
_ROLE_NAMES = {
    DocumentRole.SHIPPING_INSTRUCTION: "shipping instruction",
    DocumentRole.BILL_OF_LADING: "draft bill of lading",
}


class ReviewError(ValueError):
    """The decision is not valid for this case."""


class ReviewConflict(ReviewError):
    """The case is not in a state that accepts a decision."""


# -- triage --------------------------------------------------------------


def triage(case: CaseRecord) -> ReviewTicket | None:
    """Open a review ticket when the case needs a person.

    Args:
        case: A case the orchestrator has decided.

    Returns:
        The ticket, or None when the automated result can be released.
    """
    failed_checks = _failed_checks(case)
    if case.outcome is not CaseOutcome.NEEDS_REVIEW and not failed_checks:
        return None

    reason = case.review_reason if case.outcome is CaseOutcome.NEEDS_REVIEW else None
    return ReviewTicket(
        reason=reason,
        failed_checks=failed_checks,
        summary=_summary(case, reason, failed_checks),
        priority=_priority(case),
        team=(
            ReviewTeam.DOCUMENT_INTAKE
            if reason in BLOCKING_REASONS
            else ReviewTeam.FIELD_VERIFICATION
        ),
        questionable_fields=_questionable_fields(case, reason),
        recommended_action=(
            RECOMMENDED_ACTIONS[reason] if reason is not None else ReviewAction.CONFIRMED
        ),
    )


def _failed_checks(case: CaseRecord) -> list[str]:
    """Quality checks a decided result failed; empty for any other outcome."""
    if case.outcome not in {CaseOutcome.VERIFIED, CaseOutcome.MISMATCH}:
        return []
    gate = check_quality(case.outcome, case.documents, case.comparisons)
    return [check.name for check in gate.checks if not check.passed]


def _priority(case: CaseRecord) -> ReviewPriority:
    if differing_fields(case.comparisons):
        return ReviewPriority.HIGH
    if case.outcome is CaseOutcome.NEEDS_REVIEW:
        return ReviewPriority.NORMAL
    return ReviewPriority.LOW


def _questionable_fields(case: CaseRecord, reason: ReviewReason | None) -> list[FieldName]:
    if reason is ReviewReason.MISSING_VALUE:
        return undecided_fields(case.comparisons)
    if reason is not None:
        return list(COMPARED_FIELDS)  # nothing could be compared, so nothing is verified
    return [
        item.field
        for item in case.comparisons
        if item.is_defect or not (_trusted(item.si) and _trusted(item.bl))
    ]


def _trusted(value: FieldValue) -> bool:
    """Whether a present value has evidence and meets the confidence threshold."""
    if not value.is_present:
        return True
    return (
        value.evidence is not None
        and value.confidence is not None
        and value.confidence >= MINIMUM_CONFIDENCE
    )


def _summary(case: CaseRecord, reason: ReviewReason | None, failed_checks: list[str]) -> str:
    """State the escalation in words a reviewer can act on."""
    if reason is ReviewReason.MISSING_ATTACHMENT:
        return _missing_attachment_summary(case.documents)
    if reason is ReviewReason.WRONG_DOC_TYPE:
        return " ".join(
            f"{document.filename} is not an SI or a draft BL; it reads as '{_title(document)}'."
            for document in case.documents
            if document.role is DocumentRole.OTHER
        )
    if reason is ReviewReason.UNREADABLE:
        return " ".join(
            f"{document.filename} could not be read ({document.failure or 'no text extracted'})."
            for document in case.documents
            if not document.readable
        )
    if reason is ReviewReason.MISSING_VALUE:
        undecided = undecided_fields(case.comparisons)
        if not undecided:
            return "The comparison could not be completed."
        text = (
            f"{len(undecided)} of {len(COMPARED_FIELDS)} fields could not be decided: "
            f"{', '.join(field.value for field in undecided)}."
        )
        defects = differing_fields(case.comparisons)
        if defects:
            text += (
                " A discrepancy is already confirmed on "
                f"{', '.join(field.value for field in defects)}."
            )
        return text
    if failed_checks:
        return f"The comparison finished but failed the quality gate: {', '.join(failed_checks)}."
    return "The case needs a person to decide it."


def _missing_attachment_summary(documents: list[DocumentRead]) -> str:
    if not documents:
        return "The sender asks for a comparison, but no documents arrived with the email."
    parts = [
        f"{document.filename} does not identify itself as an SI or a BL."
        for document in documents
        if document.role is DocumentRole.UNKNOWN
    ]
    roles = {document.role for document in documents}
    parts.extend(
        f"No {name} was found among the attachments."
        for role, name in _ROLE_NAMES.items()
        if role not in roles
    )
    return " ".join(parts)


def _title(document: DocumentRead) -> str:
    """The first header line of a document, as it names itself."""
    header = document_header(document.text)
    first = header.splitlines()[0] if header else "no header"
    return first[:80]


# -- decisions -----------------------------------------------------------


def allowed_actions(case: CaseRecord) -> list[ReviewAction]:
    """Return the decisions the case accepts now.

    Confirming needs a complete automated comparison: with an undecided field
    there is no result to confirm, only values to correct.
    """
    if case.review is None or case.review.status is ReviewStatus.RESOLVED:
        return []
    complete = len(case.comparisons) == len(COMPARED_FIELDS) and not undecided_fields(
        case.comparisons
    )
    confirm = [ReviewAction.CONFIRMED] if complete else []
    return [
        *confirm,
        ReviewAction.CORRECTED,
        ReviewAction.INFORMATION_REQUESTED,
        ReviewAction.UNABLE_TO_VERIFY,
    ]


def apply_decision(case: CaseRecord, decision: ReviewDecision) -> CaseRecord:
    """Record a reviewer's decision, and resolve the case when the decision is final.

    Nothing on the case changes unless the whole decision is valid.

    Args:
        case: A case with an open review ticket.
        decision: The reviewer's decision, as submitted.

    Returns:
        The same case, with the decision in its history.
    """
    ticket = case.review
    if ticket is None:
        raise ReviewConflict(f"{case.email_id} is not in the review queue")
    if ticket.status is ReviewStatus.RESOLVED:
        raise ReviewConflict(f"{case.email_id} is already resolved")

    action = decision.action
    if action not in allowed_actions(case):
        raise ReviewError(
            "There is no complete result to confirm: at least one field is undecided. "
            "Correct the values instead."
        )
    note = (decision.note or "").strip() or None
    if action in NOTE_REQUIRED and note is None:
        raise ReviewError(f"A note is required to record {action.value}")
    if action is not ReviewAction.CORRECTED and decision.corrections:
        raise ReviewError("Corrections are only accepted with the corrected action")

    recorded = decision.model_copy(update={"note": note})
    resolution: ReviewResolution | None = None
    if action is ReviewAction.CONFIRMED:
        resolution = _resolve(case.comparisons, recorded)
    elif action is ReviewAction.CORRECTED:
        comparisons, applied = _apply_corrections(case, recorded)
        recorded = recorded.model_copy(update={"corrections": applied})
        resolution = _resolve(comparisons, recorded)
    elif action is ReviewAction.UNABLE_TO_VERIFY:
        resolution = ReviewResolution(
            outcome=CaseOutcome.NEEDS_REVIEW,
            review_reason=case.review_reason,
            comparisons=case.comparisons,
            action=action,
            reviewer=recorded.reviewer,
            at=recorded.at,
        )

    ticket.decisions.append(recorded)
    if resolution is None:
        ticket.status = ReviewStatus.AWAITING_INFORMATION
    else:
        ticket.resolution = resolution
        ticket.status = ReviewStatus.RESOLVED
        ticket.closed_at = recorded.at
    case.record_attempt(STAGE_HUMAN_REVIEW, ok=True, detail=_describe(recorded, resolution))
    return case


def _resolve(comparisons: list[FieldComparison], decision: ReviewDecision) -> ReviewResolution:
    """Turn a complete comparison into a resolution by the usual rule."""
    outcome = CaseOutcome.MISMATCH if differing_fields(comparisons) else CaseOutcome.VERIFIED
    return ReviewResolution(
        outcome=outcome,
        comparisons=comparisons,
        action=decision.action,
        reviewer=decision.reviewer,
        at=decision.at,
    )


def _apply_corrections(
    case: CaseRecord, decision: ReviewDecision
) -> tuple[list[FieldComparison], list[ValueCorrection]]:
    """Compare again with the reviewer's values in place of the extracted ones.

    Returns:
        The new comparisons, and the corrections with the values they replaced.
    """
    if not decision.corrections:
        raise ReviewError("Enter at least one corrected value")

    current = {item.field: item for item in case.comparisons}
    values: dict[DocumentSide, dict[FieldName, FieldValue]] = {
        side: {
            field: (
                _side_value(current[field], side).model_copy(deep=True)
                if field in current
                else FieldValue(field=field, note="not extracted")
            )
            for field in COMPARED_FIELDS
        }
        for side in DocumentSide
    }

    applied: list[ValueCorrection] = []
    seen: set[tuple[FieldName, DocumentSide]] = set()
    for correction in decision.corrections:
        label = f"{correction.field.value} ({correction.side.value.upper()})"
        if (correction.field, correction.side) in seen:
            raise ReviewError(f"{label} is corrected twice")
        seen.add((correction.field, correction.side))

        value = normalize_whitespace(correction.value)
        normalized = None if is_missing(value) else normalize_value(correction.field, value)
        if normalized is None:
            raise ReviewError(f"{label}: '{value}' is not a usable value")

        previous = values[correction.side][correction.field].raw
        values[correction.side][correction.field] = FieldValue(
            field=correction.field,
            raw=value,
            normalized=normalized,
            confidence=1.0,
            evidence=Evidence(
                source=_source_name(case, correction.side),
                locator=f"read by reviewer {decision.reviewer}",
                snippet=value,
            ),
            note=f"corrected by {decision.reviewer}",
        )
        applied.append(correction.model_copy(update={"value": value, "previous": previous}))

    comparisons = compare_documents(values[DocumentSide.SI], values[DocumentSide.BL])
    undecided = undecided_fields(comparisons)
    if undecided:
        raise ReviewError(
            "Still not decidable after the corrections: "
            f"{', '.join(field.value for field in undecided)}. "
            "Enter a value for both documents, or choose another action."
        )
    return comparisons, applied


def _side_value(comparison: FieldComparison, side: DocumentSide) -> FieldValue:
    return comparison.si if side is DocumentSide.SI else comparison.bl


def _source_name(case: CaseRecord, side: DocumentSide) -> str:
    document = case.document(_SIDE_ROLES[side])
    return document.filename if document else f"reviewer-supplied {side.value.upper()}"


def _describe(decision: ReviewDecision, resolution: ReviewResolution | None) -> str:
    detail = f"{decision.action.value} by {decision.reviewer}"
    if decision.corrections:
        detail += f" ({len(decision.corrections)} corrected values)"
    if resolution is not None:
        detail += f" -> {resolution.outcome.value}"
    return detail


# -- reprocessing and the queue ------------------------------------------


def reprocess(previous: CaseRecord | None, fresh: CaseRecord) -> CaseRecord:
    """Carry history onto a case that was processed again.

    Earlier attempts stay in the audit trail. A ticket that holds a human
    decision moves across unchanged, because automation never discards one.

    Args:
        previous: The stored record, when the case was processed before.
        fresh: The record the pipeline just produced.

    Returns:
        The fresh record with the history attached.
    """
    if previous is None:
        return fresh

    history = list(previous.attempts)
    history.append(
        StageAttempt(
            stage=STAGE_REPROCESS,
            attempt=_count(history, STAGE_REPROCESS) + 1,
            ok=True,
            detail=f"processed again; previous outcome {previous.final_outcome.value}",
            at=fresh.created_at,
        )
    )
    for attempt in fresh.attempts:
        history.append(attempt.model_copy(update={"attempt": _count(history, attempt.stage) + 1}))
    fresh.attempts = history
    fresh.created_at = previous.created_at

    if previous.review is not None and previous.review.decisions:
        fresh.review = previous.review
        fresh.record_attempt(STAGE_TRIAGE, ok=True, detail="human review kept from the earlier run")
    return fresh


def _count(attempts: list[StageAttempt], stage: str) -> int:
    return sum(1 for attempt in attempts if attempt.stage == stage)


def review_queue(cases: Iterable[CaseRecord]) -> list[tuple[CaseRecord, ReviewTicket]]:
    """Return queued cases with their tickets, most urgent first.

    Args:
        cases: Every stored case.

    Returns:
        Open tickets before closed ones, then by priority, then oldest first.
    """
    queued = [(case, case.review) for case in cases if case.review is not None]
    return sorted(
        queued,
        key=lambda item: (
            _STATUS_ORDER[item[1].status],
            _PRIORITY_ORDER[item[1].priority],
            item[1].opened_at,
            item[0].email_id,
        ),
    )
