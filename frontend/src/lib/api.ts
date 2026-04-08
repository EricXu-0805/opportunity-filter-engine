import type {
  ProfileData,
  ProfileRequest,
  MatchesResponse,
  OpportunitiesResponse,
  ColdEmailResponse,
  ResumeParseResponse,
  StatsResponse,
} from './types';

const API_BASE = '/api';

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

/** Transform frontend ProfileData into the backend ProfileRequest format */
function toProfileRequest(profile: ProfileData): ProfileRequest {
  return {
    name: '',
    school: 'UIUC',
    year: profile.grade.toLowerCase(),
    major: profile.major,
    college: profile.college,
    secondary_interests: [],
    international_student: profile.is_international,
    seeking_type: ['research', 'summer_program'],
    desired_fields: [],
    hard_skills: profile.skills,
    coursework: profile.coursework ?? [],
    experience_level: 'beginner',
    resume_ready: !!profile.resume_text,
    can_cold_email: true,
    research_interests_text: profile.research_interests,
  };
}

/** POST /api/matches — get ranked opportunities for a profile */
export async function getMatches(profile: ProfileData): Promise<MatchesResponse> {
  return request<MatchesResponse>('/matches', {
    method: 'POST',
    body: JSON.stringify(toProfileRequest(profile)),
  });
}

/** GET /api/opportunities — list all opportunities */
export async function getOpportunities(): Promise<OpportunitiesResponse> {
  return request<OpportunitiesResponse>('/opportunities');
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

/** GET /api/opportunities/stats/summary — dashboard stats */
export async function getStats(): Promise<StatsResponse> {
  return request<StatsResponse>('/opportunities/stats/summary');
}
