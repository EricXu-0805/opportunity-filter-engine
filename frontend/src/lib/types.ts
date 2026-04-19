// ── Skill Proficiency ────────────────────────────────────────────────
export type SkillLevel = 'beginner' | 'experienced' | 'expert';

export interface SkillWithLevel {
  name: string;
  level: SkillLevel;
}

// ── Frontend Profile (form state) ────────────────────────────────────
export interface ProfileData {
  institution: string;
  college: string;
  major: string;
  grade: string;
  is_international: boolean;
  research_interests: string;
  skills: SkillWithLevel[];
  resume_text?: string;
  coursework?: string[];
  search_weight?: number;
  linkedin_url?: string;
  github_url?: string;
  seeking_types?: string[];
  format_preference?: string;
  name?: string;
  experience_level?: string;
}

// ── Backend Profile Request ──────────────────────────────────────────
export interface ProfileRequest {
  name: string;
  school: string;
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
  search_weight: number;  // 0-100: 0=pure interests, 100=pure experience
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
}

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
  on_campus: boolean;
  description_clean: string;
  description_raw?: string;
  keywords: string[];
  deadline?: string;
  compensation_details?: string;
  duration?: string;
  start_date?: string;
  posted_date?: string;
  remote_option?: string;
  eligibility: OpportunityEligibility;
  application: OpportunityApplication;
  metadata: OpportunityMetadata;
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
  opportunity: Opportunity;
}

export interface MatchesResponse {
  total: number;
  high_priority: number;
  good_match: number;
  reach: number;
  low_fit: number;
  results: MatchResult[];
}

// ── Cold Email ───────────────────────────────────────────────────────
export interface ColdEmailResponse {
  subject: string;
  body: string;
  mailto_link: string;
  recipient?: string;
}

export interface EmailVariant {
  id: string;
  label: string;
  subject: string;
  body: string;
  recipient_email: string;
  mailto_link: string;
}

export interface EmailVariantsResponse {
  variants: EmailVariant[];
}

// ── Resume ───────────────────────────────────────────────────────────
export interface ResumeParseResponse {
  extracted_skills: string[];
  extracted_coursework: string[];
  experience_level: string;
  raw_text: string;
  success: boolean;
  message: string;
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
}

// ── Opportunities list ───────────────────────────────────────────────
export interface OpportunitiesResponse {
  opportunities: Opportunity[];
  total: number;
}
