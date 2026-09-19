# Shipping Document Verification — Project Context

## Purpose of this document

This is the planning handoff for the Shipping Document Verification project. Read it together with `docs/Shipping Document Verification Use Case.pdf` and inspect the participant data under `local-data/sdoc-hackathon-bundle/` before proposing or implementing changes.

Do not implement application functionality until explicitly requested. The current objective is to establish a clear repository and architecture so multiple teammates or AI assistants can work without inventing conflicting assumptions.

## Business problem

A shipping operations team receives mixed messages in an inbox. Each email must first be classified. For document-comparison requests, the system must compare a Shipping Instruction (SI) with a draft Bill of Lading (BL) before the BL is finalized.

The SI is the source of truth. The objective is to detect real discrepancies without raising false alarms for harmless differences in labels or formatting. Missing, unreadable, incomplete, or uncertain inputs must be sent for human review rather than guessed.

## Required email categories

Every email must be classified into exactly one of:

- `BL_COMPARISON`
- `SI_REQUEST`
- `INVOICE_QUERY`
- `GENERAL`
- `SPAM`

Only actionable `BL_COMPARISON` emails proceed to SI/BL document comparison.

## Required comparison fields

Compare exactly these seven fields:

1. `shipper`
2. `consignee`
3. `notify_party`
4. `port_of_loading`
5. `port_of_discharge`
6. `container_count`
7. `gross_weight_kg`

The SI value is authoritative. A mismatch report must identify only the differing fields and retain the original SI and BL values as evidence.

## Required outcomes and submission contract

Every email ID must be included in the final output. The confirmed output shape is:

```json
{
  "category": "BL_COMPARISON",
  "status": "OK",
  "review_reason": null,
  "defect_fields": [],
  "has_defect": false
}
```

Allowed statuses:

- `OK`: the case completed without a confirmed defect.
- `MISMATCH`: comparison completed and at least one of the seven fields differs.
- `NEEDS_REVIEW`: the system cannot make a dependable comparison.

Allowed review reasons:

- `wrong_doc_type`
- `missing_attachment`
- `unreadable`
- `missing_value`

A blank or unreadable value is uncertainty, not a mismatch.

## Confirmed input data

The static participant bundle and the participant-visible data in the Docker bundle are byte-for-byte identical.

Dataset characteristics:

- 520 individual email JSON records.
- Each record contains only `email_id`, `from`, `subject`, `body`, and `attachments`.
- 250 attachment files.
- 192 TXT files.
- 28 PDF files.
- 22 XLSX files.
- 8 DOCX files.
- 394 emails have no attachments.
- 124 emails have two attachments.
- 2 emails have one attachment.
- 195 email bodies contain forwarded-style text.

There are no structured thread IDs, reply relationships, or separate conversation objects. Forwarded history, signatures, and warning banners appear as text inside the single `body` field. A dedicated Email Thread Context Agent is therefore not part of the architecture.

The classification logic must tolerate forwarded text and boilerplate without treating them as separately retrievable conversations.

Not every email with no attachments is necessarily an error. Some messages ask someone to send a draft BL and are not yet actionable comparisons. The workflow must distinguish that situation from an explicit comparison request whose required attachment is missing.

The dataset contains explicit reliability edge cases involving wrong document types, missing attachments, unreadable or corrupt files, image-only scans, and missing required values.

## Supplied folders

### `local-data/sdoc-hackathon-bundle/`

The participant/static bundle:

- Read email JSON and attachment files directly.
- Includes `loader.py` and `sample_submission.json`.
- Does not expose the answer key.
- Suitable for local development.

### `local-data/sdoc-hackathon-docker/`

The organizer/testing distribution:

- Serves the same participant-visible data over HTTP.
- Exposes `/emails`, `/emails/{email_id}`, `/attachments/{path}`, `/sample_submission`, and `/submit`.
- Includes scoring logic and `ground_truth.json`.
- The organizer README explicitly says this package should not normally be given to participants.

Potential issue requiring verification: the email-by-ID route constructs a path from the requested ID without the explicit path-confinement check used by the attachment route, while Docker Compose mounts the complete organizer data directory. This has not been confirmed as an exploitable vulnerability. Before relying on this server outside isolated local evaluation, verify framework path normalization and restrict email IDs to the expected format or confine the resolved path to the inbox directory.

The entire `local-data/` directory is Git-ignored. In particular, never commit, publish, or build the solution around the Docker bundle's ground-truth answer key.

## Agreed technical direction

The planned stack is:

- **Next.js** for the user interface.
- **FastAPI** for document processing, AI integration, workflow execution, and API endpoints.
- **Supabase** for persistence, review state, audit history, optional authentication, and optional uploaded-file storage.

Responsibilities must remain clear:

```text
Next.js = presentation and human-review interface
FastAPI = processing, AI, validation, and comparison
Supabase = persistent state and audit history
```

The core processing pipeline should remain runnable and testable against local files without requiring Supabase. Supabase supports the product workflow; it must not become a hard dependency of basic extraction and comparison tests.

## AI strategy

The project encourages AI, but a large autonomous multi-agent system is unnecessary and likely counterproductive under the available budget.

Use AI where unstructured interpretation is required:

1. Email classification from noisy subjects and bodies.
2. Semantic field extraction from varied text, tables, layouts, and labels.
3. OCR or vision assistance for scanned/image-only documents.
4. Optional semantic verification when deterministic evidence checks cannot decide.

Use deterministic Python for:

- Workflow routing.
- File-type detection and attachment validation.
- Reading supported formats through established libraries.
- Approved synonym mapping.
- Whitespace, capitalization, numeric, and unit normalization.
- Exact SI-to-BL comparison.
- Confidence thresholds and status rules.
- Schema validation, JSON generation, retries, and audit records.

A local/open-source model and local OCR may be used to avoid paid APIs. The architecture should not require paid services.

The boxes previously described as agents are logical responsibilities. They may be implemented as ordinary Python modules or functions. Actual tool-calling autonomous agents are not required.

## Current logical architecture

1. **Shared input** receives individual JSON email records and referenced attachments.
2. **Orchestrator** creates and tracks a case and calls each pipeline stage.
3. **Shared case record** stores input data, evidence, confidence, decisions, and processing history.
4. **Email classification** assigns one of the five required categories.
5. Non-comparison categories are recorded and completed without document comparison.
6. **Attachment validation** determines whether the required SI and BL are present, readable, correctly identified, and appropriate for the request.
7. **Controlled reading fallback** tries plain text, structured PDF/Word/Excel parsing, then OCR or vision where appropriate.
8. **Document extraction** extracts the seven fields from SI and BL and records original values, source location/text, and confidence.
9. **Evidence and consistency verification** checks that extracted values are supported, SI and BL are not reversed, documents correspond to the intended shipment, and OCR did not introduce obvious contradictions.
10. **Normalization** applies approved, traceable transformations while preserving original values.
11. **Comparison** compares BL values against the SI source of truth.
12. **Quality assurance gate** ensures all required fields and evidence are accounted for and prevents unresolved uncertainty from being released as a confident result.
13. **Reporting** creates the human-readable result and required submission JSON.
14. **Exception triage** sends recoverable failures through a bounded retry path and unresolved cases to human review.
15. **Human review** confirms, corrects, requests missing information, or marks the case unable to verify.
16. Human corrections and failures feed an offline, controlled improvement process; they must not automatically rewrite production rules.

## Workflow outcomes

### Match

```text
Confirmed match -> QA -> report "No mismatch detected" -> close case
```

### Confirmed mismatch

```text
Confirmed mismatch -> QA -> discrepancy report -> corrective-action workflow
-> notify/assign -> receive corrected BL -> re-run verification -> close
```

A mismatch is a successful verification result but not necessarily a completed operational case. It normally requires correction and re-verification. An authorized human override may accept a discrepancy if business policy permits it.

### Uncertain or failed case

```text
Uncertain/failure -> exception triage -> bounded retry or human review
-> confirmed/corrected outcome -> appropriate match or mismatch route
```

## Sequential versus parallel processing

Within one email case, the workflow should remain predominantly sequential because later stages depend on validated outputs from earlier stages. The minor independent operations do not justify designing a complex parallel-agent architecture.

The meaningful concurrency strategy is to process multiple independent email cases simultaneously, with bounded worker concurrency. This is operational scaling, not a parallel agent architecture.

## Human review requirements

A human-review package should include:

- Original email record.
- Relevant SI and BL files.
- Affected fields.
- Extracted values and confidence.
- Source evidence and location.
- Reason for escalation.
- Processing attempts and failures.

The reviewer must be able to confirm or correct the result, request information, or mark the case unable to verify. The decision and audit trail must be preserved.

## Quality and evaluation priorities

Success means:

- Correctly classifying emails.
- Not missing genuine comparison requests.
- Correctly extracting the seven required fields.
- Detecting genuine discrepancies.
- Avoiding false mismatches caused by labels or formatting.
- Distinguishing missing/unreadable values from defects.
- Escalating uncertain cases with useful evidence.
- Making processing failures visible and retryable.
- Producing one correctly shaped result for every email ID.

The supplied scoreboard is useful but does not fully evaluate human-review quality, evidence clarity, or operational usability. Those require separate testing.

The implemented final score is weighted as 50% end-to-end exact defect detection, 30% email-classification macro-F1, and 20% email-level defect F1. Field-level F1 is reported separately as a diagnostic and is not directly included in the weighted total. Review handling is also reported separately as a reliability measure.

## Proposed repository boundaries

When implementation is explicitly approved, the intended shape is:

```text
shipping-document-verification/
├── apps/
│   ├── web/                  # Next.js
│   └── api/                  # FastAPI
│       ├── app/api/
│       ├── app/pipeline/
│       ├── app/document_readers/
│       ├── app/ai/
│       ├── app/models/
│       └── app/services/
├── packages/
│   └── contracts/            # Shared API contracts/types
├── supabase/
│   ├── migrations/
│   └── seed/
├── docs/
├── local-data/               # Local only; never committed
├── .env.example
└── README.md
```

Pydantic API schemas should be the source of truth for backend contracts. Frontend types should be generated or kept synchronized rather than independently invented. Database changes should be represented by migrations.

## Immediate next step

The repository currently contains only planning and handoff materials. The next session should first read this document, inspect the use-case PDF and participant bundle, and confirm the desired scope before creating the barebones Next.js, FastAPI, and Supabase structure.

Do not implement classification, extraction, OCR, comparison, or AI integrations until explicitly requested.
