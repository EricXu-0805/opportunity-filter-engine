import type {
  ProfileData,
  ProfileRequest,
  MatchesResponse,
  OpportunitiesResponse,
  ColdEmailResponse,
  EmailVariantsResponse,
  ResumeParseResponse,
  StatsResponse,
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
): Promise<ColdEmailResponse> {
  return request<ColdEmailResponse>('/cold-email', {
    method: 'POST',
    body: JSON.stringify({ profile: toProfileRequest(profile), opportunity_id: opportunityId }),
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
