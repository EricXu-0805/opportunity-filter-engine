// ── Skill Proficiency ────────────────────────────────────────────────
export type SkillLevel = 'beginner' | 'experienced' | 'expert';

export interface SkillWithLevel {
  name: string;
  level: SkillLevel;
}

// ── Frontend Profile (form state) ────────────────────────────────────
export interface ProfileData {
  institution: string;
  /**
   * Lowercase school slug from lib/schools.ts ('uiuc', 'ucb', …).
   * Optional for backward compatibility with stored profiles that
   * predate the switcher — readers default to 'uiuc' when absent.
   */
  home_school?: string;
  college: string;
  major: string;
  /**
   * Additional majors and minors beyond the primary `major` — double majors,
   * interdisciplinary combinations, minors. Optional for backward compatibility
   * with stored profiles that predate the field; maps to the backend request's
   * `secondary_interests` (extra major + keyword matching signal).
   */
  additional_majors?: string[];
  grade: string;
  is_international: boolean;
  research_interests: string;
  skills: SkillWithLevel[];
  resume_text?: string;
  coursework?: string[];
  search_weight?: number;
  /** "I'm still exploring" — widens matching for undecided students. */
  exploring?: boolean;
  /**
   * Opt-in to other schools' opportunities (default off — home school
   * first). National records and summer programs always show.
   */
  include_cross_school?: boolean;
  linkedin_url?: string;
  github_url?: string;
  /** The student's own public Google Scholar profile URL (e.g.
   * https://scholar.google.com/citations?user=…). Optional; like linkedin_url
   * it does not inform matching — it's surfaced in the cold-email signature. */
  scholar_url?: string;
  seeking_types?: string[];
  name?: string;
  experience_level?: string;
  /**
   * Account tier. 'org' is reserved at the type level only (no org tables
   * yet); readers default to 'personal' when absent.
   */
  account_type?: 'personal' | 'org';
}

// ── Backend Profile Request ──────────────────────────────────────────
export interface ProfileRequest {
  name: string;
  school: string;
  /** Lowercase school slug; drives the backend discovery-scope pre-filter. */
  home_school: string;
  year: string;
  major: string;
  college: string;
  secondary_interests: string[];
  international_student: boolean;
  seeking_type: string[];
  desired_fields: string[];
  hard_skills: SkillWithLevel[];
  coursework: string[];
  experience_level: string;
  resume_ready: boolean;
  can_cold_email: boolean;
  research_interests_text: string;
  linkedin_url: string;
  github_url: string;
  scholar_url: string;
  search_weight: number;  // 0-100: 0=pure interests, 100=pure experience
  exploring: boolean;     // widen matching for undecided students
  include_cross_school: boolean;  // opt-in to other schools' opportunities
}

// ── Opportunity (backend shape) ──────────────────────────────────────
export interface OpportunityEligibility {
  international_friendly: string; // "yes" | "no" | "unknown"
  preferred_year: string[];
  majors: string[];
  skills_required: string[];
  citizenship_required: boolean;
}

export interface OpportunityApplication {
  application_effort: string;
  requires_resume: string;
  requires_recommendation?: string;
  requires_cover_letter?: string;
  contact_method: string;
  application_url?: string;
}

export interface OpportunityMetadata {
  is_active: boolean;
  confidence_score: number;
  // OpenAlex-harvested recent papers on faculty records (title + year only —
  // the harvest stores no URLs). Absent on non-faculty records and on faculty
  // without a confident OpenAlex match.
  recent_works?: { title: string; year?: number | null }[];
}

// Multi-university discovery scope (PR #187 / #189). `school` is the
// lowercase host-school slug, null for national programs; `audience`
// says who may apply. Both optional: cached results predating #189
// simply lack them and render without scope chips.
export type OpportunityAudience = 'campus' | 'open' | 'unknown';

export interface Opportunity {
  id: string;
  title: string;
  organization: string;
  department?: string;
  lab_or_program?: string;
  pi_name?: string | null;
  opportunity_type: string;
  paid: string;
  location: string;
  url?: string;
  source?: string;
  source_url?: string;
  source_type?: string;
  school?: string | null;
  audience?: OpportunityAudience;
  on_campus: boolean;
  description_clean: string;
  description_raw?: string;
  keywords: string[];
  deadline?: string;
  deadline_is_estimate?: boolean;
  is_rolling?: boolean;
  compensation_details?: string;
  duration?: string;
  start_date?: string;
  posted_date?: string;
  remote_option?: string;
  eligibility: OpportunityEligibility;
  application: OpportunityApplication;
  metadata: OpportunityMetadata;
  // Match-card projection of metadata.recent_works (title/year only) — the
  // /matches card payload carries it top-level; the full record keeps the
  // complete list under metadata.
  recent_works?: { title: string; year?: number | string | null }[];
  // Record-scoped follow/tracking id (W8) — present on faculty detail
  // payloads only; the key for professor_follows and /professors/updates.
  professor_id?: string;
}

// ── Match Results ────────────────────────────────────────────────────
export type MatchBucket = 'high_priority' | 'good_match' | 'reach' | 'low_fit';

export interface MatchResult {
  opportunity_id: string;
  eligibility_score: number;
  readiness_score: number;
  upside_score: number;
  final_score: number;
  bucket: MatchBucket;
  reasons_fit: string[];
  reasons_gap: string[];
  next_steps: string[];
  // One concrete, student-specific sentence from the LLM rerank — the card's
  // lead line for top-K results; absent outside the reranked window.
  ai_reason?: string | null;
  opportunity: Opportunity;
}

export interface MatchesResponse {
  total: number;
  high_priority: number;
  good_match: number;
  reach: number;
  low_fit: number;
  results: MatchResult[];
  // Visible results that topically match the student's stated interests OR
  // major-derived field. Optional: absent on older backends (degrade to the
  // plain total). `thin_inventory` true → the field has few openings right now.
  field_relevant_count?: number;
  thin_inventory?: boolean;
}

// ── Cold Email ───────────────────────────────────────────────────────
/**
 * Mirrors `backend.schemas.ColdEmailResponse`. `method` reflects which
 * generator ultimately produced the email: ``"ai"`` when an LLM provider
 * was configured AND returned a usable draft, ``"template"`` otherwise
 * (either no provider configured or the LLM call failed and we fell back).
 *
 * `lab_type` is the detected wet/dry/humanities classification used by
 * the backend to pick a tone-appropriate system prompt or template ask.
 * Mirrors `src/recommender/cold_email.py:_detect_lab_type`. The frontend
 * surfaces this as a badge in `ColdEmailModal` and uses it to look up
 * the right `EmailTipsPanel` content (Skills to Highlight / Common
 * Mistakes).
 */
export type LabType = 'wet' | 'dry' | 'humanities';

/** Voice overlay for the AI engine — mirrors `ColdEmailRequest.style`. */
export type EmailStyle = 'professional' | 'warm' | 'friendly' | 'lively';

export type ColdEmailFallbackReason =
  | 'not_configured'
  | 'unavailable'
  | 'invalid_output'
  | 'fabrication';

export interface ColdEmailResponse {
  subject: string;
  body: string;
  recipient_email: string;
  mailto_link: string;
  method: 'template' | 'ai';
  lab_type?: LabType | null;
  /** The voice overlay applied (null on the template path). */
  style?: EmailStyle | null;
  /** Suggested default tone for this lab_type (UI badges it). */
  recommended_style?: EmailStyle | null;
  /** R72-A: why the template was served when AI was requested (null on success). */
  fallback_reason?: ColdEmailFallbackReason | null;
}

export type ColdEmailEngine = 'template' | 'ai';

export interface EmailVariant {
  id: string;
  label: string;
  subject: string;
  body: string;
  recipient_email: string;
  mailto_link: string;
  lab_type?: LabType | null;
  // FE-5: provenance for the AI variant — when the backend degraded to the
  // template ('AI' pill clicked but method !== 'ai'), this lets the UI surface a
  // durable "template, not AI" badge instead of only a transient chat bubble.
  method?: 'template' | 'ai';
  fallback_reason?: ColdEmailFallbackReason | null;
}

export interface EmailVariantsResponse {
  variants: EmailVariant[];
  lab_type?: LabType | null;
  recommended_style?: EmailStyle | null;
}

// ── Tailor (resume bullet rewriter, R71) ─────────────────────────────
/**
 * Mirrors `backend.schemas.TailoredBullet`. `source_evidence` is a short
 * quote from the original bullet / profile field / opportunity description
 * that the model used as grounding — never an invented citation.
 *
 * When `method === "fallback"`, `source_evidence` is hard-coded to
 * "original" so the UI can render a different chip ("Original — AI
 * unavailable") versus the AI variant.
 *
 * `source_index` (R71-E) points back into the request's
 * `original_bullets`, letting the modal render each tailored bullet
 * next to its source for side-by-side comparison even when some
 * bullets were dropped by the anti-fabrication validator.
 */
export interface TailoredBullet {
  text: string;
  source_evidence: string;
  source_index: number;
}

/**
 * Mirrors `backend.schemas.TailorResponse`. The route NEVER raises 5xx
 * for LLM problems — every failure mode degrades to `method: "fallback"`
 * with a non-empty `warnings` list:
 *   - `no_bullets_provided`       — caller sent an empty list
 *   - `llm_not_configured`        — no API key on the server
 *   - `llm_failed_or_invalid_json` — provider failed or returned non-JSON
 *   - `bullet_<i>_rejected_fabrication: foo,bar` — anti-fabrication
 *     validator caught the model inventing tokens not in profile/opp
 *   - `all_bullets_rejected`      — every bullet was flagged → passthrough
 */
export interface TailorResponse {
  tailored_bullets: TailoredBullet[];
  method: 'ai' | 'fallback';
  warnings: string[];
}

// ── Resume renovation (per-opportunity whole-résumé rework) ──────────
// Mirrors backend.schemas: /tailor/structure emits ResumeSection[]
// (structural ids + verbatim bullet text); /tailor/renovate emits
// RenovatedSection[] whose bullets carry a VARIANT CHAIN:
//   base_text  — the student's own words, the rollback floor;
//   variants   — appended reframings (macro plan / ai re-optimize / user
//                edit), each with its provenance;
//   current    — index into variants, -1 == show base_text. Rollback is a
//                pure pointer move client-side (no LLM → cannot fabricate).
export interface ResumeBulletInput {
  id: string;
  text: string;
}

export interface ResumeSectionInput {
  id: string;
  heading: string;
  kind: string;
  bullets: ResumeBulletInput[];
}

export interface StructureResumeResponse {
  sections: ResumeSectionInput[];
  method: 'ai' | 'heuristic';
  warnings: string[];
}

export type RenovatedVariantSource = 'macro' | 'ai' | 'user';

export interface RenovatedVariant {
  source: RenovatedVariantSource;
  text: string;
  source_evidence: string;
}

export type RenovationAction = 'foreground' | 'keep' | 'demote';

export interface RenovatedBullet {
  id: string;
  base_text: string;
  variants: RenovatedVariant[];
  current: number;
  action: RenovationAction | string;
}

export interface RenovatedSection {
  id: string;
  heading: string;
  kind: string;
  bullets: RenovatedBullet[];
}

export interface RenovateResponse {
  sections: RenovatedSection[];
  method: 'ai' | 'fallback';
  warnings: string[];
}

export interface BulletOptimizeResponse {
  text: string;
  source_evidence: string;
  changed: boolean;
  warnings: string[];
}

/** The working document the modal edits and supabase persists (doc jsonb). */
export interface RenovationDoc {
  sections: RenovatedSection[];
  method: 'ai' | 'fallback';
  warnings: string[];
}

// ── Resume ───────────────────────────────────────────────────────────
export interface ResumeParseResponse {
  extracted_skills: string[];
  extracted_coursework: string[];
  experience_level: string;
  raw_text: string;
  success: boolean;
  message: string;
  /** Labeled "Areas of Interest" line from the resume; seeds the interests box when empty. */
  suggested_interests?: string;
}

// ── Stats / Dashboard ────────────────────────────────────────────────
export interface StatsResponse {
  total: number;
  active: number;
  paid_total: number;
  international_friendly_total: number;
  by_type: Record<string, number>;
  by_source: Record<string, number>;
  by_paid: Record<string, number>;
  by_international: Record<string, number>;
  last_updated_at?: string | null;
}

// ── Opportunities list ───────────────────────────────────────────────
export interface OpportunitiesResponse {
  opportunities: Opportunity[];
  total: number;
}

// ── Professor updates (W8) ───────────────────────────────────────────
export type ProfessorChangeType =
  | 'research_focus'
  | 'department_or_lab'
  | 'project_availability'
  | 'public_source';

export interface ProfessorUpdateEvent {
  event_id: string;
  professor_id: string;
  professor_name: string;
  school: string;
  verified_at: string;
  source_url: string;
  change_types: ProfessorChangeType[];
  project_became_available: boolean;
}

export interface ProfessorUpdatesResponse {
  /** false only when the tracking artifact is absent/unreadable server-side. */
  available: boolean;
  events: ProfessorUpdateEvent[];
  requested: number;
  has_more: boolean;
}
