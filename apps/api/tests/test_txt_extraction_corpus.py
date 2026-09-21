"""Integrity tests for the synthetic TXT extraction acceptance corpus."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.models.extraction import (
    ALL_COMPARISON_FIELDS,
    ComparisonField,
    DocumentFieldCandidates,
    DocumentRole,
    EvidenceReference,
    ExtractionMethod,
    FieldCandidate,
    TextSpanLocator,
)

CORPUS_DIR = Path(__file__).parent / "fixtures" / "txt_extraction"


class ExpectedCandidate(BaseModel):
    """Expected raw candidate recorded in the corpus manifest."""

    model_config = ConfigDict(extra="forbid")

    field: ComparisonField
    raw_label: str
    raw_value: str
    evidence_quote: str


class CorpusCase(BaseModel):
    """One synthetic document and its expected extraction behavior."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    filename: str
    document_role: DocumentRole
    purpose: str
    expected_candidates: list[ExpectedCandidate] = Field(min_length=1)
    expected_missing_fields: list[ComparisonField]


class CorpusManifest(BaseModel):
    """Versioned TXT extraction acceptance manifest."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int
    cases: list[CorpusCase] = Field(min_length=1)


def _load_manifest() -> CorpusManifest:
    return CorpusManifest.model_validate_json((CORPUS_DIR / "manifest.json").read_text())


def _build_candidates(case: CorpusCase, text: str) -> DocumentFieldCandidates:
    candidates: list[FieldCandidate] = []
    for expected in case.expected_candidates:
        start = text.index(expected.evidence_quote)
        end = start + len(expected.evidence_quote)
        line_start = text[:start].count("\n") + 1
        line_end = line_start + expected.evidence_quote.count("\n")
        candidates.append(
            FieldCandidate(
                field=expected.field,
                document_role=case.document_role,
                raw_label=expected.raw_label,
                raw_value=expected.raw_value,
                evidence=[
                    EvidenceReference(
                        source_filename=case.filename,
                        locator=TextSpanLocator(
                            start=start,
                            end=end,
                            line_start=line_start,
                            line_end=line_end,
                        ),
                        source_text=expected.evidence_quote,
                    )
                ],
                extraction_method=ExtractionMethod.LABEL_MAP,
                confidence=1,
            )
        )
    return DocumentFieldCandidates(
        document_role=case.document_role,
        source_filename=case.filename,
        candidates=candidates,
    )


def test_manifest_is_versioned_and_case_ids_are_unique() -> None:
    manifest = _load_manifest()
    case_ids = [case.case_id for case in manifest.cases]
    filenames = [case.filename for case in manifest.cases]

    assert manifest.schema_version == 1
    assert len(case_ids) == len(set(case_ids))
    assert len(filenames) == len(set(filenames))


def test_every_case_has_complete_and_non_overlapping_expectations() -> None:
    for case in _load_manifest().cases:
        candidate_fields = {candidate.field for candidate in case.expected_candidates}
        missing_fields = set(case.expected_missing_fields)

        assert len(case.expected_missing_fields) == len(missing_fields), case.case_id
        assert candidate_fields.isdisjoint(missing_fields), case.case_id
        assert candidate_fields | missing_fields == ALL_COMPARISON_FIELDS, case.case_id


def test_expected_evidence_is_unique_and_builds_real_contracts() -> None:
    for case in _load_manifest().cases:
        source_path = CORPUS_DIR / case.filename
        text = source_path.read_text()

        for expected in case.expected_candidates:
            assert text.count(expected.evidence_quote) == 1, (
                case.case_id,
                expected.evidence_quote,
            )
            assert expected.raw_label in expected.evidence_quote
            assert expected.raw_value in expected.evidence_quote

        document = _build_candidates(case, text)
        assert len(document.candidates) == len(case.expected_candidates)


def test_corpus_preserves_multiline_party_evidence() -> None:
    case = next(item for item in _load_manifest().cases if item.case_id == "multiline_parties_si")
    shipper = next(
        item for item in case.expected_candidates if item.field == ComparisonField.SHIPPER
    )

    assert "On behalf of Seaside Holdings Pte Ltd" in shipper.raw_value
    assert "77 Harbor Road" in shipper.raw_value


def test_corpus_retains_conflicting_values_as_multiple_candidates() -> None:
    case = next(item for item in _load_manifest().cases if item.case_id == "contradictory_bl")
    text = (CORPUS_DIR / case.filename).read_text()
    document = _build_candidates(case, text)
    weights = document.candidates_for(ComparisonField.GROSS_WEIGHT_KG)

    assert [candidate.raw_value for candidate in weights] == ["66,000 KG", "67,000 KG"]
