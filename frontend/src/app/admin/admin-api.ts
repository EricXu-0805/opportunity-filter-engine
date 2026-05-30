// Admin API helper (R36 split). All /admin/* endpoints take the
// X-Admin-Token header. 401 → bad token, 503 → backend missing
// ADMIN_TOKEN env var. SESSION_KEY persists the token across reloads
// in the current tab only (sessionStorage, not localStorage).

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';
export const SESSION_KEY = 'ofe_admin_token';

export async function adminFetch<T>(
  path: string,
  token: string,
  init?: RequestInit,
): Promise<{ data?: T; status: number; error?: string }> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        ...(init?.headers || {}),
        'X-Admin-Token': token,
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
