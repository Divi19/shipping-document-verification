"""Tests for the supported Google Gen AI PDF vision adapter."""

from dataclasses import dataclass
from typing import cast

from google import genai
from google.genai import types

from app.ingestion.extractors.pdf_extractor import PDFExtractor


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
                '{"text":"Shipper: Example Trading Ltd",'
                '"tables":[{"headers":["Field","Value"],'
                '"rows":[["Shipper","Example Trading Ltd"]]}]}'
            ),
        )


class _FakeClient:
    def __init__(self) -> None:
        self.models = _FakeModels()
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_vision_fallback_stays_disabled_without_credentials() -> None:
    extractor = PDFExtractor(enable_vision_fallback=True)

    assert extractor.enable_vision_fallback is False


def test_vision_page_uses_schema_constrained_modern_sdk_request() -> None:
    fake_client = _FakeClient()
    extractor = PDFExtractor(
        gemini_client=cast(genai.Client, fake_client),
        gemini_model="test-gemini-model",
    )

    result = extractor._process_page_with_vision(b"png bytes", page_number=2)

    assert result["text"] == "Shipper: Example Trading Ltd"
    assert result["tables"][0].headers == ["Field", "Value"]
    assert result["tables"][0].page_number == 2
    assert fake_client.models.request["model"] == "test-gemini-model"
    contents = fake_client.models.request["contents"]
    assert isinstance(contents, list)
    assert isinstance(contents[1], types.Part)
    config = fake_client.models.request["config"]
    assert isinstance(config, types.GenerateContentConfig)
    assert config.response_mime_type == "application/json"
    assert config.temperature == 0


def test_injected_client_is_not_closed_by_extractor() -> None:
    fake_client = _FakeClient()
    extractor = PDFExtractor(gemini_client=cast(genai.Client, fake_client))

    extractor.close()

    assert fake_client.closed is False
