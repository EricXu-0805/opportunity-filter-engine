import {
  createClient,
  type Session,
  type SupabaseClient,
  type User,
} from '@supabase/supabase-js';

import { syncLocalIdentityOwner } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? '';
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? '';

// In production these MUST be set via Vercel env vars. We don't ship
// hardcoded fallbacks because (a) anyone cloning the repo would otherwise
// silently write to production, and (b) anon keys can be hammered with
// signInAnonymously() to flood the auth.users table.
//
// If the env vars are missing we still need a callable client so the rest
// of the app's optional-chained Supabase usage doesn't crash at import
// time — every method call is then a no-op that surfaces as 'local-only'
// storage status, which the StorageStatusBanner picks up.
const SUPABASE_CONFIGURED = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);

if (!SUPABASE_CONFIGURED && typeof window !== 'undefined') {
  console.warn(
    '[ofe] NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY are not set; ' +
    'profile/favorites/interactions will only persist in localStorage.',
  );
}

export const supabase: SupabaseClient = createClient(
  SUPABASE_URL || 'http://localhost:54321',
  SUPABASE_ANON_KEY || 'public-anon-key-not-set',
  {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      storageKey: 'ofe_auth',
      // R65 P1 Flow A: flip on so the /auth/callback page can complete
      // the PKCE OTP exchange via exchangeCodeForSession(). The callback
      // page is the *only* place a magic-link URL is ever loaded — every
      // other page boots with no ?code= in the URL, so this flag is a
      // no-op there and won't trample the existing anon-session flow.
      detectSessionInUrl: true,
      // Explicit PKCE — supabase-js v2 default, but we lock it so a
      // future dependency bump can't silently swap us to implicit and
      // break the callback handler.
      flowType: 'pkce',
    },
  },
);

const FAV_FALLBACK_KEY = STORAGE_KEYS.FAVORITES_FALLBACK;

export type StorageStatus = 'synced' | 'local-only' | 'unknown';

let lastStorageStatus: StorageStatus = 'unknown';
let lastStorageError: string | null = null;
const storageListeners = new Set<() => void>();

function setStorageStatus(next: StorageStatus, error?: string | null) {
  if (lastStorageStatus === next && lastStorageError === (error ?? null)) return;
  lastStorageStatus = next;
  lastStorageError = error ?? null;
  storageListeners.forEach(fn => { try { fn(); } catch { /* ignore */ } });
}

export function getStorageStatus(): { status: StorageStatus; error: string | null } {
  return { status: lastStorageStatus, error: lastStorageError };
}

export function onStorageStatusChange(cb: () => void): () => void {
  storageListeners.add(cb);
  return () => { storageListeners.delete(cb); };
}

function readFavFallback(): Set<string> {
  if (typeof window === 'undefined') return new Set();
  try {
    const raw = localStorage.getItem(FAV_FALLBACK_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? new Set(arr as string[]) : new Set();
  } catch { return new Set(); }
}

function writeFavFallback(set: Set<string>): void {
  if (typeof window === 'undefined') return;
  try { localStorage.setItem(FAV_FALLBACK_KEY, JSON.stringify(Array.from(set))); } catch { /* quota */ }
}

let anonSignInPromise: Promise<string | null> | null = null;

async function ensureAnonSession(): Promise<string | null> {
  if (typeof window === 'undefined') return null;
  if (!SUPABASE_CONFIGURED) {
    // The dummy client points at localhost:54321 — signInAnonymously would
    // fire a doomed network call (and its late console.warn crashes vitest
    // worker teardown in CI). Unconfigured means local-only, full stop.
    setStorageStatus('local-only', 'Supabase is not configured');
    return null;
  }
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.user?.id) {
    syncLocalIdentityOwner(session.user.id);
    setStorageStatus('synced');
    return session.user.id;
  }
  if (anonSignInPromise) return anonSignInPromise;
  anonSignInPromise = (async () => {
    const { data, error } = await supabase.auth.signInAnonymously();
    if (error) {
      const hint = error.message?.toLowerCase().includes('anonymous')
        ? 'Anonymous sign-ins are disabled for this Supabase project.'
        : error.message;
      console.warn('[ofe] anonymous sign-in failed:', error.message);
      setStorageStatus('local-only', hint || error.message);
      anonSignInPromise = null;
      return null;
    }
    syncLocalIdentityOwner(data.user?.id ?? null);
    setStorageStatus('synced');
    return data.user?.id ?? null;
  })();
  const result = await anonSignInPromise;
  anonSignInPromise = null;
  return result;
}

export async function getDeviceId(): Promise<string | null> {
  return ensureAnonSession();
}

/**
 * Read counts of the user's persisted data (favorites + interactions
 * + profile presence). Used by the post-sign-in callback page to render
 * a real "we kept your N favorites, profile, and M applications"
 * inventory — turning the success screen from a flash redirect into a
 * moment of recognition.
 *
 * Returns zeros (never errors) if RLS or network fails. UX is the
 * primary consumer; a wrong count is OK, a thrown error is not.
 */
export interface DataInventory {
  favorites: number;
  interactions: number;
  hasProfile: boolean;
  savedSearches: number;
}

export async function getDataInventory(): Promise<DataInventory> {
  const empty: DataInventory = {
    favorites: 0,
    interactions: 0,
    hasProfile: false,
    savedSearches: 0,
  };
  if (typeof window === 'undefined') return empty;
  const deviceId = await ensureAnonSession();
  if (!deviceId) return empty;

  // count: 'exact', head: true → no rows transferred, just the count
  const [fav, ints, prof, ss] = await Promise.all([
    supabase
      .from('favorites')
      .select('*', { count: 'exact', head: true })
      .eq('device_id', deviceId),
    supabase
      .from('interactions')
      .select('*', { count: 'exact', head: true })
      .eq('device_id', deviceId),
    supabase
      .from('profiles')
      .select('id', { count: 'exact', head: true })
      .eq('id', deviceId),
    supabase
      .from('saved_searches')
      .select('id', { count: 'exact', head: true })
      .eq('device_id', deviceId),
  ]);

  return {
    favorites: fav.count ?? 0,
    interactions: ints.count ?? 0,
    hasProfile: (prof.count ?? 0) > 0,
    savedSearches: ss.count ?? 0,
  };
}

// =====================================================================
// R65 P1 Flow A: magic-link auth (anon → permanent, in-place)
// =====================================================================
//
// Design:
//   - All RLS policies key off `device_id = auth.uid()::text`. Because
//     `updateUser({ email })` converts an anonymous user to a permanent
//     user *in place* (same auth.uid()), every existing row stays owned
//     by the same UUID and zero data migration is needed.
//   - Cross-device merge (Flow B) is a separate future PR. It requires
//     a SECURITY DEFINER Postgres function and is the only data-loss
//     surface, so it deserves its own review.
//
// Branching: `signInOrLinkEmail` reads the current session and picks
// the right Supabase API based on whether we're sitting on an anonymous
// session (in-place conversion), no session at all (`signInWithOtp`),
// or already a permanent user (no-op).
//
// All three paths trigger a magic-link email; the user clicks it and
// lands on `/auth/callback` which calls `exchangeCodeForSession`. The
// PKCE code_verifier lives in `ofe_auth` localStorage, which means the
// link MUST be opened in the same browser/profile that initiated the
// request — a known PKCE limitation we surface in the UI copy.

/**
 * Returns true when the session belongs to an anonymous user (created
 * via `signInAnonymously`). Reads from the JWT claim set by Supabase;
 * falls back to the user object field for older SDK shapes.
 */
export function isAnonymousUser(session: Session | null): boolean {
  if (!session?.user) return false;
  const userIsAnon = (session.user as unknown as { is_anonymous?: boolean })
    .is_anonymous;
  if (typeof userIsAnon === 'boolean') return userIsAnon;
  // Older shape: claim only on the JWT; trust the user-level field above
  // when present, otherwise assume non-anon to avoid false positives.
  return false;
}

export interface AuthState {
  session: Session | null;
  user: User | null;
  isAnonymous: boolean;
  email: string | null;
}

/**
 * Snapshot of the current auth state. Used by `<AuthButton />` to
 * render label + click target without re-implementing the same Session
 * → label pipeline in three places.
 */
export async function getAuthState(): Promise<AuthState> {
  if (typeof window === 'undefined') {
    return { session: null, user: null, isAnonymous: false, email: null };
  }
  const { data: { session } } = await supabase.auth.getSession();
  return {
    session,
    user: session?.user ?? null,
    isAnonymous: isAnonymousUser(session),
    email: session?.user?.email ?? null,
  };
}

/**
 * W10b contact reveal: the access token to send the backend, or null when the
 * caller is not a signed-in account. Anonymous sessions hold real tokens but
 * can never unlock the reveal (the backend enforces the same), so sending
 * theirs would only buy a wasted GoTrue round-trip.
 */
export async function getRevealAccessToken(): Promise<string | null> {
  if (typeof window === 'undefined' || !SUPABASE_CONFIGURED) return null;
  try {
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token || isAnonymousUser(session)) return null;
    return session.access_token;
  } catch {
    return null;
  }
}

/**
 * W10b degrade-retry: when the backend answers `sign_in_required` to a token
 * we believed valid, refresh the session once and hand back the new token —
 * or null, in which case the UI shows the sign-in affordance instead of an
 * error. Never throws.
 */
export async function refreshRevealAccessToken(): Promise<string | null> {
  if (typeof window === 'undefined' || !SUPABASE_CONFIGURED) return null;
  try {
    const { data, error } = await supabase.auth.refreshSession();
    if (error) return null;
    const session = data.session;
    if (!session?.access_token || isAnonymousUser(session)) return null;
    return session.access_token;
  } catch {
    return null;
  }
}

/**
 * Subscribe to auth state changes. Returns an unsubscribe function.
 * Wraps `onAuthStateChange` so callers don't have to deal with the
 * Supabase subscription object shape directly.
 */
export function onAuthChange(cb: (state: AuthState) => void): () => void {
  const { data } = supabase.auth.onAuthStateChange((_event, session) => {
    // W6: every uid observed here passes through the owner sync, so an
    // account switch from ANY flow clears the previous identity's local
    // data before subscribers render against the new session.
    syncLocalIdentityOwner(session?.user?.id ?? null);
    cb({
      session,
      user: session?.user ?? null,
      isAnonymous: isAnonymousUser(session),
      email: session?.user?.email ?? null,
    });
  });
  return () => { data.subscription.unsubscribe(); };
}

export type SignInOutcome =
  | { ok: true; mode: 'link-anon' | 'sign-in'; message: string }
  | { ok: false; reason: 'not-configured' | 'invalid-email' | 'rate-limited' | 'email-taken' | 'identity-taken' | 'unknown'; message: string };

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Single entry point for the sign-in UI.
 *
 * Branches on the current session:
 *   - anon session present  → `updateUser({ email })` (in-place conversion,
 *     same auth.uid() preserved → zero data migration)
 *   - no session            → `signInWithOtp({ email })` (creates or signs
 *     into a permanent user)
 *   - permanent user signed in → no-op success (UI shouldn't have shown
 *     the form, but this guards against double-submits)
 *
 * `redirectTo` should be the absolute URL of `/auth/callback` on the
 * current origin; the caller is responsible for computing it because
 * this helper is window-agnostic.
 */
export async function signInOrLinkEmail(
  email: string,
  redirectTo: string,
): Promise<SignInOutcome> {
  if (!SUPABASE_CONFIGURED) {
    return {
      ok: false,
      reason: 'not-configured',
      message: 'Sign-in is unavailable: Supabase is not configured.',
    };
  }
  const cleaned = email.trim().toLowerCase();
  if (!EMAIL_RE.test(cleaned)) {
    return {
      ok: false,
      reason: 'invalid-email',
      message: 'Please enter a valid email address.',
    };
  }

  const { data: { session } } = await supabase.auth.getSession();
  const anon = isAnonymousUser(session);

  if (session?.user && !anon) {
    return {
      ok: true,
      mode: 'sign-in',
      message: 'You are already signed in.',
    };
  }

  if (session?.user && anon) {
    const { error } = await supabase.auth.updateUser(
      { email: cleaned },
      { emailRedirectTo: redirectTo },
    );
    if (error) return mapAuthError(error.message);
    return {
      ok: true,
      mode: 'link-anon',
      message: `Check ${cleaned} for a confirmation link. Your saved data will move with you.`,
    };
  }

  const { error } = await supabase.auth.signInWithOtp({
    email: cleaned,
    options: { emailRedirectTo: redirectTo, shouldCreateUser: true },
  });
  if (error) return mapAuthError(error.message);
  return {
    ok: true,
    mode: 'sign-in',
    message: `Check ${cleaned} for your sign-in link.`,
  };
}

/**
 * R67 problem #2: dedicated "sign in to existing account" path.
 *
 * `signInOrLinkEmail` branches on the current session and tries to LINK
 * an anon account first; if Supabase rejects ("email already registered")
 * the user is stuck with no in-modal recovery action.
 *
 * This helper forces the OTP sign-in path with `shouldCreateUser: false`,
 * so it ALWAYS tries to sign the user into the existing permanent account
 * regardless of the current session state. Used by AuthModal when it sees
 * the `email-taken` outcome from `signInOrLinkEmail` — it surfaces a
 * button that calls this directly.
 *
 * Note: the anon-session's data stays under its own auth.uid() (not
 * destroyed, but not visible to the permanent user until Flow B cross-
 * device merge ships). This is the caveat the email-taken message warns
 * about.
 */
export async function signInExistingEmail(
  email: string,
  redirectTo: string,
): Promise<SignInOutcome> {
  if (!SUPABASE_CONFIGURED) {
    return {
      ok: false,
      reason: 'not-configured',
      message: 'Sign-in is unavailable: Supabase is not configured.',
    };
  }
  const cleaned = email.trim().toLowerCase();
  if (!EMAIL_RE.test(cleaned)) {
    return {
      ok: false,
      reason: 'invalid-email',
      message: 'Please enter a valid email address.',
    };
  }
  // Flow B: capture this anon session's data (bound to the target email)
  // before the redirect so it can be merged into the account on callback.
  await mintMergeGrant(cleaned);

  const { error } = await supabase.auth.signInWithOtp({
    email: cleaned,
    options: { emailRedirectTo: redirectTo, shouldCreateUser: false },
  });
  if (error) return mapAuthError(error.message);
  return {
    ok: true,
    mode: 'sign-in',
    message: `Check ${cleaned} for your sign-in link.`,
  };
}

// =====================================================================
// R65 P1 Flow B: cross-device anonymous-data merge (migrations 017/018).
// =====================================================================
//
// When a device built its OWN data while still anonymous and then signs
// into an EXISTING account (the signInExisting* paths below), that data
// lives under the throwaway anon uid and is invisible under RLS to the
// permanent account. A mint runs on the still-anon session just before
// the sign-in redirect and stashes a single-use, 15-minute grant —
// email-bound on the email path (`mintMergeGrant`), device-secret-bound
// on the OAuth path (`mintSecretMergeGrant`, the email is unknowable
// pre-consent); `redeemPendingMerge` runs once on /auth/callback after
// sign-in and merges the source rows into the now-permanent account
// (SECURITY DEFINER functions do the actual cross-uid move — see
// 017_cross_device_merge.sql + 0181_oauth_merge_secret.sql for the
// takeover-proof model).

export interface MergeSummary {
  merged: boolean;
  favorites: number;
  interactions: number;
  savedSearches: number;
  attachmentsNotMoved: number;
}

function asCount(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : 0;
}

/**
 * Mint a merge grant for the CURRENT (anonymous) session, to be redeemed
 * after signing into an existing account. `targetEmail` binds the grant to
 * the account being signed into (email path; the OAuth path uses
 * `mintSecretMergeGrant` instead).
 *
 * Best-effort and MUST NOT throw: minting is a nice-to-have on top of
 * sign-in, so any failure (RPC error, offline, private-mode storage) is
 * swallowed and the sign-in proceeds without a merge. We mint
 * unconditionally rather than gating on a data inventory — one RPC is
 * cheaper than the four count-queries an inventory read costs, and the
 * redeem side no-ops cheaply when there's nothing (or nothing new) to move.
 */
async function mintMergeGrant(targetEmail: string | null): Promise<void> {
  if (!SUPABASE_CONFIGURED || typeof window === 'undefined') return;
  try {
    const { data, error } = await supabase.rpc('mint_merge_grant', {
      p_target_email: targetEmail,
    });
    if (error || typeof data !== 'string') {
      if (error) console.warn('[ofe] merge mint skipped:', error.message);
      return;
    }
    // minted_at lets identity-owner expire an abandoned stash (W14): a grant
    // older than its deferral window stops suppressing user-scoped clears.
    try {
      localStorage.setItem(
        STORAGE_KEYS.MERGE_GRANT,
        JSON.stringify({ token: data, minted_at: Date.now() }),
      );
    } catch { /* private mode */ }
  } catch (e) {
    console.warn('[ofe] merge mint error:', e);
  }
}

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

async function sha256Hex(input: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return bytesToHex(new Uint8Array(digest));
}

/**
 * OAuth twin of `mintMergeGrant`: the target email is unknowable before
 * provider consent, so the grant is bound to a random secret instead. The
 * secret never leaves this browser except as its SHA-256 hash at mint;
 * redemption always lands back in this browser (the PKCE callback reads the
 * same localStorage), which presents the raw secret as proof of possession.
 * A stolen token is useless without it. Same best-effort/never-throw
 * contract as `mintMergeGrant`.
 */
async function mintSecretMergeGrant(): Promise<void> {
  if (!SUPABASE_CONFIGURED || typeof window === 'undefined') return;
  try {
    const secret = bytesToHex(crypto.getRandomValues(new Uint8Array(32)));
    const { data, error } = await supabase.rpc('mint_merge_grant', {
      p_target_email: null,
      p_secret_hash: await sha256Hex(secret),
    });
    if (error || typeof data !== 'string') {
      if (error) console.warn('[ofe] merge mint skipped:', error.message);
      return;
    }
    try {
      // minted_at: same abandoned-stash expiry contract as mintMergeGrant.
      localStorage.setItem(
        STORAGE_KEYS.MERGE_GRANT,
        JSON.stringify({ token: data, secret, minted_at: Date.now() }),
      );
    } catch { /* private mode */ }
  } catch (e) {
    console.warn('[ofe] merge mint error:', e);
  }
}

/**
 * W14: definitive server verdicts — the grant is dead and can NEVER be
 * redeemed, so keeping the token buys nothing. Enumerated from the RAISE
 * strings in the redeem_merge_grant bodies (supabase/migrations/017 →
 * 0181 → 021 → 023, all four keep the same wording):
 *   'redeem_merge_grant: invalid grant'                  (token unknown/not found)
 *   'redeem_merge_grant: grant already used'
 *   'redeem_merge_grant: grant expired'
 *   'redeem_merge_grant: unbound grant is not redeemable'
 * Deliberately NOT definitive (token kept, retryable):
 *   'redeem_merge_grant: no authenticated session'       (transient client state)
 *   'redeem_merge_grant: grant not bound to this session/account' — the grant
 *     is still alive server-side; a sign-in to the RIGHT account in this
 *     browser (within the server's 15-min TTL) can still redeem it.
 * 'not found' / 'already merged' don't occur in the current redeem bodies
 * ('invalid grant' covers unknown tokens; 'device already merged' is
 * mint-side) but are matched defensively against future rewording.
 */
const DEFINITIVE_GRANT_ERRORS = [
  'invalid grant',
  'already used',
  'expired',
  'unbound grant',
  'not found',
  'already merged',
] as const;

function isDefinitiveGrantError(message: string): boolean {
  const lower = message.toLowerCase();
  return DEFINITIVE_GRANT_ERRORS.some((marker) => lower.includes(marker));
}

function clearMergeGrantSlot(): void {
  try { localStorage.removeItem(STORAGE_KEYS.MERGE_GRANT); } catch { /* private mode */ }
}

/**
 * Redeem a pending merge grant (if any) after sign-in. Safe to call
 * unconditionally: returns null when there's no token.
 *
 * W14 contract: the token is kept until a DEFINITIVE server verdict —
 * RPC success (merged or no-op) or a dead-grant error (see
 * DEFINITIVE_GRANT_ERRORS). A transport failure gets ONE immediate retry;
 * if that also fails (or the RPC returns a non-definitive error) the token
 * stays stashed so the next /auth/callback land can retry instead of
 * permanently orphaning the anonymous data. Double-redeem after a kept
 * token is safe: the grant is single-use server-side, so a replay comes
 * back 'grant already used' — a definitive verdict that clears the slot.
 * Abandoned stashes expire via identity-owner's minted_at check and are
 * dropped on sign-out.
 *
 * The slot holds JSON `{token, minted_at}` (email path), JSON
 * `{token, secret, minted_at}` (OAuth path — the secret proves possession
 * against the hash stored at mint), or a legacy pre-W14 bare token string.
 */
export async function redeemPendingMerge(): Promise<MergeSummary | null> {
  if (!SUPABASE_CONFIGURED || typeof window === 'undefined') return null;
  let stashed: string | null = null;
  try { stashed = localStorage.getItem(STORAGE_KEYS.MERGE_GRANT); } catch { return null; }
  if (!stashed) return null;

  let token = stashed;
  let secret: string | null = null;
  if (stashed.startsWith('{')) {
    let parsed: { token?: unknown; secret?: unknown } | null = null;
    try {
      parsed = JSON.parse(stashed) as { token?: unknown; secret?: unknown };
    } catch { parsed = null; }
    if (
      !parsed
      || typeof parsed.token !== 'string'
      || (parsed.secret !== undefined && typeof parsed.secret !== 'string')
    ) {
      // Garbage can never be redeemed — clearing is safe (client-side
      // definitive verdict).
      clearMergeGrantSlot();
      return null;
    }
    token = parsed.token;
    secret = typeof parsed.secret === 'string' ? parsed.secret : null;
  }

  const args = secret === null ? { p_token: token } : { p_token: token, p_secret: secret };
  let rpcResult;
  try {
    rpcResult = await supabase.rpc('redeem_merge_grant', args);
  } catch (e) {
    // Transport/network failure — not a verdict. Retry once immediately
    // (transient blips are common right after the OAuth/PKCE redirect).
    console.warn('[ofe] merge redeem transport failure, retrying once:', e);
    try {
      rpcResult = await supabase.rpc('redeem_merge_grant', args);
    } catch (e2) {
      // Still no verdict: KEEP the token so the next /auth/callback land
      // can retry — sign-in still succeeded, we just don't show a merge
      // line this time.
      console.warn('[ofe] merge redeem retry failed, keeping token:', e2);
      return null;
    }
  }
  const { data, error } = rpcResult;
  if (error) {
    if (isDefinitiveGrantError(error.message ?? '')) {
      // Expired / already-used / invalid / unbound: the grant is dead —
      // consume the token. Non-fatal: sign-in still succeeded.
      clearMergeGrantSlot();
      console.warn('[ofe] merge redeem skipped (grant dead):', error.message);
    } else {
      // Server/gateway error or transient state — no verdict, keep the
      // token for the next land.
      console.warn('[ofe] merge redeem failed, keeping token:', error.message);
    }
    return null;
  }
  // Success (merged or explicit no-op) is a definitive verdict — consume.
  clearMergeGrantSlot();
  const res = data as { merged?: boolean; summary?: Record<string, unknown> } | null;
  if (!res?.merged) return { merged: false, favorites: 0, interactions: 0, savedSearches: 0, attachmentsNotMoved: 0 };
  const s = res.summary ?? {};
  return {
    merged: true,
    favorites: asCount(s.favorites),
    interactions: asCount(s.interactions),
    savedSearches: asCount(s.saved_searches),
    attachmentsNotMoved: asCount(s.attachments_not_moved),
  };
}

export type OAuthProvider = 'google' | 'azure';

function oauthOptions(provider: OAuthProvider, redirectTo: string) {
  return {
    redirectTo,
    // Entra ID multi-tenant apps don't assert email by default; the
    // school auto-detect (Phase A2) needs it.
    scopes: provider === 'azure' ? 'email' : undefined,
  };
}

/**
 * Remember which provider initiated a linkIdentity redirect. The
 * identity-already-linked-to-ANOTHER-account conflict
 * (`identity_already_exists`) is detected by GoTrue AFTER the provider
 * consent, so it lands on /auth/callback as error query params — at
 * that point the callback page needs to know the provider to offer
 * "sign in to that account instead" (plain signInWithOAuth).
 */
function stashOAuthLinkProvider(provider: OAuthProvider): void {
  if (typeof window === 'undefined') return;
  try { sessionStorage.setItem(STORAGE_KEYS.OAUTH_LINK_PROVIDER, provider); } catch { /* private mode */ }
}

/** Drop the link-provider stash so it can't outlive its flow. A stash that
 *  survives an abandoned/errored OAuth attempt would defeat the callback's
 *  gate and misroute a LATER non-OAuth email_exists conflict into the
 *  "sign in with Google/Microsoft" recovery screen. Cleared on sign-out and
 *  whenever a link attempt fails before the redirect. */
function clearOAuthLinkProvider(): void {
  if (typeof window === 'undefined') return;
  try { sessionStorage.removeItem(STORAGE_KEYS.OAUTH_LINK_PROVIDER); } catch { /* private mode */ }
}

/**
 * OAuth sign-in (Google / Microsoft Entra via the `azure` provider).
 *
 * Branches on the current session, mirroring signInOrLinkEmail:
 *   - anon session present → `linkIdentity()` — attaches the OAuth
 *     identity to the CURRENT anonymous user. Same auth.uid() before
 *     and after, so every RLS-owned row (profiles / favorites /
 *     interactions / saved_searches / match_feedback) stays owned by
 *     the same UUID — zero data migration, exactly like the magic-link
 *     flow's updateUser conversion. Requires "manual linking" enabled
 *     in the Supabase dashboard (Auth settings) — same config milestone
 *     as enabling the providers themselves.
 *   - no session / already permanent → plain `signInWithOAuth()`
 *     (sign-in to an existing or new permanent account).
 *
 * On success Supabase navigates the browser to the provider's consent
 * page, so the resolved outcome is only ever observed on failure (or
 * in tests). `redirectTo` is the same `/auth/callback` URL the magic-
 * link flow uses — the callback's exchangeCodeForSession path handles
 * both. Dark in production until NEXT_PUBLIC_AUTH_PROVIDERS lists the
 * provider (AuthModal gates the buttons), but the code path is real.
 */
export async function signInWithOAuthProvider(
  provider: OAuthProvider,
  redirectTo: string,
): Promise<SignInOutcome> {
  if (!SUPABASE_CONFIGURED) {
    return {
      ok: false,
      reason: 'not-configured',
      message: 'Sign-in is unavailable: Supabase is not configured.',
    };
  }

  const { data: { session } } = await supabase.auth.getSession();
  if (session?.user && isAnonymousUser(session)) {
    stashOAuthLinkProvider(provider);
    const { error } = await supabase.auth.linkIdentity({
      provider,
      options: oauthOptions(provider, redirectTo),
    });
    // The redirect never happened — drop the stash we just set so it can't
    // leak into a later flow's callback (see clearOAuthLinkProvider).
    if (error) { clearOAuthLinkProvider(); return mapAuthError(error.message, error.code); }
    return { ok: true, mode: 'link-anon', message: 'Redirecting to provider…' };
  }

  const { error } = await supabase.auth.signInWithOAuth({
    provider,
    options: oauthOptions(provider, redirectTo),
  });
  if (error) return mapAuthError(error.message, error.code);
  return { ok: true, mode: 'sign-in', message: 'Redirecting to provider…' };
}

/**
 * OAuth twin of `signInExistingEmail`: forces a PLAIN signInWithOAuth
 * regardless of the current session. Used after an
 * `identity_already_exists` conflict — the Google/Microsoft identity
 * already belongs to ANOTHER account, so linking is impossible and the
 * only way forward is signing into that account. The anon session's
 * data follows via the Flow B merge grant minted below.
 */
export async function signInExistingOAuth(
  provider: OAuthProvider,
  redirectTo: string,
): Promise<SignInOutcome> {
  if (!SUPABASE_CONFIGURED) {
    return {
      ok: false,
      reason: 'not-configured',
      message: 'Sign-in is unavailable: Supabase is not configured.',
    };
  }
  // Flow B: the target email isn't known until after provider consent, so the
  // grant can't be email-bound here. It's bound to a device secret instead —
  // redemption lands back in THIS browser (PKCE callback + localStorage), which
  // alone holds the raw secret, so a leaked token stays unredeemable.
  await mintSecretMergeGrant();

  const { error } = await supabase.auth.signInWithOAuth({
    provider,
    options: oauthOptions(provider, redirectTo),
  });
  if (error) return mapAuthError(error.message, error.code);
  return { ok: true, mode: 'sign-in', message: 'Redirecting to provider…' };
}

function mapAuthError(raw: string, code?: string): SignInOutcome {
  const msg = raw || 'Unknown error';
  const lower = msg.toLowerCase();
  // GoTrue's identity_already_exists: the OAuth identity is already
  // linked to a DIFFERENT user, so linkIdentity can't proceed (message
  // form: "Identity is already linked to another user"). The caller
  // offers signInExistingOAuth as the recovery path.
  if (code === 'identity_already_exists' || lower.includes('already linked')) {
    return {
      ok: false,
      reason: 'identity-taken',
      message: 'This Google/Microsoft account already belongs to another account. Sign in to that account instead — your current guest data stays on this device.',
    };
  }
  // GoTrue's email_address_invalid is a VALIDATION rejection (malformed /
  // disposable / blocked domain), unrelated to account existence. Keep it
  // out of the email-taken branch below — misclassifying it told the user
  // "this email already has an account, sign in instead" and rendered a
  // sign-in CTA that re-submits the same bad address in a dead loop. The
  // 'invalid-email' reason renders as a plain message with no CTA.
  if (
    lower.includes('email_address_invalid') ||
    lower.includes('email address is invalid')
  ) {
    return {
      ok: false,
      reason: 'invalid-email',
      message: 'That email address looks invalid. Please check it and try again.',
    };
  }
  // Supabase returns these strings for an email that's already registered
  // when we try to convert an anon user. We surface a friendlier path:
  // "use the sign-in link instead" (caller can offer to redo signInWithOtp).
  if (
    lower.includes('already registered') ||
    lower.includes('already been registered') ||
    lower.includes('user already registered')
  ) {
    return {
      ok: false,
      reason: 'email-taken',
      message: 'This email already has an account. Sign in instead — your current device data stays on this device for now.',
    };
  }
  if (lower.includes('rate') || lower.includes('too many')) {
    return {
      ok: false,
      reason: 'rate-limited',
      message: 'Too many attempts. Please wait a minute and try again.',
    };
  }
  return { ok: false, reason: 'unknown', message: msg };
}

/**
 * Sign out and immediately re-establish an anonymous session so the
 * rest of the app keeps working (saveProfile / favorites / etc. all
 * assume `ensureAnonSession` will succeed). Without the re-anon, the
 * user would be on a "no session" state until they reload.
 *
 * Returns the new device id (anon uid) or null on failure.
 */
export async function signOutOfAccount(): Promise<string | null> {
  // scope:'local' — signing out THIS device must not revoke the account's
  // sessions on every other device (the default 'global' does).
  const { error } = await supabase.auth.signOut({ scope: 'local' });
  if (error) console.warn('[ofe] signOut failed:', error.message);
  clearOAuthLinkProvider(); // don't let a stale link-provider stash cross sessions
  // W14: signing out abandons any pending Flow B merge — drop the stashed
  // grant BEFORE the re-anon so it can't defer identity-owner's clear below
  // (the server-side grant dies on its own 15-min TTL regardless).
  clearMergeGrantSlot();
  // W6: no bespoke clear here — the re-anon below lands in ensureAnonSession's
  // owner sync, where the fresh anon uid differs from the marker and the
  // signed-out account's local data is cleared.
  return ensureAnonSession();
}

export async function saveProfile(profileData: Record<string, unknown>): Promise<void> {
  const id = await ensureAnonSession();
  if (!id) return;

  const now = new Date().toISOString();

  const { error } = await supabase
    .from('profiles')
    .upsert(
      { id, profile_data: profileData, updated_at: now },
      { onConflict: 'id' },
    );

  if (error) console.warn('Failed to sync profile:', error.message);

  supabase
    .from('profile_versions')
    .insert({ device_id: id, profile_data: profileData, created_at: now })
    .then(({ error: vErr }) => {
      if (vErr && !vErr.message.includes('does not exist')) {
        console.warn('Failed to save profile version:', vErr.message);
      }
    });
}

function readLocalProfile(): Record<string, unknown> | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.PROFILE);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch { return null; }
}

// R69-D: in-flight promise dedup. Pre-R69-D, mount + onAuthChange
// (see app/home/use-profile-form.ts:100,151) both called loadProfile
// shortly after each other on page entry, producing 3-4 concurrent
// SELECT profiles?id=eq.<uid> requests per visit. Two were "wasted"
// (same result, same uid). Cache the in-flight promise so concurrent
// callers within the same event-loop burst share one request; clear
// it the next macrotask so a real later call still re-fetches fresh
// data (no long-lived stale cache).
let inflightLoadProfile: Promise<Record<string, unknown> | null> | null = null;

export async function loadProfile(): Promise<Record<string, unknown> | null> {
  if (inflightLoadProfile) return inflightLoadProfile;
  inflightLoadProfile = (async (): Promise<Record<string, unknown> | null> => {
    const local = readLocalProfile();
    const id = await ensureAnonSession();
    if (!id) return local;

    // R69-D: maybeSingle (not single). single() returns HTTP 406 when
    // the profile row doesn't exist yet — every cold visit produced
    // a console error even though the empty-row case is expected.
    // maybeSingle() returns { data: null, error: null } for missing
    // rows and the existing `if (error || !data)` fallback handles
    // both paths identically.
    const { data, error } = await supabase
      .from('profiles')
      .select('profile_data')
      .eq('id', id)
      .maybeSingle();

    if (error || !data) return local;
    return (data.profile_data as Record<string, unknown>) ?? local;
  })();
  try {
    return await inflightLoadProfile;
  } finally {
    // Clear after the current burst settles so a future explicit
    // re-fetch (e.g. after auth.uid() changes on this tab) goes to
    // the network again instead of getting a stale result.
    setTimeout(() => { inflightLoadProfile = null; }, 0);
  }
}

export async function getFavorites(): Promise<Set<string>> {
  const local = readFavFallback();
  const deviceId = await ensureAnonSession();
  if (!deviceId) {
    return local;
  }

  const { data, error } = await supabase
    .from('favorites')
    .select('opportunity_id')
    .eq('device_id', deviceId);

  if (error || !data) {
    console.warn('[ofe] getFavorites failed, using local fallback:', error?.message);
    setStorageStatus('local-only', error?.message ?? null);
    return local;
  }

  const remote = new Set(data.map((r: { opportunity_id: string }) => r.opportunity_id));

  const toPush = Array.from(local).filter(id => !remote.has(id));
  if (toPush.length > 0) {
    const rows = toPush.map(opportunity_id => ({ device_id: deviceId, opportunity_id }));
    const { error: insErr } = await supabase.from('favorites').insert(rows);
    if (!insErr) {
      toPush.forEach(id => remote.add(id));
      writeFavFallback(new Set());
    } else {
      console.warn('[ofe] favorites backfill failed:', insErr.message);
    }
  } else if (local.size > 0) {
    writeFavFallback(new Set());
  }

  writeFavFallback(remote);
  setStorageStatus('synced');
  return remote;
}

export async function toggleFavorite(opportunityId: string, isFaved: boolean): Promise<boolean> {
  const local = readFavFallback();
  if (isFaved) local.delete(opportunityId); else local.add(opportunityId);
  writeFavFallback(local);

  const deviceId = await ensureAnonSession();
  if (!deviceId) {
    return !isFaved;
  }

  if (isFaved) {
    const { error } = await supabase
      .from('favorites')
      .delete()
      .eq('device_id', deviceId)
      .eq('opportunity_id', opportunityId);
    if (error) {
      console.warn('[ofe] favorite delete failed:', error.message);
      setStorageStatus('local-only', error.message);
    } else {
      setStorageStatus('synced');
    }
    return false;
  }

  const { error } = await supabase
    .from('favorites')
    .insert({ device_id: deviceId, opportunity_id: opportunityId });
  // 23505 = unique_violation: the favorite row already exists (double-click,
  // or a retry of a request that actually landed) — an idempotent success,
  // exactly like followProfessor. The cloud row and local mirror already
  // agree, so downgrading to 'local-only' here would be a false signal.
  if (error && error.code !== '23505') {
    console.warn('[ofe] favorite insert failed:', error.message);
    setStorageStatus('local-only', error.message);
  } else {
    setStorageStatus('synced');
  }
  return true;
}

// Concierge paid-intent capture: the user asked us to tailor + send their
// outreach for them ("apply for me"). Writes one row to the waitlist table under
// the same per-user RLS as favorites; `email` is how we reach them (their
// account email, or one they type if anonymous). Returns false on failure so the
// caller can keep the UI honest. See supabase/migrations/015_analytics_waitlist.sql.
export async function joinWaitlist(
  email: string | null,
  props: Record<string, unknown> = {},
): Promise<boolean> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return false;

  const { error } = await supabase.from('waitlist').insert({
    device_id: deviceId,
    email: email || null,
    intent: 'apply_for_me',
    props,
  });
  if (error) {
    console.warn('[ofe] waitlist insert failed:', error.message);
    return false;
  }
  return true;
}

export type FeedbackCategory = 'bug' | 'idea' | 'data_issue' | 'account' | 'other';

export interface FeedbackSubmission {
  message: string;
  /** Optional — only if the submitter wants a reply. */
  email?: string | null;
  /** Optional — null means the submitter didn't classify it (never guess). */
  category?: FeedbackCategory | null;
  subject?: string | null;
  /**
   * Per-composed-message idempotency token, reused verbatim across retries of
   * the SAME message and regenerated only after a confirmed send. Without it
   * an ambiguous failure (row committed, response lost) makes a retry open a
   * second ticket. Omit it and the partial unique index simply doesn't apply.
   */
  clientToken?: string | null;
  props?: Record<string, unknown>;
}

/**
 * Outcome of one submit attempt.
 *
 * `duplicate` is a SUCCESS: the unique violation on (device_id, client_token)
 * proves the ticket from an earlier attempt exists, so reporting a failure
 * would push the user into a third attempt over a ticket we already hold.
 * Its `id` is null only when the follow-up read of the existing row fails
 * (the ticket still exists; we just can't quote its reference).
 */
export type FeedbackResult =
  | { ok: true; reason: 'created'; id: string }
  | { ok: true; reason: 'duplicate'; id: string | null }
  | { ok: false; reason: 'no-session' | 'error' };

/**
 * In-app feedback: a free-text comment / bug report / suggestion the user
 * sends via the feedback widget, stored under the same per-user RLS as
 * favorites.
 *
 * W15 (migration 026) turned these rows into TICKETS: they carry a category,
 * a subject, a handling status, and a client-minted idempotency token, and
 * the submitter may now read their own rows back (`feedback_select_own`).
 * That read policy is what makes `.select('id').single()` here return the
 * ticket UUID, which the widget shows the user as their reference — a claim
 * we can only make because the insert was confirmed.
 *
 * Retry semantics: on 23505 (the `feedback_client_token_uniq` partial index)
 * the ticket ALREADY EXISTS from a previous attempt whose response was lost.
 * We re-select it and return its id with reason 'duplicate' — success, not
 * failure. Mirrors the toggleFavorite / followProfessor 23505 contract.
 *
 * Residual: against a database where 026 has NOT been applied there is no
 * SELECT policy, so a committed insert's RETURNING clause comes back empty
 * (PGRST116) and is reported as 'error'. The retry then collides on the
 * token and resolves to 'duplicate', so the user converges on the truth
 * after one more tap rather than filing a second ticket.
 *
 * Never throws; the widget branches on the discriminated result.
 * See supabase/migrations/016_feedback.sql + 026_feedback_tickets.sql.
 */
export async function submitFeedback(input: FeedbackSubmission): Promise<FeedbackResult> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return { ok: false, reason: 'no-session' };

  const clientToken = input.clientToken || null;
  const { data, error } = await supabase
    .from('feedback')
    .insert({
      device_id: deviceId,
      message: input.message,
      email: input.email || null,
      category: input.category || null,
      subject: input.subject || null,
      client_token: clientToken,
      props: input.props ?? {},
    })
    .select('id')
    .single();

  if (!error && data?.id) return { ok: true, reason: 'created', id: data.id as string };

  if (error?.code === '23505' && clientToken) {
    const { data: existing, error: readError } = await supabase
      .from('feedback')
      .select('id')
      .eq('device_id', deviceId)
      .eq('client_token', clientToken)
      .maybeSingle();
    if (readError) {
      console.warn('[ofe] feedback duplicate re-read failed:', readError.message);
    }
    // Either way the ticket exists — only the reference may be missing.
    return { ok: true, reason: 'duplicate', id: (existing?.id as string) ?? null };
  }

  console.warn('[ofe] feedback insert failed:', error?.message ?? 'no row returned');
  return { ok: false, reason: 'error' };
}

// Concierge manual-payment orders (migration 019). The client may only
// INSERT its own pending order and SELECT its own rows — every status
// transition happens server-side (mark-paid-claimed + admin confirm).
export interface OrderRow {
  id: string;
  package: string;
  amount_cents: number;
  currency: string;
  status: 'pending' | 'awaiting_confirm' | 'paid' | 'cancelled' | 'refunded';
  channel: string;
  created_at: string;
  paid_at: string | null;
}

export async function createOrder(
  pkg: { id: string; amountCents: number; currency: string },
): Promise<OrderRow | null> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return null;

  const { data, error } = await supabase
    .from('orders')
    .insert({
      device_id: deviceId,
      package: pkg.id,
      amount_cents: pkg.amountCents,
      currency: pkg.currency,
      channel: 'manual',
    })
    .select()
    .single();
  if (error || !data) {
    console.warn('[ofe] order insert failed:', error?.message);
    return null;
  }
  return data as OrderRow;
}

export async function getMyOrders(): Promise<OrderRow[]> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return [];

  const { data, error } = await supabase
    .from('orders')
    .select('id,package,amount_cents,currency,status,channel,created_at,paid_at')
    .order('created_at', { ascending: false });
  if (error || !data) return [];
  return data as OrderRow[];
}

export async function claimOrderPaid(orderId: string): Promise<boolean> {
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;
  if (!token) return false;

  const apiBase = process.env.NEXT_PUBLIC_API_URL || '/api';
  try {
    const res = await fetch(`${apiBase}/orders/${orderId}/mark-paid-claimed`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    return res.ok;
  } catch {
    return false;
  }
}

export type InteractionType = 'contacted' | 'applied' | 'replied' | 'rejected' | 'interviewing' | 'dismissed';

export interface InteractionRecord {
  type: InteractionType;
  notes?: string;
  remind_at?: string;
  last_contacted_at?: string;
  updated_at?: string;
}

/**
 * Upsert the user's status for an opportunity.
 *
 * W14 truthful-write contract: the upsert result is checked and failure
 * THROWS — a resolved promise means the status row is actually persisted.
 * Callers own the failure UX (revert the optimistic status on catch instead
 * of flashing a false "Saved"). Throws 'session-unavailable' when no session
 * could be established (the write never happened).
 */
export async function trackInteraction(
  opportunityId: string,
  type: InteractionType,
): Promise<void> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) {
    // Designed local-only mode (unconfigured Supabase): the status lives in
    // client state for this session and the storage banner discloses that
    // nothing syncs — a no-op resolve keeps the UI functional, matching the
    // documented degraded-mode contract. A CONFIGURED environment with no
    // session is a real failure: throw so callers revert optimistic state.
    if (!SUPABASE_CONFIGURED) return;
    throw new Error('session-unavailable');
  }

  const { error } = await supabase.from('interactions').upsert(
    {
      device_id: deviceId,
      opportunity_id: opportunityId,
      interaction_type: type,
      updated_at: new Date().toISOString(),
    },
    { onConflict: 'device_id,opportunity_id' },
  );
  if (error) {
    console.warn('[ofe] trackInteraction failed:', error.message);
    throw new Error(`interaction-save-failed: ${error.message}`);
  }
}

/**
 * Patch notes/reminder/contact-date on an existing interaction row.
 *
 * W14 truthful-write contract: returns true ONLY when the UPDATE succeeded
 * without error; false when the session is unavailable or the write failed.
 * Callers own the failure UX — show a failed-save state / revert optimistic
 * edits on false instead of pretending the save landed.
 */
export async function updateInteractionDetails(
  opportunityId: string,
  patch: { notes?: string | null; remind_at?: string | null; last_contacted_at?: string | null },
): Promise<boolean> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) {
    // Local-only mode (unconfigured): the edit "landed" as far as this mode
    // can land anything — the banner discloses non-sync, so the panel's
    // Saved indicator is not a sync claim here. Configured-but-no-session
    // stays a failed save.
    return !SUPABASE_CONFIGURED ? true : false;
  }

  const { error } = await supabase
    .from('interactions')
    .update({ ...patch, updated_at: new Date().toISOString() })
    .eq('device_id', deviceId)
    .eq('opportunity_id', opportunityId);

  if (error) {
    console.warn('Failed to update interaction details:', error.message);
    return false;
  }
  return true;
}

export async function getInteractions(): Promise<Map<string, InteractionType>> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return new Map();

  const { data, error } = await supabase
    .from('interactions')
    .select('opportunity_id, interaction_type')
    .eq('device_id', deviceId);

  if (error || !data) return new Map();
  return new Map(
    data.map((r: { opportunity_id: string; interaction_type: InteractionType }) => [
      r.opportunity_id,
      r.interaction_type,
    ]),
  );
}

/**
 * Full interaction records (status + notes + reminders) for the current
 * identity.
 *
 * W14 truthful zero-state contract: an empty Map MEANS the user has zero
 * tracked interactions — never a swallowed failure. When no session can be
 * established this throws 'session-unavailable'; when the query fails it
 * flips the storage banner to 'local-only' and throws with the Supabase
 * error message. Callers own the failure UX (dashboard/tracker render error
 * states instead of confident zeros).
 */
export async function getInteractionsFull(): Promise<Map<string, InteractionRecord>> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) {
    // Unconfigured Supabase is the DESIGNED local-only mode (disclosed by
    // the storage banner, which ensureAnonSession just flipped): there are
    // genuinely zero synced interactions, so an empty Map is the truthful
    // answer. Only a CONFIGURED environment failing to produce a session is
    // an error (W14) — that's the false-zero case the throw exists for.
    if (!SUPABASE_CONFIGURED) return new Map();
    throw new Error('session-unavailable');
  }

  const { data, error } = await supabase
    .from('interactions')
    .select('opportunity_id, interaction_type, notes, remind_at, last_contacted_at, updated_at')
    .eq('device_id', deviceId);

  if (error) {
    console.warn('[ofe] getInteractionsFull failed:', error.message);
    setStorageStatus('local-only', error.message);
    throw new Error(`interactions-load-failed: ${error.message}`);
  }
  return new Map(
    (data ?? []).map((r: {
      opportunity_id: string;
      interaction_type: InteractionType;
      notes?: string;
      remind_at?: string;
      last_contacted_at?: string;
      updated_at?: string;
    }) => [
      r.opportunity_id,
      {
        type: r.interaction_type,
        notes: r.notes ?? undefined,
        remind_at: r.remind_at ?? undefined,
        last_contacted_at: r.last_contacted_at ?? undefined,
        updated_at: r.updated_at ?? undefined,
      } as InteractionRecord,
    ]),
  );
}

export async function getInteractionDetail(
  opportunityId: string,
): Promise<InteractionRecord | null> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return null;

  const { data, error } = await supabase
    .from('interactions')
    .select('interaction_type, notes, remind_at, last_contacted_at, updated_at')
    .eq('device_id', deviceId)
    .eq('opportunity_id', opportunityId)
    .maybeSingle();

  if (error || !data) return null;
  return {
    type: data.interaction_type,
    notes: data.notes ?? undefined,
    remind_at: data.remind_at ?? undefined,
    last_contacted_at: data.last_contacted_at ?? undefined,
    updated_at: data.updated_at ?? undefined,
  };
}

export async function removeInteraction(opportunityId: string): Promise<void> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return;
  await supabase.from('interactions').delete().eq('device_id', deviceId).eq('opportunity_id', opportunityId);
}

export interface StatusChange {
  fromStatus: InteractionType | null;
  toStatus: InteractionType;
  changedAt: string;
}

export async function getStatusChanges(opportunityId: string): Promise<StatusChange[]> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return [];

  const { data, error } = await supabase
    .from('interaction_status_changes')
    .select('from_status, to_status, changed_at')
    .eq('device_id', deviceId)
    .eq('opportunity_id', opportunityId)
    .order('changed_at', { ascending: true });

  if (error || !data) {
    if (error && !error.message?.toLowerCase().includes('does not exist')) {
      console.warn('[ofe] getStatusChanges failed:', error.message);
    }
    return [];
  }

  return data.map((r: { from_status: string | null; to_status: string; changed_at: string }) => ({
    fromStatus: (r.from_status ?? null) as InteractionType | null,
    toStatus: r.to_status as InteractionType,
    changedAt: r.changed_at,
  }));
}

export const ATTACHMENTS_BUCKET = 'tracker-attachments';
export const ATTACHMENTS_MAX_BYTES = 5 * 1024 * 1024;
export const ATTACHMENTS_ALLOWED_MIME = new Set([
  'application/pdf',
  'image/png',
  'image/jpeg',
  'image/webp',
  'image/gif',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain',
  'text/markdown',
]);

export interface Attachment {
  name: string;
  sizeBytes: number;
  mimeType: string;
  createdAt: string;
}

function attachmentPath(deviceId: string, opportunityId: string, filename: string): string {
  return `${deviceId}/${opportunityId}/${filename}`;
}

function sanitizeFilename(raw: string): string {
  const base = raw.replace(/[\\/:*?"<>|]/g, '_').replace(/^\.+/, '').trim();
  return base.slice(0, 200) || `file-${Date.now()}`;
}

export type AttachmentUploadResult =
  | { ok: true; name: string }
  | { ok: false; reason: 'too_large' | 'wrong_type' | 'duplicate' | 'unauthenticated' | 'unknown'; message?: string };

export async function uploadAttachment(
  opportunityId: string,
  file: File,
): Promise<AttachmentUploadResult> {
  if (file.size > ATTACHMENTS_MAX_BYTES) return { ok: false, reason: 'too_large' };
  if (!ATTACHMENTS_ALLOWED_MIME.has(file.type)) return { ok: false, reason: 'wrong_type' };

  const deviceId = await ensureAnonSession();
  if (!deviceId) return { ok: false, reason: 'unauthenticated' };

  const safeName = sanitizeFilename(file.name);
  const path = attachmentPath(deviceId, opportunityId, safeName);

  const { error } = await supabase.storage
    .from(ATTACHMENTS_BUCKET)
    .upload(path, file, { contentType: file.type, upsert: false });

  if (error) {
    const msg = error.message || '';
    if (/exists|duplicate/i.test(msg)) return { ok: false, reason: 'duplicate', message: msg };
    return { ok: false, reason: 'unknown', message: msg };
  }
  return { ok: true, name: safeName };
}

export async function listAttachments(opportunityId: string): Promise<Attachment[]> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return [];

  const prefix = `${deviceId}/${opportunityId}`;
  const { data, error } = await supabase.storage
    .from(ATTACHMENTS_BUCKET)
    .list(prefix, { limit: 100, sortBy: { column: 'created_at', order: 'desc' } });

  if (error || !data) {
    if (error) console.warn('[ofe] listAttachments failed:', error.message);
    return [];
  }

  return data
    .filter((item) => item.name && !item.name.endsWith('/'))
    .map((item) => {
      const meta = (item.metadata ?? {}) as { size?: number; mimetype?: string };
      return {
        name: item.name,
        sizeBytes: meta.size ?? 0,
        mimeType: meta.mimetype ?? 'application/octet-stream',
        createdAt: item.created_at ?? item.updated_at ?? new Date().toISOString(),
      };
    });
}

export async function deleteAttachment(opportunityId: string, filename: string): Promise<boolean> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return false;

  const { error } = await supabase.storage
    .from(ATTACHMENTS_BUCKET)
    .remove([attachmentPath(deviceId, opportunityId, filename)]);

  if (error) {
    console.warn('[ofe] deleteAttachment failed:', error.message);
    return false;
  }
  return true;
}

export async function getAttachmentSignedUrl(
  opportunityId: string,
  filename: string,
  expiresInSeconds = 300,
): Promise<string | null> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return null;

  const { data, error } = await supabase.storage
    .from(ATTACHMENTS_BUCKET)
    .createSignedUrl(attachmentPath(deviceId, opportunityId, filename), expiresInSeconds);

  if (error || !data) {
    if (error) console.warn('[ofe] getAttachmentSignedUrl failed:', error.message);
    return null;
  }
  return data.signedUrl;
}

// ── Resume renovation persistence ──────────────────────────────────────
// Mirrors the profiles (mutable upsert) + profile_versions (append-only
// snapshot) split: `resume_renovations` holds ONE working doc per
// (device, opportunity) — the per-bullet rollback history lives INSIDE the
// doc's variant chains — and `resume_renovation_versions` appends a whole-doc
// snapshot on every save as the coarse recovery net. The modal keeps its
// in-memory doc regardless, but the RESULT is reported truthfully (W13):
// the UI may only show "Saved" when the working-doc upsert actually
// succeeded — a swallowed failure flashing "Saved" is a false persistence
// claim. The version snapshot stays fire-and-forget (recovery sugar).
// See supabase/migrations/020_resume_renovations.sql.

export async function saveRenovation(
  opportunityId: string,
  doc: Record<string, unknown>,
  baseSnapshot: Record<string, unknown>,
  method: string,
  warnings: string[],
): Promise<boolean> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return false;
  const now = new Date().toISOString();

  const { error } = await supabase
    .from('resume_renovations')
    .upsert(
      {
        device_id: deviceId,
        opportunity_id: opportunityId,
        doc,
        base_snapshot: baseSnapshot,
        method,
        warnings,
        updated_at: now,
      },
      { onConflict: 'device_id,opportunity_id' },
    );
  if (error) {
    console.warn('[ofe] renovation save failed:', error.message);
    return false;
  }

  supabase
    .from('resume_renovation_versions')
    .insert({ device_id: deviceId, opportunity_id: opportunityId, doc })
    .then(({ error: vErr }) => {
      if (vErr && !vErr.message.includes('does not exist')) {
        console.warn('[ofe] renovation version snapshot failed:', vErr.message);
      }
    });
  return true;
}

export interface StoredRenovation {
  doc: Record<string, unknown>;
  base_snapshot: Record<string, unknown>;
  method: string | null;
  warnings: string[];
  updated_at: string;
}

export async function loadRenovation(
  opportunityId: string,
): Promise<StoredRenovation | null> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return null;
  const { data, error } = await supabase
    .from('resume_renovations')
    .select('doc, base_snapshot, method, warnings, updated_at')
    .eq('device_id', deviceId)
    .eq('opportunity_id', opportunityId)
    .maybeSingle();
  if (error) {
    console.warn('[ofe] renovation load failed:', error.message);
    return null;
  }
  if (!data || !data.doc || typeof data.doc !== 'object') return null;
  return {
    doc: data.doc as Record<string, unknown>,
    base_snapshot: (data.base_snapshot ?? {}) as Record<string, unknown>,
    method: (data.method as string | null) ?? null,
    warnings: Array.isArray(data.warnings) ? (data.warnings as string[]) : [],
    updated_at: String(data.updated_at ?? ''),
  };
}

export interface RenovationVersion {
  id: string;
  doc: Record<string, unknown>;
  created_at: string;
}

export async function listRenovationVersions(
  opportunityId: string,
  limit = 10,
): Promise<RenovationVersion[]> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return [];
  const { data, error } = await supabase
    .from('resume_renovation_versions')
    .select('id, doc, created_at')
    .eq('device_id', deviceId)
    .eq('opportunity_id', opportunityId)
    .order('created_at', { ascending: false })
    .limit(limit);
  if (error) {
    console.warn('[ofe] renovation versions load failed:', error.message);
    return [];
  }
  return (data ?? []).map((r) => ({
    id: String(r.id),
    doc: (r.doc ?? {}) as Record<string, unknown>,
    created_at: String(r.created_at ?? ''),
  }));
}

// ── Professor follows + verified-update read cursors (W8) ─────────────────
// Cloud rows only (migrations 022/023) — follows must survive the device and
// merge across devices, so there is deliberately NO localStorage fallback.
// Follow/unfollow THROW on failure instead of pretending success: the toggle
// renders an explicit retry state, mirroring the repo's truthful-UI rule.

// Record-scoped tracking id minted by the backend (src/tracking): validated
// here before any network call so a junk id can never reach a table row.
const PROFESSOR_ID_RE = /^prof:v1:[a-z0-9-]{1,48}:[0-9a-f]{20}$/;
const PROFESSOR_EVENT_ID_RE = /^prof-event:v1:[0-9a-f]{24}$/;

export function isCanonicalProfessorId(value: unknown): value is string {
  return typeof value === 'string' && PROFESSOR_ID_RE.test(value);
}

function assertProfessorId(professorId: string): void {
  if (!isCanonicalProfessorId(professorId)) {
    throw new Error('Not a faculty profile tracking id: ' + professorId);
  }
}

export interface ProfessorFollow {
  professorId: string;
  professorName: string | null;
  school: string | null;
  createdAt: string;
}

const FOLLOW_PAGE_SIZE = 1000;

/**
 * Every follow for the current identity, paged past PostgREST's 1000-row
 * default cap. Throws on any page failure — a partial read must not
 * masquerade as the complete follow list (or worse, an empty one).
 */
export async function listProfessorFollows(): Promise<ProfessorFollow[]> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return [];

  const follows: ProfessorFollow[] = [];
  for (let offset = 0; ; offset += FOLLOW_PAGE_SIZE) {
    const { data, error } = await supabase
      .from('professor_follows')
      .select('professor_id, professor_name, school, created_at')
      .eq('device_id', deviceId)
      .order('professor_id', { ascending: true })
      .range(offset, offset + FOLLOW_PAGE_SIZE - 1);
    if (error) throw new Error(error.message);
    const rows = data ?? [];
    for (const r of rows) {
      follows.push({
        professorId: String(r.professor_id),
        professorName: r.professor_name == null ? null : String(r.professor_name),
        school: r.school == null ? null : String(r.school),
        createdAt: String(r.created_at ?? ''),
      });
    }
    if (rows.length < FOLLOW_PAGE_SIZE) return follows;
  }
}

export async function followProfessor(
  professorId: string,
  professorName?: string | null,
  school?: string | null,
): Promise<void> {
  assertProfessorId(professorId);
  const deviceId = await ensureAnonSession();
  if (!deviceId) throw new Error('Cloud storage is unavailable');

  const { error } = await supabase.from('professor_follows').insert({
    device_id: deviceId,
    professor_id: professorId,
    professor_name: professorName?.slice(0, 200) || null,
    school: school?.slice(0, 64) || null,
  });
  // 23505 = unique_violation: already following — an idempotent success so
  // a double-tap or retry can never surface as an error.
  if (error && error.code !== '23505') throw new Error(error.message);
}

export async function unfollowProfessor(professorId: string): Promise<void> {
  assertProfessorId(professorId);
  const deviceId = await ensureAnonSession();
  if (!deviceId) throw new Error('Cloud storage is unavailable');

  const { error } = await supabase
    .from('professor_follows')
    .delete()
    .eq('device_id', deviceId)
    .eq('professor_id', professorId);
  if (error) throw new Error(error.message);
}

/**
 * Per-professor read cursors (professor_id -> last read event id). Read
 * failures degrade to an empty map with a warning: the worst outcome is a
 * seen update briefly showing as unread — never lost or fabricated data.
 */
export async function getProfessorUpdateReads(): Promise<Map<string, string>> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return new Map();

  const { data, error } = await supabase
    .from('professor_update_reads')
    .select('professor_id, last_read_event_id')
    .eq('device_id', deviceId);
  if (error || !data) {
    if (error) console.warn('[ofe] professor update reads load failed:', error.message);
    return new Map();
  }
  return new Map(
    data.map((r: { professor_id: string; last_read_event_id: string }) => [
      r.professor_id,
      r.last_read_event_id,
    ]),
  );
}

/**
 * Advance read cursors after the user has seen a professor's updates.
 * Best-effort like the other cursor-ish writes (trackInteraction): failure
 * only means the unread badge reappears, so it warns instead of throwing.
 */
export async function markProfessorUpdatesRead(
  entries: { professorId: string; lastReadEventId: string }[],
): Promise<void> {
  const rows = entries.filter(
    (e) => isCanonicalProfessorId(e.professorId)
      && PROFESSOR_EVENT_ID_RE.test(e.lastReadEventId),
  );
  if (rows.length === 0) return;
  const deviceId = await ensureAnonSession();
  if (!deviceId) return;

  const now = new Date().toISOString();
  const { error } = await supabase.from('professor_update_reads').upsert(
    rows.map((e) => ({
      device_id: deviceId,
      professor_id: e.professorId,
      last_read_event_id: e.lastReadEventId,
      updated_at: now,
    })),
    { onConflict: 'device_id,professor_id' },
  );
  if (error) console.warn('[ofe] professor updates mark-read failed:', error.message);
}
