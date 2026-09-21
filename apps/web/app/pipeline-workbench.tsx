"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { CaseWorkbench } from "@/app/case-workbench";

type DocumentRole = "shipping_instruction" | "bill_of_lading";

type PipelineSample = {
  content_type: string;
  document_role: DocumentRole;
  filename: string;
};

type Candidate = {
  confidence: number;
  extraction_method: string;
  field: string;
  raw_value: string;
};

type VerificationField = {
  field: string;
  issues: string[];
  verified_field: object | null;
};

type NormalizedField = {
  field: string;
  normalized: { kind: string; unit?: string; value: number | string };
};

type PipelineResult = {
  candidates: { candidates: Candidate[]; diagnostics: string[] } | null;
  ingestion: {
    diagnostics: string[];
    extracted_text: string;
    extractor: string | null;
    filename: string;
    status: string;
  };
  normalization: {
    document: { fields: NormalizedField[] };
    failures: { field: string; issue: string; message: string }[];
  } | null;
  verification: { fields: VerificationField[] } | null;
};

const fieldLabels: Record<string, string> = {
  shipper: "Shipper",
  consignee: "Consignee",
  notify_party: "Notify party",
  port_of_loading: "Port of loading",
  port_of_discharge: "Port of discharge",
  container_count: "Container count",
  gross_weight_kg: "Gross weight",
};

const recommendedSamples = [
  "email_059_SI.pdf",
  "email_512_SI.pdf",
  "email_001_SI.txt",
];

function displayNormalized(field: NormalizedField): string {
  return `${field.normalized.value}${field.normalized.unit ? ` ${field.normalized.unit}` : ""}`;
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail ?? `Request failed with status ${response.status}`;
  } catch {
    return `Request failed with status ${response.status}`;
  }
}

export function PipelineWorkbench({ apiConnected }: { apiConnected: boolean }) {
  const [mode, setMode] = useState<"sample" | "upload">("sample");
  const [samples, setSamples] = useState<PipelineSample[]>([]);
  const [sampleName, setSampleName] = useState("email_059_SI.pdf");
  const [role, setRole] = useState<DocumentRole>("shipping_instruction");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/pipeline", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(await readError(response));
        return (await response.json()) as PipelineSample[];
      })
      .then((available) => {
        setSamples(available);
        if (
          !available.some((sample) => sample.filename === "email_059_SI.pdf") &&
          available[0]
        ) {
          setSampleName(available[0].filename);
          setRole(available[0].document_role);
        }
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const selectedSample = useMemo(
    () => samples.find((sample) => sample.filename === sampleName),
    [sampleName, samples],
  );

  function chooseSample(filename: string) {
    setSampleName(filename);
    const sample = samples.find((item) => item.filename === filename);
    if (sample) setRole(sample.document_role);
  }

  async function runPipeline(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      let response: Response;
      if (mode === "upload") {
        if (!file) throw new Error("Choose a PDF or TXT file first.");
        const formData = new FormData();
        formData.set("file", file);
        formData.set("document_role", role);
        response = await fetch("/api/pipeline", {
          body: formData,
          method: "POST",
        });
      } else {
        response = await fetch("/api/pipeline", {
          body: JSON.stringify({ document_role: role, filename: sampleName }),
          headers: { "content-type": "application/json" },
          method: "POST",
        });
      }
      if (!response.ok) throw new Error(await readError(response));
      setResult((await response.json()) as PipelineResult);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The pipeline request failed.",
      );
    } finally {
      setLoading(false);
    }
  }

  const verificationMap = new Map(
    result?.verification?.fields.map((field) => [field.field, field]) ?? [],
  );
  const normalizedMap = new Map(
    result?.normalization?.document.fields.map((field) => [
      field.field,
      field,
    ]) ?? [],
  );
  const pipelineComplete =
    result?.normalization?.document.fields.length === 7 &&
    result.normalization.failures.length === 0;
  const pipelineOutcome =
    result?.ingestion.status !== "success"
      ? result?.ingestion.status
      : pipelineComplete
        ? "complete"
        : "needs review";

  return (
    <main>
      <header className="hero">
        <div>
          <p className="eyebrow">Local pipeline workbench</p>
          <h1>Shipping Document Verification</h1>
          <p className="subtitle">
            Inspect ingestion, candidate extraction, evidence verification, and
            normalization, then run full SI-to-BL comparison and reporting.
          </p>
        </div>
        <div className="hero-actions">
          <span
            className={`status-pill ${apiConnected ? "connected" : "offline"}`}
          >
            <span /> FastAPI {apiConnected ? "connected" : "unavailable"}
          </span>
          <Link className="nav-link" href="/review">
            Human review queue →
          </Link>
        </div>
      </header>

      {!apiConnected && (
        <section className="notice error-notice">
          <strong>Start the API first.</strong>
          <span>Open another terminal and run</span>
          <code>pnpm dev:api</code>
          <span>, then refresh this page.</span>
        </section>
      )}

      <section className="flow-strip" aria-label="Pipeline stages">
        {/* Retain the box numbers from the shared architecture diagram. */}
        {[
          ["1", "Ingest", "Read document"],
          ["5", "Extract", "Field candidates"],
          ["6", "Verify", "Evidence checks"],
          ["7", "Normalize", "Typed values"],
          ["8", "Compare", "SI against BL"],
          ["QA", "Gate", "Deterministic checks"],
          ["9", "Review", "Exception triage"],
          ["10", "Report", "Final result"],
        ].map(([number, title, detail]) => (
          <div className="flow-step" key={number}>
            <span>{number}</span>
            <div>
              <strong>{title}</strong>
              <small>{detail}</small>
            </div>
          </div>
        ))}
      </section>

      <CaseWorkbench apiConnected={apiConnected} />

      <section className="diagnostics-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Technical diagnostics</p>
            <h2>Inspect a single document</h2>
          </div>
          <p>
            Debug OCR, extraction candidates, source evidence, and normalized
            values without running a complete SI-to-BL comparison.
          </p>
        </div>

        <div className="workspace">
          <form className="control-panel" onSubmit={runPipeline}>
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Test input</p>
                <h2>Choose a document</h2>
              </div>
              <div className="segmented">
                <button
                  className={mode === "sample" ? "active" : ""}
                  onClick={() => setMode("sample")}
                  type="button"
                >
                  Included sample
                </button>
                <button
                  className={mode === "upload" ? "active" : ""}
                  onClick={() => setMode("upload")}
                  type="button"
                >
                  Upload file
                </button>
              </div>
            </div>

            {mode === "sample" ? (
              <div className="field-group">
                <label htmlFor="sample">Participant attachment</label>
                <select
                  id="sample"
                  onChange={(event) => chooseSample(event.target.value)}
                  value={sampleName}
                >
                  {samples.map((sample) => (
                    <option key={sample.filename} value={sample.filename}>
                      {sample.filename}
                    </option>
                  ))}
                </select>
                <div className="quick-samples">
                  {recommendedSamples
                    .filter((name) =>
                      samples.some((sample) => sample.filename === name),
                    )
                    .map((name) => (
                      <button
                        key={name}
                        onClick={() => chooseSample(name)}
                        type="button"
                      >
                        {name}
                      </button>
                    ))}
                </div>
                {selectedSample && (
                  <p className="hint">
                    Detected role:{" "}
                    {selectedSample.document_role === "shipping_instruction"
                      ? "Shipping Instruction"
                      : "Bill of Lading"}
                  </p>
                )}
              </div>
            ) : (
              <div className="field-group">
                <label htmlFor="file">PDF or TXT document</label>
                <input
                  accept=".pdf,.txt,application/pdf,text/plain"
                  id="file"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                  type="file"
                />
                <p className="hint">Use one SI or one draft BL per run.</p>
              </div>
            )}

            <fieldset>
              <legend>Document role</legend>
              <label className="radio-card">
                <input
                  checked={role === "shipping_instruction"}
                  name="role"
                  onChange={() => setRole("shipping_instruction")}
                  type="radio"
                />
                <span>
                  <strong>Shipping Instruction</strong>
                  <small>Source instructions from the shipper</small>
                </span>
              </label>
              <label className="radio-card">
                <input
                  checked={role === "bill_of_lading"}
                  name="role"
                  onChange={() => setRole("bill_of_lading")}
                  type="radio"
                />
                <span>
                  <strong>Draft Bill of Lading</strong>
                  <small>Carrier document to be checked</small>
                </span>
              </label>
            </fieldset>

            <button
              className="primary-button"
              disabled={loading || !apiConnected}
              type="submit"
            >
              {loading ? "Running pipeline…" : "Run document pipeline"}
            </button>
            {error && <p className="form-error">{error}</p>}
          </form>

          <section className="results-panel">
            {!result ? (
              <div className="empty-state">
                <div>↗</div>
                <h2>Results appear here</h2>
                <p>
                  Start with <strong>email_059_SI.pdf</strong>. It contains
                  native text and should complete all seven fields without OCR
                  or Gemini.
                </p>
              </div>
            ) : (
              <>
                <div className="result-heading">
                  <div>
                    <p className="eyebrow">Latest run</p>
                    <h2>{result.ingestion.filename}</h2>
                  </div>
                  <span
                    className={`result-status ${pipelineComplete ? "complete" : "partial"}`}
                  >
                    {pipelineOutcome}
                  </span>
                </div>
                <div className="metric-grid">
                  <div>
                    <small>Extractor</small>
                    <strong>{result.ingestion.extractor ?? "None"}</strong>
                  </div>
                  <div>
                    <small>Candidates</small>
                    <strong>
                      {result.candidates?.candidates.length ?? 0}/7
                    </strong>
                  </div>
                  <div>
                    <small>Verified</small>
                    <strong>
                      {result.verification?.fields.filter(
                        (field) => field.verified_field,
                      ).length ?? 0}
                      /7
                    </strong>
                  </div>
                  <div>
                    <small>Normalized</small>
                    <strong>
                      {result.normalization?.document.fields.length ?? 0}/7
                    </strong>
                  </div>
                </div>

                {(result.ingestion.diagnostics.length > 0 ||
                  result.candidates?.diagnostics.length) && (
                  <div className="diagnostics">
                    <strong>Diagnostics</strong>
                    <ul>
                      {[
                        ...result.ingestion.diagnostics,
                        ...(result.candidates?.diagnostics ?? []),
                      ].map((item, index) => (
                        <li key={`${item}-${index}`}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="field-results">
                  {Object.entries(fieldLabels).map(([field, label]) => {
                    const candidate = result.candidates?.candidates.find(
                      (item) => item.field === field,
                    );
                    const verification = verificationMap.get(field);
                    const normalized = normalizedMap.get(field);
                    return (
                      <article className="field-result" key={field}>
                        <div>
                          <small>{label}</small>
                          <strong>
                            {normalized
                              ? displayNormalized(normalized)
                              : (candidate?.raw_value ?? "Not found")}
                          </strong>
                        </div>
                        <span
                          className={
                            verification?.verified_field
                              ? "field-ok"
                              : "field-missing"
                          }
                        >
                          {verification?.verified_field
                            ? "Verified"
                            : verification?.issues.join(", ") || "Unavailable"}
                        </span>
                        {candidate && (
                          <p>
                            Raw: {candidate.raw_value} ·{" "}
                            {candidate.extraction_method} ·{" "}
                            {(candidate.confidence * 100).toFixed(1)}%
                          </p>
                        )}
                      </article>
                    );
                  })}
                </div>

                <details>
                  <summary>Extracted document text</summary>
                  <pre>
                    {result.ingestion.extracted_text ||
                      "No readable text was extracted."}
                  </pre>
                </details>
                <details>
                  <summary>Complete JSON response</summary>
                  <pre>{JSON.stringify(result, null, 2)}</pre>
                </details>
              </>
            )}
          </section>
        </div>
      </section>
    </main>
  );
}
