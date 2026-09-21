"""Evidence verification for candidates extracted from plain text."""

from app.ingestion.extractors import ContentType, ExtractedContent, IngestionStatus
from app.models.extraction import (
    ComparisonField,
    DocumentFieldCandidates,
    FieldCandidate,
    TextSpanLocator,
)
from app.models.verification import (
    CandidateAssessment,
    DocumentVerificationResult,
    FieldVerificationResult,
    VerificationIssue,
    VerificationOutcome,
    VerifiedField,
)


class TextEvidenceVerifier:
    """Verify Box 5 TXT candidates against their cited source text."""

    def __init__(self, minimum_confidence: float = 0.8) -> None:
        if not 0 <= minimum_confidence <= 1:
            raise ValueError("minimum_confidence must be between 0 and 1")
        self.minimum_confidence = minimum_confidence

    def verify(
        self,
        document: ExtractedContent,
        extracted: DocumentFieldCandidates,
    ) -> DocumentVerificationResult:
        """Verify evidence, confidence, and within-field consistency."""
        if document.content_type != ContentType.TEXT:
            raise ValueError("TextEvidenceVerifier only accepts text/plain documents")
        if document.source_filename != extracted.source_filename:
            raise ValueError("ingested and extracted source filenames do not match")

        diagnostics = list(extracted.diagnostics)
        if document.status != IngestionStatus.SUCCESS:
            diagnostics = [
                f"Document ingestion status is {document.status.value}; evidence is unavailable.",
                *document.diagnostics,
                *diagnostics,
            ]

        fields = [
            self._verify_field(
                field,
                extracted.candidates_for(field),
                document.text,
            )
            for field in ComparisonField
        ]
        return DocumentVerificationResult(
            document_role=extracted.document_role,
            source_filename=extracted.source_filename,
            fields=fields,
            diagnostics=diagnostics,
        )

    def _verify_field(
        self,
        field: ComparisonField,
        candidates: list[FieldCandidate],
        source_text: str,
    ) -> FieldVerificationResult:
        if not candidates:
            return FieldVerificationResult(
                field=field,
                issues=[VerificationIssue.MISSING_CANDIDATE],
            )

        assessments = [self._assess_candidate(candidate, source_text) for candidate in candidates]
        supported = [item for item in assessments if item.outcome == VerificationOutcome.VERIFIED]
        if not supported:
            issues = list(dict.fromkeys(issue for item in assessments for issue in item.issues))
            return FieldVerificationResult(
                field=field,
                assessments=assessments,
                issues=issues,
            )

        distinct_values = {self._compact(item.candidate.raw_value) for item in supported}
        if len(distinct_values) > 1:
            conflicted = [
                CandidateAssessment(
                    candidate=item.candidate,
                    outcome=VerificationOutcome.UNCERTAIN,
                    issues=[VerificationIssue.CONFLICTING_CANDIDATES],
                    notes=["Another evidence-supported candidate has a different raw value."],
                )
                if item.outcome == VerificationOutcome.VERIFIED
                else item
                for item in assessments
            ]
            return FieldVerificationResult(
                field=field,
                assessments=conflicted,
                issues=[VerificationIssue.CONFLICTING_CANDIDATES],
            )

        selected = max(
            supported,
            key=lambda item: item.candidate.confidence,
        )
        alternatives = [item for item in assessments if item is not selected]
        return FieldVerificationResult(
            field=field,
            assessments=assessments,
            verified_field=VerifiedField(
                field=field,
                selected=selected,
                alternatives=alternatives,
            ),
        )

    def _assess_candidate(
        self,
        candidate: FieldCandidate,
        source_text: str,
    ) -> CandidateAssessment:
        if not self._evidence_is_supported(candidate, source_text):
            return CandidateAssessment(
                candidate=candidate,
                outcome=VerificationOutcome.REJECTED,
                issues=[VerificationIssue.EVIDENCE_NOT_FOUND],
                notes=["The cited text span does not support the raw label and value."],
            )
        if "�" in candidate.raw_value or any(
            "�" in evidence.source_text for evidence in candidate.evidence
        ):
            return CandidateAssessment(
                candidate=candidate,
                outcome=VerificationOutcome.UNCERTAIN,
                issues=[VerificationIssue.LIKELY_OCR_ERROR],
                notes=["The candidate or evidence contains a replacement character."],
            )
        if candidate.confidence < self.minimum_confidence:
            return CandidateAssessment(
                candidate=candidate,
                outcome=VerificationOutcome.UNCERTAIN,
                issues=[VerificationIssue.LOW_CONFIDENCE],
                notes=[
                    f"Candidate confidence {candidate.confidence:.2f} is below "
                    f"the {self.minimum_confidence:.2f} threshold."
                ],
            )
        return CandidateAssessment(
            candidate=candidate,
            outcome=VerificationOutcome.VERIFIED,
        )

    def _evidence_is_supported(self, candidate: FieldCandidate, source_text: str) -> bool:
        for evidence in candidate.evidence:
            locator = evidence.locator
            if not isinstance(locator, TextSpanLocator):
                return False
            if source_text[locator.start : locator.end] != evidence.source_text:
                return False
            expected_line_start = source_text[: locator.start].count("\n") + 1
            expected_line_end = expected_line_start + evidence.source_text.count("\n")
            if locator.line_start is not None and locator.line_start != expected_line_start:
                return False
            if locator.line_end is not None and locator.line_end != expected_line_end:
                return False
            compact_evidence = self._compact(evidence.source_text)
            if self._compact(candidate.raw_label) not in compact_evidence:
                return False
            if self._compact(candidate.raw_value) not in compact_evidence:
                return False
        return True

    @staticmethod
    def _compact(value: str) -> str:
        return " ".join(value.casefold().split())


def verify_text_candidates(
    document: ExtractedContent,
    extracted: DocumentFieldCandidates,
    minimum_confidence: float = 0.8,
) -> DocumentVerificationResult:
    """Convenience boundary between TXT extraction and Box 6."""
    return TextEvidenceVerifier(minimum_confidence).verify(document, extracted)
