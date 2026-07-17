import type {
  ProfileData,
  ProfileRequest,
  MatchesResponse,
  OpportunitiesResponse,
  ColdEmailEngine,
  ColdEmailResponse,
  EmailStyle,
  EmailVariantsResponse,
  StatsResponse,
  TailorResponse,
  StructureResumeResponse,
  ResumeSectionInput,
  RenovateResponse,
  BulletOptimizeResponse,
} from './types';
import { track } from './analytics';
import { bySlug } from './schools';

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

/**
 * Split the free-text research-interests box into discrete topic terms for
 * `desired_fields`, which the matcher intersects with each opportunity's
 * keywords for an exact-match bonus. Previously hardcoded to [], so that bonus
 * path was dead for every real user. Splits on commas/semicolons/newlines and
 * the conjunction "and" (so "computer vision and machine learning" → two terms),
 * trims, dedupes, and caps at 20 (the backend also caps). Non-matching terms are
 * harmless — the matcher only rewards terms that actually intersect a keyword.
 */
export function deriveDesiredFields(interests: string | undefined): string[] {
  if (!interests) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of interests.split(/[,;\n]|\s+and\s+/i)) {
    const term = raw.trim();
    const key = term.toLowerCase();
    if (term.length >= 2 && term.length <= 100 && !seen.has(key)) {
      seen.add(key);
      out.push(term);
    }
    if (out.length >= 20) break;
  }
  return out;
}

function toProfileRequest(profile: ProfileData): ProfileRequest {
  const homeSchool = profile.home_school ?? 'uiuc';
  return {
    name: profile.name ?? '',
    // Free-text display name (cold-email "…student at {school}");
    // home_school is the slug the matcher's scope filter consumes.
    school: bySlug(homeSchool)?.shortName ?? 'UIUC',
    home_school: homeSchool,
    year: profile.grade.toLowerCase(),
    major: profile.major,
    college: profile.college,
    // Additional majors/minors feed the matcher's secondary-major + keyword signal.
    secondary_interests: profile.additional_majors ?? [],
    international_student: profile.is_international,
    seeking_type: profile.seeking_types ?? ['research', 'summer_program'],
    desired_fields: deriveDesiredFields(profile.research_interests),
    hard_skills: profile.skills.map((s) => ({ name: s.name, level: s.level })),
    coursework: profile.coursework ?? [],
    experience_level: profile.experience_level ?? 'beginner',
    resume_ready: !!profile.resume_text,
    can_cold_email: true,
    research_interests_text: profile.research_interests,
    linkedin_url: profile.linkedin_url ?? '',
    github_url: profile.github_url ?? '',
    search_weight: profile.search_weight ?? 50,
    exploring: profile.exploring ?? false,
    include_cross_school: profile.include_cross_school ?? false,
  };
}

/** POST /api/matches — get ranked opportunities for a profile */
export async function getMatches(
  profile: ProfileData,
  options: { llm?: boolean } = {},
): Promise<MatchesResponse> {
  // The LLM reranker is the server default (scores topical fit + writes each
  // card's concrete lead reason via OpenRouter); the "AI smart match" toggle
  // only opts OUT (?llm=false). The older embedding ?semantic path is retired
  // — it regressed the ranking; this replaces it.
  const qs = options.llm === false ? '?llm=false' : '';
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

export interface RoadmapSkill {
  skill: string;
  needed_by: number;
  priority: string;
  estimated_time: string;
  courses: string[];
}
export interface RoadmapResult {
  skills: RoadmapSkill[];
  total_labs: number;
}

/** Aggregate the skill gaps across a target set of opportunities (e.g. favorites)
 *  into one dependency-ordered learning path. */
export async function getRoadmap(
  profile: ProfileData,
  opportunityIds: string[],
): Promise<RoadmapResult> {
  return request<RoadmapResult>('/roadmap', {
    method: 'POST',
    body: JSON.stringify({ profile: toProfileRequest(profile), opportunity_ids: opportunityIds }),
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
  /** True when a stream failed after partial output — `reply` holds what arrived. */
  errored?: boolean;
}

/** One Ask-AI model the picker may offer (mirrors `llm.chat_model_options`). */
export interface ChatModelOption {
  id: string;
  label: string;
}

/**
 * With `onDelta`, requests SSE streaming (`?stream=1`) and invokes it per
 * content chunk; the resolved `reply` is the accumulated text. An old backend
 * answering plain JSON degrades gracefully (single `onDelta` with the full
 * reply). Without `onDelta`, the blocking JSON path is unchanged.
 */
export async function chatWithOpportunity(
  opportunityId: string,
  message: string,
  history: ChatMessage[],
  profile: ProfileData | null,
  model?: string,
  onDelta?: (chunk: string) => void,
): Promise<ChatResponse> {
  void track('ai_feature_used', { feature: 'chat' });
  const path = `/opportunities/${encodeURIComponent(opportunityId)}/chat`;
  const body = JSON.stringify({
    message,
    history,
    profile: profile ? toProfileRequest(profile) : null,
    ...(model ? { model } : {}),
  });
  if (!onDelta) {
    return request<ChatResponse>(path, { method: 'POST', body });
  }

  const res = await fetch(`${API_BASE}${path}?stream=1`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body,
  });
  if (!res.ok) {
    const errBody = await res.text().catch(() => 'Unknown error');
    throw new Error(`API ${res.status}: ${errBody}`);
  }
  if (!res.headers.get('content-type')?.includes('text/event-stream') || !res.body) {
    const json = (await res.json()) as ChatResponse;
    onDelta(json.reply);
    return json;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let reply = '';
  let method: 'llm' | 'local' = 'llm';
  let errored = false;
  let done = false;

  const handleFrame = (frame: string) => {
    for (const line of frame.split('\n')) {
      if (!line.startsWith('data: ')) continue;
      const payload = JSON.parse(line.slice(6)) as {
        delta?: string;
        error?: boolean;
        done?: boolean;
        method?: 'llm' | 'local';
      };
      if (typeof payload.delta === 'string') {
        reply += payload.delta;
        onDelta(payload.delta);
      }
      if (payload.error) errored = true;
      if (payload.done) {
        done = true;
        if (payload.method) method = payload.method;
      }
    }
  };

  try {
    for (;;) {
      const { value, done: readerDone } = await reader.read();
      if (readerDone) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        handleFrame(frame);
      }
    }
  } catch (err) {
    if (reply) return { reply, method, errored: true };
    throw err;
  }
  if (!reply && !done) {
    throw new Error('API stream: connection closed before any data');
  }
  return { reply, method, errored };
}

/** Ask-AI model options — empty array when OpenRouter isn't configured
 * (the picker then stays hidden). Never throws — returns [] on any error. */
export async function getChatModels(): Promise<ChatModelOption[]> {
  try {
    const res = await request<{ models: ChatModelOption[] }>('/chat/models');
    return res.models ?? [];
  } catch {
    return [];
  }
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
  options: { engine?: ColdEmailEngine; style?: EmailStyle; resumeBullets?: string[] } = {},
): Promise<ColdEmailResponse> {
  void track('ai_feature_used', { feature: 'cold_email' });
  const body: Record<string, unknown> = {
    profile: toProfileRequest(profile),
    opportunity_id: opportunityId,
  };
  if (options.engine) body.engine = options.engine;
  if (options.style) body.style = options.style;
  // The student's real resume experience bullets, so the AI draft can cite
  // their actual work. Additive + optional; the backend grounds them.
  if (options.resumeBullets && options.resumeBullets.length > 0) {
    body.resume_bullets = options.resumeBullets;
  }
  return request<ColdEmailResponse>('/cold-email', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export type ColdEmailStage = 'drafting' | 'judging' | 'critiquing' | 'revising';

/**
 * SSE variant of `generateColdEmail`: relays `{"stage": ...}` progress events
 * while the multi-call pipeline runs (draft → critique → revise), then
 * resolves with the final payload carried by the `done` event. Throws on any
 * transport/shape problem — callers fall back to the blocking route.
 */
export async function generateColdEmailStream(
  profile: ProfileData,
  opportunityId: string,
  options: { engine?: ColdEmailEngine; style?: EmailStyle; resumeBullets?: string[] } = {},
  onStage?: (stage: ColdEmailStage) => void,
): Promise<ColdEmailResponse> {
  // NOTE: the funnel event fires only after a successful done event (bottom of
  // this function) — a failed stream falls back to generateColdEmail, which
  // tracks itself, so one user click never double-counts ai_feature_used.
  const body: Record<string, unknown> = {
    profile: toProfileRequest(profile),
    opportunity_id: opportunityId,
  };
  if (options.engine) body.engine = options.engine;
  if (options.style) body.style = options.style;
  if (options.resumeBullets && options.resumeBullets.length > 0) {
    body.resume_bullets = options.resumeBullets;
  }

  const res = await fetch(`${API_BASE}/cold-email/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const errBody = await res.text().catch(() => 'Unknown error');
    throw new Error(`API ${res.status}: ${errBody}`);
  }
  if (!res.headers.get('content-type')?.includes('text/event-stream') || !res.body) {
    throw new Error('API stream: not an event stream');
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let final: ColdEmailResponse | null = null;

  const handleFrame = (frame: string) => {
    for (const line of frame.split('\n')) {
      if (!line.startsWith('data: ')) continue;
      const payload = JSON.parse(line.slice(6)) as { stage?: string } & Record<string, unknown>;
      if (payload.stage === 'done') {
        final = payload as unknown as ColdEmailResponse;
      } else if (payload.stage) {
        onStage?.(payload.stage as ColdEmailStage);
      }
    }
  };

  try {
    for (;;) {
      const { value, done: readerDone } = await reader.read();
      if (readerDone) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        handleFrame(frame);
      }
    }
  } finally {
    // Release the connection even when a parse error throws mid-stream —
    // otherwise the fallback path opens a second connection while this one
    // lingers until GC.
    void reader.cancel().catch(() => {});
  }
  // TS doesn't reset a closed-over let's narrowing on function calls, so it
  // still believes `final` is null here despite handleFrame's assignment.
  const f = final as unknown as (ColdEmailResponse & { stage?: string }) | null;
  if (!f) throw new Error('API stream: closed before the done event');
  // Version-skew guard: a done event missing the core fields must trigger the
  // blocking fallback, not flow undefined into the compose UI / mailto link.
  if (typeof f.subject !== 'string' || typeof f.body !== 'string') {
    throw new Error('API stream: malformed done payload');
  }
  void track('ai_feature_used', { feature: 'cold_email' });
  return f;
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

export async function refineEmail(
  currentBody: string,
  instruction: string,
  profile?: ProfileData,
  opportunityId?: string,
  options: { resumeBullets?: string[] } = {},
): Promise<{ body: string; method: string; fallback_reason?: string }> {
  return request<{ body: string; method: string; fallback_reason?: string }>('/cold-email/refine', {
    method: 'POST',
    body: JSON.stringify({
      current_body: currentBody,
      instruction: instruction,
      profile: profile ? toProfileRequest(profile) : null,
      opportunity_id: opportunityId ?? null,
      // The student's real resume bullets keep experience claims grounded when
      // a refine instruction asks to emphasize them (additive + optional).
      ...(options.resumeBullets && options.resumeBullets.length > 0
        ? { resume_bullets: options.resumeBullets }
        : {}),
    }),
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
  void track('ai_feature_used', { feature: 'tailor' });
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

/**
 * Resume renovation, stage 0: structure the raw résumé text into sections +
 * bullets (verbatim extraction; the backend degrades to a heuristic split on
 * any LLM issue and never 5xxes for it).
 */
export async function structureResume(
  resumeText: string,
  options: { locale?: string } = {},
): Promise<StructureResumeResponse> {
  const body: Record<string, unknown> = { resume_text: resumeText };
  if (options.locale) body.locale = options.locale;
  return request<StructureResumeResponse>('/tailor/structure', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/**
 * Resume renovation, stage 1+2: macro plan (reorder + foreground/keep/demote,
 * ID-only — structurally cannot fabricate) plus grounded rewrites of the
 * foregrounded bullets. Returns the variant-chain document; rejected rewrites
 * fall back to base_text with a warning, never a 5xx.
 */
export async function renovateResume(
  profile: ProfileData,
  opportunityId: string,
  sections: ResumeSectionInput[],
  options: { locale?: string } = {},
): Promise<RenovateResponse> {
  void track('ai_feature_used', { feature: 'renovate' });
  const body: Record<string, unknown> = {
    profile: toProfileRequest(profile),
    opportunity_id: opportunityId,
    sections,
  };
  if (options.locale) body.locale = options.locale;
  return request<RenovateResponse>('/tailor/renovate', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/**
 * Per-bullet re-optimize: one grounded rewrite of `currentText` toward the
 * opportunity (optionally steered by `instruction`), validated against
 * base_text + the student's material. A rejected rewrite comes back with
 * `changed: false` and the original text — never a fabricated claim.
 */
export async function optimizeBullet(
  profile: ProfileData,
  opportunityId: string,
  currentText: string,
  baseText: string,
  options: { instruction?: string; locale?: string } = {},
): Promise<BulletOptimizeResponse> {
  void track('ai_feature_used', { feature: 'bullet_optimize' });
  const body: Record<string, unknown> = {
    profile: toProfileRequest(profile),
    opportunity_id: opportunityId,
    current_text: currentText,
    base_text: baseText,
  };
  if (options.instruction) body.instruction = options.instruction;
  if (options.locale) body.locale = options.locale;
  return request<BulletOptimizeResponse>('/tailor/bullet', {
    method: 'POST',
    body: JSON.stringify(body),
  });
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

export interface ResponsivenessSignal {
  contacted_n: number;
  replied_n: number;
}

/**
 * GET /api/opportunities/responsiveness — anonymous aggregate signals
 * (opportunity_id → counts). The backend only ships aggregates with
 * contacted_n >= its min-N floor; nothing individual-level ever arrives here.
 */
export async function getResponsivenessSignals(): Promise<Record<string, ResponsivenessSignal>> {
  const data = await request<{ signals?: Record<string, ResponsivenessSignal> }>(
    '/opportunities/responsiveness',
  );
  return data.signals ?? {};
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
