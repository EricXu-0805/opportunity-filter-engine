// Page-local types for /admin (R36 split).
// Mirrors the response shapes returned by the FastAPI admin endpoints
// (src/api/admin_routes.py — adminFetch consumers below).

import type { useT } from '@/i18n/client';

export type FieldKey =
  | 'empty_majors'
  | 'empty_keywords'
  | 'empty_description'
  | 'missing_deadline'
  | 'missing_skills';

export interface SourceRow {
  source: string;
  total: number;
  empty_majors?: number;
  empty_keywords?: number;
  empty_description?: number;
  short_description?: number;
  missing_deadline?: number;
  rolling_deadline?: number;
  missing_skills?: number;
  past_deadline?: number;
  stale_verify?: number;
  flagged_inactive?: number;
}

export interface WorstField {
  id: string;
  title: string;
  source: string;
  missing_count: number;
  missing_fields?: FieldKey[];
  url: string;
}

export interface AdminResponse {
  total: number;
  global: Record<string, number>;
  sources: SourceRow[];
  worst_fields: WorstField[];
  generated_at: string;
  data_updated_at?: string | null;
}

export interface HistoryEntry {
  t: string;
  total: number;
  empty_majors?: number;
  empty_keywords?: number;
  missing_deadline?: number;
  rolling_deadline?: number;
  flagged_inactive?: number;
}

export interface CollectorRow {
  source: string;
  status: string;
  fetched?: number;
  new?: number;
  updated?: number;
  error?: string;
  deep?: boolean;
}

export interface CollectorStatus {
  sources: CollectorRow[];
  last_run_at?: string | null;
  duration_seconds?: number;
  total_in_file?: number;
}

export interface CollectorHistorySourceCounts {
  status?: string;
  new?: number;
  updated?: number;
  fetched?: number;
}

export interface CollectorHistoryEntry {
  t?: string;
  duration_seconds?: number;
  total_new?: number;
  total_updated?: number;
  total_in_file?: number;
  sources?: Record<string, CollectorHistorySourceCounts>;
}

export interface HealthAlert {
  level: 'alert' | 'warn';
  kind: string;
  message: string;
  metric?: string;
  current?: number;
  baseline?: number;
  delta?: number;
  pct_jump?: number;
}

export interface HealthResponse {
  ok: boolean;
  alerts: HealthAlert[];
  checked_at: string;
}

export interface SavedSearchHealth {
  status: 'ok' | 'unconfigured';
  missing?: string[];
  searches?: { total: number; digest_opt_in: number };
  refresh?: { last_run_at: string | null; never_run: number; stale_over_48h: number };
  digest?: { last_sent_at: string | null; opted_in_never_sent: number };
  resend_configured?: boolean;
  generated_at?: string;
}

// ---------------------------------------------------------------------------
// Support tickets (W15). A feedback row is a ticket: it carries handling
// state, an assignee, a reply with its OWN delivery outcome, and a resolution
// that is separate from the reply. Workflow fields are optional here because
// the list endpoint is shared with pre-W15 rows (and with a backend that may
// not have shipped yet) — the UI reads them through the DEFAULT_* fallbacks
// below rather than assuming a value the server never sent.
// ---------------------------------------------------------------------------

export const TICKET_STATUSES = [
  'open',
  'triaged',
  'in_progress',
  'waiting_on_user',
  'resolved',
  'closed',
] as const;
export type TicketStatus = (typeof TICKET_STATUSES)[number];

/** Statuses an operator can pick directly. Resolving/closing goes through the
 *  resolve control instead, because both REQUIRE a resolution. */
export const TICKET_OPEN_STATUSES = [
  'open',
  'triaged',
  'in_progress',
  'waiting_on_user',
] as const;

/** Terminal statuses — reaching one always needs a resolution. */
export const TICKET_CLOSING_STATUSES = ['resolved', 'closed'] as const;

export const PRIORITIES = ['low', 'normal', 'high', 'urgent'] as const;
export type Priority = (typeof PRIORITIES)[number];

export const TICKET_RESOLUTIONS = [
  'fixed',
  'expected_behavior',
  'duplicate',
  'data_corrected',
  'unable_to_reproduce',
  'wont_fix',
  'user_guidance_provided',
] as const;
export type TicketResolution = (typeof TICKET_RESOLUTIONS)[number];

/** What actually happened to a reply. 'stored' is NOT 'sent'. */
export type ReplyDelivery = 'stored' | 'emailed' | 'email_failed';

export const DEFAULT_TICKET_STATUS: TicketStatus = 'open';
export const DEFAULT_PRIORITY: Priority = 'normal';

export interface Ticket {
  id: string;
  created_at: string;
  updated_at?: string | null;
  category?: string | null;
  subject?: string | null;
  message: string;
  email: string | null;
  props?: { path?: string } & Record<string, unknown>;
  status?: TicketStatus;
  priority?: Priority;
  assigned_to?: string | null;
  admin_reply?: string | null;
  admin_reply_at?: string | null;
  admin_reply_by?: string | null;
  admin_reply_delivery?: ReplyDelivery | null;
  resolution?: TicketResolution | null;
  resolution_note?: string | null;
  resolved_by?: string | null;
  resolved_at?: string | null;
}

/** Pre-W15 name kept so older call sites keep compiling. */
export type FeedbackEntry = Ticket;

export interface TicketEvent {
  actor: string;
  action: string;
  from_value?: string | null;
  to_value?: string | null;
  note?: string | null;
  created_at: string;
}

export interface TicketDetail {
  ticket: Ticket;
  events: TicketEvent[];
}

export interface TicketPatch {
  status?: TicketStatus;
  priority?: Priority;
  assigned_to?: string | null;
  resolution?: TicketResolution;
  resolution_note?: string;
}

export interface TicketFilters {
  status: TicketStatus | '';
  priority: Priority | '';
  unresolvedOnly: boolean;
}

export interface TicketWorkflow {
  /** Set when the inbox itself could not be read. The section then renders the
   *  failure instead of disappearing as if there were no tickets. */
  loadError: string | null;
  filters: TicketFilters;
  onFiltersChange: (f: TicketFilters) => void;
  details: Record<string, TicketDetail | undefined>;
  detailLoading: Record<string, boolean>;
  onOpen: (id: string) => void;
  /** Resolves to true only once the API confirmed AND the refetch ran. */
  onPatch: (id: string, patch: TicketPatch) => Promise<boolean>;
  onReply: (id: string, reply: string, deliver: boolean) => Promise<boolean>;
  pending: Record<string, boolean>;
  errors: Record<string, string | null>;
  replyPending: Record<string, boolean>;
  replyErrors: Record<string, string | null>;
}

export interface FeedbackRateRow {
  key: string;
  n: number;
  up_rate: number;
}

export interface FeedbackReplayReport {
  mode: 'weight_replay' | 'score_band_agreement';
  current_agreement: number | null;
  best_candidate: { eligibility: number; readiness: number; upside: number } | null;
  delta: number | null;
  sample_n: number;
  note: string;
}

export interface FeedbackAnalysis {
  insufficient?: boolean;
  needed?: number;
  sample_n: number;
  up_rate?: number;
  by_bucket?: FeedbackRateRow[];
  by_score_band?: FeedbackRateRow[];
  by_school?: FeedbackRateRow[];
  by_position?: FeedbackRateRow[];
  keyword_overlap?: { available: boolean; reason: string };
  replay?: FeedbackReplayReport;
}

export interface FeedbackInbox {
  status: 'ok' | 'skipped';
  reason?: string;
  entries?: Ticket[];
  count?: number;
  match_feedback?: {
    up: number;
    down: number;
    up_7d: number;
    down_7d: number;
    sample_size: number;
    top_downvoted: { opportunity_id: string; downs: number; title: string | null }[];
    analysis?: FeedbackAnalysis;
  };
}

export interface OrderEntry {
  id: string;
  device_id: string;
  package: string;
  amount_cents: number;
  currency: string;
  status: string;
  channel: string;
  note?: string | null;
  created_at: string;
  paid_at?: string | null;
}

export interface OrdersInbox {
  status: 'ok' | 'skipped';
  reason?: string;
  orders?: OrderEntry[];
  count?: number;
}

// ---------------------------------------------------------------------------
// Operations queue (W15). One table, four kinds — collector failures, data
// drift, notification failures, and manual review all share a lifecycle so
// nothing rots in a queue nobody opens.
// ---------------------------------------------------------------------------

export const OPS_KINDS = [
  'collector_failure',
  'data_drift',
  'notification_failure',
  'manual_review',
] as const;
export type OpsIncidentKind = (typeof OPS_KINDS)[number];

/** Kinds where an operator can meaningfully re-run the thing that failed. */
export const OPS_RETRYABLE_KINDS: readonly OpsIncidentKind[] = [
  'collector_failure',
  'notification_failure',
];

export const OPS_STATUSES = [
  'open',
  'acknowledged',
  'investigating',
  'resolved',
  'suppressed',
] as const;
export type OpsIncidentStatus = (typeof OPS_STATUSES)[number];

/** Statuses that take an incident out of the working queue. Both require a
 *  resolution, so neither is offered on the plain status control. */
export const OPS_CLOSED_STATUSES: readonly OpsIncidentStatus[] = ['resolved', 'suppressed'];

export type OpsFailureState = 'failed' | 'timed_out' | 'blocked' | 'partial' | 'recovered';

/** Operational outcomes. 'auto_recovered' is detector evidence, so it is only
 *  offered once a detector actually observed a recovery. */
export const OPS_OPERATIONAL_RESOLUTIONS = [
  'fixed',
  'legitimate_change',
  'wont_fix',
  'duplicate',
  'not_reproducible',
  'suppressed',
] as const;

/** Review outcomes. Ambiguity is a first-class answer: an operator must never
 *  be cornered into verified/rejected when the evidence does not support one. */
export const OPS_REVIEW_RESOLUTIONS = [
  'verified',
  'rejected',
  'unknown',
  'conflicting',
  'needs_more_evidence',
] as const;

export type OpsResolution =
  | (typeof OPS_OPERATIONAL_RESOLUTIONS)[number]
  | (typeof OPS_REVIEW_RESOLUTIONS)[number]
  | 'auto_recovered';

export interface OpsIncident {
  id: string;
  kind: OpsIncidentKind;
  dedup_key: string;
  scope?: string | null;
  entity_type?: string | null;
  entity_id?: string | null;
  field?: string | null;
  title: string;
  summary?: string | null;
  detail?: Record<string, unknown> | null;
  priority?: Priority;
  status?: OpsIncidentStatus;
  failure_state?: OpsFailureState | null;
  assigned_to?: string | null;
  first_detected_at?: string | null;
  last_detected_at?: string | null;
  occurrence_count?: number;
  last_success_at?: string | null;
  attempt_count?: number;
  last_attempt_at?: string | null;
  next_retry_at?: string | null;
  resolution?: OpsResolution | null;
  resolution_note?: string | null;
  resolved_by?: string | null;
  resolved_at?: string | null;
}

export interface OpsIncidentEvent {
  actor: string;
  action: string;
  from_value?: string | null;
  to_value?: string | null;
  note?: string | null;
  created_at: string;
}

export interface OpsIncidentDetail {
  incident: OpsIncident;
  events: OpsIncidentEvent[];
}

export type OpsRollup = Partial<Record<OpsIncidentKind, number>>;

export interface OpsIncidentsResponse {
  incidents?: OpsIncident[];
  rollup?: OpsRollup;
}

export interface OpsPatch {
  status?: OpsIncidentStatus;
  priority?: Priority;
  assigned_to?: string | null;
  resolution?: OpsResolution;
  resolution_note?: string;
}

export interface OpsFilters {
  kind: OpsIncidentKind | '';
  /** 'unresolved' is the default working view; 'all' shows closed ones too. */
  status: OpsIncidentStatus | 'unresolved' | 'all';
}

export interface OpsWorkflow {
  incidents: OpsIncident[];
  rollup: OpsRollup;
  loaded: boolean;
  error: string | null;
  filters: OpsFilters;
  onFiltersChange: (f: OpsFilters) => void;
  details: Record<string, OpsIncidentDetail | undefined>;
  detailLoading: Record<string, boolean>;
  onOpen: (id: string) => void;
  onPatch: (id: string, patch: OpsPatch) => Promise<boolean>;
  /** Records an operator retry attempt. Never claims the retry worked. */
  onRetry: (id: string) => Promise<boolean>;
  pending: Record<string, boolean>;
  errors: Record<string, string | null>;
}

export type TriggerStatus = {
  kind: 'idle' | 'busy' | 'ok' | 'err';
  message?: string;
};

export type TFunc = ReturnType<typeof useT>['t'];
