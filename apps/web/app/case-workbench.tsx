"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

type AvailableCase = {
  attachment_count: number;
  attachment_names: string[];
  email_id: string;
  subject: string;
};

type Evidence = { locator: string; snippet: string; source: string };
type FieldValue = {
  confidence: number | null;
  evidence: Evidence | null;
  normalized: string | null;
  raw: string | null;
};
type Comparison = {
  bl: FieldValue;
  field: string;
  matches: boolean | null;
  note: string | null;
  si: FieldValue;
};
type FinalReport = {
  category: string;
  comparisons: Comparison[];
  defect_fields: string[];
  email_id: string;
  human_readable_report: string;
  match_status: "match" | "mismatch" | "uncertain" | "not_applicable";
  outcome: string;
  processing_status: string;
  quality_gate: {
    checks: { detail: string; name: string; passed: boolean }[];
    minimum_confidence: number;
    status: "pass" | "fail" | "not_applicable";
  };
  review_status: string;
};

const labels: Record<string, string> = {
  shipper: "Shipper",
  consignee: "Consignee",
  notify_party: "Notify party",
  port_of_loading: "Port of loading",
  port_of_discharge: "Port of discharge",
  container_count: "Container count",
  gross_weight_kg: "Gross weight",
};

const recommendedCases = ["email_004", "email_059", "email_507"] as const;

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail ?? `Request failed with status ${response.status}`;
  } catch {
    return `Request failed with status ${response.status}`;
  }
}

function comparisonStatus(comparison: Comparison): string {
  if (comparison.matches === null) return "uncertain";
  return comparison.matches ? "match" : "mismatch";
}

export function CaseWorkbench({ apiConnected }: { apiConnected: boolean }) {
  const [cases, setCases] = useState<AvailableCase[]>([]);
  const [emailId, setEmailId] = useState("");
  const [report, setReport] = useState<FinalReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/cases", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(await readError(response));
        return (await response.json()) as AvailableCase[];
      })
      .then((available) => {
        setCases(available);
        const preferred =
          available.find((item) => item.email_id === "email_004") ??
          available.find((item) => item.attachment_count >= 2) ??
          available[0];
        if (preferred) setEmailId(preferred.email_id);
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const selected = useMemo(
    () => cases.find((item) => item.email_id === emailId),
    [cases, emailId],
  );

  function chooseCase(id: string) {
    setEmailId(id);
    setReport(null);
    setError(null);
  }

  async function runCase(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      const response = await fetch("/api/cases", {
        body: JSON.stringify({ email_id: emailId }),
        headers: { "content-type": "application/json" },
        method: "POST",
      });
      if (!response.ok) throw new Error(await readError(response));
      setReport((await response.json()) as FinalReport);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Case processing failed.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="case-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Complete workflow</p>
          <h2>Comparison, quality gate, and final report</h2>
        </div>
        <p>
          Runs a complete email case through orchestration and compares the SI
          against the draft BL across all seven normalized fields.
        </p>
      </div>

      <div className="workspace">
        <form className="control-panel" onSubmit={runCase}>
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Case input</p>
              <h2>Choose an email</h2>
            </div>
          </div>
          <div className="field-group">
            <label htmlFor="case-email">Participant inbox record</label>
            <select
              id="case-email"
              onChange={(event) => chooseCase(event.target.value)}
              value={emailId}
            >
              {cases.map((item) => (
                <option key={item.email_id} value={item.email_id}>
                  {item.email_id} — {item.subject}
                </option>
              ))}
            </select>
            <div className="quick-samples">
              {recommendedCases
                .filter((id) => cases.some((item) => item.email_id === id))
                .map((id) => (
                  <button key={id} onClick={() => chooseCase(id)} type="button">
                    {id}
                  </button>
                ))}
            </div>
            <p className="hint">
              Try email_004 for a confirmed mismatch, email_059 for a
              correctable missing value, or email_507 for a missing-attachment
              review.
            </p>
          </div>
          {selected && (
            <div className="case-details">
              <strong>{selected.subject}</strong>
              <span>{selected.attachment_count} attachment(s)</span>
              <ul>
                {selected.attachment_names.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            </div>
          )}
          <button
            className="primary-button"
            disabled={loading || !apiConnected || !emailId}
            type="submit"
          >
            {loading
              ? "Running complete workflow…"
              : "Run comparison and report"}
          </button>
          {error && <p className="form-error">{error}</p>}
        </form>

        <section className="results-panel case-results">
          {!report ? (
            <div className="empty-state compact-empty">
              <div>⇄</div>
              <h2>Final result appears here</h2>
              <p>
                Choose an email with both SI and draft BL attachments. A correct
                complete run shows seven comparisons and a passing QA gate.
              </p>
            </div>
          ) : (
            <>
              <div className="result-heading">
                <div>
                  <p className="eyebrow">Final result</p>
                  <h2>{report.email_id}</h2>
                </div>
                <span className={`result-status ${report.match_status}`}>
                  {report.match_status.replaceAll("_", " ")}
                </span>
              </div>

              {report.review_status !== "not_required" && (
                <div className="review-callout">
                  <span>
                    This case is in the human review queue (
                    {report.review_status.replaceAll("_", " ")}).
                  </span>
                  <Link
                    className="text-link"
                    href={`/review?case=${encodeURIComponent(report.email_id)}`}
                  >
                    Open in review queue →
                  </Link>
                </div>
              )}

              <div className="metric-grid report-metrics">
                <div>
                  <small>Category</small>
                  <strong>{report.category}</strong>
                </div>
                <div>
                  <small>Final status</small>
                  <strong>{report.processing_status}</strong>
                </div>
                <div>
                  <small>Differences</small>
                  <strong>{report.defect_fields.length}</strong>
                </div>
                <div>
                  <small>QA gate</small>
                  <strong>{report.quality_gate.status}</strong>
                </div>
              </div>

              <div className="comparison-table">
                <div className="comparison-header">
                  <strong>Field</strong>
                  <strong>SI value</strong>
                  <strong>BL value</strong>
                  <strong>Result</strong>
                </div>
                {report.comparisons.map((comparison) => {
                  const status = comparisonStatus(comparison);
                  return (
                    <article className="comparison-row" key={comparison.field}>
                      <strong>
                        {labels[comparison.field] ?? comparison.field}
                      </strong>
                      <div>
                        <span>{comparison.si.raw ?? "Unavailable"}</span>
                        {comparison.si.evidence && (
                          <small>
                            {comparison.si.evidence.source} ·{" "}
                            {comparison.si.evidence.locator}
                          </small>
                        )}
                      </div>
                      <div>
                        <span>{comparison.bl.raw ?? "Unavailable"}</span>
                        {comparison.bl.evidence && (
                          <small>
                            {comparison.bl.evidence.source} ·{" "}
                            {comparison.bl.evidence.locator}
                          </small>
                        )}
                      </div>
                      <span className={`comparison-badge ${status}`}>
                        {status}
                      </span>
                      {comparison.note && <p>{comparison.note}</p>}
                    </article>
                  );
                })}
              </div>

              <div className={`qa-panel ${report.quality_gate.status}`}>
                <div>
                  <strong>Quality assurance gate</strong>
                  <span>{report.quality_gate.status}</span>
                </div>
                <ul>
                  {report.quality_gate.checks.map((check) => (
                    <li key={check.name}>
                      <b>{check.passed ? "✓" : "✕"}</b>
                      <span>
                        <strong>{check.name.replaceAll("_", " ")}</strong>
                        <small>{check.detail}</small>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>

              <details open>
                <summary>Human-readable final report</summary>
                <pre>{report.human_readable_report}</pre>
              </details>
              <details>
                <summary>Structured JSON output</summary>
                <pre>{JSON.stringify(report, null, 2)}</pre>
              </details>
            </>
          )}
        </section>
      </div>
    </section>
  );
}
