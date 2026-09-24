import type { TargetResumeLine, TargetResumeV1 } from './target-resume';

/** Capacity limits apply to a single call, never to the complete résumé. */
export const FULL_TARGET_AI_VERSION = 'full-target-v1' as const;
export const FULL_TARGET_AI_MAX_BODY_BYTES = 2 * 1024 * 1024 + 64 * 1024;
export const FULL_TARGET_AI_MAX_UNITS = 24;
export const FULL_TARGET_AI_MAX_UNIT_CHARACTERS = 16_000;
export const FULL_TARGET_AI_MAX_EXPERIENCE_CHARACTERS = 6_000;
export const FULL_TARGET_AI_MAX_TARGET_CHARACTERS = 24_000;
export const FULL_TARGET_AI_MAX_PROMPT_CHARACTERS = 60_000;

export type TargetResumeAiPriority = 'high' | 'normal' | 'low';
export type TargetResumeAiReasonCode =
  | 'no_change' | 'unit_too_large' | 'context_too_large' | 'target_too_large'
  | 'model_unavailable' | 'invalid_model_response' | 'ungrounded_rewrite'
  | 'missing_result' | 'no_target_evidence' | 'budget_exhausted' | 'timeout';
export interface TargetResumeAiEvidence {
  field: 'description' | 'requirement';
  requirement_index: number | null;
  start: number;
  end: number;
  quote: string;
}
export interface TargetResumeAiUnit {
  unit_id: string;
  section_id: string;
  block_id: string;
  evidence: TargetResumeLine['evidence'];
  role: string;
  label: string;
  original: string;
  before_text: string;
}
export interface TargetResumeAiSuggestion {
  priority: TargetResumeAiPriority;
  reason: string;
  target_evidence: TargetResumeAiEvidence[];
  /** Only experience units may replace text. Fact units must return null. */
  proposed_text: string | null;
}
export interface TargetResumeAiReceipt {
  unit_id: string;
  section_id: string;
  block_id: string;
  evidence: TargetResumeLine['evidence'];
  before_text: string;
  status: 'suggested' | 'unchanged' | 'skipped';
  reason_code: TargetResumeAiReasonCode | null;
  suggestion: TargetResumeAiSuggestion | null;
}
export interface TargetResumeAiRequest {
  version: 1;
  request_id: string;
  locale: 'en' | 'zh';
  draft: TargetResumeV1;
  document_signature: string;
  selected_unit_ids: string[];
}
export interface TargetResumeAiResponse {
  version: 1;
  pipeline_version: typeof FULL_TARGET_AI_VERSION;
  request_id: string;
  document_id: string;
  opportunity_id: string;
  document_signature: string;
  base: TargetResumeV1['base'];
  manifest: { unit_ids: string[]; protected_unit_count: number };
  method: 'ai' | 'partial' | 'unavailable';
  logical_calls: 0 | 1;
  provider_attempts_upper_bound: 0 | 2;
  receipts: TargetResumeAiReceipt[];
}
export interface PreparedTargetResumeAi {
  draft: TargetResumeV1;
  document_signature: string;
  /** Exact canonical draft bytes used for synchronous compare-before-apply. */
  canonical_draft: string;
  units: TargetResumeAiUnit[];
  protected_unit_count: number;
  batches: string[][];
  skipped: TargetResumeAiReceipt[];
}
