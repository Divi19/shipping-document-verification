"""Comparison quality gate and final reporting tests."""

from pathlib import Path

from app.models.email.schemas import ParsedEmail
from app.pipeline import (
    CaseOutcome,
    CaseRecord,
    MatchStatus,
    Pipeline,
    QualityGateStatus,
    ReportStatus,
    build_report,
)
from app.pipeline.readers import PlainTextReader
from tests.test_pipeline import BL_TEXT, SI_TEXT, make_email, write_case


def _mismatch_case(tmp_path: Path) -> tuple[ParsedEmail, CaseRecord]:
    paths = write_case(tmp_path, "email_004", SI_TEXT, BL_TEXT)
    email = make_email("email_004", "Attached are the SI and draft BL.", paths)
    case = Pipeline(dataset_root=tmp_path, readers=(PlainTextReader(),)).run(email)
    return email, case


def test_mismatch_report_passes_qa_and_retains_evidence(tmp_path: Path) -> None:
    _, case = _mismatch_case(tmp_path)

    report = build_report(case)

    assert report.outcome is CaseOutcome.MISMATCH
    assert report.processing_status is ReportStatus.COMPLETE
    assert report.match_status is MatchStatus.MISMATCH
    assert report.quality_gate.status is QualityGateStatus.PASS
    assert {field.value for field in report.defect_fields} == {"consignee", "notify_party"}
    assert all(check.passed for check in report.quality_gate.checks)
    assert "Mismatch detected" in report.human_readable_report
    assert "email_004_SI.txt" in report.human_readable_report


def test_quality_gate_blocks_a_final_report_when_confidence_is_missing(tmp_path: Path) -> None:
    _, case = _mismatch_case(tmp_path)
    case.comparisons[0].si.confidence = None

    report = build_report(case)

    assert report.quality_gate.status is QualityGateStatus.FAIL
    assert report.processing_status is ReportStatus.QA_FAILED
    confidence = next(
        check for check in report.quality_gate.checks if check.name == "confidence_threshold"
    )
    assert confidence.passed is False


def test_uncertain_case_is_reported_for_review_instead_of_as_a_mismatch(tmp_path: Path) -> None:
    paths = write_case(
        tmp_path,
        "email_004",
        SI_TEXT.replace("Gross Wt (kgs): 131,058 KG", ""),
        BL_TEXT,
    )
    email = make_email("email_004", "Attached are the SI and draft BL.", paths)
    case = Pipeline(dataset_root=tmp_path, readers=(PlainTextReader(),)).run(email)

    report = build_report(case)

    assert report.outcome is CaseOutcome.NEEDS_REVIEW
    assert report.processing_status is ReportStatus.NEEDS_REVIEW
    assert report.match_status is MatchStatus.UNCERTAIN
    assert report.quality_gate.status is QualityGateStatus.FAIL
    assert report.review_status == "pending"
