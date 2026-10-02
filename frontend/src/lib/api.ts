import type { EmailTargetConditions, EmailConditionIssue } from './email-target-conditions';
import { assertProfileInput, ProfileInputError } from './profile-input';
import type { EmailTextSelection } from './email-revision';
import { validateResumeMaster } from './resume-master';
import type {
  ProfileData,
  ProfileRequest,
  MatchesResponse,
  OpportunitiesResponse,
  ColdEmailEngine,
  ColdEmailResponse,
  ExperienceUsage,
  EmailStyle,
  EmailVariantsResponse,
  EmailContactContext,
  EmailContactContextReceipt,
  StatsResponse,
  TailorResponse,
  StructureResumeResponse,
  ResumeProcessingCoverage,
  ResumeSectionInput,
  RenovateResponse,
  BulletOptimizeResponse,
  ProfessorUpdatesResponse,
  DeadlineFilterValue,
} from './types';
import { track } from './analytics';
import { normalizeEmailContactContext } from './email-contact-context';
import { COLD_EMAIL_STREAM_TIMEOUT_MS, ColdEmailStreamError } from './cold-email-stream';
import { captureOwnerToken, isOwnerTokenValid, isTokenOwnerStillCurrent, type OwnerToken } from './identity-owner';
import { FULL_TARGET_AI_MAX_BODY_BYTES, type TargetResumeAiRequest, type TargetResumeAiResponse } from './target-resume-ai-protocol';
import { TARGET_RESUME_PLAN_MAX_BODY_BYTES, type TargetResumePlanRequest, type TargetResumePlanResponse } from './target-resume-plan-protocol';
import { bySlug } from './schools';
import { isFellowshipPreference, RELEASE_SCOPE } from './release-scope';
import { getRevealAccessToken, refreshRevealAccessToken } from './supabase';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly retryable: boolean,
    public readonly requestId?: string,
    public readonly detail?: unknown,
    /** Server-stated wait before retrying, from `Retry-After`. */
    public readonly retryAfterMs?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

type RequestOptions = RequestInit & {
  timeoutMs?: number;
  /**
   * Extra attempts for a server-declared retryable failure. Opt-in per call,
   * because "retryable" describes the SERVER's state, not whether repeating
   * this particular request is safe — a cold-email send must never replay.
   */
  retries?: number;
};

// A server that says "retry in 5s" and a client that gives up immediately is
// the same failure twice. Cap the honoured delay so a bad header cannot park
// the page, and cap the total so a genuinely down backend still fails fast.
const MAX_RETRY_DELAY_MS = 8_000;
const DEFAULT_RETRY_DELAY_MS = 1_500;

function retryDelayMs(error: ApiError, attempt: number): number {
  if (typeof error.retryAfterMs === 'number' && error.retryAfterMs >= 0) {
    return Math.min(error.retryAfterMs, MAX_RETRY_DELAY_MS);
  }
  return Math.min(DEFAULT_RETRY_DELAY_MS * 2 ** attempt, MAX_RETRY_DELAY_MS);
}

function parseRetryAfter(header: string | null | undefined): number | undefined {
  if (!header) return undefined;
  const seconds = Number(header.trim());
  if (Number.isFinite(seconds) && seconds >= 0) return seconds * 1000;
  const at = Date.parse(header);
  return Number.isNaN(at) ? undefined : Math.max(0, at - Date.now());
}

function safeHttpMessage(status: number): string {
  if (status === 429 || status === 503) {
    return 'The service is busy. Please try again shortly.';
  }
  if (status === 504) {
    return 'The request took too long. Please try again.';
  }
  if (status >= 500) {
    return 'The service is temporarily unavailable. Please try again.';
  }
  return 'The request could not be completed.';
}

async function apiErrorFromResponse(res: Response): Promise<ApiError> {
  const raw = await res.text().catch(() => '');
  let detail: unknown = null;
  try {
    detail = raw && raw.length <= 1_000_000 ? JSON.parse(raw) : null;
  } catch {
    // HTML/text gateway bodies are intentionally ignored.
  }
  const fastApiDetail = (
    detail
    && typeof detail === 'object'
    && 'detail' in detail
  ) ? detail.detail : undefined;
  const envelope = (
    detail
    && typeof detail === 'object'
    && 'detail' in detail
    && typeof detail.detail === 'object'
    && detail.detail !== null
  ) ? detail.detail as Record<string, unknown> : {};
  const message = typeof envelope.message === 'string'
    ? envelope.message.slice(0, 240)
    : (
      res.status < 500 && typeof fastApiDetail === 'string'
        ? fastApiDetail.slice(0, 240)
        : safeHttpMessage(res.status)
    );
  const validationCode = Array.isArray(fastApiDetail)
    && fastApiDetail.length > 0
    && fastApiDetail[0]
    && typeof fastApiDetail[0] === 'object'
    && typeof (fastApiDetail[0] as Record<string, unknown>).type === 'string'
    ? String((fastApiDetail[0] as Record<string, unknown>).type).slice(0, 80)
    : null;
  const code = typeof envelope.code === 'string'
    ? envelope.code.slice(0, 80)
    : validationCode ?? `HTTP_${res.status}`;
  return new ApiError(
    res.status,
    code,
    code === 'PROFILE_INPUT_LIMIT_EXCEEDED' || code === 'PROFILE_INPUT_INVALID'
      ? 'Check your profile input. Your original content is kept.' : message,
    envelope.retryable === true || res.status >= 500 || res.status === 429,
    res.headers?.get?.('x-request-id') ?? undefined,
    fastApiDetail,
    parseRetryAfter(res.headers?.get?.('retry-after')),
  );
}

async function request<T>(url: string, options: RequestOptions = {}): Promise<T> {
  const { retries = 0, ...rest } = options;
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await requestOnce<T>(url, rest);
    } catch (error) {
      const retryable = error instanceof ApiError && error.retryable;
      if (!retryable || attempt >= retries || rest.signal?.aborted) throw error;
      await new Promise((resolve) => {
        setTimeout(resolve, retryDelayMs(error, attempt));
      });
    }
  }
}

async function requestOnce<T>(
  url: string,
  options: Omit<RequestOptions, 'retries'> = {},
): Promise<T> {
  const {
    timeoutMs = 60_000,
    signal: callerSignal,
    headers: callerHeaders,
    ...fetchOptions
  } = options;
  const controller = new AbortController();
  let response: Response | undefined;
  let interruption: ApiError | DOMException | null = null;
  let rejectInterruption!: (error: ApiError | DOMException) => void;
  const interrupted = new Promise<never>((_resolve, reject) => { rejectInterruption = reject; });
  const cancelResponseBody = () => {
    // Real fetch aborts its reader; a late/fake response may ignore that signal.
    // Cancellation is best effort (a body already locked by json/text rejects).
    try { void response?.body?.cancel().catch(() => {}); } catch { /* no raw transport error */ }
  };
  const interrupt = (error: ApiError | DOMException) => {
    if (interruption !== null) return; // the first timeout/caller decision wins
    interruption = error;
    rejectInterruption(error);
    controller.abort(error);
    cancelResponseBody();
  };
  const throwIfInterrupted = () => { if (interruption !== null) throw interruption; };
  const abortFromCaller = () => interrupt(new DOMException('The request was cancelled.', 'AbortError'));
  if (callerSignal?.aborted) abortFromCaller();
  else callerSignal?.addEventListener('abort', abortFromCaller, { once: true });
  const timer = setTimeout(() => interrupt(new ApiError(
    408, 'REQUEST_TIMEOUT', 'The request took too long. Please try again.', true,
  )), timeoutMs);

  try {
    return await Promise.race([interrupted, (async () => {
      throwIfInterrupted();
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (callerHeaders instanceof Headers) {
        callerHeaders.forEach((value, key) => { headers[key] = value; });
      } else if (Array.isArray(callerHeaders)) {
        for (const [key, value] of callerHeaders) headers[key] = value;
      } else if (callerHeaders) {
        Object.assign(headers, callerHeaders);
      }
      try {
        response = await fetch(`${API_BASE}${url}`, { ...fetchOptions, headers, signal: controller.signal });
      } catch {
        throwIfInterrupted();
        // Preserve existing retry policy: a raw network failure did not opt in
        // to replay, even for an endpoint which retries declared HTTP failures.
        throw new ApiError(0, 'NETWORK_ERROR', 'The service could not be reached. Please try again.', false);
      }
      if (interruption !== null) { cancelResponseBody(); throwIfInterrupted(); }
      if (!response.ok) {
        let error: ApiError;
        try { error = await apiErrorFromResponse(response); }
        catch {
          throwIfInterrupted();
          error = new ApiError(response.status, `HTTP_${response.status}`, safeHttpMessage(response.status), response.status >= 500 || response.status === 429);
        }
        throwIfInterrupted();
        throw error;
      }
      try {
        const result = await response.json() as T;
        throwIfInterrupted();
        return result;
      } catch {
        throwIfInterrupted();
        throw new ApiError(response.status, 'INVALID_RESPONSE', 'The response could not be read. Please try again.', false);
      }
    })()]);
  } finally {
    // One deadline covers headers AND success/error body consumption. The
    // race also settles when a fetch/body implementation ignores AbortSignal.
    clearTimeout(timer);
    callerSignal?.removeEventListener('abort', abortFromCaller);
  }
}

export const WRITING_AUTH_TIMEOUT_MS = 15_000;

/** Preserve legacy unresolved callers, but never cross an identity generation. */
function isWritingOwnerCurrent(owner: OwnerToken): boolean {
  return isTokenOwnerStillCurrent(owner)
    && captureOwnerToken().generation === owner.generation
    && (owner.generation < 0 || isOwnerTokenValid(owner, owner.uid));
}

/** Bound the pre-request identity lookup; a late SDK result cannot start a POST. */
async function writingAccessToken(owner: OwnerToken, signal?: AbortSignal): Promise<string | null> {
  let timedOut = false;
  let rejectCancel!: (error: DOMException) => void;
  const cancelled = new Promise<never>((_resolve, reject) => { rejectCancel = reject; });
  const abort = () => rejectCancel(new DOMException('The request was cancelled.', 'AbortError'));
  const active = () => {
    if (signal?.aborted) throw new DOMException('The request was cancelled.', 'AbortError');
    if (!isWritingOwnerCurrent(owner)) throw new ApiError(409, 'WRITING_OWNER_CHANGED', 'The active profile changed. Your draft is kept.', false);
    if (timedOut) throw new ApiError(408, 'WRITING_AUTH_TIMEOUT', 'Your sign-in could not be checked. Your draft is kept. Please try again.', false);
  };
  active();
  signal?.addEventListener('abort', abort, { once: true });
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => { timedOut = true; reject(new ApiError(408, 'WRITING_AUTH_TIMEOUT',
      'Your sign-in could not be checked. Your draft is kept. Please try again.', false)); }, WRITING_AUTH_TIMEOUT_MS);
  });
  try {
    const token = await Promise.race([getRevealAccessToken(), deadline, cancelled]);
    active();
    return token;
  } catch (error) {
    active();
    if (error instanceof ApiError || (error instanceof DOMException && error.name === 'AbortError')) throw error;
    throw new ApiError(0, 'WRITING_AUTH_UNAVAILABLE', 'Your sign-in could not be checked. Your draft is kept. Please try again.', false);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}

/** A completed draft with a locked recipient must not trigger a second generation. */
async function requestWritingWithAuth<T>(url: string, init: Omit<RequestInit, 'headers'>): Promise<T> {
  const owner = captureOwnerToken();
  const token = await writingAccessToken(owner, init.signal ?? undefined);
  const assertOwner = () => {
    if (!isWritingOwnerCurrent(owner)) throw new ApiError(409, 'WRITING_OWNER_CHANGED', 'The active profile changed. Your draft is kept.', false);
  };
  assertOwner();
  const result = await request<T>(url, { ...init, retries: 0,
    headers: token ? { Authorization: `Bearer ${token}` } : {} });
  assertOwner();
  return result;
}

/** One deadline covers session lookup, HTTP bodies, and the one auth refresh. */
export const CONTACT_REVEAL_TIMEOUT_MS = 30_000;

/** GET-only auth recovery. Transport failures require an explicit user retry. */
async function requestWithRevealRetry<T>(
  url: string,
  init: Omit<RequestInit, 'headers'>,
  isStaleReveal: (resp: T) => boolean,
): Promise<T> {
  const controller = new AbortController();
  let interruption: ApiError | DOMException | null = null;
  let rejectInterruption!: (error: ApiError | DOMException) => void;
  const interrupted = new Promise<never>((_resolve, reject) => { rejectInterruption = reject; });
  const interrupt = (error: ApiError | DOMException) => {
    if (interruption !== null) return;
    interruption = error;
    rejectInterruption(error);
    controller.abort(error);
  };
  const assertActive = () => { if (interruption !== null) throw interruption; };
  const callerSignal = init.signal;
  const abort = () => interrupt(new DOMException('The request was cancelled.', 'AbortError'));
  if (callerSignal?.aborted) abort();
  else callerSignal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(() => interrupt(new ApiError(
    408, 'CONTACT_REVEAL_TIMEOUT', 'The contact email could not be loaded. Please try again.', true,
  )), CONTACT_REVEAL_TIMEOUT_MS);
  const headers = (auth: string | null): Record<string, string> => ({
    'Content-Type': 'application/json',
    ...(auth ? { Authorization: `Bearer ${auth}` } : {}),
  });
  try {
    return await Promise.race([interrupted, (async () => {
      assertActive();
      const token = await getRevealAccessToken({ throwOnError: true });
      assertActive();
      let resp = await request<T>(url, { ...init, signal: controller.signal, headers: headers(token) });
      assertActive();
      if (token && isStaleReveal(resp)) {
        const fresh = await refreshRevealAccessToken({ throwOnError: true });
        assertActive();
        if (fresh) {
          resp = await request<T>(url, { ...init, signal: controller.signal, headers: headers(fresh) });
          assertActive();
        }
      }
      return resp;
    })()]);
  } finally {
    clearTimeout(timer);
    callerSignal?.removeEventListener('abort', abort);
  }
}

/**
 * Split the free-text research-interests box into discrete topic terms for
 * `desired_fields`, which the matcher intersects with each opportunity's
 * keywords for an exact-match bonus. Previously hardcoded to [], so that bonus
 * path was dead for every real user. Splits on commas/semicolons/newlines and
 * the conjunction "and" (so "computer vision and machine learning" → two terms),
 * trims and dedupes without discarding later terms. The full text also travels unchanged. Non-matching terms are
 * harmless — the matcher only rewards terms that actually intersect a keyword.
 */
export function deriveDesiredFields(interests: string | undefined): string[] {
  if (!interests) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of interests.split(/[,;\n]|\s+and\s+/i)) {
    const term = raw.trim();
    const key = term.toLowerCase();
    if (term.length >= 2 && !seen.has(key)) {
      seen.add(key);
      out.push(term);
    }
  }
  return out;
}

export function toProfileRequest(profile: ProfileData): ProfileRequest {
  const homeSchool = profile.home_school ?? 'uiuc';
  const requestedSeekingTypes =
    profile.seeking_types ?? ['research', 'summer_program'];
  const acceptedSeekingTypes = requestedSeekingTypes.filter(
    (value) => RELEASE_SCOPE.fellowships || !isFellowshipPreference(value),
  );
  const request: ProfileRequest = {
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
    // Only a missing legacy field receives defaults above. An explicit empty
    // selection stays empty; Match rejects it, while material tools allow it.
    seeking_type: acceptedSeekingTypes,
    desired_fields: deriveDesiredFields(profile.research_interests),
    // Provenance travels with the level or the level is a lie on arrival: the
    // server decides whether a skill may back "I have experience with X", and
    // it can only withhold that for an import it can still see is an import.
    // An explicit field list is what dropped them here in the first place.
    hard_skills: profile.skills.map((s) => ({
      name: s.name,
      level: s.level,
      ...(s.source !== undefined && s.source !== null ? { source: s.source } : {}),
      ...(s.confirmed === true ? { confirmed: true } : {}),
    })),
    coursework: profile.coursework ?? [],
    experience_level: profile.experience_level ?? 'beginner',
    resume_ready: !!profile.resume_text,
    can_cold_email: true,
    research_interests_text: profile.research_interests,
    linkedin_url: profile.linkedin_url ?? '',
    github_url: profile.github_url ?? '',
    scholar_url: profile.scholar_url ?? '',
    search_weight: profile.search_weight ?? 50,
    exploring: profile.exploring ?? false,
    include_cross_school:
      RELEASE_SCOPE.crossSchoolMatching && (profile.include_cross_school ?? false),
  };
  assertProfileInput(request);
  return request;
}

/** POST /api/matches — get ranked opportunities for a profile */
export async function getMatches(
  profile: ProfileData,
  options: {
    llm?: boolean;
    limit?: number;
    cursor?: string | null;
    signal?: AbortSignal;
  } = {},
): Promise<MatchesResponse> {
  // Deterministic is the release default. Both source-controlled acceptance
  // and an explicit user action are required before the request can opt in.
  const llm = RELEASE_SCOPE.matchAiRefine && options.llm === true;
  const params = new URLSearchParams({ llm: llm ? 'true' : 'false' });
  if (options.limit !== undefined) params.set('limit', String(options.limit));
  if (options.cursor) params.set('cursor', options.cursor);
  return request<MatchesResponse>(`/matches?${params.toString()}`, {
    method: 'POST',
    body: JSON.stringify(toProfileRequest(profile)),
    signal: options.signal,
    timeoutMs: 70_000,
    // Matching computes a snapshot; it writes nothing, so replaying it is safe.
    // The backend has always answered MATCH_BUSY / MATCH_TIMEOUT with
    // retryable:true and Retry-After:5 — nothing consumed either, so a student
    // whose first click landed while the single match worker was occupied saw
    // an error page for a condition that clears in seconds.
    retries: 2,
  });
}

export interface MatchViewRequestState {
  tab: 'all' | 'high_priority' | 'good_match' | 'reach' | 'starred';
  search_query: string;
  paid: '' | 'yes' | 'no';
  intl: '' | 'yes' | 'no';
  source: string;
  on_campus: '' | 'yes' | 'no';
  deadline: DeadlineFilterValue;
  min_score: number;
  scope: '' | 'campus' | 'open';
  sort_by: 'score' | 'deadline' | 'newest';
  show_dismissed: boolean;
  favorite_ids: string[];
  dismissed_ids: string[];
  today: string;
}

/** Exact, bounded results view. Search/filter/count semantics live on the
 * complete canonical snapshot; `results` contains only the requested page. */
export async function getMatchView(
  profile: ProfileData,
  view: MatchViewRequestState,
  options: {
    cursor?: string | null;
    pageSize?: number;
    llm?: boolean;
    signal?: AbortSignal;
  } = {},
): Promise<MatchesResponse> {
  // Same two gates getMatches applies, and in the query string for the same
  // reason the route documents: the server's spend backstop reads the query,
  // not the body.
  const llm = RELEASE_SCOPE.matchAiRefine && options.llm === true;
  return request<MatchesResponse>(`/matches/view?llm=${llm ? 'true' : 'false'}`, {
    method: 'POST',
    body: JSON.stringify({
      profile: toProfileRequest(profile),
      view,
      page_size: options.pageSize ?? 50,
      cursor: options.cursor ?? null,
    }),
    signal: options.signal,
    timeoutMs: 70_000,
    retries: 2,
  });
}

export async function getOpportunities(): Promise<OpportunitiesResponse> {
  return request<OpportunitiesResponse>('/opportunities');
}

export interface FellowshipQuery {
  opportunity_type?: 'summer_program' | 'fellowship' | 'research' | 'internship';
  international_friendly?: 'yes' | 'no';
  limit?: number;
  offset?: number;
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
  if (query.offset) params.set('offset', String(query.offset));
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
  /** Course codes are campus-scoped ('uiuc' is the only verified catalog);
   *  null means generic self-study guidance, not campus courses. */
  course_catalog?: 'uiuc' | null;
}
export interface RoadmapResult {
  skills: RoadmapSkill[];
  /** Targets actually resolved against the current corpus (legacy name). */
  total_labs: number;
  // Accounting fields (additive; absent on older backends): they keep stale
  // favorite ids and evidence-free records from masquerading as "all set".
  requested_targets?: number;
  resolved_targets?: number;
  unresolved_targets?: number;
  inactive_targets?: number;
  unverified_targets?: number;
  targets_with_skill_evidence?: number;
  targets_without_skill_evidence?: number;
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
  /** Echo of the requested id (absent on older backends). */
  opportunity_id?: string;
  /** Canonical unknown-semantics trace (see MatchResult.unknowns). */
  unknowns?: string[];
  /** False when this opportunity is excluded from the profile's /matches
   *  universe — the score above is informational, not a listed match. */
  in_results?: boolean;
  /** Why it is excluded ('citizenship_restricted', 'cross_school_hidden', …). */
  excluded_reason?: string | null;
  /** Matching-logic version — same string /matches serves. */
  matcher_version?: string;
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
    throw await apiErrorFromResponse(res);
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
  options: { llm?: boolean } = {},
): Promise<MatchExplanationResponse> {
  // Mirror getMatches so every surface reaches the same deterministic
  // conclusion while AI refine remains outside the accepted release.
  const llm = RELEASE_SCOPE.matchAiRefine && options.llm === true;
  const qs = `?llm=${llm ? 'true' : 'false'}`;
  return request<MatchExplanationResponse>(
    `/matches/${encodeURIComponent(opportunityId)}/explain${qs}`,
    {
      method: 'POST',
      body: JSON.stringify(toProfileRequest(profile)),
    },
  );
}

export async function getOpportunityById(
  id: string,
  options: { signal?: AbortSignal } = {},
): Promise<Record<string, unknown>> {
  // Reveal-aware: a signed-in session gets contact_email back on the detail
  // payload; a stale token refreshes + retries once, then degrades to the
  // anonymous shape (contact_email_status: 'sign_in_required').
  return requestWithRevealRetry<Record<string, unknown>>(
    `/opportunities/${encodeURIComponent(id)}`,
    options,
    (resp) => resp.contact_email_status === 'sign_in_required',
  );
}

/**
 * POST /api/professors/updates — verified change events for the professors the
 * user follows, newest first. `available: false` means the tracking artifact
 * hasn't been published yet (an honest empty state, not an error).
 */
export async function getProfessorUpdates(
  ids: string[],
  limit = 50,
): Promise<ProfessorUpdatesResponse> {
  if (ids.length === 0) {
    return { available: true, events: [], requested: 0, has_more: false };
  }
  return request<ProfessorUpdatesResponse>('/professors/updates', {
    method: 'POST',
    // The API caps a request at 200 ids; the newest events across the first
    // 200 follows is plenty for the dashboard feed.
    body: JSON.stringify({ ids: ids.slice(0, 200), limit }),
  });
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

export interface ShortlistFetchResult {
  opportunities: Record<string, unknown>[];
  unavailableIds: string[];
}

// ids arrive from Supabase rows / localStorage — external, unvalidated data
// the TS `string[]` parameter type does not actually guarantee at runtime.
function isValidShortlistRequestId(id: unknown): id is string {
  return typeof id === 'string' && id.length <= 100 && id.trim().length > 0;
}

function normalizeShortlistIds(ids: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const id of ids) {
    if (!seen.has(id)) {
      seen.add(id);
      out.push(id);
    }
  }
  return out;
}

function shortlistContractError(code: string): ApiError {
  return new ApiError(502, code, 'Your shortlist could not be verified. Please retry.', true);
}

/**
 * Fail-closed sibling of getOpportunitiesByIds for the shortlist journey:
 * a stale/duplicate/mismatched batch response must never render as another
 * opportunity or a silently-shrunk list. Validates every returned id belongs
 * to what was requested, is unique, and that the batch's own requested/found
 * accounting is internally coherent — any violation rejects the whole call
 * as a safe ApiError instead of returning a partially-trusted result.
 */
export async function getShortlistOpportunities(ids: string[]): Promise<ShortlistFetchResult> {
  // Fail closed before any network request — a malformed id (not a real
  // string, too long, or whitespace-only) never partially resolves; raw ids
  // that pass are used exactly as given, never trimmed/rewritten.
  for (const id of ids) {
    if (!isValidShortlistRequestId(id)) throw shortlistContractError('SHORTLIST_MALFORMED_REQUEST_ID');
  }
  const uniq = normalizeShortlistIds(ids);
  if (uniq.length === 0) return { opportunities: [], unavailableIds: [] };

  const chunks: string[][] = [];
  for (let i = 0; i < uniq.length; i += 200) chunks.push(uniq.slice(i, i + 200));

  const responses = await Promise.all(chunks.map(async (chunk) => ({
    chunk,
    body: await request<{ opportunities: Record<string, unknown>[]; requested?: number; found?: number }>(
      '/opportunities/batch',
      { method: 'POST', body: JSON.stringify({ ids: chunk }) },
    ),
  })));

  const byId = new Map<string, Record<string, unknown>>();
  for (const { chunk, body } of responses) {
    if (
      !body
      || !Array.isArray(body.opportunities)
      || typeof body.requested !== 'number'
      || typeof body.found !== 'number'
      || body.requested !== chunk.length
      || body.found !== body.opportunities.length
    ) {
      throw shortlistContractError('SHORTLIST_CONTRACT_MISMATCH');
    }
    const chunkSet = new Set(chunk);
    for (const opp of body.opportunities) {
      if (!opp || typeof opp !== 'object' || Array.isArray(opp)) {
        throw shortlistContractError('SHORTLIST_MALFORMED_RESULT');
      }
      const id = (opp as Record<string, unknown>).id;
      if (typeof id !== 'string' || id.trim().length === 0) throw shortlistContractError('SHORTLIST_MALFORMED_RESULT');
      if (!chunkSet.has(id)) throw shortlistContractError('SHORTLIST_UNKNOWN_ID');
      if (byId.has(id)) throw shortlistContractError('SHORTLIST_DUPLICATE_ID');
      byId.set(id, opp);
    }
  }

  const opportunities: Record<string, unknown>[] = [];
  const unavailableIds: string[] = [];
  for (const id of uniq) {
    const opp = byId.get(id);
    if (opp) opportunities.push(opp);
    else unavailableIds.push(id);
  }
  return { opportunities, unavailableIds };
}

/** Cold Email always sends an explicit evidence envelope. An empty confirmed
 * library must never resurrect legacy raw strings as experience facts. */
export function coldEmailExperienceEvidence(profile: ProfileData | undefined) {
  const master = validateResumeMaster(profile?.resume_master);
  if (!master.ok) throw new ApiError(400, 'INVALID_EMAIL_EXPERIENCE_CONTEXT', 'Review your master résumé before using these materials.', false);
  return {
    version: 2,
    resume_text: profile?.resume_text ?? '',
    entries: profile?.experience_entries ?? [],
    // Carry current relationships explicitly; never infer an activity from prose.
    resume_master: master.value,
  };
}

/** POST /api/cold-email — generate a cold email draft */
export async function generateColdEmail(
  profile: ProfileData,
  opportunityId: string,
  options: { engine?: ColdEmailEngine; style?: EmailStyle; resumeBullets?: string[]; expectedTargetVersion?: string; contactContext?: EmailContactContext | null } = {},
): Promise<ColdEmailResponse> {
  void track('ai_feature_used', { feature: 'cold_email' });
  const body: Record<string, unknown> = {
    profile: toProfileRequest(profile),
    opportunity_id: opportunityId,
    experience_evidence: coldEmailExperienceEvidence(profile),
  };
  if (options.contactContext != null) body.contact_context = normalizeEmailContactContext(options.contactContext);
  if (options.engine) body.engine = options.engine;
  if (options.style) body.style = options.style;
  if (options.expectedTargetVersion !== undefined) body.expected_target_version = options.expectedTargetVersion;
  return requestWritingWithAuth<ColdEmailResponse>(
    '/cold-email',
    { method: 'POST', body: JSON.stringify(body) },
  );
}

export type ColdEmailStage = 'drafting' | 'judging' | 'critiquing' | 'revising';

/**
 * SSE variant of `generateColdEmail`: relays `{"stage": ...}` progress events
 * while the multi-call pipeline runs (draft → critique → revise), then
 * resolves with the final payload carried by the `done` event. Throws on any
 * transport/shape problem. Only a definite unsupported endpoint permits a blocking compatibility request.
 */
export async function generateColdEmailStream(
  profile: ProfileData,
  opportunityId: string,
  options: { engine?: ColdEmailEngine; style?: EmailStyle; resumeBullets?: string[]; expectedTargetVersion?: string; contactContext?: EmailContactContext | null; signal?: AbortSignal } = {},
  onStage?: (stage: ColdEmailStage) => void,
): Promise<ColdEmailResponse> {
  const contactContext = options.contactContext == null ? undefined : normalizeEmailContactContext(options.contactContext);
  const token = captureOwnerToken();
  const controller = new AbortController();
  let response: Response | undefined;
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  let interruption: ColdEmailStreamError | null = null;
  let retired = false;
  let cancelledBody = false;
  const cancelBody = (body: ReadableStream<Uint8Array> | null | undefined) => {
    try { if (body) void Promise.resolve(body.cancel()).catch(() => {}); } catch { /* safe best effort */ }
  };
  const release = () => {
    if (cancelledBody || (!reader && !response?.body)) return;
    cancelledBody = true;
    if (reader) { try { void Promise.resolve(reader.cancel()).catch(() => {}); } catch { /* safe best effort */ } }
    else cancelBody(response?.body);
  };
  let rejectInterruption!: (error: ColdEmailStreamError) => void;
  const interrupted = new Promise<never>((_resolve, reject) => { rejectInterruption = reject; });
  const interrupt = (code: 'timeout' | 'cancelled') => {
    if (interruption || retired) return;
    interruption = new ColdEmailStreamError(code);
    rejectInterruption(interruption);
    controller.abort(); release();
  };
  const active = () => {
    if (!isWritingOwnerCurrent(token)) interrupt('cancelled');
    if (interruption) throw interruption;
  };
  const abortFromCaller = () => interrupt('cancelled');
  if (options.signal?.aborted) abortFromCaller();
  else options.signal?.addEventListener('abort', abortFromCaller, { once: true });
  const timer = setTimeout(() => interrupt('timeout'), COLD_EMAIL_STREAM_TIMEOUT_MS);
  try {
    return await Promise.race([interrupted, (async () => {
      active();
      const body: Record<string, unknown> = { profile: toProfileRequest(profile), opportunity_id: opportunityId,
        experience_evidence: coldEmailExperienceEvidence(profile) };
      if (contactContext !== undefined) body.contact_context = contactContext;
      if (options.engine) body.engine = options.engine;
      if (options.style) body.style = options.style;
      if (options.expectedTargetVersion !== undefined) body.expected_target_version = options.expectedTargetVersion;
      // Freeze nested course/experience arrays before credentials yield control.
      const requestBody = JSON.stringify(body);
      // Authentication, headers and the complete SSE body share one deadline.
      const streamToken = await getRevealAccessToken();
      active();
      response = await fetch(`${API_BASE}/cold-email/stream`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream',
          ...(streamToken ? { Authorization: `Bearer ${streamToken}` } : {}) },
        body: requestBody, signal: controller.signal,
      });
      if (interruption) { cancelBody(response.body); active(); }
      if (!response.ok) {
        // Read only recognized source/context conflicts, within the existing deadline.
        // Upstream messages and unknown conflict codes never reach the editor.
        if ((response.status === 409 || response.status === 422 || response.status === 413) && response.headers?.get('content-type')?.includes('application/json')) {
          const failure: unknown = await response.json().catch(() => null);
          active();
          if (failure && typeof failure === 'object' && 'detail' in failure) {
            const detail = (failure as { detail: unknown }).detail;
            if (detail && typeof detail === 'object' && 'code' in detail) {
              const code = detail.code;
              if (code === 'PROFILE_INPUT_LIMIT_EXCEEDED' || code === 'PROFILE_INPUT_INVALID') {
                throw new ApiError(response.status, code, 'Check your profile input.', false, undefined, detail);
              }
              if ((response.status === 409 && (code === 'WRITING_TARGET_CHANGED' || code === 'EMAIL_CONTACT_INSTRUCTIONS'))
                || (response.status === 422 && code === 'EMAIL_READING_CHANGED')
                || (response.status === 413 && code === 'EMAIL_INPUT_TOO_LARGE')) {
                throw new ColdEmailStreamError(code, response.status);
              }
            }
          }
        }
        throw new ColdEmailStreamError(response.status === 404 || response.status === 405 ? 'unsupported' : 'http_error', response.status);
      }
      if (!response.headers.get('content-type')?.includes('text/event-stream') || !response.body) {
        throw new ColdEmailStreamError('invalid_response');
      }
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let final: ColdEmailResponse | null = null;
      while (final === null) {
        const { value, done } = await reader.read();
        active();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let index;
        while (final === null && (index = buffer.indexOf('\n\n')) !== -1) {
          const frame = buffer.slice(0, index); buffer = buffer.slice(index + 2);
          for (const line of frame.split('\n')) {
            active();
            if (!line.startsWith('data: ')) continue;
            let payload: unknown;
            try { payload = JSON.parse(line.slice(6)); } catch { throw new ColdEmailStreamError('invalid_response'); }
            if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new ColdEmailStreamError('invalid_response');
            const data = payload as Record<string, unknown>;
            if (data.stage === 'error') {
              if (data.code === 'EMAIL_INPUT_TOO_LARGE' && data.status === 413) {
                throw new ColdEmailStreamError('EMAIL_INPUT_TOO_LARGE', 413);
              }
              throw new ColdEmailStreamError('invalid_response');
            }
            if (data.stage === 'done') {
              if (typeof data.subject !== 'string' || typeof data.body !== 'string') throw new ColdEmailStreamError('invalid_response');
              final = data as unknown as ColdEmailResponse;
              break;
            }
            if (data.stage === 'drafting' || data.stage === 'judging' || data.stage === 'critiquing' || data.stage === 'revising') {
              onStage?.(data.stage); active();
            }
          }
        }
      }
      if (!final) throw new ColdEmailStreamError('invalid_response');
      active();
      void track('ai_feature_used', { feature: 'cold_email' }, token);
      return final;
    })()]);
  } catch (error) {
    active();
    if (error instanceof ColdEmailStreamError || error instanceof ProfileInputError || error instanceof ApiError && ['INVALID_EMAIL_EXPERIENCE_CONTEXT', 'PROFILE_INPUT_LIMIT_EXCEEDED', 'PROFILE_INPUT_INVALID'].includes(error.code)) throw error;
    throw new ColdEmailStreamError('network_error');
  } finally {
    retired = true; clearTimeout(timer);
    options.signal?.removeEventListener('abort', abortFromCaller);
    release();
  }
}

export async function getEmailVariants(
  profile: ProfileData,
  opportunityId: string,
  /** Deprecated compatibility argument: unconfirmed raw strings are ignored. */
  _legacyResumeBullets: string[] = [],
  options: { expectedTargetVersion?: string; contactContext?: EmailContactContext | null } = {},
): Promise<EmailVariantsResponse> {
  return requestWritingWithAuth<EmailVariantsResponse>(
    '/cold-email/variants',
    {
      method: 'POST',
      body: JSON.stringify({
        profile: toProfileRequest(profile),
        opportunity_id: opportunityId,
        expected_target_version: options.expectedTargetVersion,
        ...(options.contactContext == null ? {} : { contact_context: normalizeEmailContactContext(options.contactContext) }),
        experience_evidence: coldEmailExperienceEvidence(profile),
      }),
    },
  );
}

export interface EmailRefineResponse {
  body?: string;
  method: string;
  fallback_reason?: string;
  scope?: 'selection';
  outcome?: 'proposal' | 'no_change';
  reason?: 'provider_unavailable' | 'insufficient_evidence' | 'review_required' | 'invalid_output' | 'fabrication' | 'unchanged' | 'target_conditions';
  target_conditions?: EmailTargetConditions;
  condition_issues?: EmailConditionIssue[];
  proposal?: Omit<EmailTextSelection, 'text'> & { original_text: string; replacement: string; base_body_sha256: string };
  experience_usage?: ExperienceUsage;
  opportunity_id?: string | null;
  target_version?: string | null;
  contact_context_receipt?: EmailContactContextReceipt;
}

export async function refineEmail(
  currentBody: string,
  instruction: string,
  profile: ProfileData | undefined,
  // Required: refine rewrites a draft against one target's evidence, and the
  // server resolves that target before it will spend anything. Optional here
  // only ever meant "send null and hope"; the modal has always had the id.
  opportunityId: string,
  /** Legacy resumeBullets are ignored; only confirmed profile entries count. */
  options: { resumeBullets?: string[]; expectedTargetVersion?: string; contactContext?: EmailContactContext | null; selection?: EmailTextSelection; subject?: string } = {},
): Promise<EmailRefineResponse> {
  return request<EmailRefineResponse>('/cold-email/refine', {
    method: 'POST',
    body: JSON.stringify({
      current_body: currentBody,
      ...(options.selection ? { selection: options.selection, subject: options.subject ?? '' } : {}),
      instruction: instruction,
      profile: profile ? toProfileRequest(profile) : null,
      opportunity_id: opportunityId,
      expected_target_version: options.expectedTargetVersion,
      ...(options.contactContext == null ? {} : { contact_context: normalizeEmailContactContext(options.contactContext) }),
      experience_evidence: coldEmailExperienceEvidence(profile),
    }),
  });
}

export interface EmailValidationResponse {
  opportunity_id: string;
  target_version: string;
  pipeline_version: string;
  contact_context_receipt: EmailContactContextReceipt;
  target_conditions: EmailTargetConditions;
  outcome: 'ready' | 'review_required';
  issues: EmailConditionIssue[];
}

/** Checks the current text against explicit target conditions without generating or sending mail. */
export async function validateEmailDraft(subject: string, body: string, profile: ProfileData, opportunityId: string,
  options: { expectedTargetVersion: string; contactContext: EmailContactContext; signal?: AbortSignal }): Promise<EmailValidationResponse> {
  return request<EmailValidationResponse>('/cold-email/validate', {
    method: 'POST', timeoutMs: 25000, signal: options.signal,
    body: JSON.stringify({ subject, body, profile: toProfileRequest(profile), opportunity_id: opportunityId,
      expected_target_version: options.expectedTargetVersion, contact_context: normalizeEmailContactContext(options.contactContext),
      experience_evidence: coldEmailExperienceEvidence(profile) }),
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
 * `locale` (R71-D) selects the language of the model's instructions; each
 * rewrite stays in its own bullet's language (w14.1). Backend normalizes
 * region tags ('zh-CN' / 'zh_TW' / 'zh') to 'zh', and any unknown
 * value falls back to 'en' rather than 422-ing — so we can safely
 * pass `useT().locale` through without sanitization.
 */
export async function tailorResume(
  profile: ProfileData,
  opportunityId: string,
  originalBullets: string[],
  options: { locale?: string; expectedPipelineVersion?: string; expectedTargetVersion?: string; sourceBullets?: string[] } = {},
): Promise<TailorResponse> {
  void track('ai_feature_used', { feature: 'tailor' });
  const body: Record<string, unknown> = {
    profile: toProfileRequest(profile),
    opportunity_id: opportunityId,
    original_bullets: originalBullets,
  };
  // sourceBullets[i] is bullet i's evidence when its text is reviewed wording.
  if (options.sourceBullets) body.source_bullets = options.sourceBullets;
  if (options.locale) body.locale = options.locale;
  if (options.expectedPipelineVersion) body.expected_pipeline_version = options.expectedPipelineVersion;
  if (options.expectedTargetVersion !== undefined) body.expected_target_version = options.expectedTargetVersion;
  return request<TailorResponse>('/tailor', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export interface TailorStatus {
  ai_available: boolean;
  pipeline_version: string;
}

export const TAILOR_STATUS_TIMEOUT_MS = 15_000;

/** One public source read, bounded through the complete body. A fetch/body
 * implementation that ignores abort still cannot hold the editor indefinitely. */
export async function getTailorStatus(): Promise<TailorStatus> {
  const controller = new AbortController();
  let response: Response | undefined;
  const message = 'Tailoring rules could not be checked. Please try again.';
  const invalid = () => new ApiError(200, 'INVALID_TAILOR_STATUS', message, true);
  const timeout = () => new ApiError(408, 'TAILOR_STATUS_TIMEOUT', message, true);
  const http = (status: number) => new ApiError(status, `HTTP_${status}`, message, status === 429 || status >= 500);
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      void response?.body?.cancel().catch(() => {});
      reject(timeout());
    }, TAILOR_STATUS_TIMEOUT_MS);
  });
  try {
    return await Promise.race([deadline, (async () => {
      response = await fetch(`${API_BASE}/tailor/status`, {
        method: 'GET', cache: 'no-store', credentials: 'omit',
        headers: { Accept: 'application/json' }, signal: controller.signal,
      });
      if (controller.signal.aborted) { void response.body?.cancel().catch(() => {}); throw timeout(); }
      let body: string;
      try { body = await response.text(); }
      catch {
        if (controller.signal.aborted) throw timeout();
        if (!response.ok) throw http(response.status);
        throw invalid();
      }
      if (controller.signal.aborted) throw timeout();
      if (!response.ok) throw http(response.status);
      let value: unknown;
      try { value = JSON.parse(body); } catch { throw invalid(); }
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid();
      const result = value as Record<string, unknown>;
      if (typeof result.ai_available !== 'boolean' || typeof result.pipeline_version !== 'string'
        || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(result.pipeline_version)) throw invalid();
      return { ai_available: result.ai_available, pipeline_version: result.pipeline_version };
    })()]);
  } catch (error) {
    if (controller.signal.aborted) throw timeout();
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, 'TAILOR_STATUS_UNAVAILABLE', message, true);
  } finally { if (timer !== undefined) clearTimeout(timer); }
}

/**
 * The VAPID public key the backend's private key will sign pushes with.
 *
 * Only the server knows which key that is, so it is the only correct source:
 * the browser accepts any well-formed key when minting a subscription, and a
 * mismatch surfaces nowhere until delivery silently stops. `null` when the
 * server has no key configured (503) or is unreachable — the caller then
 * offers no subscribe control rather than one that cannot work.
 */
export async function getVapidPublicKey(): Promise<string | null> {
  try {
    const { key } = await request<{ key: string }>('/push/vapid-public-key');
    return key || null;
  } catch {
    return null;
  }
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
  options: { locale?: string; expectedTargetVersion?: string } = {},
): Promise<RenovateResponse> {
  void track('ai_feature_used', { feature: 'renovate' });
  const body: Record<string, unknown> = {
    profile: toProfileRequest(profile),
    opportunity_id: opportunityId,
    sections,
  };
  if (options.locale) body.locale = options.locale;
  if (options.expectedTargetVersion !== undefined) body.expected_target_version = options.expectedTargetVersion;
  return request<RenovateResponse>('/tailor/renovate', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** One explicit batch of whole-document suggestions. Replays may spend again,
 * so retries remain opt-in at the workspace, never automatic in transport. */
export async function generateTargetResumeSuggestions(
  payload: TargetResumeAiRequest,
  options: { owner: OwnerToken; signal?: AbortSignal },
): Promise<TargetResumeAiResponse> {
  const body = JSON.stringify({ ...payload, include_check_version: true });
  if (new TextEncoder().encode(body).byteLength > FULL_TARGET_AI_MAX_BODY_BYTES) {
    throw new ApiError(413, 'FULL_TARGET_BODY_TOO_LARGE', 'This complete document exceeds the AI request limit.', false);
  }
  if (options.signal?.aborted || !isOwnerTokenValid(options.owner, options.owner.uid)) {
    throw new ApiError(409, 'FULL_TARGET_OWNER_CHANGED', 'The active profile changed.', false);
  }
  const token = await writingAccessToken(options.owner, options.signal).catch((error: unknown) => {
    if (options.signal?.aborted || !isOwnerTokenValid(options.owner, options.owner.uid)) {
      throw new ApiError(409, 'FULL_TARGET_OWNER_CHANGED', 'The active profile changed.', false);
    }
    throw error;
  });
  if (options.signal?.aborted || !isOwnerTokenValid(options.owner, options.owner.uid)) {
    throw new ApiError(409, 'FULL_TARGET_OWNER_CHANGED', 'The active profile changed.', false);
  }
  return request<TargetResumeAiResponse>('/tailor/full-target/suggestions', {
    method: 'POST', body, signal: options.signal, cache: 'no-store',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    retries: 0,
  });
}

/** One complete-document selection plan. Freeze the body before auth;
 * a cancelled or stale owner must never dispatch private material. */
export async function generateTargetResumePlan(
  payload: TargetResumePlanRequest,
  options: { owner: OwnerToken; signal?: AbortSignal },
): Promise<TargetResumePlanResponse> {
  const body = JSON.stringify({ ...payload, include_check_version: true });
  if (new TextEncoder().encode(body).byteLength > TARGET_RESUME_PLAN_MAX_BODY_BYTES) {
    throw new ApiError(413, 'TARGET_RESUME_PLAN_BODY_TOO_LARGE', 'This complete document exceeds the AI request limit.', false);
  }
  if (options.signal?.aborted || !isOwnerTokenValid(options.owner, options.owner.uid)) {
    throw new ApiError(409, 'TARGET_RESUME_PLAN_OWNER_CHANGED', 'The active profile changed.', false);
  }
  const token = await writingAccessToken(options.owner, options.signal).catch((error: unknown) => {
    if (options.signal?.aborted || !isOwnerTokenValid(options.owner, options.owner.uid)) {
      throw new ApiError(409, 'TARGET_RESUME_PLAN_OWNER_CHANGED', 'The active profile changed.', false);
    }
    throw error;
  });
  if (options.signal?.aborted || !isOwnerTokenValid(options.owner, options.owner.uid)) {
    throw new ApiError(409, 'TARGET_RESUME_PLAN_OWNER_CHANGED', 'The active profile changed.', false);
  }
  return request<TargetResumePlanResponse>('/tailor/full-target/selection-plan', {
    method: 'POST', body, signal: options.signal, cache: 'no-store',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    retries: 0,
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
  options: { instruction?: string; locale?: string; expectedTargetVersion?: string } = {},
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
  if (options.expectedTargetVersion !== undefined) body.expected_target_version = options.expectedTargetVersion;
  return request<BulletOptimizeResponse>('/tailor/bullet', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export interface ExtractBulletsResponse {
  pipeline_version?: string;
  generated_at?: string;
  bullets: string[];
  method: 'ai' | 'heuristic' | 'mixed';
  warnings?: string[];
  processing?: ResumeProcessingCoverage;
}

/**
 * POST /api/tailor/extract-bullets — LLM-extract resume bullet lines from
 * raw text (catches "dark bullets" the glyph heuristic misses). Always
 * resolves: backend degrades to the glyph heuristic on any LLM issue.
 */
export async function extractResumeBullets(
  resumeText: string,
  options: { expectedPipelineVersion?: string } = {},
): Promise<ExtractBulletsResponse> {
  return request<ExtractBulletsResponse>('/tailor/extract-bullets', {
    method: 'POST',
    body: JSON.stringify({ resume_text: resumeText,
      ...(options.expectedPipelineVersion ? { expected_pipeline_version: options.expectedPipelineVersion } : {}) }),
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

/**
 * One mailed match. `opportunity_id` is the only field the new backend reads —
 * it rehydrates title, link, organization, source and deadline from the
 * canonical record, because a digest outlives the tab that asked for it and a
 * client-supplied claim would sit in an inbox under our name with nothing
 * behind it.
 *
 * ROLLOUT BRIDGE — keep sending the legacy fields for now.
 * Vercel and Render deploy independently and the frontend usually lands first,
 * so for one release we send both shapes: an OLD backend still renders from
 * title/url/..., and the NEW backend accepts them and throws them away. The
 * follow-up PR, once both sides are on the same SHA, drops them here and
 * forbids them there. Removing them earlier breaks the deploy window.
 */
export interface EmailMatchItem {
  opportunity_id: string;
  title?: string;
  url?: string;
  score?: number;
  source?: string;
  deadline?: string | null;
  organization?: string;
  record_kind?: 'listing' | 'faculty_contact' | 'unknown';
}

/** The bearer header a digest send must carry.
 *
 *  The server now mails the CALLER's own confirmed address and refuses any
 *  other, so a request with no token is not "an anonymous send" — it is a 401.
 *  `request` does not attach credentials on its own, which is why this is
 *  explicit here rather than inherited.
 */
async function digestAuthHeaders(): Promise<Record<string, string>> {
  const token = await getRevealAccessToken();
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export async function sendMatchesEmail(
  email: string,
  items: EmailMatchItem[],
  subjectHint = '',
): Promise<{ ok: boolean; count: number }> {
  return request('/email/send-matches', {
    method: 'POST',
    headers: await digestAuthHeaders(),
    // ROLLOUT BRIDGE: `email` is the caller's OWN session address, sent only
    // so a Render still running the previous build has a recipient. The
    // current backend ignores the value and refuses it outright when it names
    // anyone but the session. Dropped once both sides are on the same SHA.
    body: JSON.stringify({ email, items, subject_hint: subjectHint }),
  });
}

/**
 * One saved row: which target, plus the notes and status the user owns.
 * The describing fields are the same ROLLOUT BRIDGE as EmailMatchItem.
 */
export interface EmailFavoriteItem {
  opportunity_id: string;
  notes?: string;
  status?: string;
  title?: string;
  url?: string;
  score?: number;
  source?: string;
  deadline?: string | null;
  record_kind?: 'listing' | 'faculty_contact' | 'unknown';
}

export async function sendFavoritesEmail(
  email: string,
  items: EmailFavoriteItem[],
): Promise<{ ok: boolean; count: number }> {
  return request('/email/send-favorites', {
    method: 'POST',
    headers: await digestAuthHeaders(),
    // ROLLOUT BRIDGE, same as sendMatchesEmail.
    body: JSON.stringify({ email, items }),
  });
}

export interface ImportedOpportunityExtras extends Record<string, unknown> {
  suggested_skills?: string[];
  suggested_description?: string;
  description_source?: 'page_excerpt' | 'page_text' | 'pasted_text';
  ai_input_scope?: 'full_source' | 'source_excerpt';
  needs_manual_review?: boolean;
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
  extra_fields: ImportedOpportunityExtras;
}

export interface ImportUrlResponse {
  ok: boolean;
  error_code?: 'import_input_too_large' | 'import_source_unreadable';
  /** The unreadable-source reasons the page words differently: a sign-in, bot-check or error page,
   *  and a page its scripts have yet to fill. */
  error_reason?: 'access_page' | 'javascript_required';
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
    if (err instanceof ApiError && (err.code === 'import_input_too_large' || err.code === 'import_source_unreadable')) {
      const reason = err.code === 'import_source_unreadable'
        ? (err.detail as { reason?: unknown } | null | undefined)?.reason : undefined;
      return reason === 'access_page' || reason === 'javascript_required'
        ? { ok: false, error_code: err.code, error_reason: reason, llm_enriched: false }
        : { ok: false, error_code: err.code, llm_enriched: false };
    }
    const structured = err instanceof ApiError
      ? fastApiDetailText(err.detail)
      : null;
    if (structured) {
      return { ok: false, error: structured, llm_enriched: false };
    }
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
    if (err instanceof ApiError && (err.code === 'import_input_too_large' || err.code === 'import_source_unreadable')) {
      return { ok: false, error_code: err.code, llm_enriched: false };
    }
    const structured = err instanceof ApiError
      ? fastApiDetailText(err.detail)
      : null;
    if (structured) {
      return { ok: false, error: structured, llm_enriched: false };
    }
    const message = err instanceof Error ? err.message : String(err);
    const detail = parseFastApiDetail(message);
    if (detail) {
      return { ok: false, error: detail, llm_enriched: false };
    }
    throw err;
  }
}

function fastApiDetailText(detail: unknown): string | null {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: unknown };
    if (first && typeof first.msg === 'string') return first.msg;
  }
  return null;
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
