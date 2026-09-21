"use client";

import type {
  InboxRun,
  ReviewPackage,
  ReviewQueue,
  ReviewQueueItem,
  ReviewStatus,
} from "@sdoc/contracts";
import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";

import { ReviewPackageView } from "@/app/review/review-package";
import {
  actionLabels,
  fieldLabels,
  priorityLabels,
  readError,
  reasonLabels,
  statusLabels,
  teamLabels,
} from "@/lib/review";
import { readReviewer, subscribeReviewer, writeReviewer } from "@/lib/reviewer";

type QueueTab = Exclude<ReviewStatus, "not_required">;
type LoadedPackage = {
  error: string | null;
  id: string;
  reviewPackage: ReviewPackage | null;
};

const TABS: readonly QueueTab[] = [
  "pending",
  "awaiting_information",
  "resolved",
];

const emptyTabText: Record<QueueTab, string> = {
  awaiting_information: "No case is waiting for information.",
  pending: "No case is waiting for a reviewer.",
  resolved: "No case has been resolved yet.",
};

async function fetchJson<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, { cache: "no-store", ...init });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as T;
}

function describeError(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function QueueCard({
  item,
  onOpen,
  selected,
}: {
  item: ReviewQueueItem;
  onOpen: () => void;
  selected: boolean;
}) {
  const fields = item.questionable_fields ?? [];
  return (
    <button
      aria-current={selected ? "true" : undefined}
      className={`queue-card${selected ? " selected" : ""}`}
      onClick={onOpen}
      type="button"
    >
      <span className="queue-card-top">
        <strong>{item.email_id}</strong>
        <span className={`priority-badge ${item.priority}`}>
          {priorityLabels[item.priority]}
        </span>
      </span>
      <span className="queue-subject">{item.subject || "(no subject)"}</span>
      <span className="queue-meta">
        {item.reason ? reasonLabels[item.reason] : "Quality gate"} ·{" "}
        {teamLabels[item.team]}
      </span>
      <span className="queue-summary">{item.summary}</span>
      {fields.length > 0 && fields.length < 7 && (
        <span className="field-chips">
          {fields.map((field) => (
            <span key={field}>{fieldLabels[field]}</span>
          ))}
        </span>
      )}
      {item.last_decision && (
        <span className="queue-meta">
          {actionLabels[item.last_decision.action].title} by{" "}
          {item.last_decision.reviewer}
        </span>
      )}
    </button>
  );
}

export function ReviewWorkbench({
  apiConnected,
  initialCase,
}: {
  apiConnected: boolean;
  initialCase: string | null;
}) {
  const reviewer = useSyncExternalStore(
    subscribeReviewer,
    readReviewer,
    () => "",
  );
  const [tab, setTab] = useState<QueueTab>("pending");
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [queueVersion, setQueueVersion] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(initialCase);
  const [packageVersion, setPackageVersion] = useState(0);
  const [loaded, setLoaded] = useState<LoadedPackage | null>(null);
  const [inboxRun, setInboxRun] = useState<InboxRun | null>(null);
  const [processing, setProcessing] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!apiConnected) return;
    let active = true;
    fetchJson<ReviewQueue>("/api/review")
      .then((value) => {
        if (active) setQueue(value);
      })
      .catch((reason: unknown) => {
        if (active)
          setError(describeError(reason, "The queue could not be loaded."));
      });
    return () => {
      active = false;
    };
  }, [apiConnected, queueVersion]);

  useEffect(() => {
    if (!apiConnected || !selectedId) return;
    let active = true;
    fetchJson<ReviewPackage>(`/api/review/${encodeURIComponent(selectedId)}`)
      .then((reviewPackage) => {
        if (active) setLoaded({ error: null, id: selectedId, reviewPackage });
      })
      .catch((reason: unknown) => {
        if (active)
          setLoaded({
            error: describeError(
              reason,
              "The review package could not be loaded.",
            ),
            id: selectedId,
            reviewPackage: null,
          });
      });
    return () => {
      active = false;
    };
  }, [apiConnected, selectedId, packageVersion]);

  const current = loaded && loaded.id === selectedId ? loaded : null;
  const loadingPackage =
    apiConnected && selectedId !== null && current === null;
  const items = queue?.items.filter((item) => item.status === tab) ?? [];
  const counts = queue?.counts;
  const openCount =
    (counts?.pending ?? 0) + (counts?.awaiting_information ?? 0);

  function openCase(emailId: string) {
    setSelectedId(emailId);
    window.history.replaceState(
      null,
      "",
      `/review?case=${encodeURIComponent(emailId)}`,
    );
  }

  function handleDecided(updated: ReviewPackage) {
    setLoaded({
      error: null,
      id: updated.email.email_id,
      reviewPackage: updated,
    });
    setQueueVersion((version) => version + 1);
  }

  async function processInbox() {
    setProcessing(true);
    setError(null);
    try {
      setInboxRun(await fetchJson<InboxRun>("/api/review", { method: "POST" }));
      setQueueVersion((version) => version + 1);
    } catch (reason) {
      setError(describeError(reason, "The inbox could not be processed."));
    } finally {
      setProcessing(false);
    }
  }

  async function retryCase() {
    if (!selectedId) return;
    setRetrying(true);
    setError(null);
    try {
      await fetchJson<unknown>(
        `/api/review/${encodeURIComponent(selectedId)}/retry`,
        { method: "POST" },
      );
      setPackageVersion((version) => version + 1);
      setQueueVersion((version) => version + 1);
    } catch (reason) {
      setError(describeError(reason, "The case could not be processed again."));
    } finally {
      setRetrying(false);
    }
  }

  const inboxSummary = inboxRun
    ? `${inboxRun.processed} emails processed${
        inboxRun.skipped ? ` (${inboxRun.skipped} already done)` : ""
      }. ${inboxRun.queued_for_review} cases need a person.`
    : queue && queue.items.length > 0
      ? `${openCount} open cases · ${counts?.resolved ?? 0} resolved`
      : "Run the inbox through the pipeline to find the cases it cannot decide on its own.";

  return (
    <main>
      <header className="hero">
        <div>
          <p className="eyebrow">Human in the loop</p>
          <h1>Review queue</h1>
          <p className="subtitle">
            Cases the pipeline could not decide on its own, with the source
            evidence and the reason. Confirm, correct, request information, or
            mark a case unable to verify. The final report updates at once.
          </p>
        </div>
        <div className="hero-actions">
          <span
            className={`status-pill ${apiConnected ? "connected" : "offline"}`}
          >
            <span /> FastAPI {apiConnected ? "connected" : "unavailable"}
          </span>
          <Link className="nav-link" href="/">
            ← Verification workbench
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

      <section className="queue-toolbar">
        <div>
          <strong>Shared inbox</strong>
          <span>{inboxSummary}</span>
        </div>
        <button
          className="primary-button toolbar-button"
          disabled={!apiConnected || processing}
          onClick={processInbox}
          type="button"
        >
          {processing ? "Processing inbox…" : "Process inbox"}
        </button>
      </section>

      {error && <p className="form-error page-error">{error}</p>}

      <div className="review-layout">
        <aside aria-label="Review queue" className="control-panel queue-panel">
          <div className="segmented queue-tabs" role="tablist">
            {TABS.map((option) => (
              <button
                aria-selected={tab === option}
                className={tab === option ? "active" : ""}
                key={option}
                onClick={() => setTab(option)}
                role="tab"
                type="button"
              >
                {statusLabels[option]}
                <span className="count">{counts?.[option] ?? 0}</span>
              </button>
            ))}
          </div>
          <div className="queue-list">
            {items.length === 0 ? (
              <p className="queue-empty">
                {queue && queue.items.length > 0
                  ? emptyTabText[tab]
                  : "The queue is empty. Process the inbox to fill it."}
              </p>
            ) : (
              items.map((item) => (
                <QueueCard
                  item={item}
                  key={item.email_id}
                  onOpen={() => openCase(item.email_id)}
                  selected={item.email_id === selectedId}
                />
              ))
            )}
          </div>
        </aside>

        {current?.reviewPackage ? (
          <ReviewPackageView
            onDecided={handleDecided}
            onRetry={retryCase}
            onReviewerChange={writeReviewer}
            retrying={retrying}
            reviewPackage={current.reviewPackage}
            reviewer={reviewer}
          />
        ) : (
          <section className="results-panel">
            <div className="empty-state">
              <div>⚑</div>
              <h2>
                {loadingPackage
                  ? "Loading the review package…"
                  : current?.error
                    ? "Review package unavailable"
                    : "Choose a case"}
              </h2>
              <p>
                {current?.error ??
                  "Open a case from the queue to see the original email, both documents, the fields in question with their evidence, and why it was escalated."}
              </p>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
