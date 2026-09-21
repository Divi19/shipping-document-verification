"""Where case records live between processing and review.

A case that needs a human is written here the moment it is decided, with its
reason, evidence and review ticket - not held back until someone answers. The
reviewer's decision (``app.pipeline.review.apply_decision``) updates the same
record.

The in-memory implementation keeps tests isolated. The JSON implementation is
used by the deployed prototype so a process restart does not immediately erase
the review queue and its decisions.
"""

import json
from pathlib import Path
from threading import RLock
from typing import Protocol

from .models import CaseOutcome, CaseRecord


class CaseStore(Protocol):
    """Persistence for case records."""

    def save(self, case: CaseRecord) -> CaseRecord:
        """Insert or replace a case."""

    def get(self, email_id: str) -> CaseRecord | None:
        """Return a case, or None when it has not been processed."""

    def list(self, outcome: CaseOutcome | None = None) -> list[CaseRecord]:
        """Return cases, optionally filtered by the final outcome."""


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
            cases = [case for case in cases if case.final_outcome is outcome]
        return cases

    def clear(self) -> None:
        self._cases.clear()


class JsonCaseStore(InMemoryCaseStore):
    """Small atomic JSON store for a single-process prototype deployment."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = Path(path)
        self._lock = RLock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self._cases = {
                email_id: CaseRecord.model_validate(case) for email_id, case in payload.items()
            }
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Cannot load case store {self.path}: {exc}") from exc

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        payload = {email_id: case.model_dump(mode="json") for email_id, case in self._cases.items()}
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def save(self, case: CaseRecord) -> CaseRecord:
        with self._lock:
            saved = super().save(case)
            self._flush()
            return saved

    def get(self, email_id: str) -> CaseRecord | None:
        with self._lock:
            return super().get(email_id)

    def list(self, outcome: CaseOutcome | None = None) -> list[CaseRecord]:
        with self._lock:
            return super().list(outcome)

    def clear(self) -> None:
        with self._lock:
            super().clear()
            self._flush()
