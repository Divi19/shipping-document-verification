"""Where case records live between processing and review.

A case that needs a human is written here the moment it is decided, with its
reason, evidence and review ticket - not held back until someone answers. The
reviewer's decision (``app.pipeline.review.apply_decision``) updates the same
record.

The in-memory implementation is enough for the prototype and for tests. A
Supabase-backed store implements the same protocol; nothing else changes.
"""

from typing import Protocol

from .models import CaseOutcome, CaseRecord


class CaseStore(Protocol):
    """Persistence for case records."""

    def save(self, case: CaseRecord) -> CaseRecord:
        """Insert or replace a case."""

    def get(self, email_id: str) -> CaseRecord | None:
        """Return a case, or None when it has not been processed."""

    def list(self, outcome: CaseOutcome | None = None) -> list[CaseRecord]:
        """Return cases, optionally filtered by outcome."""


class InMemoryCaseStore:
    """Dictionary-backed store, ordered by insertion."""

    def __init__(self) -> None:
        self._cases: dict[str, CaseRecord] = {}

    def save(self, case: CaseRecord) -> CaseRecord:
        self._cases[case.email_id] = case
        return case

    def get(self, email_id: str) -> CaseRecord | None:
        return self._cases.get(email_id)

    def list(self, outcome: CaseOutcome | None = None) -> list[CaseRecord]:
        cases = list(self._cases.values())
        if outcome is not None:
            cases = [case for case in cases if case.outcome is outcome]
        return cases

    def clear(self) -> None:
        self._cases.clear()
