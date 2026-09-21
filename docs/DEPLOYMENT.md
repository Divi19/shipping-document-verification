# Deployment: Render API and Vercel web app

The deployed prototype uses a Dockerized FastAPI service on Render and the
Next.js application on Vercel. The container includes only the participant-safe
`inbox/` and `attachments/` data. Never add the organizer-only
`ground_truth.json` to this repository or deployment image.

## 1. Before deploying

1. Merge the deployment branch into the Git branch that will be hosted.
2. Confirm the participant data is tracked:

   ```bash
   git ls-files local-data/sdoc-hackathon-bundle/inbox | head
   git ls-files local-data/sdoc-hackathon-bundle/attachments | head
   ```

3. Build and test the container locally:

   ```bash
   docker build -t sdoc-api .
   docker run --rm -p 8000:8000 \
     -e GEMINI_API_KEY="YOUR_KEY" \
     -e GEMINI_ENABLE_FALLBACK=true \
     -e GEMINI_MODEL=gemini-2.5-flash-lite \
     sdoc-api
   ```

4. Check <http://localhost:8000/health> and run:

   ```bash
   curl -X POST http://localhost:8000/cases/email_004/run-report
   ```

## 2. Deploy FastAPI to Render

1. In Render, choose **New → Blueprint**.
2. Connect this GitHub repository and select `render.yaml`.
3. Choose the production branch.
4. When prompted for `GEMINI_API_KEY`, paste the key from Google AI Studio.
5. Create the free web service and wait for its health check to pass.
6. Copy its public URL, for example:

   ```text
   https://shipping-document-verification-api.onrender.com
   ```

The Blueprint already supplies:

```text
SDOC_DATA_DIR=/app/data
GEMINI_ENABLE_FALLBACK=true
GEMINI_MODEL=gemini-2.5-flash-lite
```

Render supplies `PORT`; do not add it manually. Supabase variables are not
required. Test these URLs before continuing:

```text
https://YOUR-RENDER-URL/health
https://YOUR-RENDER-URL/cases/available
```

Then send a POST request to:

```text
https://YOUR-RENDER-URL/cases/email_004/run-report
```

The expected result has seven comparisons, QA status `pass`, and mismatch
fields `consignee` and `notify_party`.

## 3. Deploy Next.js to Vercel

1. In Vercel, choose **Add New → Project** and import the same repository.
2. Set **Root Directory** to exactly `apps/web`. Do not use the repository root.
3. Keep the detected **Next.js** framework. The build command should remain
   `pnpm run build`; no custom install or build command is required.
4. Under **Environment Variables**, add this for Production and Preview:

   ```text
   API_BASE_URL=https://YOUR-RENDER-URL
   ```

5. Deploy. The generated contract required by the workspace is committed to
   the repository, so no additional "outside Root Directory" setting is needed.
6. After changing `API_BASE_URL`, redeploy; existing deployments do not receive
   environment-variable changes retroactively.

## 4. Demonstration check

1. Open the Render `/health` URL first to wake the free service.
2. Open the Vercel URL and confirm it says **FastAPI connected**.
3. In **Complete workflow**, select `email_004`.
4. Click **Run comparison and report**.
5. Confirm seven field rows, two mismatches, a passing QA gate, evidence
   locations, the human-readable report, and structured JSON.
6. Use **Technical diagnostics** only when demonstrating OCR, extraction,
   evidence verification, or normalization for one document.

## Organizer Docker package

The supplied organizer package is not a runtime dependency of the public app.
It contains an answer key and scoring server intended for offline evaluation.
Keep it outside the Git repository. Its `POST /submit` endpoint can score a
locally generated submission without exposing the ground truth, but it should
not be deployed with the participant-facing prototype.
