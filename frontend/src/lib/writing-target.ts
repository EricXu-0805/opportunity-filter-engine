import { ApiError } from './api';
import { isPublicDetail } from './public-target-shape';
import { PUBLIC_RELEASE_CACHE_VERSION } from './release-scope';
import type { Opportunity } from './types';

export const WRITING_TARGET_TIMEOUT_MS = 15_000;

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
/** Complete public value, including new fields. No projection, trimming or
 * source claims. Object key order is irrelevant; array/content order is exact.
 * This key also accepts an initial card for comparison, never as a read receipt. */
export function writingTargetKey(value: Opportunity | null): string | null {
  if (value === null) return null;
  try {
    return JSON.stringify(value, (_key, item: unknown) => record(item)
      ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0))
      : item) ?? null;
  } catch { return null; }
}

const invalid = () => new ApiError(200, 'INVALID_TARGET_RESPONSE', 'The opportunity could not be verified.', false);
const timedOut = () => new ApiError(408, 'TARGET_READ_TIMEOUT', 'The opportunity check took too long. Please try again.', true);
const cancelled = () => new DOMException('The opportunity check was cancelled.', 'AbortError');
const httpError = (status: number) => new ApiError(status, `HTTP_${status}`,
  status === 404 ? 'The opportunity could not be found.' : 'The opportunity could not be checked. Please try again.',
  status === 429 || status >= 500);

/** One anonymous authoritative detail read. Never waits for auth/reveal and
 * never retries. A single deadline includes both success and error bodies,
 * even when a mock/custom fetch or its body ignores AbortSignal. */
export async function readWritingTarget(id: string,
  options: { signal?: AbortSignal; timeoutMs?: number } = {}): Promise<Opportunity> {
  if (options.signal?.aborted) throw cancelled();
  let encodedId: string;
  try {
    if (typeof id !== 'string' || id.length === 0 || Array.from(id).length > 100 || /[\u0000-\u001f\u007f]/.test(id)) throw new Error();
    encodedId = encodeURIComponent(id);
  } catch { throw new ApiError(400, 'INVALID_TARGET_ID', 'The opportunity could not be checked.', false); }
  const timeoutMs = options.timeoutMs ?? WRITING_TARGET_TIMEOUT_MS;
  if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 2_147_483_647) {
    throw new ApiError(400, 'INVALID_TARGET_TIMEOUT', 'The opportunity could not be checked.', false);
  }
  const controller = new AbortController();
  let timeout = false;
  let response: Response | undefined;
  const abort = () => controller.abort(); // Never expose caller-provided reasons.
  options.signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(() => { timeout = true; controller.abort(); }, timeoutMs);
  const assertActive = () => { if (controller.signal.aborted) throw timeout ? timedOut() : cancelled(); };
  const bounded = <T,>(operation: () => Promise<T>): Promise<T> => new Promise((resolve, reject) => {
    const stop = () => { clean(); reject(timeout ? timedOut() : cancelled()); };
    const clean = () => controller.signal.removeEventListener('abort', stop);
    if (controller.signal.aborted) { stop(); return; }
    controller.signal.addEventListener('abort', stop, { once: true });
    try {
      operation().then(value => { clean(); resolve(value); }, error => { clean(); reject(error); });
    } catch (error) { clean(); reject(error); }
  });
  try {
    assertActive();
    const base = process.env.NEXT_PUBLIC_API_URL || '/api';
    response = await bounded<Response>(() => fetch(`${base.replace(/\/$/, '')}/opportunities/${encodedId}?_release_scope=${encodeURIComponent(PUBLIC_RELEASE_CACHE_VERSION)}`, {
      method: 'GET', cache: 'no-store', credentials: 'omit', signal: controller.signal,
      headers: { Accept: 'application/json' },
    }).then(received => {
      // A fetch implementation may ignore abort and deliver a stream after
      // this call has retired. Release it without reading or accepting it.
      if (controller.signal.aborted) void received.body?.cancel().catch(() => {});
      return received;
    }));
    assertActive();
    let text: string;
    try { text = await bounded(() => response!.text()); }
    catch (error) {
      assertActive();
      if (!response.ok) throw httpError(response.status);
      throw error;
    }
    assertActive();
    // Error bodies are consumed within the deadline but never exposed as
    // messages/codes/details: an upstream could return private HTML or text.
    if (!response.ok) throw httpError(response.status);
    let value: unknown;
    try { value = JSON.parse(text); } catch { throw invalid(); }
    if (!isPublicDetail(value, id)) throw invalid();
    return value;
  } catch (error) {
    assertActive();
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, 'TARGET_READ_FAILED', 'The opportunity could not be checked. Please try again.', true);
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', abort);
    void response?.body?.cancel().catch(() => {});
  }
}
