import type { TargetResumeSupportGroup, TargetResumeSupportEvidence } from './target-resume-support';
import type { TargetResumeLine, TargetResumeV1 } from './target-resume';

/** Capacity limits apply to a single call, never to the complete résumé. */
export const FULL_TARGET_AI_VERSION = 'full-target-v6' as const;
export const FULL_TARGET_AI_MAX_BODY_BYTES = 2 * 1024 * 1024 + 64 * 1024;
export const FULL_TARGET_AI_MAX_UNITS = 20;
/** One generation call writes at most this many experience rewrites. */
export const FULL_TARGET_AI_MAX_EXPERIENCE_UNITS = 8;
export const FULL_TARGET_AI_MAX_UNIT_CHARACTERS = 16_000;
export const FULL_TARGET_AI_MAX_EXPERIENCE_CHARACTERS = 6_000;
export const FULL_TARGET_AI_MAX_TARGET_CHARACTERS = 24_000;
export const FULL_TARGET_AI_MAX_PROMPT_CHARACTERS = 60_000;
/** Direction longer than this is refused by name; it is never clipped. */
export const FULL_TARGET_AI_MAX_INTERESTS_CHARACTERS = 8_000;
/** Server instruction length; the batch planner counts it toward every prompt. */
export const FULL_TARGET_AI_SYSTEM_PROMPT_CHARACTERS = 8_373;
/** The server cuts at most this many anchors from the target for one prompt. */
export const FULL_TARGET_AI_MAX_ANCHORS = 48;

export type TargetResumeAiPriority = 'high' | 'normal' | 'low';
/** Why an experience line was kept as written ("unchanged"). */
export type TargetResumeAiKeepCode =
  | 'no_change' | 'no_link' | 'already_aligned' | 'no_safe_change' | 'cosmetic_only'
  | 'beyond_allowed_edit' | 'rewrite_rejected' | 'review_rejected';
/** Why a line got no usable result ("skipped"). rewrite_unchecked is retryable:
 * the rewrite passed the checks but the faithfulness review did not finish. */
export type TargetResumeAiSkipCode =
  | 'unit_too_large' | 'context_too_large' | 'target_too_large' | 'target_has_no_text'
  | 'interests_too_large' | 'batch_context_too_large'
  | 'model_unavailable' | 'invalid_model_response' | 'missing_result'
  | 'budget_exhausted' | 'timeout' | 'rewrite_unchecked';
export type TargetResumeAiReasonCode = TargetResumeAiKeepCode | TargetResumeAiSkipCode;
export const TARGET_RESUME_AI_OPS = ['lead_with', 'relabel', 'verb_first', 'personal_first', 'tighten', 'translate'] as const;
export type TargetResumeAiOp = typeof TARGET_RESUME_AI_OPS[number];
export interface TargetResumeLegacyEvidence {
  field: 'description' | 'requirement';
  requirement_index: number | null;
  start: number;
  end: number;
  quote: string;
}
export interface TargetResumePaperEvidence {
  field: 'paper_title' | 'paper_abstract'; paper_index: number; start: number; end: number; quote: string;
}
export interface TargetResumeLabEvidence {
  field: 'lab_heading' | 'lab_text'; page_index: number; section_index: number; start: number; end: number; quote: string;
}
export type TargetResumeAiEvidence = TargetResumeLegacyEvidence | TargetResumePaperEvidence | TargetResumeLabEvidence;
/** A phrase of the student's line tied to a literal target quote, both with server offsets.
 * `entailed` is true only when the faithfulness review confirmed the phrase names the
 * quoted thing; otherwise the quote is the opportunity's own words, nothing more. */
export interface TargetResumeAiLink {
  id: string;
  relation: 'same' | 'broader';
  entailed: boolean;
  target_evidence: TargetResumeAiEvidence;
  source_evidence: TargetResumeSupportEvidence;
  written_as: string | null;
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
  source_evidence?: TargetResumeSupportEvidence[];
  priority: TargetResumeAiPriority;
  reason: string;
  /** The deduplicated link targets, in link order; empty when nothing was linked. */
  target_evidence: TargetResumeAiEvidence[];
  /** Only a reviewed experience rewrite replaces text. Fact units and kept lines return null. */
  proposed_text: string | null;
  links: TargetResumeAiLink[];
  ops: TargetResumeAiOp[];
  /** The rewrite with the posting's terms taken back out, when that still passed every check. */
  alternative_text: string | null;
  /** The reason for alternative_text, without the relabel; present exactly when alternative_text is. */
  alternative_reason?: string;
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
  support_groups?: TargetResumeSupportGroup[];
  version: 1;
  request_id: string;
  locale: 'en' | 'zh';
  draft: TargetResumeV1;
  document_signature: string;
  selected_unit_ids: string[];
}
export interface TargetResumeAiResponse {
  support_groups?: TargetResumeSupportGroup[];
  /** Absent in older responses; never infer it from pipeline_version. */
  check_version?: string | null;
  version: 1;
  pipeline_version: typeof FULL_TARGET_AI_VERSION;
  request_id: string;
  document_id: string;
  opportunity_id: string;
  document_signature: string;
  base: TargetResumeV1['base'];
  manifest: { unit_ids: string[]; protected_unit_count: number };
  method: 'ai' | 'partial' | 'unavailable';
  /** The generation call plus, when a rewrite reached it, the faithfulness review. */
  logical_calls: 0 | 1 | 2;
  provider_attempts_upper_bound: 0 | 2 | 4;
  receipts: TargetResumeAiReceipt[];
}
export interface PreparedTargetResumeAi {
  support_groups?: TargetResumeSupportGroup[];
  draft: TargetResumeV1;
  document_signature: string;
  /** Exact canonical draft bytes used for synchronous compare-before-apply. */
  canonical_draft: string;
  units: TargetResumeAiUnit[];
  protected_unit_count: number;
  batches: string[][];
  skipped: TargetResumeAiReceipt[];
}
