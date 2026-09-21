# Shipping Document Verification

Monorepo for an evidence-backed shipping-document verification prototype. It
classifies email cases, reads SI/BL attachments, extracts and normalizes seven
fields, compares the documents, applies a deterministic QA gate, and produces
structured and human-readable reports.

For the production hosting sequence, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Repository boundaries

- `apps/web`: Next.js verification and technical-diagnostics workbench.
- `apps/api`: FastAPI ingestion, orchestration, comparison, QA, and reporting service.
- `packages/contracts`: TypeScript contracts generated from FastAPI's Pydantic-backed OpenAPI schema.
- `supabase`: Optional local Supabase configuration and future database migrations.
- `local-data`: Participant-safe demo inbox and attachments used locally and in the API image.

The FastAPI application and its tests do not require Supabase.

## Prerequisites

- Node.js 22 or newer
- Corepack
- [uv](https://docs.astral.sh/uv/)
- Tesseract 5, required only for local OCR of image-only PDFs
- Docker Desktop or another Docker-compatible runtime, only when running local Supabase

The repository pins pnpm through the `packageManager` field and Python 3.12 through `apps/api/.python-version`. `uv` downloads a compatible Python interpreter when needed.

## Installation

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm install:api
pnpm contracts:generate
```

Generated OpenAPI and TypeScript contract files are intentionally ignored. Run `pnpm contracts:generate` after installing dependencies and whenever a Pydantic response model or FastAPI route changes.

## Environment setup

Copy the placeholder environment file for local use:

```bash
cp .env.example .env
```

The scaffold uses `http://localhost:8000` as the default API URL, so no environment variable is required for the standard local ports. To override it when starting Next.js:

```bash
API_BASE_URL=http://localhost:8000 pnpm dev:web
```

Do not commit `.env`, local credentials, service-role keys, or other secrets.

`SDOC_DATA_DIR` may point to an alternate participant-bundle directory. When it is unset,
the API uses `local-data/sdoc-hackathon-bundle`.

PDF ingestion first reads native text, then uses local Tesseract OCR for image-only pages.
Install Tesseract with `brew install tesseract` on macOS or your platform's package manager.
Docling remains available as an explicitly enabled heavier fallback but is disabled by default.

Gemini fallbacks are optional and disabled by default. Deterministic extraction remains the
primary path. To opt in, set `GEMINI_ENABLE_FALLBACK=true`, provide `GEMINI_API_KEY`, and
optionally override `GEMINI_MODEL`. The same setting enables evidence-gated semantic field
extraction and PDF vision only after local methods are insufficient. Enabling a cloud fallback
may consume the quota or billing associated with the supplied API key.

## Local development

Start FastAPI in one terminal:

```bash
pnpm dev:api
```

Start Next.js in another terminal:

```bash
pnpm dev:web
```

The services are then available at:

- Next.js: <http://localhost:3000>
- FastAPI health: <http://localhost:8000/health>
- FastAPI OpenAPI: <http://localhost:8000/openapi.json>

The Next.js page presents the complete SI-to-BL verification workflow first.
The single-document workbench appears below it as **Technical diagnostics** for
inspecting ingestion, extraction, evidence verification, and normalization.

For a quick validation, open <http://localhost:3000> and run these included samples in order:

1. `email_059_SI.pdf` — native PDF text; expected to reach 7/7 normalized fields.
2. `email_001_SI.txt` — deterministic TXT baseline.
3. `email_512_SI.pdf` — image-only scan for testing local OCR/fallback behaviour.
4. `email_511_BL.pdf` — deliberately corrupt edge case; expected to report `unreadable`.

The **Human review queue** at <http://localhost:3000/review> handles the cases
the pipeline cannot decide. For a quick end-to-end demonstration, run
`email_059` in **Complete workflow**, follow **Open in review queue**, and
correct the BL gross weight to `131,322 KG`. The seven comparisons and final
report update to `verified` while retaining the automated `needs_review`
outcome in the audit history. Reviewers can also request information or close a
case as unable to verify. **Process full inbox** is available for batch testing,
but may take several minutes and invoke configured Gemini fallbacks. See
[docs/pipeline.md](docs/pipeline.md#human-review) for the rules.

If the page reports `FastAPI unavailable`, ensure `pnpm dev:api` is running in a separate
terminal. If port 8000 is already in use, stop the older API process with `Ctrl+C` before
starting it again.

## Optional local Supabase

Supabase is not required for the health endpoint, frontend, contract generation, or tests. With Docker running:

```bash
pnpm supabase:start
pnpm supabase:status
pnpm supabase:stop
```

Authentication, storage, Realtime, Edge Runtime, and analytics are disabled in the initial configuration. The migrations directory is intentionally empty until an approved persistence model exists.

## Verification pipeline

The classification and comparison pipeline lives in `apps/api/app/pipeline`.
`docs/pipeline.md` describes the flow, the outcome vocabulary and the contract
for adding document readers and label synonyms.

```bash
pnpm pipeline:run -- --text-only                  # run the inbox, plain text only
pnpm pipeline:run                                  # run with every reader
pnpm pipeline:score local-data/submission.json     # score against the organiser scorer
```

AI is used in two narrow places - classifying an email no rule matched, and
recovering a field no label matched - and both are verified before they are
believed (see `docs/pipeline.md`). Set `GEMINI_API_KEY` to enable it; without a
key the pipeline runs its deterministic path and still escalates whatever it
cannot decide. `pnpm pipeline:run -- --no-ai` forces that path.

`--text-only` skips the PDF/Word/Excel readers, which is the fastest way to see
the effect of a change. The run writes `local-data/submission.json` (one entry
per email id) and prints a summary of outcomes and escalation reasons.

The dataset root defaults to `local-data/sdoc-hackathon-bundle`; override it
with `SDOC_DATA_DIR`.

Scoring reads `ground_truth.json` and the organisers' `scoring.py` from the
separate organizer package. That answer-key package stays outside Git and is
never read by the application. Only the participant-safe inbox and attachments
under `local-data/sdoc-hackathon-bundle` are committed for the live demo.

## Quality commands

```bash
pnpm format          # apply Prettier and Ruff formatting
pnpm format:check    # check formatting
pnpm lint            # ESLint and Ruff
pnpm typecheck       # regenerate contracts, run TypeScript, and run mypy
pnpm test            # Vitest and pytest
pnpm build           # contracts, Next.js production build, and API bytecode check
pnpm verify          # run every check above without applying formatting
```

Run the FastAPI production process from source with:

```bash
uv --directory apps/api run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

After `pnpm build`, run the Next.js production server with:

```bash
pnpm --filter @sdoc/web start
```

## Shared contract workflow

`HealthResponse` is defined as a Pydantic model in `apps/api/app/models/health.py`. FastAPI exposes it in OpenAPI, `openapi-typescript` generates the corresponding TypeScript schema, and `packages/contracts` exports the frontend type. The frontend must import that shared type instead of defining a separate response interface.

Use this sequence after changing an API contract:

```bash
pnpm contracts:generate
pnpm typecheck
pnpm test
```

## Local hackathon data

Place the supplied bundles only under:

```text
local-data/
├── sdoc-hackathon-bundle/
└── sdoc-hackathon-docker/
```

`local-data/` is Git-ignored. Never stage or commit participant datasets, Docker datasets, organizer evaluation data, local databases, generated outputs, dependency folders, build outputs, or secrets. Organizer-only evaluation data must not influence application behavior.

## Current structure

```text
shipping-document-verification/
├── apps/
│   ├── api/
│   │   ├── app/
│   │   │   ├── models/
│   │   │   └── main.py
│   │   ├── scripts/
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── uv.lock
│   └── web/
│       ├── app/
│       ├── lib/
│       ├── eslint.config.mjs
│       ├── next.config.ts
│       ├── package.json
│       └── tsconfig.json
├── packages/
│   └── contracts/
│       ├── src/
│       ├── eslint.config.mjs
│       ├── package.json
│       └── tsconfig.json
├── supabase/
│   ├── migrations/
│   └── config.toml
├── docs/
├── local-data/
├── .env.example
├── package.json
├── pnpm-lock.yaml
└── pnpm-workspace.yaml
```

## Deliberate limitations

Before feature work begins, the team should decide on the persistence schema, deployment environment, runtime response validation strategy, and browser-to-API networking policy. There is currently no CORS configuration because the only API check runs from the Next.js server. Supabase services beyond the local database/API baseline remain disabled, and no authentication, queues, workers, dashboard, document processing, comparison logic, OCR, or AI integrations exist.
