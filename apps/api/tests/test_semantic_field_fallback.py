"""Tests for the optional schema-constrained semantic extraction fallback."""

from dataclasses import dataclass
from typing import cast

import pytest
from google import genai
from google.genai import types

from app.field_extraction import (
    GeminiSemanticProvider,
    SemanticCandidateOutput,
    SemanticExtractionOutput,
    SemanticFieldFallback,
    TextFieldExtractor,
    gemini_semantic_fallback_from_env,
)
from app.ingestion.extractors import TextExtractor
from app.models.extraction import ComparisonField, DocumentRole, ExtractionMethod
from app.models.verification import VerificationOutcome
from app.verification import TextEvidenceVerifier


class _FakeProvider:
    def __init__(
        self,
        output: SemanticExtractionOutput | None = None,
        error: Exception | None = None,
    ) -> None:
        self.output = output or SemanticExtractionOutput()
        self.error = error
        self.calls: list[frozenset[ComparisonField]] = []
        self.closed = False

    def extract(
        self,
        text: str,
        document_role: DocumentRole,
        requested_fields: frozenset[ComparisonField],
    ) -> SemanticExtractionOutput:
        del text, document_role
        self.calls.append(requested_fields)
        if self.error is not None:
            raise self.error
        return self.output

    def close(self) -> None:
        self.closed = True


@dataclass
class _FakeResponse:
    parsed: object | None
    text: str | None


class _FakeModels:
    def __init__(self) -> None:
        self.request: dict[str, object] = {}

    def generate_content(self, **kwargs: object) -> _FakeResponse:
        self.request = kwargs
        return _FakeResponse(
            parsed=None,
            text=(
                '{"candidates":[{"field":"port_of_loading",'
                '"raw_label":"Place of Receipt / Load","raw_value":"Singapore",'
                '"evidence_quote":"Place of Receipt / Load: Singapore",'
                '"confidence":0.91}]}'
            ),
        )


class _FakeClient:
    def __init__(self) -> None:
        self.models = _FakeModels()

    def close(self) -> None:
        pass


def _proposal(
    field: ComparisonField,
    raw_label: str,
    raw_value: str,
    evidence_quote: str,
) -> SemanticCandidateOutput:
    return SemanticCandidateOutput(
        field=field,
        raw_label=raw_label,
        raw_value=raw_value,
        evidence_quote=evidence_quote,
        confidence=0.91,
    )


def test_semantic_fallback_adds_only_exact_evidence_backed_missing_field() -> None:
    text = "Shipper: Example Trading Ltd\nPlace of Receipt / Load: Singapore\n"
    provider = _FakeProvider(
        SemanticExtractionOutput(
            candidates=[
                _proposal(
                    ComparisonField.PORT_OF_LOADING,
                    "Place of Receipt / Load",
                    "Singapore",
                    "Place of Receipt / Load: Singapore",
                )
            ]
        )
    )
    document = TextExtractor().extract_bytes(text.encode(), "sample_si.txt")
    extractor = TextFieldExtractor(SemanticFieldFallback(provider))

    result = extractor.extract(document, DocumentRole.SHIPPING_INSTRUCTION)

    loading = result.candidates_for(ComparisonField.PORT_OF_LOADING)[0]
    assert loading.extraction_method == ExtractionMethod.SEMANTIC_MODEL
    assert loading.evidence[0].source_text == "Place of Receipt / Load: Singapore"
    assert provider.calls == [frozenset(set(ComparisonField) - {ComparisonField.SHIPPER})]

    verified = TextEvidenceVerifier().verify(document, result)
    verified_loading = next(
        item for item in verified.fields if item.field == ComparisonField.PORT_OF_LOADING
    )
    assert verified_loading.verified_field is not None
    assert verified_loading.verified_field.selected.outcome == VerificationOutcome.VERIFIED


def test_semantic_fallback_cannot_overwrite_deterministic_candidate() -> None:
    text = "Shipper: Deterministic Trading Ltd\n"
    provider = _FakeProvider(
        SemanticExtractionOutput(
            candidates=[
                _proposal(
                    ComparisonField.SHIPPER,
                    "Shipper",
                    "Deterministic Trading Ltd",
                    "Shipper: Deterministic Trading Ltd",
                )
            ]
        )
    )
    document = TextExtractor().extract_bytes(text.encode(), "sample_si.txt")

    result = TextFieldExtractor(SemanticFieldFallback(provider)).extract(
        document, DocumentRole.SHIPPING_INSTRUCTION
    )

    shippers = result.candidates_for(ComparisonField.SHIPPER)
    assert len(shippers) == 1
    assert shippers[0].extraction_method == ExtractionMethod.LABEL_MAP
    assert "field was not requested" in result.diagnostics[-1]


@pytest.mark.parametrize(
    ("raw_value", "evidence_quote", "reason"),
    [
        ("Singapore", "Place of Receipt: Jakarta", "raw value"),
        ("Singapore", "Invented quote", "not present"),
    ],
)
def test_semantic_fallback_rejects_unsupported_proposals(
    raw_value: str, evidence_quote: str, reason: str
) -> None:
    text = "Place of Receipt: Jakarta\n"
    provider = _FakeProvider(
        SemanticExtractionOutput(
            candidates=[
                _proposal(
                    ComparisonField.PORT_OF_LOADING,
                    "Place of Receipt",
                    raw_value,
                    evidence_quote,
                )
            ]
        )
    )
    document = TextExtractor().extract_bytes(text.encode(), "sample_si.txt")

    result = TextFieldExtractor(SemanticFieldFallback(provider)).extract(
        document, DocumentRole.SHIPPING_INSTRUCTION
    )

    assert result.candidates_for(ComparisonField.PORT_OF_LOADING) == []
    assert reason in result.diagnostics[-1]


def test_complete_deterministic_extraction_does_not_call_provider() -> None:
    text = "\n".join(
        [
            "Shipper: Example Trading Ltd",
            "Consignee: Example Imports LLC",
            "Notify Party: Example Logistics LLC",
            "Port of Loading: Singapore",
            "Port of Discharge: Rotterdam",
            "Container Count: 3",
            "Gross Weight: 66,000 KG",
        ]
    )
    provider = _FakeProvider()
    document = TextExtractor().extract_bytes(text.encode(), "sample_si.txt")

    result = TextFieldExtractor(SemanticFieldFallback(provider)).extract(
        document, DocumentRole.SHIPPING_INSTRUCTION
    )

    assert len(result.candidates) == 7
    assert provider.calls == []


def test_provider_failure_leaves_deterministic_result_usable() -> None:
    provider = _FakeProvider(error=RuntimeError("temporary provider outage"))
    document = TextExtractor().extract_bytes(b"Shipper: Example Trading Ltd", "sample_si.txt")

    result = TextFieldExtractor(SemanticFieldFallback(provider)).extract(
        document, DocumentRole.SHIPPING_INSTRUCTION
    )

    assert len(result.candidates_for(ComparisonField.SHIPPER)) == 1
    assert result.diagnostics[-1] == "Semantic fallback failed: RuntimeError."


def test_oversized_document_does_not_call_provider() -> None:
    provider = _FakeProvider()
    document = TextExtractor().extract_bytes(b"unmapped text", "sample_si.txt")
    fallback = SemanticFieldFallback(provider, max_document_chars=5)

    result = TextFieldExtractor(fallback).extract(document, DocumentRole.SHIPPING_INSTRUCTION)

    assert provider.calls == []
    assert result.diagnostics[-1] == (
        "Semantic fallback skipped because the document exceeds the input limit."
    )


def test_gemini_provider_uses_structured_output_and_requested_fields() -> None:
    fake_client = _FakeClient()
    provider = GeminiSemanticProvider(
        cast(genai.Client, fake_client),
        model="test-gemini-model",
    )

    result = provider.extract(
        "Place of Receipt / Load: Singapore",
        DocumentRole.SHIPPING_INSTRUCTION,
        frozenset({ComparisonField.PORT_OF_LOADING}),
    )

    assert result.candidates[0].field == ComparisonField.PORT_OF_LOADING
    assert fake_client.models.request["model"] == "test-gemini-model"
    assert "port_of_loading" in str(fake_client.models.request["contents"])
    config = fake_client.models.request["config"]
    assert isinstance(config, types.GenerateContentConfig)
    assert config.response_mime_type == "application/json"
    assert config.temperature == 0


def test_environment_factory_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_ENABLE_FALLBACK", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "unused-key")

    assert gemini_semantic_fallback_from_env() is None


def test_fallback_close_releases_provider() -> None:
    provider = _FakeProvider()

    SemanticFieldFallback(provider).close()

    assert provider.closed is True
