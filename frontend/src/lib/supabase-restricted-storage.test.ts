import { afterEach, describe, expect, it, vi } from 'vitest';

// Keep the actual installed SDK and application client configuration. Only
// browser/network boundaries are controlled; no auth provider is contacted.
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe('Supabase initialization with restricted browser storage', () => {
  it.each(['available', 'getter-denied'] as const)('keeps the existing auth session when sessionStorage is %s', async (storageMode) => {
    vi.resetModules();
    vi.stubEnv('NEXT_PUBLIC_SUPABASE_URL', 'http://127.0.0.1:54324');
    vi.stubEnv('NEXT_PUBLIC_SUPABASE_ANON_KEY', 'test-public-key');
    const fetch = vi.fn(() => Promise.reject(new Error('This regression must not access a provider')));
    vi.stubGlobal('fetch', fetch);
    // Cross-tab messaging is unrelated to this constructor regression. Avoid
    // leaving Node's native BroadcastChannel alive after the browser fixture.
    vi.stubGlobal('BroadcastChannel', undefined);
    const session = {
      access_token: 'synthetic-access-token', refresh_token: 'synthetic-refresh-token',
      token_type: 'bearer', expires_at: Math.floor(Date.now() / 1000) + 3600,
      user: { id: 'restricted-storage-owner', aud: 'authenticated', role: 'authenticated',
        app_metadata: {}, user_metadata: {}, created_at: '2026-01-01T00:00:00Z' },
    };
    const stored = JSON.stringify(session);
    localStorage.setItem('ofe_auth', stored);
    const descriptor = Object.getOwnPropertyDescriptor(window, 'sessionStorage')!;
    const blocked = vi.fn(() => { throw new DOMException('Storage unavailable', 'SecurityError'); });
    if (storageMode === 'getter-denied') {
      Object.defineProperty(window, 'sessionStorage', { configurable: true, get: blocked });
    }
    let client: Awaited<typeof import('./supabase')>['supabase'] | undefined;
    try {
      client = (await import('./supabase')).supabase;
      const result = await client.auth.getSession();
      expect(result.error).toBeNull();
      expect(result.data.session?.user.id).toBe(session.user.id);
      // Phoenix's optional socket-history fallback must not replace the
      // application's auth storage or silently claim a new user identity.
      expect(localStorage.getItem('ofe_auth')).toBe(stored);
      expect(fetch).not.toHaveBeenCalled();
      if (storageMode === 'getter-denied') {
        expect(blocked).toHaveBeenCalled();
        expect(() => window.sessionStorage).toThrow('Storage unavailable');
      }
    } finally {
      await client?.auth.stopAutoRefresh();
      await client?.removeAllChannels();
      Object.defineProperty(window, 'sessionStorage', descriptor);
    }
  });
});
