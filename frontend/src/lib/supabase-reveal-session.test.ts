import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const sdk = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return { session: vi.fn(), refresh: vi.fn() };
});
vi.mock('@supabase/supabase-js', () => ({ createClient: () => ({ auth: { getSession: sdk.session, refreshSession: sdk.refresh } }) }));
import { getAuthState, getRevealAccessToken, refreshRevealAccessToken } from './supabase';
const session = { access_token: 'test-token', user: { id: 'user-a', is_anonymous: false, email: 'student@example.com' } };
const absent = { data: { session: null }, error: null };
const available = { data: { session }, error: null };
beforeEach(() => { sdk.session.mockReset(); sdk.refresh.mockReset(); });
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe.each([
  ['auth state', getAuthState, sdk.session],
  ['reveal token', getRevealAccessToken, sdk.session],
  ['refresh token', refreshRevealAccessToken, sdk.refresh],
] as const)('strict %s', (_label, read, method) => {
  it.each(['returned', 'rejected'] as const)('surfaces %s SDK errors without exposing their contents', async mode => {
    const sensitive = 'private SDK token and provider diagnostic';
    if (mode === 'returned') method.mockResolvedValue({ data: { session: null }, error: new Error(sensitive) });
    else method.mockRejectedValue(new Error(sensitive));
    const result = await read({ throwOnError: true }).catch(error => error);
    expect(result).toBeInstanceOf(Error);
    expect(result.message).toMatch(/sign-in could not be/);
    expect(result.message).not.toContain(sensitive);
    expect(result.cause).toBeUndefined();
  });
  it('does not accept a session when the SDK also reports an error', async () => {
    method.mockResolvedValue({ data: { session }, error: new Error('partial SDK error') });
    await expect(read({ throwOnError: true })).rejects.toThrow(/sign-in could not be/);
  });
});

describe.each([
  ['reveal token', getRevealAccessToken, sdk.session],
  ['refresh token', refreshRevealAccessToken, sdk.refresh],
] as const)('%s compatibility', (_label, read, method) => {
  it('returns a formal account token in strict mode', async () => {
    method.mockResolvedValue(available); await expect(read({ throwOnError: true })).resolves.toBe('test-token');
  });
  it.each(['absent', 'anonymous', 'missing-token'] as const)('keeps %s distinct from a failed read', async kind => {
    const result = kind === 'absent' ? absent : { data: { session: { ...session,
      ...(kind === 'anonymous' ? { user: { ...session.user, is_anonymous: true } } : { access_token: '' }) } }, error: null };
    method.mockResolvedValue(result); await expect(read({ throwOnError: true })).resolves.toBeNull();
  });
  it.each(['returned', 'rejected'] as const)('keeps default %s failures nullable for existing callers', async kind => {
    if (kind === 'returned') method.mockResolvedValue({ data: { session: null }, error: new Error('SDK failure') });
    else method.mockRejectedValue(new Error('SDK failure'));
    await expect(read()).resolves.toBeNull();
  });
});

describe('auth state compatibility', () => {
  it('returns the formal account state in strict mode', async () => {
    sdk.session.mockResolvedValue(available);
    await expect(getAuthState({ throwOnError: true })).resolves.toEqual({ session, user: session.user, isAnonymous: false, email: session.user.email });
  });
  it('keeps a confirmed absent session as signed out in strict mode', async () => {
    sdk.session.mockResolvedValue(absent);
    await expect(getAuthState({ throwOnError: true })).resolves.toEqual({ session: null, user: null, isAnonymous: false, email: null });
  });
  it('preserves default SDK-returned-error behavior for existing callers', async () => {
    sdk.session.mockResolvedValue({ data: { session: null }, error: new Error('SDK failure') });
    await expect(getAuthState()).resolves.toEqual({ session: null, user: null, isAnonymous: false, email: null });
  });
  it('preserves default rejected-read behavior for existing callers', async () => {
    const original = new Error('SDK failure'); sdk.session.mockRejectedValue(original);
    await expect(getAuthState()).rejects.toBe(original);
  });
});


describe('unconfigured strict reads', () => {
  it('surfaces unavailable configuration without changing default token behavior', async () => {
    vi.stubEnv('NEXT_PUBLIC_SUPABASE_URL', ''); vi.stubEnv('NEXT_PUBLIC_SUPABASE_ANON_KEY', '');
    vi.resetModules(); const local = await import('./supabase');
    await expect(local.getAuthState({ throwOnError: true })).rejects.toThrow('Sign-in is unavailable.');
    await expect(local.getRevealAccessToken({ throwOnError: true })).rejects.toThrow('Sign-in is unavailable.');
    await expect(local.refreshRevealAccessToken({ throwOnError: true })).rejects.toThrow('Sign-in is unavailable.');
    await expect(local.getRevealAccessToken()).resolves.toBeNull();
    await expect(local.refreshRevealAccessToken()).resolves.toBeNull();
    expect(sdk.session).not.toHaveBeenCalled(); expect(sdk.refresh).not.toHaveBeenCalled();
    vi.stubGlobal('window', undefined);
    await expect(local.getAuthState({ throwOnError: true })).resolves.toEqual({ session: null, user: null, isAnonymous: false, email: null });
  });
});
