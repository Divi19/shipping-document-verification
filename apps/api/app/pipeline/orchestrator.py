"""The orchestrator: runs the stages, keeps the case record, bounds the retries.

One email in, one :class:`CaseRecord` out. The orchestrator owns sequencing and
failure handling; the stages themselves stay small and testable.

Two rules it enforces:

* A case that cannot be decided is *recorded* as NEEDS_REVIEW immediately, with
  its reason and whatever evidence exists. It is not held back from the report
  until a human answers - the reviewer's decision updates the record later.
* Retries are bounded and only happen where another attempt can plausibly help:
  a second reader for a document that failed to parse. A missing attachment is
  never retried, because nothing about it will change.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from app.agents.email_classifier import EmailClassifier
from app.models.email.schemas import EmailAttachment, EmailCategory, ParsedEmail

from . import status
from .compare import compare_documents
from .documents import detect_role, is_readable
from .fields import extract_fields
from .models import CaseOutcome, CaseRecord, DocumentRead, DocumentRole, FieldName, FieldValue
from .readers import DocumentReader, ReaderError, default_readers, readers_for


class FieldResolver(Protocol):
    """Recovers fields deterministic extraction could not find.

    Implemented by the model-assisted resolver in ``app.ai``. It may only ever
    return values it can evidence from the document; the orchestrator records
    what it recovered so a reviewer can see that a model was involved.
    """

    def resolve(
        self, text: str, source: str, missing: Sequence[FieldName]
    ) -> dict[FieldName, FieldValue]:
        """Return the fields it could evidence, which may be none of them."""


STAGE_CLASSIFY = "classify"
STAGE_READ = "read_document"
STAGE_EXTRACT = "extract_fields"
STAGE_RESOLVE = "resolve_missing_fields"
STAGE_COMPARE = "compare"
STAGE_DECIDE = "decide"


class Pipeline:
    """Run the verification workflow for one email at a time."""

    def __init__(
        self,
        dataset_root: Path,
        classifier: EmailClassifier | None = None,
        readers: Sequence[DocumentReader] | None = None,
        max_attempts_per_document: int = 2,
        field_resolver: FieldResolver | None = None,
    ) -> None:
        self.dataset_root = Path(dataset_root)
        self.classifier = classifier or EmailClassifier()
        self.readers = tuple(readers) if readers is not None else default_readers()
        self.max_attempts_per_document = max_attempts_per_document
        self.field_resolver = field_resolver

    def run(self, email: ParsedEmail) -> CaseRecord:
        """Process one email and return its case record."""
        classified = self.classifier.classify(email)
        case = CaseRecord(
            email_id=email.email_id,
            category=classified.category,
            outcome=CaseOutcome.NOT_APPLICABLE,
            classification_reasoning=classified.reasoning,
        )
        case.record_attempt(
            STAGE_CLASSIFY,
            ok=True,
            detail=f"{classified.category.value} ({classified.decided_by.value}): "
            f"{classified.reasoning}",
        )

        if classified.category is not EmailCategory.BL_COMPARISON:
            return self._finish(case, email)

        for attachment in email.attachments:
            case.documents.append(self._read_document(case, attachment))

        si = case.document(DocumentRole.SHIPPING_INSTRUCTION)
        bl = case.document(DocumentRole.BILL_OF_LADING)
        if si is not None and bl is not None:
            si_fields = self._extract(case, si)
            bl_fields = self._extract(case, bl)
            case.comparisons = compare_documents(si_fields, bl_fields)
            case.record_attempt(
                STAGE_COMPARE,
                ok=True,
                detail=f"compared {len(case.comparisons)} fields",
            )

        return self._finish(case, email)

    def run_all(self, emails: Sequence[ParsedEmail]) -> list[CaseRecord]:
        """Process a batch of emails, in order."""
        return [self.run(email) for email in emails]

    # -- stages ---------------------------------------------------------

    def _read_document(self, case: CaseRecord, attachment: EmailAttachment) -> DocumentRead:
        """Read one attachment, trying at most ``max_attempts_per_document`` readers."""
        path = self.dataset_root / attachment.path
        candidates = readers_for(path, self.readers)[: self.max_attempts_per_document]

        if not path.exists():
            case.record_attempt(STAGE_READ, ok=False, detail=f"{attachment.filename}: not on disk")
            return DocumentRead(
                path=attachment.path,
                filename=attachment.filename,
                reader="none",
                readable=False,
                failure="file not found",
            )

        if not candidates:
            case.record_attempt(
                STAGE_READ, ok=False, detail=f"{attachment.filename}: unsupported type"
            )
            return DocumentRead(
                path=attachment.path,
                filename=attachment.filename,
                reader="none",
                readable=False,
                failure=f"no reader for {path.suffix or 'unknown type'}",
            )

        failure = "unknown"
        for reader in candidates:
            try:
                text = reader.read(path)
            except ReaderError as exc:
                failure = str(exc)
                case.record_attempt(
                    STAGE_READ, ok=False, detail=f"{attachment.filename} via {reader.name}: {exc}"
                )
                continue

            if not is_readable(text):
                # A scan or a truncated file: the reader "worked" but produced
                # nothing usable, which is an escalation, not an empty document.
                failure = "no usable text (scanned image or damaged file)"
                case.record_attempt(
                    STAGE_READ,
                    ok=False,
                    detail=f"{attachment.filename} via {reader.name}: {failure}",
                )
                continue

            role = detect_role(text)
            case.record_attempt(
                STAGE_READ,
                ok=True,
                detail=f"{attachment.filename} via {reader.name}: {role.value}",
            )
            return DocumentRead(
                path=attachment.path,
                filename=attachment.filename,
                reader=reader.name,
                readable=True,
                role=role,
                text=text,
            )

        return DocumentRead(
            path=attachment.path,
            filename=attachment.filename,
            reader=candidates[-1].name,
            readable=False,
            failure=failure,
        )

    def _extract(self, case: CaseRecord, document: DocumentRead) -> dict[FieldName, FieldValue]:
        fields = extract_fields(document.text, document.filename)
        found = sum(1 for value in fields.values() if value.is_present)
        case.record_attempt(
            STAGE_EXTRACT,
            ok=found == len(fields),
            detail=f"{document.filename}: {found}/{len(fields)} fields found",
        )

        missing = [field for field, value in fields.items() if not value.is_present]
        if missing and self.field_resolver is not None:
            fields = self._resolve_missing(case, document, fields, missing)

        return fields

    def _resolve_missing(
        self,
        case: CaseRecord,
        document: DocumentRead,
        fields: dict[FieldName, FieldValue],
        missing: Sequence[FieldName],
    ) -> dict[FieldName, FieldValue]:
        """Ask the model for fields no label matched, and record what it found.

        A document may word a field in a way the synonym table has never seen.
        The resolver only returns values it can evidence in the document, so
        anything it cannot support stays missing and the case still escalates.
        """
        assert self.field_resolver is not None
        recovered = self.field_resolver.resolve(document.text, document.filename, missing)
        for field, value in recovered.items():
            fields[field] = value

        case.record_attempt(
            STAGE_RESOLVE,
            ok=bool(recovered),
            detail=(
                f"{document.filename}: model recovered "
                f"{len(recovered)}/{len(missing)} missing fields "
                f"({', '.join(f.value for f in recovered) or 'none'})"
            ),
        )
        return fields

    def _finish(self, case: CaseRecord, email: ParsedEmail) -> CaseRecord:
        outcome, reason = status.decide(case.category, email.body, case.documents, case.comparisons)
        case.outcome = outcome
        case.review_reason = reason
        case.record_attempt(
            STAGE_DECIDE,
            ok=outcome is not CaseOutcome.NEEDS_REVIEW,
            detail=f"{outcome.value}" + (f" ({reason.value})" if reason else ""),
        )
        return case
