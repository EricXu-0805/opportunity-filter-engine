import {
  createClient,
  type Session,
  type SupabaseClient,
  type User,
} from '@supabase/supabase-js';

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

const FAV_FALLBACK_KEY = 'ofe_favs_fallback';

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
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.user?.id) {
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
 * Subscribe to auth state changes. Returns an unsubscribe function.
 * Wraps `onAuthStateChange` so callers don't have to deal with the
 * Supabase subscription object shape directly.
 */
export function onAuthChange(cb: (state: AuthState) => void): () => void {
  const { data } = supabase.auth.onAuthStateChange((_event, session) => {
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
 * data stays under its own auth.uid() (not destroyed, but not visible
 * to the permanent user until Flow B cross-device merge ships) — the
 * same caveat the email-taken path warns about.
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
  const { error } = await supabase.auth.signOut();
  if (error) console.warn('[ofe] signOut failed:', error.message);
  clearOAuthLinkProvider(); // don't let a stale link-provider stash cross sessions
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
  if (error) {
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

// In-app feedback: a free-text comment / bug report / suggestion the user
// sends via the feedback widget, stored under the same per-user RLS as
// favorites. `email` is optional (only if they want a reply). Insert-only —
// the client cannot read feedback back. Returns false on failure so the
// widget stays honest. See supabase/migrations/016_feedback.sql.
export async function submitFeedback(
  message: string,
  email: string | null,
  props: Record<string, unknown> = {},
): Promise<boolean> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return false;

  const { error } = await supabase.from('feedback').insert({
    device_id: deviceId,
    message,
    email: email || null,
    props,
  });
  if (error) {
    console.warn('[ofe] feedback insert failed:', error.message);
    return false;
  }
  return true;
}

export type InteractionType = 'applied' | 'replied' | 'rejected' | 'interviewing' | 'dismissed';

export interface InteractionRecord {
  type: InteractionType;
  notes?: string;
  remind_at?: string;
  last_contacted_at?: string;
  updated_at?: string;
}

export async function trackInteraction(
  opportunityId: string,
  type: InteractionType,
): Promise<void> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return;

  await supabase.from('interactions').upsert(
    {
      device_id: deviceId,
      opportunity_id: opportunityId,
      interaction_type: type,
      updated_at: new Date().toISOString(),
    },
    { onConflict: 'device_id,opportunity_id' },
  );
}

export async function updateInteractionDetails(
  opportunityId: string,
  patch: { notes?: string | null; remind_at?: string | null; last_contacted_at?: string | null },
): Promise<void> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return;

  const { error } = await supabase
    .from('interactions')
    .update({ ...patch, updated_at: new Date().toISOString() })
    .eq('device_id', deviceId)
    .eq('opportunity_id', opportunityId);

  if (error) console.warn('Failed to update interaction details:', error.message);
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

export async function getInteractionsFull(): Promise<Map<string, InteractionRecord>> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return new Map();

  const { data, error } = await supabase
    .from('interactions')
    .select('opportunity_id, interaction_type, notes, remind_at, last_contacted_at, updated_at')
    .eq('device_id', deviceId);

  if (error || !data) return new Map();
  return new Map(
    data.map((r: {
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
