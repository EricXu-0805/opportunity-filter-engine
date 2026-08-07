// Admin API helper (R36 split). All /admin/* endpoints take the
// X-Admin-Token header. 401 → bad token, 503 → backend missing
// ADMIN_TOKEN env var. SESSION_KEY persists the token across reloads
// in the current tab only (sessionStorage, not localStorage).

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';
export const SESSION_KEY = 'ofe_admin_token';

// Every operator shares ONE ADMIN_TOKEN, so the backend cannot tell them
// apart. X-Admin-Actor is a self-declared label the operator types once per
// tab; it is written into the append-only audit trail so a ticket/incident
// history reads "who claims to have done this", not "who provably did it".
// The UI must label it honestly — see admin.actor.hint.
export const ACTOR_SESSION_KEY = 'ofe_admin_actor';
export const DEFAULT_ACTOR = 'operator';

export function getAdminActor(): string {
  try {
    const stored = sessionStorage.getItem(ACTOR_SESSION_KEY);
    const trimmed = (stored ?? '').trim();
    return trimmed || DEFAULT_ACTOR;
  } catch {
    return DEFAULT_ACTOR;
  }
}

export function setAdminActor(value: string): string {
  const label = value.trim() || DEFAULT_ACTOR;
  try { sessionStorage.setItem(ACTOR_SESSION_KEY, label); } catch { /* private mode */ }
  return label;
}

const READ_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

export async function adminFetch<T>(
  path: string,
  token: string,
  init?: RequestInit,
): Promise<{ data?: T; status: number; error?: string }> {
  try {
    const method = (init?.method ?? 'GET').toUpperCase();
    const mutating = !READ_METHODS.has(method);
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      // Forced after the `init` spread so no caller can accidentally make
      // feedback, order, or other operator-only responses cacheable.
      cache: 'no-store',
      headers: {
        ...(init?.headers || {}),
        'X-Admin-Token': token,
        // Only on writes: reads produce no audit rows, so there is nothing to
        // attribute and no reason to ship the label around.
        ...(mutating ? { 'X-Admin-Actor': getAdminActor() } : {}),
      },
    });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      return { status: res.status, error: text || `HTTP ${res.status}` };
    }
    return { status: res.status, data: (await res.json()) as T };
  } catch (e) {
    return { status: 0, error: e instanceof Error ? e.message : String(e) };
  }
}
