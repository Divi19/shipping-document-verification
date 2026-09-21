# AI Project Handoff

Last updated: 2026-09-21  
Current integration branch at handoff: `integrate_review`

## Read this first

This is the current technical handoff for the Shipping Document Verification project. It is intended to let another coding assistant continue without reconstructing the project from chat history.

Treat the running code, tests, and this document as the current source of truth. Some older planning notes in `docs/PROJECT.md`, `docs/project-context.md`, and the lower historical sections of `README.md` describe an earlier scaffold and are now stale. Do not delete or rewrite those files without being asked. In particular, `docs/PROJECT.md` is currently an untracked, user-owned file.

Before changing anything:

1. Check the current branch and working tree with `git status --short --branch`.
2. Preserve unrelated and untracked user files.
3. Read the nearest `AGENTS.md` for any directory being changed.
4. Run the relevant focused tests, then `pnpm verify` for integration work.
5. Do not push, rewrite history, or merge into another branch unless explicitly requested.

## Project objective

The product verifies draft Bills of Lading (BLs) against Shipping Instructions (SIs). It processes synthetic organizer-provided emails and attachments, identifies actionable SI/BL comparison cases, extracts seven required fields, compares the BL against the SI as the source of truth, and produces a report or a human-review package.

The seven comparison fields are fixed:

- `shipper`
- `consignee`
- `notify_party`
- `port_of_loading`
- `port_of_discharge`
- `container_count`
- `gross_weight_kg`

The system must distinguish a confirmed mismatch from missing, uncertain, unreadable, or invalid evidence. The latter conditions require review; they must not be reported as ordinary mismatches.

## Current end-to-end architecture

```text
Organizer email JSON and attachments
                 |
                 v
1. Rules-first email classification
   Gemini fallback only when rules are inconclusive
                 |
                 v
2. Attachment validation and SI/BL role assignment
                 |
                 v
3-4. Structured document ingestion
     native readers -> optional Docling -> Tesseract OCR
     -> Gemini vision only for difficult unresolved pages
                 |
                 v
5. Field candidate extraction
   deterministic labels/patterns + evidence-gated Gemini fallback
                 |
                 v
6. Evidence verification
   values must be supported by document evidence
                 |
                 v
7. Typed deterministic normalization
                 |
                 v
8. Deterministic SI-to-BL comparison
                 |
                 v
   Deterministic quality-assurance gate
          |                         |
          | complete                | uncertain / QA failure
          v                         v
10. Reporting              9. Exception triage
                           -> controlled retry or human review
                           -> reviewer resolution
                                    |
                                    v
                              updated final report
```

A confirmed mismatch with complete evidence and a passing QA gate goes directly to reporting. It does not require human review. Review is for missing fields or attachments, unreadable inputs, uncertain evidence, invalid document roles, and failed QA controls.

## Important design decisions

### Structured ingestion, not Markdown as the data contract

Markdown remains useful as a compatibility and display representation, especially for tables. It is not the authoritative internal format because flattening directly to Markdown loses page, paragraph, table-cell, image, bounding-box, and extraction-method evidence. The pipeline keeps structured ingestion data and evidence locators, then derives display text where required.

### Candidates before trusted values

Box 5 emits field candidates rather than immediately trusted values. A candidate records the field, raw label, raw value, evidence references, extraction method, and confidence. Multiple contradictory candidates must remain visible instead of being silently collapsed.

Boxes 6 and 7 verify evidence and produce typed normalized values. The comparison layer consumes only verified normalized values.

### Party comparison

Party fields compare the primary legal entity identity, not the postal address. For example, formatting differences in `CO., LTD` versus `CO LTD` are equivalent, but meaningful entity words and legal suffixes are not discarded.

The complete original party block, addresses, qualifiers, and secondary entities remain in the evidence. Address or secondary-entity conflicts may be warnings, but they are not one of the seven comparison defects. This prevents routine address formatting from creating false mismatches.

### Deterministic final decisions

Normalization, comparison, QA, triage policy, and report structure are deterministic. AI may propose semantic candidates or classifications, but it does not get to invent unsupported values or make the final comparison decision.

### Levenshtein matching

Levenshtein/fuzzy matching was deliberately deferred until after the core workflow. Do not add it casually. If implemented later, benchmark it per field and use conservative thresholds in candidate-label mapping or Box 8 comparison tolerance. It should not silently mutate normalized values, and evidence/raw values must remain visible.

## Where AI is used

Gemini is a meaningful fallback rather than the default for clean documents:

1. Email classification when deterministic rules cannot classify confidently.
2. Recovery of unresolved fields after deterministic extraction.
3. Semantic extraction in the single-document diagnostic workbench.
4. Vision reading for difficult PDF pages after local/native extraction is insufficient.

Semantic answers are evidence-gated: the proposed value and quoted evidence must genuinely occur in the source. Clean cases can complete without an AI call. This is intentional: AI handles semantic ambiguity, while deterministic logic protects auditability and repeatability.

Current Gemini settings:

```env
GEMINI_API_KEY=your-key
GEMINI_ENABLE_FALLBACK=true
GEMINI_MODEL=gemini-2.5-flash-lite
```

`gemini-2.5-flash-lite` replaced an obsolete internal `gemini-2.0-flash` default. The app should degrade to local/deterministic behavior when Gemini is disabled or unavailable, although difficult cases may then require review.

## Ingestion and extraction behavior

The document ingestion boundary was stabilized so callers receive structured document data rather than relying on a misleading declared type. The orchestration layer uses the real ingestion readers, including native PDF extraction and OCR, rather than a separate mock-only path.

The fallback order is broadly:

1. Native document/PDF text and structure.
2. Docling when installed and compatible.
3. Render image-only PDF pages.
4. Tesseract OCR, retaining confidence and location evidence.
5. Gemini vision fallback when enabled and local extraction is insufficient.
6. Route unresolved content to review.

Tesseract succeeding does not guarantee all seven fields will be recovered. OCR can produce text with low confidence or lose layout semantics, so a scanned case can correctly show a Tesseract extraction method while still requiring semantic fallback or review.

## Comparison, QA, reporting, and review

The comparison layer treats the SI as the source of truth and produces a result for every required field. Outcomes preserve both SI and BL values, evidence, match state, and confidence.

The QA gate checks that:

- all seven fields were considered;
- every accepted value has evidence;
- confidence meets the required threshold;
- mismatches show both SI and BL values;
- no unresolved errors remain; and
- the output follows the required structure.

Reporting produces a human-readable result, structured JSON, an evidence summary, and the final processing status.

Exception triage chooses between a controlled retry and human review. Human-review actions are:

- confirm the automated result;
- correct one or more values;
- request more information; or
- mark the case unable to verify.

Reviewer corrections pass through the same normalization and comparison rules as automated values. The original automated result remains immutable and visible beside the human resolution; the final outcome is derived rather than rewriting history.

Review state is stored by a JSON case store using atomic file replacement. Configure it with:

```env
SDOC_CASE_STORE_PATH=.cache/sdoc-cases.json
```

The Docker/Render deployment uses `/tmp/sdoc-cases.json`. This survives an API process restart inside the same container but not a Render redeploy or service replacement. A durable database, such as Supabase, is a future production improvement. Supabase is not currently used and can be omitted from the prototype configuration.

## Data provenance and safety

The active demo corpus is organizer-provided synthetic data, not fabricated by this project. The deployment-safe subset is tracked at:

```text
local-data/sdoc-hackathon-bundle/inbox/        520 email JSON files
local-data/sdoc-hackathon-bundle/attachments/ 250 attachment files
```

Only the participant-safe `inbox` and `attachments` folders are included in the backend Docker image.

The organizer Docker download at the following local path includes an answer key:

```text
/Users/divieleischranjan/Downloads/sdoc-hackathon-docker (1)/data_v2/ground_truth.json
```

Do not copy, commit, bundle, or deploy that ground-truth file. It may be used only for offline accuracy evaluation when the complete organizer package is available. The live product currently reads the bundled files directly; it does not depend on the organizer Docker API.

Runtime cache files and generated case-store data are not source data and should remain ignored rather than committed.

## User experience

The primary page is ordered by product importance:

1. Full email verification
   - select a bundled email case;
   - run the SI/BL workflow;
   - inspect all seven comparisons;
   - inspect the QA gate; and
   - view the final report or review requirement.
2. Extraction diagnostics
   - inspect one document;
   - see its reader/OCR method;
   - inspect candidates and evidence verification; and
   - see normalized field values.

The review page at `/review` provides a queue, document/evidence context, and reviewer actions. The pipeline stage strip includes Box 9 triage.

The full-inbox action processes all 520 cases synchronously and therefore requires confirmation. It can take several minutes and may consume Gemini quota if fallback is enabled.

## Useful known cases

Use these cases for targeted manual verification:

| Case | Expected behavior |
| --- | --- |
| `email_004` | Confirmed mismatch in `consignee` and `notify_party`; QA passes; no human review. |
| `email_059` | Missing BL gross weight initially enters review. Correct BL gross weight to `131,322 KG`; final result becomes verified with seven comparisons and passing QA, while the automated result remains `needs_review`. |
| `email_507` | Missing attachment enters review. Requesting information changes the review state to awaiting information. |
| `email_511` | Corrupt/unreadable BL enters unreadable-document review. |
| `email_512` | Scanned/difficult PDF exercises Tesseract and fallback diagnostics; unresolved fields may require review. |

Useful single-document diagnostic samples:

- `email_059_SI.pdf` for native PDF extraction;
- `email_001_SI.txt` for plain-text extraction;
- `email_512_SI.pdf` for scanned PDF/OCR behavior; and
- `email_511_BL.pdf` for unreadable/corrupt input handling.

## Source-code map

### Backend

| Area | Path |
| --- | --- |
| FastAPI entry point | `apps/api/app/main.py` |
| Dependency composition and AI adapters | `apps/api/app/composition.py` |
| End-to-end orchestration | `apps/api/app/pipeline/orchestrator.py` |
| Pipeline domain models | `apps/api/app/pipeline/models.py` |
| Status derivation | `apps/api/app/pipeline/status.py` |
| Ingestion-backed readers | `apps/api/app/pipeline/readers.py` |
| Boxes 5-7 bridge | `apps/api/app/pipeline/extraction_adapter.py` |
| Deterministic comparison | `apps/api/app/pipeline/compare.py` |
| Exception triage and human review | `apps/api/app/pipeline/review.py` |
| Final reporting | `apps/api/app/pipeline/reporting.py` |
| JSON case persistence | `apps/api/app/pipeline/store.py` |
| Case workflow API | `apps/api/app/api/cases.py` |
| Review API | `apps/api/app/api/review.py` |

### Frontend and contracts

| Area | Path |
| --- | --- |
| Document diagnostics workbench | `apps/web/app/pipeline-workbench.tsx` |
| Full case workflow | `apps/web/app/case-workbench.tsx` |
| Human-review UI | `apps/web/app/review/` |
| Next.js backend relays | `apps/web/app/api/` |
| Generated TypeScript API contract | `packages/contracts/src/generated/api.ts` |

The generated API contract is intentionally committed because Vercel builds the frontend independently and does not run the Python contract generator.

## Local setup and testing

Install dependencies from the repository root:

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm install:api
pnpm contracts:generate
```

Run locally in two terminals:

```bash
export SDOC_CASE_STORE_PATH=.cache/sdoc-cases.json
pnpm dev:api
```

```bash
pnpm dev:web
```

Run the full verification suite:

```bash
UV_CACHE_DIR=/private/tmp/sdoc-uv-cache pnpm verify
```

Useful pipeline commands:

```bash
pnpm pipeline:run -- --text-only
pnpm pipeline:run
pnpm pipeline:run -- --no-ai
```

At the last full integration check, all of the following passed:

- 290 backend Pytest tests;
- 7 frontend tests;
- 1 contracts test;
- Prettier;
- Ruff format and lint checks;
- ESLint;
- mypy;
- TypeScript checking;
- the Next.js production build;
- the backend Docker build;
- a browser walkthrough of the main and review workflows; and
- a container smoke test that resolved `email_059` from pending review to a verified seven-field result.

The JSON review state was also confirmed to survive an API process restart. Non-failing Starlette/httpx deprecation warnings remained.

Do not assume this historical pass means new changes are safe: rerun the focused tests and the complete suite after material integration work.

## Deployment

The root `Dockerfile` builds the backend with Python 3.12, Tesseract, the API code, and the deployment-safe sample corpus. `render.yaml` contains the Render service definition.

### Render backend

Deploy the repository using the root Dockerfile and configure:

```env
SDOC_DATA_DIR=/app/data
SDOC_CASE_STORE_PATH=/tmp/sdoc-cases.json
GEMINI_API_KEY=your-key
GEMINI_ENABLE_FALLBACK=true
GEMINI_MODEL=gemini-2.5-flash-lite
```

Render supplies `PORT`; do not hard-code it. The free filesystem is ephemeral, so reviewer state can be lost on redeployment.

### Vercel frontend

The Vercel Root Directory must be exactly:

```text
apps/web
```

Do not use the repository root. Use the normal `pnpm run build` command and configure:

```env
API_BASE_URL=https://your-render-service.example
```

See `docs/DEPLOYMENT.md` for the complete current hosting guide.

## Known limitations and sensible next work

1. The complete SI/BL flow runs bundled email cases. Arbitrary upload currently supports one-document diagnostics, not a user-uploaded email plus SI and BL pair.
2. Human-review state is not durable across cloud service replacement or redeployment.
3. There is no authentication or role-based access control for reviewers.
4. “Request information” records a state and note but does not send a real email.
5. Full-inbox processing is synchronous and can be slow or quota-heavy.
6. Supabase is not integrated.
7. Fuzzy/Levenshtein matching remains a benchmarked future enhancement.
8. Organizer ground truth is not part of the application; accuracy scoring remains an offline task.
9. Gemini free-tier availability, quota, and network access are external constraints.

If time is limited, prioritize deployment smoke tests, a short demo path using the known cases, and clear failure states over adding more extraction heuristics.

## Git and collaboration conventions

The user prefers:

- standard commit subjects with two or three concise body bullets;
- logically separated commits, but not one tiny commit per file;
- the existing Git identity;
- no AI/Codex co-author attribution or trailers;
- local commits only unless explicitly asked to push; and
- a readable ticket-by-ticket summary after implementation.

The integration branch progression was broadly:

```text
extraction_divi
  -> integrate_extraction
  -> integrate_reporting
  -> integrate_review
```

Teammate work has already been merged and adapted across ingestion/classification, orchestration, comparison/reporting, and review/triage. Do not casually replace those integrations with an isolated teammate implementation from `main`; compare history and preserve the current adapters and tests.

## Recommended continuation checklist

When taking over this repository:

1. Read this file, `docs/pipeline.md`, and `docs/DEPLOYMENT.md`.
2. Inspect `git status`, the current branch, and recent commits.
3. Identify whether the request is diagnosis, planning, or implementation before changing code.
4. Trace changes through the structured pipeline contract rather than bypassing orchestration.
5. Preserve evidence, automated results, and human resolutions separately.
6. Keep deterministic decisions independent from AI availability.
7. Regenerate and commit the API contract when backend schemas change.
8. Test at least one verified/mismatch case and one review-required case.
9. Run `pnpm verify` before declaring the integration complete.
10. Report remaining limitations honestly; do not claim deployment durability or arbitrary pair upload exists when it does not.

