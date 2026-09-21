"use client";

import type { FieldValue, ReviewAction, ReviewPackage } from "@sdoc/contracts";
import { FormEvent, useState } from "react";

import {
  ACTION_ORDER,
  CorrectionDraft,
  FIELD_ORDER,
  SIDES,
  actionLabels,
  buildDecision,
  comparisonRows,
  comparisonStatus,
  correctionKey,
  decisionBlocker,
  fieldLabels,
  formatConfidence,
  formatDateTime,
  humanize,
  priorityLabels,
  readError,
  reasonLabels,
  statusLabels,
  teamLabels,
} from "@/lib/review";

type ReviewPackageViewProps = {
  onDecided: (updated: ReviewPackage) => void;
  onRetry: () => void;
  onReviewerChange: (name: string) => void;
  retrying: boolean;
  reviewPackage: ReviewPackage;
  reviewer: string;
};

function attachmentUrl(emailId: string, filename: string): string {
  return `/api/review/${encodeURIComponent(emailId)}/attachments/${encodeURIComponent(filename)}`;
}

function ValueCell({
  corrected,
  value,
}: {
  corrected: boolean;
  value: FieldValue | undefined;
}) {
  if (!value) {
    return (
      <div>
        <span className="muted-value">Not compared</span>
      </div>
    );
  }
  const confidence = formatConfidence(value.confidence);
  return (
    <div>
      <span className={value.raw ? undefined : "muted-value"}>
        {value.raw ?? "Unavailable"}
        {corrected && <em className="flag corrected">Corrected</em>}
      </span>
      {value.evidence && (
        <small>
          {value.evidence.source} · {value.evidence.locator}
        </small>
      )}
      {value.evidence?.snippet && (
        <code className="evidence-snippet" title={value.evidence.snippet}>
          {value.evidence.snippet}
        </code>
      )}
      {confidence && <small>{confidence}</small>}
      {!value.normalized && value.note && (
        <small className="value-note">{value.note}</small>
      )}
    </div>
  );
}

export function ReviewPackageView({
  onDecided,
  onRetry,
  onReviewerChange,
  retrying,
  reviewPackage,
  reviewer,
}: ReviewPackageViewProps) {
  const { email, report, ticket } = reviewPackage;
  const decisions = ticket.decisions ?? [];
  const open = reviewPackage.allowed_actions.length > 0;
  const questionable = new Set(open ? (ticket.questionable_fields ?? []) : []);
  const corrected = new Set(
    decisions.flatMap((decision) =>
      (decision.corrections ?? []).map((item) =>
        correctionKey(item.field, item.side),
      ),
    ),
  );

  return (
    <section className="results-panel review-package">
      <div className="result-heading">
        <div>
          <p className="eyebrow">Review package</p>
          <h2>{email.email_id}</h2>
          <p className="package-subject">{email.subject}</p>
        </div>
        <span className={`review-status ${ticket.status}`}>
          {statusLabels[ticket.status]}
        </span>
      </div>

      <div className={`escalation ${ticket.priority}`}>
        <strong>
          {ticket.reason ? reasonLabels[ticket.reason] : "Quality gate failed"}
        </strong>
        <p>{ticket.summary}</p>
      </div>

      <div className="metric-grid report-metrics">
        <div>
          <small>Priority</small>
          <strong>{priorityLabels[ticket.priority]}</strong>
        </div>
        <div>
          <small>Assigned to</small>
          <strong>{teamLabels[ticket.team]}</strong>
        </div>
        <div>
          <small>Automated outcome</small>
          <strong>{humanize(reviewPackage.automated_outcome)}</strong>
        </div>
        <div>
          <small>Final outcome</small>
          <strong>{humanize(report.outcome)}</strong>
        </div>
      </div>

      <details open={open}>
        <summary>Original email</summary>
        <dl className="email-meta">
          <dt>From</dt>
          <dd>{email.from_address}</dd>
          <dt>Subject</dt>
          <dd>{email.subject}</dd>
          <dt>Attachments</dt>
          <dd>{email.attachments.join(", ") || "None"}</dd>
        </dl>
        <pre>{email.body}</pre>
      </details>

      <h3 className="package-heading">SI and BL documents</h3>
      {reviewPackage.documents.length === 0 ? (
        <p className="hint">No documents arrived with this email.</p>
      ) : (
        <div className="document-list">
          {reviewPackage.documents.map((doc) => (
            <article
              className={`document-card${doc.readable ? "" : " unreadable"}`}
              key={doc.filename}
            >
              <div className="document-card-top">
                <div>
                  <strong>{doc.filename}</strong>
                  <small>
                    {doc.readable
                      ? `${humanize(doc.role)} · read by ${doc.reader}`
                      : `Unreadable · ${doc.failure ?? "no text extracted"}`}
                  </small>
                </div>
                <a
                  className="text-link"
                  href={attachmentUrl(email.email_id, doc.filename)}
                  rel="noreferrer"
                  target="_blank"
                >
                  Open original ↗
                </a>
              </div>
              {doc.text && (
                <details>
                  <summary>Extracted text</summary>
                  <pre>{doc.text}</pre>
                </details>
              )}
            </article>
          ))}
        </div>
      )}

      <h3 className="package-heading">
        {ticket.resolution ? "Fields after review" : "Fields and evidence"}
      </h3>
      <div className="comparison-table">
        <div className="comparison-header">
          <strong>Field</strong>
          <strong>SI value</strong>
          <strong>BL value</strong>
          <strong>Result</strong>
        </div>
        {comparisonRows(report.comparisons).map(({ comparison, field }) => {
          const status = comparisonStatus(comparison);
          return (
            <article
              className={`comparison-row${questionable.has(field) ? " questionable" : ""}`}
              key={field}
            >
              <strong>
                {fieldLabels[field]}
                {questionable.has(field) && <em className="flag">Check</em>}
              </strong>
              <ValueCell
                corrected={corrected.has(correctionKey(field, "si"))}
                value={comparison?.si}
              />
              <ValueCell
                corrected={corrected.has(correctionKey(field, "bl"))}
                value={comparison?.bl}
              />
              <span className={`comparison-badge ${status.replace(" ", "-")}`}>
                {status}
              </span>
              {comparison?.note && <p>{comparison.note}</p>}
            </article>
          );
        })}
      </div>

      {open && (
        <DecisionForm
          key={`${email.email_id}-${decisions.length}`}
          onDecided={onDecided}
          onReviewerChange={onReviewerChange}
          reviewPackage={reviewPackage}
          reviewer={reviewer}
        />
      )}

      {decisions.length > 0 && (
        <div className="decision-history">
          <h3 className="package-heading">Decision history</h3>
          <ol>
            {decisions.map((decision, index) => (
              <li key={`${decision.at ?? index}-${decision.action}`}>
                <div>
                  <strong>{actionLabels[decision.action].title}</strong>
                  <small>
                    {decision.reviewer} · {formatDateTime(decision.at)}
                  </small>
                </div>
                {decision.note && <p>{decision.note}</p>}
                {(decision.corrections ?? []).map((item) => (
                  <small key={correctionKey(item.field, item.side)}>
                    {fieldLabels[item.field]} ({item.side.toUpperCase()}):{" "}
                    {item.previous ?? "unavailable"} → {item.value}
                  </small>
                ))}
              </li>
            ))}
          </ol>
        </div>
      )}

      <details open={decisions.length > 0}>
        <summary>Final report · {humanize(report.processing_status)}</summary>
        <pre>{report.human_readable_report}</pre>
      </details>

      <details>
        <summary>
          Processing history ({reviewPackage.attempts.length} steps)
        </summary>
        <ol className="attempt-list">
          {reviewPackage.attempts.map((attempt, index) => (
            <li className={attempt.ok ? "ok" : "failed"} key={index}>
              <b>{attempt.ok ? "✓" : "✕"}</b>
              <span>
                <strong>
                  {humanize(attempt.stage)} #{attempt.attempt}
                </strong>
                <small>{attempt.detail}</small>
              </span>
            </li>
          ))}
        </ol>
      </details>

      <div className="package-footer">
        <button
          className="secondary-button"
          disabled={retrying}
          onClick={onRetry}
          type="button"
        >
          {retrying ? "Retrying…" : "Retry processing"}
        </button>
        <p className="hint">
          Runs this email through the pipeline again. Earlier attempts and human
          decisions stay on the record.
        </p>
      </div>
    </section>
  );
}

function DecisionForm({
  onDecided,
  onReviewerChange,
  reviewPackage,
  reviewer,
}: Omit<ReviewPackageViewProps, "onRetry" | "retrying">) {
  const { email, ticket } = reviewPackage;
  const allowed = reviewPackage.allowed_actions;
  const [action, setAction] = useState<ReviewAction>(
    allowed.includes(ticket.recommended_action)
      ? ticket.recommended_action
      : "corrected", // always allowed while the case is open
  );
  const [note, setNote] = useState("");
  const [draft, setDraft] = useState<CorrectionDraft>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const decision = buildDecision(reviewer, action, note, draft);
  const blocker = decisionBlocker(decision);
  const extracted = new Map(
    reviewPackage.comparisons.map((item) => [item.field, item]),
  );
  const questionable = new Set(ticket.questionable_fields ?? []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (blocker) return;
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/review/${encodeURIComponent(email.email_id)}`,
        {
          body: JSON.stringify(decision),
          headers: { "content-type": "application/json" },
          method: "POST",
        },
      );
      if (!response.ok) throw new Error(await readError(response));
      onDecided((await response.json()) as ReviewPackage);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The decision could not be recorded.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="decision-panel" onSubmit={submit}>
      <div className="decision-heading">
        <h3>Reviewer decision</h3>
        <label className="reviewer-field">
          <span>Your name</span>
          <input
            autoComplete="name"
            onChange={(event) => onReviewerChange(event.target.value)}
            placeholder="e.g. Jamie Tan"
            type="text"
            value={reviewer}
          />
        </label>
      </div>

      <fieldset>
        <legend>Decision</legend>
        <div className="action-grid">
          {ACTION_ORDER.map((option) => {
            const enabled = allowed.includes(option);
            return (
              <label
                className={`radio-card${enabled ? "" : " disabled"}`}
                key={option}
              >
                <input
                  checked={action === option}
                  disabled={!enabled}
                  name="action"
                  onChange={() => setAction(option)}
                  type="radio"
                />
                <span>
                  <strong>
                    {actionLabels[option].title}
                    {enabled && option === ticket.recommended_action && (
                      <em className="flag recommended">Recommended</em>
                    )}
                  </strong>
                  <small>
                    {enabled
                      ? actionLabels[option].description
                      : "Not possible while a field is undecided."}
                  </small>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      {action === "corrected" && (
        <div className="correction-grid">
          <div className="correction-header">
            <span>Field</span>
            <span>SI value</span>
            <span>BL value</span>
          </div>
          {FIELD_ORDER.map((field) => (
            <div
              className={`correction-row${questionable.has(field) ? " questionable" : ""}`}
              key={field}
            >
              <span>{fieldLabels[field]}</span>
              {SIDES.map((side) => {
                const key = correctionKey(field, side);
                return (
                  <input
                    aria-label={`${fieldLabels[field]} (${side.toUpperCase()})`}
                    key={side}
                    onChange={(event) =>
                      setDraft((previous) => ({
                        ...previous,
                        [key]: event.target.value,
                      }))
                    }
                    placeholder={
                      extracted.get(field)?.[side]?.raw ?? "Not extracted"
                    }
                    type="text"
                    value={draft[key] ?? ""}
                  />
                );
              })}
            </div>
          ))}
          <p className="hint">
            Leave a box empty to keep the extracted value. Every value you enter
            is normalized and compared exactly like an extracted one.
          </p>
        </div>
      )}

      <div className="field-group note-group">
        <label htmlFor="review-note">{actionLabels[action].note}</label>
        <textarea
          id="review-note"
          onChange={(event) => setNote(event.target.value)}
          rows={3}
          value={note}
        />
      </div>

      <button
        className="primary-button"
        disabled={submitting || blocker !== null}
        type="submit"
      >
        {submitting ? "Recording…" : `Record: ${actionLabels[action].title}`}
      </button>
      {blocker && <p className="hint">{blocker}</p>}
      {error && <p className="form-error">{error}</p>}
    </form>
  );
}
