import type { components } from "./generated/api";

type Schemas = components["schemas"];

export type HealthResponse = Schemas["HealthResponse"];

export type CaseOutcome = Schemas["CaseOutcome"];
export type DocumentRead = Schemas["DocumentRead"];
export type DocumentSide = Schemas["DocumentSide"];
export type FieldComparison = Schemas["FieldComparison"];
export type FieldName = Schemas["FieldName"];
export type FieldValue = Schemas["FieldValue"];
export type FinalReport = Schemas["FinalReport"];
export type InboxRun = Schemas["InboxRun"];
export type ReviewAction = Schemas["ReviewAction"];
export type ReviewDecision = Schemas["ReviewDecision"];
export type ReviewDecisionRequest = Schemas["DecisionRequest"];
export type ReviewPackage = Schemas["ReviewPackage"];
export type ReviewPriority = Schemas["ReviewPriority"];
export type ReviewQueue = Schemas["ReviewQueue"];
export type ReviewQueueItem = Schemas["ReviewQueueItem"];
export type ReviewReason = Schemas["ReviewReason"];
export type ReviewStatus = Schemas["ReviewStatus"];
export type ReviewTeam = Schemas["ReviewTeam"];
export type ReviewTicket = Schemas["ReviewTicket"];
export type StageAttempt = Schemas["StageAttempt"];
