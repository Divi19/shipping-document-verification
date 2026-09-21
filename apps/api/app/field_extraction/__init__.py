"""Required-field extraction services."""

from app.field_extraction.semantic import (
    GeminiSemanticProvider,
    SemanticCandidateOutput,
    SemanticExtractionOutput,
    SemanticFieldFallback,
    gemini_semantic_fallback_from_env,
)
from app.field_extraction.text import TextFieldExtractor, extract_text_fields

__all__ = [
    "GeminiSemanticProvider",
    "SemanticCandidateOutput",
    "SemanticExtractionOutput",
    "SemanticFieldFallback",
    "TextFieldExtractor",
    "extract_text_fields",
    "gemini_semantic_fallback_from_env",
]
