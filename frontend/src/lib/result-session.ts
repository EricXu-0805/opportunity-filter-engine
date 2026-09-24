import { captureOwnerToken, isOwnerTokenValid, type OwnerToken } from './identity-owner';
import { hashProfile } from './match-utils';
import type { MatchViewRequestState } from './api';
import type { ProfileData } from './types';

export const RESULT_SESSION_PARAM = 'returnSession';
export const RESULT_SESSION_PREFIX = 'ofe_result_session_v1:';
const MAX_AGE_MS = 30 * 60 * 1000;
const MAX_SESSIONS = 8;
const ID = /^[a-zA-Z0-9-]{16,64}$/;
const PUBLIC_KEYS = new Set(['tab', 'q', 'paid', 'intl', 'source', 'loc', 'dl', 'min', 'scope', 'sort', 'ai']);

export interface ResultCursorState {
  requestKey: string;
  page: number;
  cursors: Array<[number, string | null]>;
}
export interface ResultSession extends ResultCursorState {
  v: 1;
  id: string;
  owner: { uid: string | null; generation: number };
  returnUrl: string;
  showDismissed: boolean;
  anchorId: string | null;
  anchorOffset: number | null;
  scrollY: number;
  viewedIds: string[];
  savedAt: number;
}

/** A staleness key, never an identity credential. Matches the data hook. */
export function resultRequestKey(profile: ProfileData, semantic: boolean, view: MatchViewRequestState): string {
  return `${hashProfile(profile)}:${semantic ? '1' : '0'}:${JSON.stringify(view)}`;
}

/** Only public filters on this exact local route may become a return link. */
export function publicResultsUrl(raw: string): string | null {
  if (raw.length > 3000 || !raw.startsWith('/results') || raw.startsWith('//') || /[\\\u0000-\u001f\u007f]/.test(raw)) return null;
  try {
    const url = new URL(raw, 'https://result-session.invalid');
    if (url.origin !== 'https://result-session.invalid' || url.pathname !== '/results') return null;
    const params = new URLSearchParams();
    for (const [key, value] of url.searchParams) {
      if (/[\\\u0000-\u001f\u007f]/.test(key + value)) return null;
      if (PUBLIC_KEYS.has(key)) params.set(key, value);
    }
    const query = params.toString();
    return query ? `/results?${query}` : '/results';
  } catch { return null; }
}

export function resultSessionUrl(url: string, id: string): string {
  const safe = publicResultsUrl(url) ?? '/results';
  if (!ID.test(id)) return safe;
  return `${safe}${safe.includes('?') ? '&' : '?'}${RESULT_SESSION_PARAM}=${encodeURIComponent(id)}`;
}

export function sessionBelongsToOwner(session: ResultSession, token: OwnerToken): boolean {
  return isOwnerTokenValid(token, token.uid)
    && session.owner.uid === token.uid && session.owner.generation === token.generation;
}

function validSession(value: unknown, id: string): value is ResultSession {
  if (!value || typeof value !== 'object') return false;
  const s = value as ResultSession;
  if (s.v !== 1 || s.id !== id || !ID.test(id) || !s.owner
    || !(s.owner.uid === null || typeof s.owner.uid === 'string')
    || !Number.isInteger(s.owner.generation) || s.owner.generation < 0
    || typeof s.requestKey !== 'string' || s.requestKey.length > 128_000
    || !Number.isInteger(s.page) || s.page < 1 || s.page > 10_000
    || typeof s.returnUrl !== 'string' || s.returnUrl.length > 3000
    || publicResultsUrl(s.returnUrl) !== s.returnUrl
    || typeof s.showDismissed !== 'boolean'
    || !(s.anchorId === null || (typeof s.anchorId === 'string' && s.anchorId.length <= 200))
    || !(s.anchorOffset === null || (Number.isFinite(s.anchorOffset) && Math.abs(s.anchorOffset) < 100_000))
    || !Number.isFinite(s.scrollY) || s.scrollY < 0 || s.scrollY > 10_000_000
    || !Number.isFinite(s.savedAt) || Date.now() - s.savedAt > MAX_AGE_MS || s.savedAt > Date.now() + 60_000
    || !Array.isArray(s.viewedIds) || s.viewedIds.length > 512
    || !s.viewedIds.every((x) => typeof x === 'string' && x.length <= 200)
    || !Array.isArray(s.cursors) || s.cursors.length > 128) return false;
  const pages = new Set<number>();
  for (const entry of s.cursors) {
    if (!Array.isArray(entry) || entry.length !== 2) return false;
    const [page, cursor] = entry;
    if (!Number.isInteger(page) || page < 1 || page > 10_000 || pages.has(page)) return false;
    if (page === 1 ? cursor !== null : typeof cursor !== 'string' || !cursor || cursor.length > 2048) return false;
    pages.add(page);
  }
  return pages.has(1) && pages.has(s.page);
}

export function readResultSession(id: string | null, token = captureOwnerToken()): ResultSession | null {
  if (!id || !ID.test(id) || !isOwnerTokenValid(token, token.uid)) return null;
  try {
    const raw = sessionStorage.getItem(RESULT_SESSION_PREFIX + id);
    if (!raw || raw.length > 500_000) return null;
    const value: unknown = JSON.parse(raw);
    return validSession(value, id) && sessionBelongsToOwner(value, token) ? value : null;
  } catch { return null; }
}

type SessionInput = Omit<ResultSession, 'v' | 'id' | 'owner' | 'savedAt'> & { id?: string };
export function writeResultSession(input: SessionInput, token = captureOwnerToken()): ResultSession | null {
  if (!isOwnerTokenValid(token, token.uid)) return null;
  try {
    const id = input.id ?? crypto.randomUUID();
    const cursors = input.cursors.filter(([page]) => page !== 1).slice(-127);
    const session: ResultSession = {
      v: 1, id, owner: { uid: token.uid, generation: token.generation },
      requestKey: input.requestKey, page: input.page, returnUrl: input.returnUrl,
      showDismissed: input.showDismissed, anchorId: input.anchorId,
      anchorOffset: input.anchorOffset, scrollY: input.scrollY,
      cursors: [[1, null], ...cursors], viewedIds: [...new Set(input.viewedIds)].slice(-512), savedAt: Date.now(),
    };
    if (!validSession(session, id)) return null;
    const serialized = JSON.stringify(session);
    sessionStorage.setItem(RESULT_SESSION_PREFIX + id, serialized);
    if (sessionStorage.getItem(RESULT_SESSION_PREFIX + id) !== serialized || !isOwnerTokenValid(token, token.uid)) return null;
    const keys = Array.from({ length: sessionStorage.length }, (_, i) => sessionStorage.key(i))
      .filter((key): key is string => !!key && key.startsWith(RESULT_SESSION_PREFIX) && key !== RESULT_SESSION_PREFIX + id);
    // Retain a bounded set of earlier visits for browser Back, never result rows.
    for (const key of keys.slice(0, Math.max(0, keys.length - MAX_SESSIONS + 1))) {
      try { sessionStorage.removeItem(key); } catch { /* restoration remains optional */ }
    }
    return session;
  } catch { return null; }
}

/** Revokes only this unguessable visit id, never another owner's newer visit. */
export function discardResultSession(id: string): void {
  if (!ID.test(id)) return;
  try { sessionStorage.removeItem(RESULT_SESSION_PREFIX + id); } catch { /* fail closed on read */ }
}
