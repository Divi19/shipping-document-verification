import type {
  DocumentSide,
  FieldComparison,
  FieldName,
  ReviewAction,
  ReviewDecisionRequest,
  ReviewPriority,
  ReviewReason,
  ReviewStatus,
  ReviewTeam,
} from "@sdoc/contracts";

export const FIELD_ORDER: readonly FieldName[] = [
  "shipper",
  "consignee",
  "notify_party",
  "port_of_loading",
  "port_of_discharge",
  "container_count",
  "gross_weight_kg",
];

export const SIDES: readonly DocumentSide[] = ["si", "bl"];

export const ACTION_ORDER: readonly ReviewAction[] = [
  "confirmed",
  "corrected",
  "information_requested",
  "unable_to_verify",
];

export const fieldLabels: Record<FieldName, string> = {
  shipper: "Shipper",
  consignee: "Consignee",
  notify_party: "Notify party",
  port_of_loading: "Port of loading",
  port_of_discharge: "Port of discharge",
  container_count: "Container count",
  gross_weight_kg: "Gross weight",
};

export const actionLabels: Record<
  ReviewAction,
  { title: string; description: string; note: string }
> = {
  confirmed: {
    title: "Confirm result",
    description: "The automated comparison is right. Release it as final.",
    note: "Note (optional)",
  },
  corrected: {
    title: "Correct values",
    description:
      "Enter values as they appear in the source documents. The comparison runs again.",
    note: "Where you read the values (optional)",
  },
  information_requested: {
    title: "Request information",
    description:
      "Ask the sender for a missing, readable, or complete document. The case waits.",
    note: "Message to the sender (required)",
  },
  unable_to_verify: {
    title: "Mark unable to verify",
    description: "Close the case without a result, and record why.",
    note: "Why it cannot be verified (required)",
  },
};

export const reasonLabels: Record<ReviewReason, string> = {
  missing_attachment: "Missing attachment",
  missing_value: "Missing value",
  unreadable: "Unreadable document",
  wrong_doc_type: "Wrong document type",
};

export const teamLabels: Record<ReviewTeam, string> = {
  document_intake: "Document intake",
  field_verification: "Field verification",
};

export const priorityLabels: Record<ReviewPriority, string> = {
  high: "High",
  low: "Low",
  normal: "Normal",
};

export const statusLabels: Record<ReviewStatus, string> = {
  awaiting_information: "Awaiting information",
  not_required: "Not required",
  pending: "Pending",
  resolved: "Resolved",
};

/** Reviewer input per field and side, keyed as `field:side`. */
export type CorrectionDraft = Partial<
  Record<`${FieldName}:${DocumentSide}`, string>
>;

export function correctionKey(
  field: FieldName,
  side: DocumentSide,
): `${FieldName}:${DocumentSide}` {
  return `${field}:${side}`;
}

export function noteRequired(action: ReviewAction): boolean {
  return action === "information_requested" || action === "unable_to_verify";
}

/** Build the decision payload; only filled-in corrections are sent, in field order. */
export function buildDecision(
  reviewer: string,
  action: ReviewAction,
  note: string,
  draft: CorrectionDraft,
): ReviewDecisionRequest {
  const corrections =
    action === "corrected"
      ? FIELD_ORDER.flatMap((field) =>
          SIDES.flatMap((side) => {
            const value = draft[correctionKey(field, side)]?.trim();
            return value ? [{ field, side, value }] : [];
          }),
        )
      : [];
  return {
    action,
    corrections,
    note: note.trim() || null,
    reviewer: reviewer.trim(),
  };
}

/** Explain why the decision cannot be sent yet, or return null when it can. */
export function decisionBlocker(
  decision: ReviewDecisionRequest,
): string | null {
  if (!decision.reviewer) return "Enter your name to record a decision.";
  if (noteRequired(decision.action) && !decision.note)
    return "Write a note for this decision.";
  if (decision.action === "corrected" && !decision.corrections?.length)
    return "Enter at least one corrected value.";
  return null;
}

/** One row per compared field, in order, even when nothing was compared. */
export function comparisonRows(
  comparisons: FieldComparison[],
): { comparison: FieldComparison | null; field: FieldName }[] {
  return FIELD_ORDER.map((field) => ({
    comparison: comparisons.find((item) => item.field === field) ?? null,
    field,
  }));
}

export function comparisonStatus(comparison: FieldComparison | null): string {
  if (
    !comparison ||
    comparison.matches === null ||
    comparison.matches === undefined
  )
    return comparison ? "uncertain" : "not compared";
  return comparison.matches ? "match" : "mismatch";
}

/** Turn a FastAPI error body (string or validation list) into one message. */
export function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item) => (item as { msg?: string }).msg ?? String(item))
      .join("; ");
  }
  return `Request failed with status ${status}`;
}

export async function readError(response: Response): Promise<string> {
  try {
    return errorMessage(await response.json(), response.status);
  } catch {
    return errorMessage(null, response.status);
  }
}

/** `needs_review` -> `needs review`, for enum values shown as text. */
export function humanize(value: string): string {
  return value.replaceAll("_", " ");
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatConfidence(
  value: number | null | undefined,
): string | null {
  return value === null || value === undefined
    ? null
    : `${Math.round(value * 100)}% confidence`;
}
