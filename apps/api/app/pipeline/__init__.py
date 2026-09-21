"""Verification pipeline: classify, read, extract, compare, decide, escalate."""

from .models import (
    COMPARED_FIELDS,
    CaseOutcome,
    CaseRecord,
    DocumentRead,
    DocumentRole,
    Evidence,
    FieldComparison,
    FieldName,
    FieldValue,
    ReviewAction,
    ReviewDecision,
    ReviewReason,
    StageAttempt,
)
from .orchestrator import Pipeline
from .readers import DocumentReader, ReaderError
from .reporting import (
    FinalReport,
    MatchStatus,
    QualityGate,
    QualityGateStatus,
    ReportStatus,
    build_report,
    evaluate_quality,
    render_report,
)
from .submission import SubmissionStatus, build_submission, submission_entry, write_submission

__all__ = [
    "COMPARED_FIELDS",
    "CaseOutcome",
    "CaseRecord",
    "DocumentRead",
    "DocumentReader",
    "DocumentRole",
    "Evidence",
    "FieldComparison",
    "FieldName",
    "FieldValue",
    "FinalReport",
    "MatchStatus",
    "Pipeline",
    "QualityGate",
    "QualityGateStatus",
    "ReaderError",
    "ReviewAction",
    "ReviewDecision",
    "ReviewReason",
    "ReportStatus",
    "StageAttempt",
    "SubmissionStatus",
    "build_submission",
    "build_report",
    "evaluate_quality",
    "render_report",
    "submission_entry",
    "write_submission",
]
