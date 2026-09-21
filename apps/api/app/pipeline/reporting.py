"""Quality-gate and reporting output for completed pipeline cases.

Reports describe the result that currently stands: the reviewer's resolution
when there is one, otherwise the automated result. The automated outcome is
always reported beside it, so a human override is never hidden.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from .models import (
    COMPARED_FIELDS,
    CaseOutcome,
    CaseRecord,
    DocumentRead,
    FieldComparison,
    FieldName,
    ReviewAction,
    ReviewStatus,
    ReviewTicket,
)
from .submission import SubmissionEntry, submission_entry

MINIMUM_CONFIDENCE = 0.8


class QualityGateStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


class ReportStatus(StrEnum):
    COMPLETE = "complete"
    NEEDS_REVIEW = "needs_review"
    AWAITING_DOCUMENTS = "awaiting_documents"
    NOT_APPLICABLE = "not_applicable"
    QA_FAILED = "qa_failed"
    UNABLE_TO_VERIFY = "unable_to_verify"


class MatchStatus(StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNCERTAIN = "uncertain"
    NOT_APPLICABLE = "not_applicable"


class QualityCheck(BaseModel):
    """One deterministic reporting precondition."""

    name: str
    passed: bool
    detail: str


class QualityGate(BaseModel):
    """Checks that prevent incomplete comparison reports from being final."""

    status: QualityGateStatus
    minimum_confidence: float = MINIMUM_CONFIDENCE
    checks: list[QualityCheck] = Field(default_factory=list)


class EvidenceSummary(BaseModel):
    """Compact evidence view for one compared field."""

    field: FieldName
    status: MatchStatus
    si_value: str | None
    bl_value: str | None
    si_source: str | None
    bl_source: str | None
    si_locator: str | None
    bl_locator: str | None


class FinalReport(BaseModel):
    """Structured and human-readable final output from the reporting agent.

    ``outcome`` is the result that stands; ``automated_outcome`` is what the
    pipeline decided before any human review.
    """

    email_id: str
    category: str
    outcome: CaseOutcome
    automated_outcome: CaseOutcome
    processing_status: ReportStatus
    match_status: MatchStatus
    defect_fields: list[FieldName]
    review_status: ReviewStatus
    review: ReviewTicket | None = None
    quality_gate: QualityGate
    comparisons: list[FieldComparison]
    evidence_summary: list[EvidenceSummary]
    submission: SubmissionEntry
    human_readable_report: str


def evaluate_quality(case: CaseRecord) -> QualityGate:
    """Run the deterministic gate on the result that currently stands."""
    return check_quality(
        case.final_outcome,
        case.documents,
        case.final_comparisons,
        reviewed=case.resolution is not None,
    )


def check_quality(
    outcome: CaseOutcome,
    documents: list[DocumentRead],
    comparisons: list[FieldComparison],
    *,
    reviewed: bool = False,
) -> QualityGate:
    """Run the gate shown between comparison and reporting.

    Args:
        outcome: The outcome being released.
        documents: The documents the case read.
        comparisons: The comparisons behind the outcome.
        reviewed: True when a reviewer produced the comparisons. A person read
            the source, so an unreadable file no longer blocks the result.

    Returns:
        The gate status and every check with its detail.
    """
    if outcome in {CaseOutcome.NOT_APPLICABLE, CaseOutcome.AWAITING_DOCUMENTS}:
        return QualityGate(status=QualityGateStatus.NOT_APPLICABLE)

    comparison_fields = [comparison.field for comparison in comparisons]
    seven_fields = len(comparison_fields) == 7 and set(comparison_fields) == set(COMPARED_FIELDS)
    values = [value for item in comparisons for value in (item.si, item.bl)]
    evidence_complete = bool(values) and all(
        not value.is_present or value.evidence is not None for value in values
    )
    confidence_complete = bool(values) and all(
        not value.is_present
        or (value.confidence is not None and value.confidence >= MINIMUM_CONFIDENCE)
        for value in values
    )
    mismatches = [item for item in comparisons if item.matches is False]
    mismatches_explained = all(
        item.note
        and item.si.raw is not None
        and item.bl.raw is not None
        and item.si.evidence is not None
        and item.bl.evidence is not None
        for item in mismatches
    )
    no_unresolved = bool(comparisons) and all(item.matches is not None for item in comparisons)
    documents_readable = reviewed or (bool(documents) and all(item.readable for item in documents))

    checks = [
        QualityCheck(
            name="seven_fields_considered",
            passed=seven_fields,
            detail=f"{len(set(comparison_fields))}/7 unique fields compared",
        ),
        QualityCheck(
            name="evidence_complete",
            passed=evidence_complete,
            detail="every present SI and BL value has source evidence",
        ),
        QualityCheck(
            name="confidence_threshold",
            passed=confidence_complete,
            detail=f"every present value meets confidence >= {MINIMUM_CONFIDENCE:.2f}",
        ),
        QualityCheck(
            name="mismatches_explained",
            passed=mismatches_explained,
            detail="every mismatch includes both values, evidence, and a reason",
        ),
        QualityCheck(
            name="no_unresolved_errors",
            passed=no_unresolved and documents_readable,
            detail=(
                "all comparisons are decidable and a reviewer read the source documents"
                if reviewed
                else "all comparisons are decidable and both documents are readable"
            ),
        ),
        QualityCheck(
            name="output_structure",
            passed=True,
            detail="the report conforms to the FinalReport schema",
        ),
    ]
    return QualityGate(
        status=(
            QualityGateStatus.PASS
            if all(check.passed for check in checks)
            else QualityGateStatus.FAIL
        ),
        checks=checks,
    )


def build_report(case: CaseRecord) -> FinalReport:
    """Create the final structured report without rerunning earlier stages."""
    gate = evaluate_quality(case)
    comparisons = case.final_comparisons
    return FinalReport(
        email_id=case.email_id,
        category=case.category.value,
        outcome=case.final_outcome,
        automated_outcome=case.outcome,
        processing_status=_processing_status(case, gate),
        match_status=_match_status(case.final_outcome),
        defect_fields=case.final_defect_fields,
        review_status=case.review_status,
        review=case.review,
        quality_gate=gate,
        comparisons=comparisons,
        evidence_summary=[_evidence_summary(item) for item in comparisons],
        submission=submission_entry(case),
        human_readable_report=render_report(case, gate),
    )


def _match_status(outcome: CaseOutcome) -> MatchStatus:
    if outcome is CaseOutcome.VERIFIED:
        return MatchStatus.MATCH
    if outcome is CaseOutcome.MISMATCH:
        return MatchStatus.MISMATCH
    if outcome is CaseOutcome.NEEDS_REVIEW:
        return MatchStatus.UNCERTAIN
    return MatchStatus.NOT_APPLICABLE


def _processing_status(case: CaseRecord, gate: QualityGate) -> ReportStatus:
    resolution = case.resolution
    if resolution is not None:
        # A reviewer has taken responsibility for the result, so it is final
        # even when a check the reviewer accepted still fails.
        if resolution.action is ReviewAction.UNABLE_TO_VERIFY:
            return ReportStatus.UNABLE_TO_VERIFY
        return ReportStatus.COMPLETE
    if gate.status is QualityGateStatus.FAIL and case.outcome is not CaseOutcome.NEEDS_REVIEW:
        return ReportStatus.QA_FAILED
    return {
        CaseOutcome.VERIFIED: ReportStatus.COMPLETE,
        CaseOutcome.MISMATCH: ReportStatus.COMPLETE,
        CaseOutcome.NEEDS_REVIEW: ReportStatus.NEEDS_REVIEW,
        CaseOutcome.AWAITING_DOCUMENTS: ReportStatus.AWAITING_DOCUMENTS,
        CaseOutcome.NOT_APPLICABLE: ReportStatus.NOT_APPLICABLE,
    }[case.outcome]


def _evidence_summary(comparison: FieldComparison) -> EvidenceSummary:
    status = (
        MatchStatus.UNCERTAIN
        if comparison.matches is None
        else MatchStatus.MATCH
        if comparison.matches
        else MatchStatus.MISMATCH
    )
    return EvidenceSummary(
        field=comparison.field,
        status=status,
        si_value=comparison.si.raw,
        bl_value=comparison.bl.raw,
        si_source=comparison.si.evidence.source if comparison.si.evidence else None,
        bl_source=comparison.bl.evidence.source if comparison.bl.evidence else None,
        si_locator=comparison.si.evidence.locator if comparison.si.evidence else None,
        bl_locator=comparison.bl.evidence.locator if comparison.bl.evidence else None,
    )


def render_report(case: CaseRecord, gate: QualityGate | None = None) -> str:
    """Render a concise Markdown report for an operator."""
    quality = gate or evaluate_quality(case)
    outcome = case.final_outcome
    comparisons = case.final_comparisons
    lines = [
        f"# Shipping document verification: {case.email_id}",
        "",
        f"- Category: {case.category.value}",
        f"- Outcome: {outcome.value}",
    ]
    if case.resolution is not None:
        automated = case.outcome.value
        if case.review_reason is not None:
            automated += f" ({case.review_reason.value})"
        lines.append(f"- Automated outcome: {automated}")
    lines.append(f"- Quality gate: {quality.status.value}")
    if case.final_review_reason is not None:
        lines.append(f"- Review reason: {case.final_review_reason.value}")

    if outcome is CaseOutcome.VERIFIED:
        lines.extend(["", "## Result", "No mismatch detected. All seven fields were verified."])
    elif outcome is CaseOutcome.MISMATCH:
        lines.extend(["", "## Result", "Mismatch detected in the following fields:", ""])
        for comparison in comparisons:
            if comparison.is_defect:
                lines.extend([*_comparison_lines(comparison), ""])
    elif outcome is CaseOutcome.NEEDS_REVIEW:
        closed = case.resolution is not None
        lines.extend(
            [
                "",
                "## Result",
                "A reviewer could not verify this case."
                if closed
                else "The comparison is uncertain and requires review.",
            ]
        )
        for comparison in comparisons:
            if comparison.matches is None:
                lines.extend(["", *_comparison_lines(comparison)])
    elif outcome is CaseOutcome.AWAITING_DOCUMENTS:
        lines.extend(["", "## Result", "Awaiting the required documents."])
    else:
        lines.extend(["", "## Result", "No document comparison was required."])

    if case.review is not None:
        lines.extend(["", *_review_lines(case.review)])

    if quality.checks:
        lines.extend(["", "## Quality assurance"])
        for check in quality.checks:
            lines.append(f"- {'PASS' if check.passed else 'FAIL'} — {check.name}: {check.detail}")
    return "\n".join(lines).rstrip() + "\n"


def _comparison_lines(comparison: FieldComparison) -> list[str]:
    lines = [
        f"### {comparison.field.value}",
        f"- SI: {_value(comparison.si.raw)}",
        f"- BL: {_value(comparison.bl.raw)}",
    ]
    if comparison.note:
        lines.append(f"- Reason: {comparison.note}")
    for label, value in (("SI", comparison.si), ("BL", comparison.bl)):
        if value.evidence is not None:
            lines.append(f"- {label} evidence: {value.evidence.source}, {value.evidence.locator}")
            lines.append(f"  {value.evidence.snippet}")
    return lines


def _review_lines(ticket: ReviewTicket) -> list[str]:
    """List the escalation and every reviewer decision, oldest first."""
    lines = [
        "## Human review",
        f"- Status: {ticket.status.value}",
        f"- Assigned to: {ticket.team.value} ({ticket.priority.value} priority)",
        f"- Escalation: {ticket.summary}",
    ]
    for decision in ticket.decisions:
        stamp = decision.at.strftime("%Y-%m-%d %H:%M UTC")
        entry = f"- {stamp} — {decision.action.value} by {decision.reviewer}"
        lines.append(f"{entry}: {decision.note}" if decision.note else entry)
        for correction in decision.corrections:
            lines.append(
                f"  - {correction.field.value} ({correction.side.value.upper()}): "
                f"{_value(correction.previous)} -> {correction.value}"
            )
    return lines


def _value(value: object) -> str:
    return str(value) if value is not None else "(unavailable)"
