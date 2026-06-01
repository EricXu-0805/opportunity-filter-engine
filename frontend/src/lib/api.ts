import type {
  ProfileData,
  ProfileRequest,
  MatchesResponse,
  OpportunitiesResponse,
  ColdEmailEngine,
  ColdEmailResponse,
  EmailVariantsResponse,
  ResumeParseResponse,
  StatsResponse,
  TailorResponse,
} from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const errBody = await res.text().catch(() => 'Unknown error');
    throw new Error(`API ${res.status}: ${errBody}`);
  }
  return res.json() as Promise<T>;
}

function toProfileRequest(profile: ProfileData): ProfileRequest {
  return {
    name: profile.name ?? '',
    school: 'UIUC',
    year: profile.grade.toLowerCase(),
    major: profile.major,
    college: profile.college,
    secondary_interests: [],
    international_student: profile.is_international,
    seeking_type: profile.seeking_types ?? ['research', 'summer_program'],
    desired_fields: [],
    hard_skills: profile.skills.map((s) => ({ name: s.name, level: s.level })),
    coursework: profile.coursework ?? [],
    experience_level: profile.experience_level ?? 'beginner',
    resume_ready: !!profile.resume_text,
    can_cold_email: true,
    research_interests_text: profile.research_interests,
    linkedin_url: profile.linkedin_url ?? '',
    github_url: profile.github_url ?? '',
    search_weight: profile.search_weight ?? 50,
  };
}

/** POST /api/matches — get ranked opportunities for a profile */
export async function getMatches(
  profile: ProfileData,
  options: { semantic?: boolean } = {},
): Promise<MatchesResponse> {
  const qs = options.semantic ? '?semantic=true' : '';
  return request<MatchesResponse>(`/matches${qs}`, {
    method: 'POST',
    body: JSON.stringify(toProfileRequest(profile)),
  });
}

export async function getOpportunities(): Promise<OpportunitiesResponse> {
  return request<OpportunitiesResponse>('/opportunities');
}

export interface FellowshipQuery {
  opportunity_type?: 'summer_program' | 'fellowship' | 'research' | 'internship';
  international_friendly?: 'yes' | 'no';
  limit?: number;
}

export async function getFellowshipOpportunities(
  query: FellowshipQuery = {},
): Promise<OpportunitiesResponse> {
  const params = new URLSearchParams();
  params.set('opportunity_type', query.opportunity_type ?? 'summer_program');
  if (query.international_friendly) {
    params.set('international_friendly', query.international_friendly);
  }
  params.set('limit', String(query.limit ?? 500));
  return request<OpportunitiesResponse>(`/opportunities?${params.toString()}`);
}

export async function getFeaturedFellowships(limit = 3): Promise<OpportunitiesResponse> {
  const params = new URLSearchParams({
    opportunity_type: 'summer_program',
    limit: String(limit),
  });
  return request<OpportunitiesResponse>(`/opportunities?${params.toString()}`);
}

export interface GapAnalysis {
  missing_skills: string[];
  suggested_coursework: string[];
  resume_tips: string[];
  preparation_timeline: { skill: string; estimated_time: string; priority: string }[];
}

export async function getGapAnalysis(profile: ProfileData, opportunityId: string): Promise<GapAnalysis> {
  return request<GapAnalysis>(`/matches/${encodeURIComponent(opportunityId)}/gaps`, {
    method: 'POST',
    body: JSON.stringify(toProfileRequest(profile)),
  });
}

export interface MatchExplanationResponse {
  explanation: string;
  method: 'llm' | 'local';
  final_score: number;
  bucket: string;
  reasons_fit: string[];
  reasons_gap: string[];
  eligibility_score: number;
  readiness_score: number;
  upside_score: number;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatResponse {
  reply: string;
  method: 'llm' | 'local';
}

export async function chatWithOpportunity(
  opportunityId: string,
  message: string,
  history: ChatMessage[],
  profile: ProfileData | null,
): Promise<ChatResponse> {
  return request<ChatResponse>(
    `/opportunities/${encodeURIComponent(opportunityId)}/chat`,
    {
      method: 'POST',
      body: JSON.stringify({
        message,
        history,
        profile: profile ? toProfileRequest(profile) : null,
      }),
    },
  );
}

export async function getMatchExplanation(
  profile: ProfileData,
  opportunityId: string,
): Promise<MatchExplanationResponse> {
  return request<MatchExplanationResponse>(
    `/matches/${encodeURIComponent(opportunityId)}/explain`,
    {
      method: 'POST',
      body: JSON.stringify(toProfileRequest(profile)),
    },
  );
}

export async function getOpportunityById(id: string): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/opportunities/${encodeURIComponent(id)}`);
}

export async function getOpportunitiesByIds(ids: string[]): Promise<Record<string, unknown>[]> {
  if (ids.length === 0) return [];
  const uniq = Array.from(new Set(ids));
  const chunks: string[][] = [];
  for (let i = 0; i < uniq.length; i += 200) chunks.push(uniq.slice(i, i + 200));
  const responses = await Promise.all(chunks.map(chunk =>
    request<{ opportunities: Record<string, unknown>[] }>('/opportunities/batch', {
      method: 'POST',
      body: JSON.stringify({ ids: chunk }),
    }),
  ));
  return responses.flatMap(r => r.opportunities);
}

/** POST /api/cold-email — generate a cold email draft */
export async function generateColdEmail(
  profile: ProfileData,
  opportunityId: string,
  options: { engine?: ColdEmailEngine } = {},
): Promise<ColdEmailResponse> {
  const body: Record<string, unknown> = {
    profile: toProfileRequest(profile),
    opportunity_id: opportunityId,
  };
  if (options.engine) body.engine = options.engine;
  return request<ColdEmailResponse>('/cold-email', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function getEmailVariants(
  profile: ProfileData,
  opportunityId: string,
): Promise<EmailVariantsResponse> {
  return request<EmailVariantsResponse>('/cold-email/variants', {
    method: 'POST',
    body: JSON.stringify({ profile: toProfileRequest(profile), opportunity_id: opportunityId }),
  });
}

/** POST /api/resume/upload — upload & parse a resume PDF */
export async function uploadResume(file: File): Promise<ResumeParseResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${API_BASE}/resume/upload`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const errBody = await res.text().catch(() => 'Unknown error');
    throw new Error(`API ${res.status}: ${errBody}`);
  }
  return res.json() as Promise<ResumeParseResponse>;
}

export async function refineEmail(
  currentBody: string,
  instruction: string,
): Promise<{ body: string; method: string }> {
  return request<{ body: string; method: string }>('/cold-email/refine', {
    method: 'POST',
    body: JSON.stringify({ current_body: currentBody, instruction: instruction }),
  });
}

/**
 * POST /api/tailor — rewrite resume bullets for one opportunity.
 *
 * Always resolves (never throws for LLM problems): on any backend
 * failure mode the response has `method: "fallback"` and a non-empty
 * `warnings` list. The only thrown errors are 404 (opportunity not
 * found) and network failures. Mirrors the cold-email "always returns
 * usable" contract.
 *
 * `locale` (R71-D) selects the output language. Backend normalizes
 * region tags ('zh-CN' / 'zh_TW' / 'zh') to 'zh', and any unknown
 * value falls back to 'en' rather than 422-ing — so we can safely
 * pass `useT().locale` through without sanitization.
 */
export async function tailorResume(
  profile: ProfileData,
  opportunityId: string,
  originalBullets: string[],
  options: { locale?: string } = {},
): Promise<TailorResponse> {
  const body: Record<string, unknown> = {
    profile: toProfileRequest(profile),
    opportunity_id: opportunityId,
    original_bullets: originalBullets,
  };
  if (options.locale) body.locale = options.locale;
  return request<TailorResponse>('/tailor', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export interface TailorStatus {
  ai_available: boolean;
}

export async function getTailorStatus(): Promise<TailorStatus> {
  return request<TailorStatus>('/tailor/status');
}

export interface ExtractBulletsResponse {
  bullets: string[];
  method: 'ai' | 'heuristic';
}

/**
 * POST /api/tailor/extract-bullets — LLM-extract resume bullet lines from
 * raw text (catches "dark bullets" the glyph heuristic misses). Always
 * resolves: backend degrades to the glyph heuristic on any LLM issue.
 */
export async function extractResumeBullets(
  resumeText: string,
): Promise<ExtractBulletsResponse> {
  return request<ExtractBulletsResponse>('/tailor/extract-bullets', {
    method: 'POST',
    body: JSON.stringify({ resume_text: resumeText }),
  });
}

export interface GitHubParseResponse {
  username: string;
  extracted_skills: string[];
  topics: string[];
  repo_count: number;
  top_repos: string[];
}

export async function parseGitHubProfile(username: string): Promise<GitHubParseResponse> {
  return request<GitHubParseResponse>(`/resume/github/${encodeURIComponent(username)}`);
}

/** GET /api/opportunities/stats/summary — dashboard stats */
export async function getStats(): Promise<StatsResponse> {
  return request<StatsResponse>('/opportunities/stats/summary');
}

/**
 * Fire-and-forget ping to wake a sleeping Render free-tier backend.
 * First cold-start can take 20-40s; calling this on app mount means the
 * backend is usually warm by the time the user hits "Generate Matches".
 * Swallows errors — purely an optimization.
 */
export async function wakeBackend(): Promise<void> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 60_000);
    try {
      await fetch(`${API_BASE}/health`, {
        cache: 'no-store',
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeout);
    }
  } catch { /* swallow */ }
}

export interface UpcomingDeadline {
  id: string;
  title: string;
  organization?: string;
  deadline: string;
  days_left: number;
  opportunity_type: string;
  paid: string;
  url?: string;
  source?: string;
}

export interface UpcomingResponse {
  total: number;
  opportunities: UpcomingDeadline[];
  days: number;
}

export async function getUpcomingDeadlines(days = 30): Promise<UpcomingResponse> {
  return request<UpcomingResponse>(`/opportunities/upcoming?days=${days}`);
}

export interface EmailMatchItem {
  title: string;
  url?: string;
  score?: number;
  source?: string;
  deadline?: string | null;
  organization?: string;
}

export async function sendMatchesEmail(
  email: string,
  items: EmailMatchItem[],
  subjectHint = '',
): Promise<{ ok: boolean; count: number }> {
  return request('/email/send-matches', {
    method: 'POST',
    body: JSON.stringify({ email, items, subject_hint: subjectHint }),
  });
}

export interface EmailFavoriteItem {
  title: string;
  url?: string;
  score?: number;
  source?: string;
  deadline?: string | null;
  notes?: string;
  status?: string;
}

export async function sendFavoritesEmail(
  email: string,
  items: EmailFavoriteItem[],
): Promise<{ ok: boolean; count: number }> {
  return request('/email/send-favorites', {
    method: 'POST',
    body: JSON.stringify({ email, items }),
  });
}

export async function sendRestoreLink(
  email: string,
  deviceId: string,
): Promise<{ ok: boolean; note?: string }> {
  return request('/email/restore-link', {
    method: 'POST',
    body: JSON.stringify({ email, device_id: deviceId }),
  });
}

export async function verifyRestoreLink(
  params: { d: string; t: string; s: string },
): Promise<{ ok: boolean; device_id: string }> {
  const qs = new URLSearchParams(params).toString();
  return request(`/email/verify-restore?${qs}`);
}

export interface ImportedOpportunity {
  source: string;
  source_url: string;
  title: string;
  description_raw: string;
  url: string;
  organization?: string | null;
  deadline?: string | null;
  posted_date?: string | null;
  location?: string | null;
  raw_html?: string | null;
  extra_fields: Record<string, unknown>;
}

export interface ImportUrlResponse {
  ok: boolean;
  opportunity?: ImportedOpportunity;
  error?: string;
  llm_enriched: boolean;
}

export async function importByUrl(url: string): Promise<ImportUrlResponse> {
  try {
    return await request<ImportUrlResponse>('/import-url', {
      method: 'POST',
      body: JSON.stringify({ url }),
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const detail = parseFastApiDetail(message);
    if (detail) {
      return { ok: false, error: detail, llm_enriched: false };
    }
    throw err;
  }
}

export async function importByText(text: string): Promise<ImportUrlResponse> {
  try {
    return await request<ImportUrlResponse>('/import-text', {
      method: 'POST',
      body: JSON.stringify({ text }),
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const detail = parseFastApiDetail(message);
    if (detail) {
      return { ok: false, error: detail, llm_enriched: false };
    }
    throw err;
  }
}

function parseFastApiDetail(rawErrorMessage: string): string | null {
  const match = rawErrorMessage.match(/^API \d+:\s*(\{.*\})\s*$/);
  if (!match) return null;
  try {
    const body = JSON.parse(match[1]) as { detail?: unknown };
    if (typeof body.detail === 'string') return body.detail;
    if (Array.isArray(body.detail) && body.detail.length > 0) {
      const first = body.detail[0] as { msg?: unknown };
      if (first && typeof first.msg === 'string') return first.msg;
    }
    return null;
  } catch {
    return null;
  }
}
