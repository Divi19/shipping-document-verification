"""The model client, behind a protocol so nothing else depends on a vendor.

Two rules hold everywhere AI is used in this pipeline:

* the model is asked only where interpretation is genuinely needed - wording a
  rule cannot settle, or a field whose label is absent;
* whatever it answers is **checked** before it is believed. A model that says
  it is confident has proved nothing.

Without an API key the client is simply absent and every caller falls back to
its deterministic behaviour, so the whole system still runs offline.
"""

import json
import logging
import os
import re
from typing import Any, Protocol

logger = logging.getLogger(__name__)

API_KEY_ENV = "GEMINI_API_KEY"
MODEL_ENV = "GEMINI_MODEL"
DEFAULT_MODEL = "gemini-2.0-flash"

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class LlmClient(Protocol):
    """Anything that can answer a prompt with a JSON object."""

    name: str

    def generate_json(self, prompt: str) -> dict[str, Any] | None:
        """Return the parsed JSON object, or None if nothing usable came back."""


def parse_json_object(text: str) -> dict[str, Any] | None:
    """Pull a JSON object out of a model response.

    Models wrap JSON in prose or code fences often enough that this has to be
    tolerant - but it never guesses: anything unparseable returns None and the
    caller keeps its deterministic answer.
    """
    match = _JSON_BLOCK.search(text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class GeminiClient:
    """Gemini-backed client. Imported lazily so the SDK stays optional."""

    name = "gemini"

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self.model_name = model or os.environ.get(MODEL_ENV, DEFAULT_MODEL)
        self._api_key = api_key
        self._model: Any = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            import google.generativeai as genai

            genai.configure(api_key=self._api_key)  # type: ignore[attr-defined]
            self._model = genai.GenerativeModel(self.model_name)  # type: ignore[attr-defined]
        return self._model

    def generate_json(self, prompt: str) -> dict[str, Any] | None:
        try:
            response = self._ensure_model().generate_content(prompt)
            return parse_json_object(response.text or "")
        except Exception as exc:  # noqa: BLE001 - the model is never load-bearing
            # A model failure must never fail a case: the caller keeps its
            # deterministic result and, where that is nothing, escalates.
            logger.warning("Model call failed (%s): %s", self.model_name, exc)
            return None


def build_client(api_key: str | None = None, model: str | None = None) -> LlmClient | None:
    """Return a configured client, or None when no key is available."""
    key = api_key or os.environ.get(API_KEY_ENV)
    if not key:
        logger.info("%s is not set; running with deterministic logic only", API_KEY_ENV)
        return None
    return GeminiClient(key, model)
