"""Exception triage, reviewer decisions, and the report after review."""

from pathlib import Path

import pytest

from app.pipeline import (
    COMPARED_FIELDS,
    CaseOutcome,
    CaseRecord,
    DocumentSide,
    FieldName,
    Pipeline,
    QualityGateStatus,
    ReportStatus,
    ReviewAction,
    ReviewConflict,
    ReviewDecision,
    ReviewError,
    ReviewPriority,
    ReviewReason,
    ReviewStatus,
    ReviewTeam,
    ValueCorrection,
    allowed_actions,
    apply_decision,
    build_report,
    reprocess,
    review_queue,
    submission_entry,
    triage,
)
from app.pipeline.readers import PlainTextReader
from tests.test_pipeline import BL_TEXT, SI_TEXT, make_email, write_case

BL_MATCHING = BL_TEXT.replace("UAB NOVAKOPA", "EAST BRIGHT FZ-LLC")
BL_WEIGHT_TBA = BL_MATCHING.replace("Gross Weight (KG): 131,058 KG", "Gross Weight (KG): TBA")
SI_NO_PORT_OR_WEIGHT = SI_TEXT.replace("POD: KARACHI, PAKISTAN (PKKHI)\n", "").replace(
    "Gross Wt (kgs): 131,058 KG\n", ""
)
ATTACHED = "Attached are the SI and draft BL. Please check."

SI_VALUES = {
    FieldName.SHIPPER: "APRIL FAR EAST (M) SDN BHD",
    FieldName.CONSIGNEE: "EAST BRIGHT FZ-LLC",
    FieldName.NOTIFY_PARTY: "EAST BRIGHT FZ-LLC",
    FieldName.PORT_OF_LOADING: "NANTONG, CHINA",
    FieldName.PORT_OF_DISCHARGE: "KARACHI, PAKISTAN",
    FieldName.CONTAINER_COUNT: "6 x 40'HC",
    FieldName.GROSS_WEIGHT_KG: "131,058 KG",
}


def run_case(root: Path, si: str | None, bl: str | None, body: str = ATTACHED) -> CaseRecord:
    paths = write_case(root, "email_004", si, bl)
    pipeline = Pipeline(dataset_root=root, readers=(PlainTextReader(),))
    return pipeline.run(make_email("email_004", body, paths))


def decide(
    action: ReviewAction,
    note: str | None = None,
    corrections: tuple[tuple[FieldName, DocumentSide, str], ...] = (),
) -> ReviewDecision:
    return ReviewDecision(
        reviewer="Ops reviewer",
        action=action,
        note=note,
        corrections=[
            ValueCorrection(field=field, side=side, value=value)
            for field, side, value in corrections
        ],
    )


def correct_bl_weight(value: str) -> ReviewDecision:
    return decide(
        ReviewAction.CORRECTED,
        note="Read from the draft BL.",
        corrections=((FieldName.GROSS_WEIGHT_KG, DocumentSide.BL, value),),
    )


class TestTriage:
    def test_a_clean_result_needs_no_ticket(self, tmp_path: Path) -> None:
        case = run_case(tmp_path, SI_TEXT, BL_MATCHING)

        assert case.outcome is CaseOutcome.VERIFIED
        assert case.review is None
        assert case.review_status is ReviewStatus.NOT_REQUIRED
        assert all(attempt.stage != "triage" for attempt in case.attempts)

    def test_missing_value_goes_to_field_verification(self, tmp_path: Path) -> None:
        case = run_case(tmp_path, SI_TEXT, BL_WEIGHT_TBA)

        ticket = case.review
        assert ticket is not None
        assert ticket.status is ReviewStatus.PENDING
        assert ticket.reason is ReviewReason.MISSING_VALUE
        assert ticket.team is ReviewTeam.FIELD_VERIFICATION
        assert ticket.priority is ReviewPriority.NORMAL
        assert ticket.questionable_fields == [FieldName.GROSS_WEIGHT_KG]
        assert ticket.recommended_action is ReviewAction.CORRECTED
        assert "gross_weight_kg" in ticket.summary
        assert case.attempts[-1].stage == "triage"

    def test_a_confirmed_discrepancy_raises_priority(self, tmp_path: Path) -> None:
        bl = BL_TEXT.replace("Gross Weight (KG): 131,058 KG", "Gross Weight (KG): TBA")
        case = run_case(tmp_path, SI_TEXT, bl)

        assert case.review is not None
        assert case.review.priority is ReviewPriority.HIGH
        assert "consignee" in case.review.summary

    def test_missing_attachment_goes_to_document_intake(self, tmp_path: Path) -> None:
        case = run_case(tmp_path, SI_TEXT, None)

        ticket = case.review
        assert ticket is not None
        assert ticket.reason is ReviewReason.MISSING_ATTACHMENT
        assert ticket.team is ReviewTeam.DOCUMENT_INTAKE
        assert ticket.recommended_action is ReviewAction.INFORMATION_REQUESTED
        assert ticket.questionable_fields == list(COMPARED_FIELDS)
        assert "No draft bill of lading" in ticket.summary

    def test_wrong_document_is_named_in_the_summary(self, tmp_path: Path) -> None:
        case = run_case(tmp_path, SI_TEXT, "COMMERCIAL INVOICE\nInvoice No: 77\nAmount: 10\n" * 3)

        assert case.review is not None
        assert case.review.reason is ReviewReason.WRONG_DOC_TYPE
        assert "email_004_BL.txt is not an SI or a draft BL" in case.review.summary
        assert "COMMERCIAL INVOICE" in case.review.summary

    def test_a_quality_gate_failure_is_queued_for_sign_off(self, tmp_path: Path) -> None:
        case = run_case(tmp_path, SI_TEXT, BL_MATCHING)
        case.comparisons[0].bl.confidence = 0.4

        ticket = triage(case)

        assert ticket is not None
        assert ticket.reason is None
        assert ticket.failed_checks == ["confidence_threshold"]
        assert ticket.priority is ReviewPriority.LOW
        assert ticket.recommended_action is ReviewAction.CONFIRMED
        assert ticket.questionable_fields == [FieldName.SHIPPER]


class TestDecisions:
    def test_a_correction_resolves_the_case_beside_the_automated_result(
        self, tmp_path: Path
    ) -> None:
        case = run_case(tmp_path, SI_TEXT, BL_WEIGHT_TBA)

        apply_decision(case, correct_bl_weight("131,058 KG"))

        assert case.outcome is CaseOutcome.NEEDS_REVIEW  # automated result kept
        assert case.final_outcome is CaseOutcome.VERIFIED
        automated = next(c for c in case.comparisons if c.field is FieldName.GROSS_WEIGHT_KG)
        final = next(c for c in case.final_comparisons if c.field is FieldName.GROSS_WEIGHT_KG)
        assert automated.bl.raw is None
        assert automated.bl.note == "Unsupported gross weight: 'TBA'."
        assert final.bl.raw == "131,058 KG"
        assert final.bl.evidence is not None
        assert final.bl.evidence.source == "email_004_BL.txt"
        assert "Ops reviewer" in final.bl.evidence.locator

        assert case.review is not None
        assert case.review.status is ReviewStatus.RESOLVED
        assert case.review.closed_at is not None
        assert case.review.decisions[0].corrections[0].previous is None  # nothing usable read
        assert case.attempts[-1].stage == "human_review"

    def test_a_correction_can_reveal_a_discrepancy(self, tmp_path: Path) -> None:
        case = run_case(tmp_path, SI_TEXT, BL_WEIGHT_TBA)

        apply_decision(case, correct_bl_weight("132,500 KG"))

        assert case.final_outcome is CaseOutcome.MISMATCH
        assert case.final_defect_fields == [FieldName.GROSS_WEIGHT_KG]
        entry = submission_entry(case)
        assert entry["status"] == "MISMATCH"
        assert entry["defect_fields"] == ["gross_weight_kg"]

    def test_corrections_that_leave_a_field_undecided_change_nothing(self, tmp_path: Path) -> None:
        case = run_case(tmp_path, SI_NO_PORT_OR_WEIGHT, BL_MATCHING)
        decision = decide(
            ReviewAction.CORRECTED,
            corrections=((FieldName.GROSS_WEIGHT_KG, DocumentSide.SI, "131,058 KG"),),
        )

        with pytest.raises(ReviewError, match="port_of_discharge"):
            apply_decision(case, decision)

        assert case.review is not None
        assert case.review.status is ReviewStatus.PENDING
        assert case.review.decisions == []

    @pytest.mark.parametrize("value", ["TBA", "N/A", "heavy"])
    def test_a_placeholder_or_unparseable_correction_is_refused(
        self, tmp_path: Path, value: str
    ) -> None:
        case = run_case(tmp_path, SI_TEXT, BL_WEIGHT_TBA)

        with pytest.raises(ReviewError, match="not a usable value"):
            apply_decision(case, correct_bl_weight(value))

    def test_duplicate_corrections_are_refused(self, tmp_path: Path) -> None:
        case = run_case(tmp_path, SI_TEXT, BL_WEIGHT_TBA)
        field, side = FieldName.GROSS_WEIGHT_KG, DocumentSide.BL
        decision = decide(
            ReviewAction.CORRECTED,
            corrections=((field, side, "131,058 KG"), (field, side, "131,000 KG")),
        )

        with pytest.raises(ReviewError, match="corrected twice"):
            apply_decision(case, decision)

    def test_there_is_nothing_to_confirm_while_a_field_is_undecided(self, tmp_path: Path) -> None:
        case = run_case(tmp_path, SI_TEXT, BL_WEIGHT_TBA)

        assert ReviewAction.CONFIRMED not in allowed_actions(case)
        with pytest.raises(ReviewError, match="no complete result to confirm"):
            apply_decision(case, decide(ReviewAction.CONFIRMED))

    def test_confirming_a_quality_failure_releases_the_automated_result(
        self, tmp_path: Path
    ) -> None:
        case = run_case(tmp_path, SI_TEXT, BL_MATCHING)
        case.comparisons[0].bl.confidence = 0.4
        case.review = triage(case)

        assert ReviewAction.CONFIRMED in allowed_actions(case)
        apply_decision(case, decide(ReviewAction.CONFIRMED, note="Shipper checked by hand."))

        report = build_report(case)
        assert report.outcome is CaseOutcome.VERIFIED
        assert report.quality_gate.status is QualityGateStatus.FAIL  # still reported honestly
        assert report.processing_status is ReportStatus.COMPLETE  # a person signed it off

    def test_a_request_for_information_waits_for_a_final_decision(self, tmp_path: Path) -> None:
        case = run_case(tmp_path, SI_TEXT, BL_WEIGHT_TBA)

        apply_decision(
            case,
            decide(ReviewAction.INFORMATION_REQUESTED, note="Asked the carrier for the weight."),
        )

        assert case.review_status is ReviewStatus.AWAITING_INFORMATION
        assert case.resolution is None
        report = build_report(case)
        assert report.review_status is ReviewStatus.AWAITING_INFORMATION
        assert report.processing_status is ReportStatus.NEEDS_REVIEW

        apply_decision(case, correct_bl_weight("131,058 KG"))

        assert build_report(case).review_status is ReviewStatus.RESOLVED
        assert case.review is not None
        assert [d.action for d in case.review.decisions] == [
            ReviewAction.INFORMATION_REQUESTED,
            ReviewAction.CORRECTED,
        ]

    @pytest.mark.parametrize(
        "action", [ReviewAction.INFORMATION_REQUESTED, ReviewAction.UNABLE_TO_VERIFY]
    )
    def test_a_request_or_closure_needs_a_note(self, tmp_path: Path, action: ReviewAction) -> None:
        case = run_case(tmp_path, SI_TEXT, BL_WEIGHT_TBA)

        with pytest.raises(ReviewError, match="note is required"):
            apply_decision(case, decide(action, note="   "))

    def test_corrections_need_the_corrected_action(self, tmp_path: Path) -> None:
        case = run_case(tmp_path, SI_TEXT, BL_WEIGHT_TBA)
        decision = decide(
            ReviewAction.UNABLE_TO_VERIFY,
            note="Cannot tell.",
            corrections=((FieldName.GROSS_WEIGHT_KG, DocumentSide.BL, "131,058 KG"),),
        )

        with pytest.raises(ReviewError, match="only accepted with the corrected action"):
            apply_decision(case, decision)

    def test_unable_to_verify_closes_the_case_without_a_result(self, tmp_path: Path) -> None:
        case = run_case(tmp_path, SI_TEXT, BL_WEIGHT_TBA)

        apply_decision(
            case, decide(ReviewAction.UNABLE_TO_VERIFY, note="Carrier cannot confirm the weight.")
        )

        report = build_report(case)
        assert report.outcome is CaseOutcome.NEEDS_REVIEW
        assert report.processing_status is ReportStatus.UNABLE_TO_VERIFY
        assert report.review_status is ReviewStatus.RESOLVED
        assert report.submission["status"] == "NEEDS_REVIEW"
        assert report.submission["review_reason"] == "missing_value"
        assert "A reviewer could not verify this case." in report.human_readable_report

    def test_a_resolved_case_accepts_no_further_decision(self, tmp_path: Path) -> None:
        case = run_case(tmp_path, SI_TEXT, BL_WEIGHT_TBA)
        apply_decision(case, correct_bl_weight("131,058 KG"))

        with pytest.raises(ReviewConflict, match="already resolved"):
            apply_decision(case, correct_bl_weight("131,000 KG"))
        assert allowed_actions(case) == []

    def test_a_case_outside_the_queue_is_refused(self, tmp_path: Path) -> None:
        case = run_case(tmp_path, SI_TEXT, BL_TEXT)

        assert case.outcome is CaseOutcome.MISMATCH
        with pytest.raises(ReviewConflict, match="not in the review queue"):
            apply_decision(case, correct_bl_weight("131,058 KG"))


class TestReportAfterReview:
    def test_the_report_shows_the_final_and_the_automated_outcome(self, tmp_path: Path) -> None:
        case = run_case(tmp_path, SI_TEXT, BL_WEIGHT_TBA)
        apply_decision(case, correct_bl_weight("131,058 KG"))

        report = build_report(case)

        assert report.outcome is CaseOutcome.VERIFIED
        assert report.automated_outcome is CaseOutcome.NEEDS_REVIEW
        assert report.processing_status is ReportStatus.COMPLETE
        assert report.quality_gate.status is QualityGateStatus.PASS
        assert report.review_status is ReviewStatus.RESOLVED
        assert report.submission["status"] == "OK"
        text = report.human_readable_report
        assert "- Outcome: verified" in text
        assert "- Automated outcome: needs_review (missing_value)" in text
        assert "## Human review" in text
        assert "gross_weight_kg (BL): (unavailable) -> 131,058 KG" in text

    def test_values_read_from_an_unreadable_file_pass_the_gate(self, tmp_path: Path) -> None:
        case = run_case(tmp_path, SI_TEXT, "%PDF-1.4 damaged scan")
        assert case.review_reason is ReviewReason.UNREADABLE
        corrections = tuple(
            (field, side, value) for field, value in SI_VALUES.items() for side in DocumentSide
        )

        apply_decision(case, decide(ReviewAction.CORRECTED, corrections=corrections))

        report = build_report(case)
        assert report.outcome is CaseOutcome.VERIFIED
        assert report.quality_gate.status is QualityGateStatus.PASS
        bl_weight = next(
            c for c in case.final_comparisons if c.field is FieldName.GROSS_WEIGHT_KG
        ).bl
        assert bl_weight.evidence is not None
        assert bl_weight.evidence.source == "reviewer-supplied BL"


class TestReprocessing:
    def test_a_second_run_keeps_the_history_and_the_human_decision(self, tmp_path: Path) -> None:
        previous = run_case(tmp_path, SI_TEXT, BL_WEIGHT_TBA)
        apply_decision(
            previous, decide(ReviewAction.INFORMATION_REQUESTED, note="Asked for the weight.")
        )
        ticket = previous.review

        fresh = reprocess(previous, run_case(tmp_path, SI_TEXT, BL_WEIGHT_TBA))

        assert fresh.review is ticket
        assert fresh.created_at == previous.created_at
        stages = [attempt.stage for attempt in fresh.attempts]
        assert "reprocess" in stages
        assert "human_review" in stages
        classify = [a.attempt for a in fresh.attempts if a.stage == "classify"]
        assert classify == [1, 2]

    def test_a_ticket_without_decisions_is_triaged_again(self, tmp_path: Path) -> None:
        previous = run_case(tmp_path, SI_TEXT, BL_WEIGHT_TBA)

        fresh = reprocess(previous, run_case(tmp_path, SI_TEXT, BL_MATCHING))

        assert fresh.outcome is CaseOutcome.VERIFIED
        assert fresh.review is None


def test_the_queue_puts_open_and_urgent_cases_first(tmp_path: Path) -> None:
    normal = run_case(tmp_path / "a", SI_TEXT, BL_WEIGHT_TBA)
    normal.email_id = "email_001"
    high = run_case(
        tmp_path / "b",
        SI_TEXT,
        BL_TEXT.replace("Gross Weight (KG): 131,058 KG", "Gross Weight (KG): TBA"),
    )
    high.email_id = "email_002"
    resolved = run_case(tmp_path / "c", SI_TEXT, BL_WEIGHT_TBA)
    resolved.email_id = "email_003"
    apply_decision(resolved, correct_bl_weight("131,058 KG"))
    clean = run_case(tmp_path / "d", SI_TEXT, BL_MATCHING)

    ordered = [case.email_id for case, _ in review_queue([resolved, normal, clean, high])]

    assert ordered == ["email_002", "email_001", "email_003"]
