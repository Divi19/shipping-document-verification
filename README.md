# Shipping Document Verification

Barebones monorepo for the shipping document verification project. The repository currently contains framework setup, shared health contracts, optional local infrastructure, and verification tooling only. Shipping-document business logic and product features are intentionally out of scope.

## Repository boundaries

- `apps/web`: Next.js presentation layer and minimal FastAPI connectivity check.
- `apps/api`: FastAPI service, Pydantic API models, and OpenAPI export.
- `packages/contracts`: TypeScript contracts generated from FastAPI's Pydantic-backed OpenAPI schema.
- `supabase`: Optional local Supabase configuration and future database migrations.
- `local-data`: Local hackathon bundles only; the entire directory is Git-ignored.

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

PDF ingestion first reads native text, then tries optional Docling and local Tesseract OCR.
Install Tesseract with `brew install tesseract` on macOS or your platform's package manager.

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

The Next.js page provides a local document-pipeline workbench. It can run bundled samples or
uploaded TXT/PDF files through ingestion, Box 5 extraction, Box 6 evidence verification, and
Box 7 normalization.

For a quick validation, open <http://localhost:3000> and run these included samples in order:

1. `email_059_SI.pdf` — native PDF text; expected to reach 7/7 normalized fields.
2. `email_001_SI.txt` — deterministic TXT baseline.
3. `email_512_SI.pdf` — image-only scan for testing local OCR/fallback behaviour.
4. `email_511_BL.pdf` — deliberately corrupt edge case; expected to report `unreadable`.

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
