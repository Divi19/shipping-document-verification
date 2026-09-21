"""Render processed cases for human review.

The evaluator submission remains in ``submission.py``. This module formats the
same CaseRecord for an operator without rerunning extraction or comparison.
"""

from .models import CaseOutcome, CaseRecord, FieldComparison


def _value(value: object) -> str:
    """Render an optional value without exposing Python's ``None``."""
    return str(value) if value is not None else "(unavailable)"


def _evidence(label: str, comparison: FieldComparison) -> list[str]:
    lines: list[str] = []
    evidence = comparison.si.evidence
    if evidence is not None:
        lines.append(f"- {label} evidence: {evidence.source}, {evidence.locator}")
        lines.append(f"  {evidence.snippet}")
    evidence = comparison.bl.evidence
    if evidence is not None:
        lines.append(f"- BL evidence: {evidence.source}, {evidence.locator}")
        lines.append(f"  {evidence.snippet}")
    return lines


def _comparison_lines(comparison: FieldComparison) -> list[str]:
    """Render one mismatch or uncertain field with its supporting context."""
    lines = [f"### {comparison.field.value}"]
    lines.append(f"- SI: {_value(comparison.si.raw)}")
    lines.append(f"- BL: {_value(comparison.bl.raw)}")
    if comparison.si.normalized is not None:
        lines.append(f"- SI normalized: {comparison.si.normalized}")
    if comparison.bl.normalized is not None:
        lines.append(f"- BL normalized: {comparison.bl.normalized}")
    if comparison.note:
        lines.append(f"- Reason: {comparison.note}")
    if comparison.si.note and not comparison.si.is_present:
        lines.append(f"- SI detail: {comparison.si.note}")
    if comparison.bl.note and not comparison.bl.is_present:
        lines.append(f"- BL detail: {comparison.bl.note}")
    lines.extend(_evidence("SI", comparison))
    return lines


def render_report(case: CaseRecord) -> str:
    """Render a concise Markdown report for a reviewer."""
    lines = [
        f"# Shipping document verification: {case.email_id}",
        "",
        f"- Category: {case.category.value}",
        f"- Status: {case.outcome.value}",
    ]

    if case.review_reason is not None:
        lines.append(f"- Review reason: {case.review_reason.value}")
    if case.review is not None:
        lines.append(f"- Reviewed by: {case.review.reviewer}")
        lines.append(f"- Review action: {case.review.action.value}")
        if case.review.note:
            lines.append(f"- Review note: {case.review.note}")

    if case.outcome is CaseOutcome.VERIFIED:
        lines.extend(["", "## Result", "No mismatch detected. All seven fields were verified."])
    elif case.outcome is CaseOutcome.MISMATCH:
        lines.extend(["", "## Result", "Mismatch detected in the following fields:", ""])
        for comparison in case.comparisons:
            if comparison.is_defect:
                lines.extend(_comparison_lines(comparison))
                lines.append("")
    elif case.outcome is CaseOutcome.NEEDS_REVIEW:
        lines.extend(["", "## Result", "The case needs human review.", ""])
        uncertain = [comparison for comparison in case.comparisons if comparison.matches is None]
        for comparison in uncertain:
            lines.extend(_comparison_lines(comparison))
            lines.append("")
        unreadable = [document for document in case.documents if not document.readable]
        if unreadable:
            lines.append("### Document issues")
            for document in unreadable:
                lines.append(
                    f"- {document.filename}: {document.failure or 'document could not be read'}"
                )
        if not uncertain and not unreadable and case.review_reason is not None:
            lines.append(f"Reason: {case.review_reason.value}")
    elif case.outcome is CaseOutcome.AWAITING_DOCUMENTS:
        lines.extend(["", "## Result", "Awaiting the required documents; no comparison was performed."])
    else:
        lines.extend(["", "## Result", "No document comparison was required."])

    return "\n".join(lines).rstrip() + "\n"
