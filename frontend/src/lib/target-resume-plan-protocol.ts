import type { TargetResumeV1 } from './target-resume';
import type { TargetResumeAiEvidence } from './target-resume-ai-protocol';

export const TARGET_RESUME_PLAN_VERSION = 'full-target-plan-v2' as const;
export const TARGET_RESUME_PLAN_MAX_BODY_BYTES = 2 * 1024 * 1024 + 64 * 1024;
export const TARGET_RESUME_PLAN_MAX_PROMPT_CHARACTERS = 120_000;
export interface TargetResumePlanOptions { target_pages: 1 | 2 }
export type TargetResumePlanAction = 'keep' | 'compress' | 'omit';
export interface TargetResumePlanManifestItem {
  section_id: string; block_id: string; line_ids: string[];
}
/** Covers the current draft, not every unconfirmed item ever imported. */
export interface TargetResumePlanScope {
  unreferenced_experience_ids: string[];
  pending_experience_ids: string[];
  stale_experience_ids: string[];
  unmapped_range_count: number;
}
export interface TargetResumePlanSourceEvidence {
  unit_id: string; start: number; end: number; quote: string;
}
export interface TargetResumePlanRewrite {
  unit_id: string;
  status: 'suggested' | 'skipped';
  reason_code: 'ungrounded_rewrite' | 'not_shorter' | null;
  proposed_text: string | null;
}
export interface TargetResumePlanItem {
  section_id: string; block_id: string; action: TargetResumePlanAction;
  reason: string;
  target_evidence: TargetResumeAiEvidence[];
  source_evidence: TargetResumePlanSourceEvidence[];
  rewrites: TargetResumePlanRewrite[];
}
export interface TargetResumePlanRequest {
  version: 1; request_id: string; locale: 'en' | 'zh';
  draft: TargetResumeV1; document_signature: string;
  options: TargetResumePlanOptions;
}
export type TargetResumePlanReason = 'context_too_large' | 'target_too_large'
  | 'no_plan_items' | 'budget_exhausted' | 'model_unavailable' | 'timeout'
  | 'invalid_model_response' | 'no_target_evidence' | 'no_source_evidence';
export interface TargetResumePlanResponse {
  /** Absent in older responses; never infer it from pipeline_version. */
  check_version?: string | null;
  version: 1; pipeline_version: typeof TARGET_RESUME_PLAN_VERSION;
  request_id: string; document_id: string; opportunity_id: string;
  document_signature: string; base: TargetResumeV1['base'];
  options: TargetResumePlanOptions;
  manifest: TargetResumePlanManifestItem[]; scope: TargetResumePlanScope;
  method: 'ai' | 'unavailable'; complete: boolean;
  reason_code: TargetResumePlanReason | null;
  logical_calls: 0 | 1; provider_attempts_upper_bound: 0 | 2;
  items: TargetResumePlanItem[];
}
export interface PreparedTargetResumePlan {
  draft: TargetResumeV1; canonical_draft: string; document_signature: string;
  options: TargetResumePlanOptions;
  manifest: TargetResumePlanManifestItem[]; scope: TargetResumePlanScope;
}
/** Explicit user decisions, separate from generated advice and rewrites. */
export interface ApplyTargetResumePlanOptions {
  selection_block_ids: string[];
  rewrite_unit_ids: string[];
  current_context: { profile_signature: string; source_signature: string; target_signature: string };
  options: TargetResumePlanOptions;
}
