"""Evidence and consistency verification services."""

from app.verification.text import TextEvidenceVerifier, verify_text_candidates

__all__ = ["TextEvidenceVerifier", "verify_text_candidates"]
