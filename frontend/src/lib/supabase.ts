import {
  createClient,
  type Session,
  type SupabaseClient,
  type User,
} from '@supabase/supabase-js';

import {
  advanceOwnerEpoch,
  advanceOwnerEpochIfUnchanged,
  bumpAuthObservationRevision,
  captureOwnerToken,
  enqueuePrivateWrite,
  enterLocalOnlyMode,
  getAuthObservationRevision,
  isOwnerTokenValid,
  isTokenOwnerStillCurrent,
  isOwnerScopedLoadError,
  OwnerNotReadyError,
  OwnerScopedLoadError,
  OwnerMismatchError,
  readUserScopedRaw,
  syncLocalIdentityOwner,
  writeUserScopedRaw,
  type OwnerToken,
} from './identity-owner';
import { RELEASE_SCOPE } from './release-scope';
import { STORAGE_KEYS } from './storage-keys';

export { OwnerMismatchError, OwnerNotReadyError } from './identity-owner';
export type { OwnerToken } from './identity-owner';

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

// Token-less, like readUserScopedRaw itself: every call site below already
// re-validated (or is explicitly asking "what does the CURRENT owner's
// fallback show", e.g. after its own token went stale) before reaching
// this — it reflects whichever identity is genuinely ready right now, not
// a specific captured token.
function readFavFallback(): Set<string> {
  if (typeof window === 'undefined') return new Set();
  const raw = readUserScopedRaw(FAV_FALLBACK_KEY);
  if (!raw) return new Set();
  try {
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? new Set(arr as string[]) : new Set();
  } catch { return new Set(); }
}

// `token` MUST be the SAME already-validated token the caller just checked
// via isOwnerTokenValid immediately before calling this — defense in depth
// so a future call site that forgets that check still cannot attribute a
// write to the wrong identity.
function writeFavFallback(set: Set<string>, token: OwnerToken): boolean {
  if (typeof window === 'undefined') return false;
  return writeUserScopedRaw(FAV_FALLBACK_KEY, JSON.stringify(Array.from(set)), token);
}

let anonSignInPromise: Promise<string | null> | null = null;

/**
 * Establishes (or confirms) the confirmed-local-only degrade: a real
 * null-owner window FIRST (advanceOwnerEpoch — a no-op if already null),
 * then the explicit local-only realm (enterLocalOnlyMode, which itself
 * refuses to clear a real prior account's data — see its own doc
 * comment). Status is marked 'local-only' ONLY when the realm is
 * CONFIRMED established, never merely attempted: an unconfirmed realm
 * (a real prior account's marker is sitting here, or storage threw) must
 * surface as 'unknown', not falsely announce local data as safe.
 */
/**
 * `sinceEpoch`, when given, gates the transition on `advanceOwnerEpochIfUnchanged`
 * instead of an unconditional `advanceOwnerEpoch(null)` — required at any call
 * site reached after an await (a late anon-sign-in failure): without it, a
 * live sign-in that completed WHILE this attempt was in flight would be
 * silently rolled back to a null owner by an abandoned attempt's own error
 * handling. Returns false (and touches nothing) when the epoch moved on
 * since `sinceEpoch` was captured — the caller must trust whatever that
 * live event already established instead.
 */
function establishLocalOnlyDegrade(reason: string, sinceEpoch?: number): boolean {
  if (sinceEpoch !== undefined) {
    if (!advanceOwnerEpochIfUnchanged(null, sinceEpoch)) return false;
  } else {
    advanceOwnerEpoch(null);
  }
  const localOnlyOk = enterLocalOnlyMode();
  setStorageStatus(
    localOnlyOk ? 'local-only' : 'unknown',
    localOnlyOk ? reason : 'a prior account\'s local data could not be verified — storage stays blocked until it can be',
  );
  return true;
}

async function ensureAnonSession(): Promise<string | null> {
  if (typeof window === 'undefined') return null;
  if (!SUPABASE_CONFIGURED) {
    // The dummy client points at localhost:54321 — signInAnonymously would
    // fire a doomed network call (and its late console.warn crashes vitest
    // worker teardown in CI). Unconfigured means local-only, full stop.
    establishLocalOnlyDegrade('Supabase is not configured');
    return null;
  }
  // Captured BEFORE either await below. getSession()/signInAnonymously() are
  // not ordered relative to the live onAuthChange event stream — a slow
  // resolution can arrive after that authoritative stream has already
  // advanced past it. advanceOwnerEpochIfUnchanged applies this
  // observation only if nothing did; see identity-owner.ts. sinceRevision
  // is the belt-and-suspenders companion: a same-uid TOKEN_REFRESHED/
  // INITIAL_SESSION live event bumps the revision but NOT the epoch (see
  // advanceOwnerEpoch's own doc comment on same-uid re-observations), and
  // that event may be the FIRST successful sync for this uid (blocked ->
  // ready) — this resolution must not treat "epoch unchanged" as license
  // to re-run its own stale-but-matching-uid sync over it.
  const sinceEpoch = captureOwnerToken().epoch;
  const sinceRevision = getAuthObservationRevision();
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.user?.id) {
    // syncLocalIdentityOwner has no epoch awareness of its own — it must
    // only run when this observation is actually accepted, never for a
    // stale result the guard drops (a late-arriving U1 after a live switch
    // to U2 must not clear/reclaim U2's local storage as U1).
    if (
      getAuthObservationRevision() === sinceRevision
      && advanceOwnerEpochIfUnchanged(session.user.id, sinceEpoch)
    ) {
      // The uid IS current (the epoch CAS above just confirmed it), but
      // sync itself can still fail closed (an unverified clear/marker
      // write) — that means local USER_SCOPED data is NOT yet confirmed
      // usable for this uid, even though the account resolution is real.
      // Marking 'synced' anyway would tell the storage-status banner
      // "your data is safely synced" while isLocalOwnerReady is still
      // 'blocked' underneath it — a truthfulness bug, not a data-safety
      // one (every actual read/write still re-checks readiness itself).
      const synced = await syncLocalIdentityOwner(session.user.id);
      setStorageStatus(
        synced ? 'synced' : 'unknown',
        synced ? null : 'local data ownership could not be verified',
      );
      return session.user.id;
    }
    // B1: dropped as stale — a live event already advanced the shared
    // owner past this observation before we got here. That live event's
    // OWN processing (onAuthChange's wrapper) already ran
    // syncLocalIdentityOwner and set whatever status follows from IT —
    // returning our own stale session.user.id (or re-marking 'synced' for
    // an observation that was just rejected) would let a caller trust an
    // identity that is no longer current. The CURRENT global owner
    // (already established by that live event) is the only trustworthy
    // answer.
    return captureOwnerToken().uid;
  }
  if (anonSignInPromise) return anonSignInPromise;
  anonSignInPromise = (async () => {
    const { data, error } = await supabase.auth.signInAnonymously();
    if (error) {
      const hint = error.message?.toLowerCase().includes('anonymous')
        ? 'Anonymous sign-ins are disabled for this Supabase project.'
        : error.message;
      console.warn('[ofe] anonymous sign-in failed:', error.message);
      // B2: a confirmed anon-sign-in failure is ALSO a confirmed
      // local-only degrade — same realm-establishment discipline as the
      // unconfigured branch above. Gated on sinceEpoch: this runs after
      // TWO awaits, so a live sign-in could have already superseded this
      // attempt entirely.
      anonSignInPromise = null;
      if (
        getAuthObservationRevision() !== sinceRevision
        || !establishLocalOnlyDegrade(hint || error.message, sinceEpoch)
      ) {
        // Stale — a live event already established a more current outcome
        // (e.g. a real sign-in completed while this was in flight). Trust
        // the CURRENT global owner, not this abandoned attempt's null.
        return captureOwnerToken().uid;
      }
      return null;
    }
    if (
      getAuthObservationRevision() === sinceRevision
      && advanceOwnerEpochIfUnchanged(data.user?.id ?? null, sinceEpoch)
    ) {
      const synced = await syncLocalIdentityOwner(data.user?.id ?? null);
      setStorageStatus(
        synced ? 'synced' : 'unknown',
        synced ? null : 'local data ownership could not be verified',
      );
      return data.user?.id ?? null;
    }
    // B1: same stale-drop as above — a live event already superseded
    // this resolution.
    return captureOwnerToken().uid;
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
  // Async because the owner transition now runs inside the same exclusive
  // lock every private mutation takes. The two synchronous fences below —
  // the observation revision and the owner epoch — still land before this
  // function first yields, so a hook that reacts to ANY of this still finds
  // the previous identity's local data already blocked.
  const { data } = supabase.auth.onAuthStateChange(async (_event, session) => {
    // Bumped FIRST, unconditionally, even for a same-uid re-observation —
    // this is THE authoritative choke point every async resolution
    // elsewhere (ensureAnonSession) checks to detect "something landed
    // while I was in flight," and a same-uid TOKEN_REFRESHED/
    // INITIAL_SESSION event carries no epoch bump of its own to signal that.
    bumpAuthObservationRevision();
    // Advance the shared owner epoch next (the authoritative source
    // private-write helpers check), then syncLocalIdentityOwner's
    // clear/claim, then notify subscribers — so any hook reacting to this
    // event (capturing a fresh owner token, reading local storage) always
    // sees post-transition state on both.
    advanceOwnerEpoch(session?.user?.id ?? null);
    // W6: every uid observed here passes through the owner sync, so an
    // account switch from ANY flow clears the previous identity's local
    // data before subscribers render against the new session. A failed
    // (fail-closed) sync must not be papered over as 'synced' — the
    // storage-status banner would tell U2 their data is safe while
    // isLocalOwnerReady is still 'blocked' underneath it.
    const uid = session?.user?.id ?? null;
    if (uid) {
      const synced = await syncLocalIdentityOwner(uid);
      setStorageStatus(
        synced ? 'synced' : 'unknown',
        synced ? null : 'local data ownership could not be verified',
      );
    } else {
      // A null-uid event (sign-out, or the transient window before a
      // replacement session exists) must not leave a PREVIOUS identity's
      // 'synced' status lingering — the banner would keep claiming data is
      // safely synced for an account that just signed out. 'unknown', not
      // 'local-only': that confirmed status requires enterLocalOnlyMode's
      // own explicit realm-establishment (see ensureAnonSession), not
      // merely the fact that no uid is known at this instant.
      setStorageStatus('unknown', null);
    }
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
  | { ok: false; reason: 'not-configured' | 'feature-disabled' | 'invalid-email' | 'rate-limited' | 'email-taken' | 'identity-taken' | 'unknown'; message: string };

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

/**
 * `redeemPendingMerge`'s result. `MergeSummary | null` used to collapse two
 * different situations into the same `null` — "there was nothing to merge"
 * and "there WAS a grant but we could not confirm what happened to it" (a
 * network drop mid-RPC) — and /auth/callback treated both as a green light
 * to show success. `'failed'` is the second case: retryable, and MUST leave
 * the caller unable to silently proceed as if the merge had been resolved.
 */
export type MergeRedemptionOutcome =
  | { kind: 'none' }
  | { kind: 'success'; summary: MergeSummary }
  | { kind: 'failed' };

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
 * unconditionally: returns `{kind:'none'}` when there's no token.
 *
 * W14 contract: the token is kept until a DEFINITIVE server verdict —
 * RPC success (merged or no-op) or a dead-grant error (see
 * DEFINITIVE_GRANT_ERRORS). A transport failure gets ONE immediate retry;
 * if that also fails (or the RPC returns a non-definitive error) the token
 * stays stashed and `{kind:'failed'}` is returned so the next
 * /auth/callback land can retry instead of permanently orphaning the
 * anonymous data. Double-redeem after a kept token is safe: migration 026
 * makes redeeming the SAME token idempotent (replays the stored result),
 * and a genuinely dead grant answers with a definitive error that clears
 * the slot. Abandoned stashes expire via identity-owner's minted_at check
 * and are dropped on sign-out.
 *
 * The slot holds JSON `{token, minted_at}` (email path), JSON
 * `{token, secret, minted_at}` (OAuth path — the secret proves possession
 * against the hash stored at mint), or a legacy pre-W14 bare token string.
 *
 * A throw reading the slot itself (private-mode storage) is reported as
 * `'failed'`, not `'none'` — a genuinely-absent grant and an unreadable one
 * are indistinguishable here, and collapsing them into "nothing to merge"
 * would silently drop a real pending merge with no way for the user to
 * even learn it happened, let alone retry.
 */
export async function redeemPendingMerge(): Promise<MergeRedemptionOutcome> {
  if (!SUPABASE_CONFIGURED || typeof window === 'undefined') return { kind: 'none' };
  let stashed: string | null = null;
  try { stashed = localStorage.getItem(STORAGE_KEYS.MERGE_GRANT); } catch { return { kind: 'failed' }; }
  if (!stashed) return { kind: 'none' };

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
      return { kind: 'none' };
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
      return { kind: 'failed' };
    }
  }
  const { data, error } = rpcResult;
  if (error) {
    if (isDefinitiveGrantError(error.message ?? '')) {
      // Expired / already-used / invalid / unbound: the grant is dead —
      // consume the token. Non-fatal: sign-in still succeeded.
      clearMergeGrantSlot();
      console.warn('[ofe] merge redeem skipped (grant dead):', error.message);
      return { kind: 'none' };
    }
    // Server/gateway error or transient state — no verdict, keep the
    // token for the next land.
    console.warn('[ofe] merge redeem failed, keeping token:', error.message);
    return { kind: 'failed' };
  }
  // Success (merged or explicit no-op) is a definitive verdict — consume.
  clearMergeGrantSlot();
  const res = data as { merged?: boolean; summary?: Record<string, unknown> } | null;
  if (!res?.merged) {
    return {
      kind: 'success',
      summary: { merged: false, favorites: 0, interactions: 0, savedSearches: 0, attachmentsNotMoved: 0 },
    };
  }
  const s = res.summary ?? {};
  return {
    kind: 'success',
    summary: {
      merged: true,
      favorites: asCount(s.favorites),
      interactions: asCount(s.interactions),
      savedSearches: asCount(s.saved_searches),
      attachmentsNotMoved: asCount(s.attachments_not_moved),
    },
  };
}

export type OAuthProvider = 'google' | 'azure';

function oauthProviderReleaseRejection(
  provider: OAuthProvider,
): SignInOutcome | null {
  if (provider !== 'azure' || RELEASE_SCOPE.microsoftSchoolAuth) return null;
  return {
    ok: false,
    reason: 'feature-disabled',
    message: 'Microsoft school sign-in is not available in this release.',
  };
}

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
  const releaseRejection = oauthProviderReleaseRejection(provider);
  if (releaseRejection) return releaseRejection;

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
  const releaseRejection = oauthProviderReleaseRejection(provider);
  if (releaseRejection) return releaseRejection;

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

/**
 * `originToken` MUST be captured (via captureOwnerToken()) at the moment
 * the caller's own save intent began — a debounced autosave timer's
 * creation, a toggle's click handler — never re-captured just before this
 * call. Re-verified before EVERY network round-trip's own await boundary
 * (preflight, post-ensure, pre-version-insert): a stale caller (identity
 * moved on while this was in flight) must never write ANY of these three
 * things under the wrong account. The main upsert's error is thrown, not
 * swallowed — callers need to know a save failed to surface it, matching
 * every other private-write helper in this file.
 */
// Returns whether the profile actually reached the server (the main
// upsert committed) — false for EVERY no-op path (stale/blocked origin
// token, no cloud backend available). A caller must check this: `void`
// made "saved" and "silently rejected because the identity moved on"
// indistinguishable, the exact false-success shape this whole file's
// other private-write helpers were hardened against. The version-insert's
// own outcome does NOT affect this return — it stays best-effort in
// OUTCOME per its own comment below, only its SCHEDULING is no longer
// fire-and-forget.
// One serialization domain for the whole profile row, at the single
// exported entry point rather than at each caller: the home form's
// autosave/unmount-flush/submit AND the results page's cross-school toggle
// all write this same row, so a per-caller queue would still let a slow
// write from one screen commit after a faster one from another and roll the
// row back on every other device. Keyed by (owner uid, owner epoch) via
// enqueuePrivateWrite, so a genuine identity change starts a fresh queue.
//
// Client-side ordering is NOT the durability story, though — it cannot see
// the user's other devices at all. The revision check inside
// commit_profile_patch_cas (migration 027) is what actually makes a save
// safe; this queue only keeps ONE browser's own writes from interleaving.
const PROFILE_ROW_WRITE_ID = 'profile-row';

/** What the caller believes it is editing, captured when the edit intent
 *  began. Every field is part of the CAS contract:
 *   - expectedRevision  the revision this edit was made against (0 = create)
 *   - patch             ONLY the keys this intent actually changed. Never the
 *                       whole document: the server shallow-merges it, so a
 *                       key that is not here cannot be cleared by a caller
 *                       holding a stale snapshot.
 *   - token             the owner active at intent time (see OwnerToken)
 *   - mutationId        the client's own id for this attempt, used ONLY by the
 *                       coordinator's outbox to match a late response to the
 *                       pending write it belongs to. Deliberately not sent:
 *                       the server derives idempotency from the revision plus
 *                       the patch itself (see 027's header), so a mutation-id
 *                       table would be a second, weaker source of truth.
 */
export interface ProfilePatchIntent {
  expectedRevision: number;
  patch: Record<string, unknown>;
  token: OwnerToken;
  mutationId: string;
}

export type ProfilePatchOutcome =
  /** The patch was applied; `revision`/`profile` are the new canonical row. */
  | { status: 'saved'; revision: number; profile: Record<string, unknown> }
  /** Already stored — a redundant save, or a retry of a lost response. */
  | { status: 'already-saved'; revision: number; profile: Record<string, unknown> }
  /** Another device got there first. NOTHING was written; `profile` is the
   *  current row so the caller can rebase onto it. */
  | { status: 'conflict'; revision: number; profile: Record<string, unknown> }
  /** No row to patch (deleted), or this account was merged into another.
   *  Fail closed: the caller must reload, never recreate. */
  | { status: 'missing'; reason: 'absent' | 'merged_away' }
  /** No cloud backend at all — the confirmed local-only degrade. */
  | { status: 'local-only' }
  /** The identity moved on before or during the call. Nothing was written
   *  and nothing about it is news to whoever is signed in now. */
  | { status: 'abandoned' }
  /** The request itself failed (network, RLS, permission). Retriable. */
  | { status: 'transport-error'; message: string }
  /** The RPC returned something this client cannot interpret. Treated as a
   *  failure, never as success — an unknown status must not clear a pending
   *  write the way a confirmed one does. */
  | { status: 'malformed'; message: string };

function readCasRow(value: unknown): { revision: number; profile: Record<string, unknown> } | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const revision = row.revision;
  const profile = row.profile;
  // A stored row is revision >= 1 by construction (027's CHECK). Anything
  // else — a float, 0, a string, a missing field — means this response cannot
  // be used as the base for the next save, so it is not accepted as one.
  if (typeof revision !== 'number' || !Number.isInteger(revision) || revision < 1) return null;
  // An array or a JSON null is not a profile. Accepting either would hand the
  // coordinator something it would then merge patches into.
  if (!profile || typeof profile !== 'object' || Array.isArray(profile)) return null;
  return { revision, profile: profile as Record<string, unknown> };
}

/**
 * The ONE way this app writes a profile row. There is no upsert path and no
 * separate history insert: migration 027 does both inside a single
 * transaction, and revokes the direct table privileges that made the old
 * two-statement client possible.
 */
export async function commitProfilePatch(intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> {
  return enqueuePrivateWrite(
    intent.token,
    PROFILE_ROW_WRITE_ID,
    () => commitProfilePatchRow(intent),
  );
}

async function commitProfilePatchRow(intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> {
  const { token, expectedRevision, patch, mutationId } = intent;
  // Preflight — before any network call at all.
  //
  // "Abandoned" means the identity MOVED ON, and only that. A token whose
  // owner is still the current one but is not yet CONFIRMED for local
  // storage is a different situation entirely: nothing has been resolved
  // yet, and it is ensureAnonSession below — not this check — that decides
  // whether there is a cloud backend at all. Rejecting here would report a
  // browser with no backend as somebody else's write.
  if (!isOwnerTokenValid(token, token.uid) && !isTokenOwnerStillCurrent(token)) {
    return { status: 'abandoned' };
  }
  if (!Number.isInteger(expectedRevision) || expectedRevision < 0) {
    return { status: 'malformed', message: 'expectedRevision must be a non-negative integer' };
  }
  if (Object.keys(patch).length === 0) {
    return { status: 'malformed', message: 'refusing to send an empty patch' };
  }

  const id = await ensureAnonSession();
  if (!id) return { status: 'local-only' }; // no cloud backend available
  // Re-verified after ensureAnonSession's own await, BEFORE the request is
  // built: the uid sent as p_expected_device_id has to be the one the edit
  // intent was captured under, not whoever resolved in the meantime.
  if (!isOwnerTokenValid(token, id)) return { status: 'abandoned' };

  const { data, error } = await supabase.rpc('commit_profile_patch_cas', {
    p_expected_device_id: id,
    p_expected_revision: expectedRevision,
    p_patch: patch,
  });

  // Origin BEFORE outcome: if the identity moved on while this was in
  // flight, neither the success nor the failure is the current identity's
  // news — reporting either would let a form now rendering U2 act on U1's
  // result.
  if (!isOwnerTokenValid(token, id)) return { status: 'abandoned' };
  if (error) return { status: 'transport-error', message: error.message };

  const envelope = data as Record<string, unknown> | null;
  const status = envelope && typeof envelope === 'object' ? envelope.status : null;
  if (status === 'applied' || status === 'unchanged') {
    const row = readCasRow(envelope);
    if (!row) return { status: 'malformed', message: `no row in ${String(status)} response` };
    return {
      status: status === 'applied' ? 'saved' : 'already-saved',
      revision: row.revision,
      profile: row.profile,
    };
  }
  if (status === 'conflict') {
    const row = readCasRow(envelope);
    if (!row) return { status: 'malformed', message: 'no row in conflict response' };
    return { status: 'conflict', revision: row.revision, profile: row.profile };
  }
  if (status === 'missing') {
    const reason = (envelope as Record<string, unknown>).reason;
    // A reason this client does not know is NOT "absent". Defaulting it that
    // way would let a future server-side state (a lock, a legal hold, a
    // quarantine) be reported to the user as "your profile does not exist",
    // and the caller acts differently on the two.
    if (reason !== 'absent' && reason !== 'merged_away') {
      return { status: 'malformed', message: `unknown missing reason: ${String(reason)}` };
    }
    return { status: 'missing', reason };
  }
  // Anything else — an older deployed function, a proxy rewriting the body —
  // is unknown, and unknown is a failure. Never treat it as saved.
  return { status: 'malformed', message: `unexpected CAS status: ${String(status)}` };
}


function readLocalProfile(): Record<string, unknown> | null {
  const raw = readUserScopedRaw(STORAGE_KEYS.PROFILE);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch { return null; }
}

// R69-D: in-flight promise dedup, keyed by (uid, epoch) — NOT a single
// global slot. A bare global would dedupe a NEW identity's loadProfile()
// call against an OLD identity's still-in-flight promise (including a
// U1->null->U1 cycle, which is a DIFFERENT epoch despite the same uid —
// see identity-owner.ts's own "full cycle" test for why uid alone can't
// tell these apart). Pre-R69-D, mount + onAuthChange (see
// app/home/use-profile-form.ts) both called loadProfile shortly after
// each other on page entry, producing 3-4 concurrent SELECT requests per
// visit for the SAME identity — this cache still collapses those, since
// they share the same (uid, epoch) key, while never collapsing across a
// genuine identity transition.
/**
 * A read's full result, not just its row. Under CAS a profile without the
 * revision it was read at is unusable — the next save has nothing to compare
 * against — and "the cloud says you have no row" has to stay distinguishable
 * from "there is no cloud", because only one of them may be created into.
 */
export interface LoadedProfile {
  /** 'cloud'        — a stored row came back; `revision` is its revision.
   *  'cloud-absent' — the backend CONFIRMED there is no row (revision 0).
   *  'local-only'   — there is no cloud backend at all; `profile` is this
   *                   browser's mirror, and nothing may be written remotely. */
  source: 'cloud' | 'cloud-absent' | 'local-only';
  profile: Record<string, unknown> | null;
  revision: number;
  /** The token this read finally validated under — the one a follow-up write
   *  derived from this load must be attributed to. */
  token: OwnerToken;
}

const inflightLoadProfile = new Map<string, Promise<LoadedProfile>>();

function loadProfileKey(token: OwnerToken): string {
  return JSON.stringify([token.uid, token.epoch]);
}

/**
 * Whose failure a not-ready owner check is.
 *
 * The same triangle everywhere in loadProfile, so the answer cannot drift
 * between the check before the SELECT and the one after it: a candidate that
 * IS the ensured identity and is still exactly the current owner has simply
 * lost the proof that this browser's data is theirs — their own failure, and
 * reportable, or the screen they are looking at waits forever. Anything else
 * — a uid that does not match, a takeover, a superseded epoch — belongs to
 * nobody and must never hand a screen a capability.
 */
function notReadyFor(candidate: OwnerToken, ensuredId: string | null): Error {
  if (candidate.uid === ensuredId && isTokenOwnerStillCurrent(candidate)) {
    return new OwnerScopedLoadError(candidate, new OwnerNotReadyError());
  }
  return new OwnerNotReadyError();
}

export async function loadProfile(): Promise<LoadedProfile> {
  // Dedup key is the pre-ensure "start-attempt" token: concurrent calls
  // captured at (near-)identical moments — including two concurrent
  // FIRST-ever calls, both uid: null — correctly collapse onto one
  // in-flight promise (R69-D's original mount+onAuthChange double-fire).
  const startAttempt = captureOwnerToken();
  const key = loadProfileKey(startAttempt);
  const existing = inflightLoadProfile.get(key);
  if (existing) return existing;

  const promise = (async (): Promise<LoadedProfile> => {
    const id = await ensureAnonSession();
    let token = startAttempt;
    if (!isOwnerTokenValid(token, id)) {
      if (token.uid !== null) {
        // A KNOWN identity moved on mid-flight, OR this browser's local
        // data is not confirmed for it (a blocked/unverified clear). Both
        // are "we could not read your profile", NOT "you do not have one":
        // returning null here let the caller hydrate defaults and then
        // save them over a row it never read. Never retried here; a fresh
        // loadProfile() call captures the current state.
        //
        // Which of the two it is decides whose failure it is — see above.
        throw notReadyFor(token, id);
      }
      // token.uid === null: nothing had resolved yet at capture time, so
      // this is the browser's first-ever resolution, not an abandonment —
      // the ORIGINAL bug: a pre-ensure null-uid token can never validate
      // against a real first-ever uid, so first-ever loadProfile() always
      // returned null. Mirror getFavorites: re-check against the CURRENT
      // state: only continue if nothing raced further since ensureAnonSession
      // resolved (including a same-uid-but-new-epoch U1->null->U1 cycle,
      // which the epoch comparison inside isOwnerTokenValid still rejects).
      const freshToken = captureOwnerToken();
      if (!isOwnerTokenValid(freshToken, id)) throw notReadyFor(freshToken, id);
      token = freshToken;
    }

    // FROM HERE ON the identity this read belongs to is fixed. Everything
    // below either succeeds for `token` or fails for `token` — and the
    // difference between "this person's read failed" and "this read was
    // abandoned because somebody else took the browser over" is one the
    // caller cannot reconstruct, so it is carried out with the failure.
    try {
      // Only now — ensure+ready confirmed for THIS token — is it safe to
      // read the local fallback (readLocalProfile is itself readiness-gated,
      // this is belt-and-suspenders against a stale caller reaching it at
      // all).
      const local = readLocalProfile();
      // Confirmed local-only degrade: revision 0 and NOT 'cloud-absent' — the
      // caller must not read this as "the server says you have no profile" and
      // create one, because no server was asked.
      if (!id) return { source: 'local-only', profile: local, revision: 0, token };

      // R69-D: maybeSingle (not single). single() returns HTTP 406 when
      // the profile row doesn't exist yet — every cold visit produced
      // a console error even though the empty-row case is expected.
      // maybeSingle() returns { data: null, error: null } for missing rows.
      const result = await supabase
        .from('profiles')
        .select('profile_data, revision')
        .eq('id', id)
        .maybeSingle();

      // Re-verify after the SELECT's own await — same reasoning as above: a
      // read we can no longer attribute is an error, not an empty profile.
      // BEFORE the query's own error is even looked at: a takeover is not
      // this identity's failure to report, whatever the query said.
      //
      if (!isOwnerTokenValid(token, id)) throw notReadyFor(token, id);

      // A real query error (network, RLS misconfiguration) is NOT the same
      // as a confirmed-absent row — collapsing both into "fall back to
      // local" let a transient backend failure masquerade as "you have no
      // cloud profile yet," which downstream first-visit logic could act on
      // incorrectly. Throw (like every other private-write helper in this
      // file) so the caller can tell the difference; maybeSingle's
      // confirmed `data === null` is the ONLY case that legitimately falls
      // back to the local mirror.
      if (result.error) {
        console.warn('[ofe] loadProfile SELECT failed:', result.error.message);
        throw new Error(`Failed to load profile: ${result.error.message}`);
      }
      const data = result.data as { profile_data?: unknown; revision?: unknown } | null;
      // CONFIRMED absent. Deliberately does NOT fall back to the local mirror
      // any more: under CAS the caller has to know the row is absent (so it may
      // create it at revision 0) as opposed to present-but-unread. The mirror
      // is still reconciled — by the coordinator, which can compare it against
      // this answer instead of having it silently substituted here.
      if (!data) return { source: 'cloud-absent', profile: null, revision: 0, token };
      const revision = data.revision;
      if (typeof revision !== 'number' || !Number.isInteger(revision) || revision < 1) {
        // A row without a usable revision cannot be saved over: every write
        // would have to guess what it is overwriting, which is the exact
        // failure CAS exists to remove. Fail closed rather than fall back to a
        // blind write. (Reachable only against a backend that has not applied
        // migration 027.)
        throw new Error('Failed to load profile: stored row has no usable revision');
      }
      const profile = (data.profile_data as Record<string, unknown>) ?? {};
      return { source: 'cloud', profile, revision, token };
    } catch (err) {
      // Ownership is decided FIRST, then the error is interpreted.
      //
      // An already-scoped failure — including everything notReadyFor decided
      // above — is passed through with the token it was raised with.
      // Re-wrapping would replace whoever actually owned it.
      if (isOwnerScopedLoadError(err)) throw err;
      // OWNER-CURRENTNESS decides, not realm validity. A read abandoned
      // because somebody else took the browser over belongs to nobody, and
      // tagging it with this token would hand a superseded screen a
      // capability it must never get. But an owner who is still exactly
      // current and has merely lost the proof that this browser's data is
      // theirs has a failure of their OWN — reported, or the screen they are
      // looking at waits on a spinner forever.
      if (!isTokenOwnerStillCurrent(token)) throw new OwnerNotReadyError();
      throw new OwnerScopedLoadError(token, err);
    }
  })();

  inflightLoadProfile.set(key, promise);
  try {
    return await promise;
  } catch (err) {
    // A FAILED read is dropped from the dedup map immediately, not a
    // macrotask later: a same-uid re-observation (TOKEN_REFRESHED after a
    // grant is redeemed, a readiness recovery) does not advance the epoch,
    // so the retry it triggers hashes to this very key — and would be
    // handed back the rejection it is retrying.
    if (inflightLoadProfile.get(key) === promise) inflightLoadProfile.delete(key);
    throw err;
  } finally {
    // Clear after the current burst settles so a future explicit
    // re-fetch (e.g. after auth.uid() changes on this tab) goes to
    // the network again instead of getting a stale result.
    setTimeout(() => {
      if (inflightLoadProfile.get(key) === promise) inflightLoadProfile.delete(key);
    }, 0);
  }
}

// getFavorites is not a pure read: on success it backfills local-only ids up
// to the remote table and mirrors the merged result back into the local
// fallback. Both are private-write side effects (RLS protects the remote
// table but nothing protects the browser fallback), so this function
// captures its OWN owner token at invocation and re-validates it — using
// isOwnerTokenValid directly, not a throw, since a read degrading to
// "local-only for now" is the honest answer to "I can no longer trust this
// in-flight read for the current identity" — immediately before every
// side-effecting step, exactly like a write helper.
export async function getFavorites(): Promise<Set<string>> {
  let token = captureOwnerToken();
  let local = readFavFallback();
  const deviceId = await ensureAnonSession();
  if (!isOwnerTokenValid(token, deviceId)) {
    if (token.uid !== null) {
      // A previously-KNOWN identity changed mid-flight — a genuine
      // abandonment. Never retried here; stays local-only.
      return readFavFallback();
    }
    // token.uid === null: nothing had been resolved yet at capture time,
    // so this isn't abandoning a known identity — it's the browser's
    // first-ever resolution, which ensureAnonSession above just completed.
    // A null token is never a wildcard for a WRITE, but for a READ there
    // is no cross-account corruption risk in continuing under the
    // freshly-established identity — refusing to would silently omit
    // every server-side favorite on the very first load. Only continue if
    // the shared primitive's CURRENT state still exactly matches what was
    // just resolved (no further race since) — no retry loop beyond this
    // one immediate re-check.
    const freshToken = captureOwnerToken();
    if (!isOwnerTokenValid(freshToken, deviceId)) return readFavFallback();
    token = freshToken;
    local = readFavFallback(); // re-read: identity-owner's sync may have run since the read above
  }
  if (!deviceId) {
    return local;
  }

  const { data, error } = await supabase
    .from('favorites')
    .select('opportunity_id')
    .eq('device_id', deviceId);
  if (!isOwnerTokenValid(token, deviceId)) return readFavFallback();

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
    if (!isOwnerTokenValid(token, deviceId)) return readFavFallback();
    if (!insErr) {
      toPush.forEach(id => remote.add(id));
      writeFavFallback(new Set(), token);
    } else {
      console.warn('[ofe] favorites backfill failed:', insErr.message);
    }
  } else if (local.size > 0) {
    writeFavFallback(new Set(), token);
  }

  writeFavFallback(remote, token);
  setStorageStatus('synced');
  return remote;
}

export async function toggleFavorite(
  opportunityId: string,
  isFaved: boolean,
  token: OwnerToken,
): Promise<boolean> {
  const deviceId = await ensureAnonSession();
  if (!isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();

  if (!deviceId) {
    // Unconfigured Supabase / no session at all — local-only is the only
    // possible storage, and the token is already confirmed valid for it.
    const local = readFavFallback();
    if (isFaved) local.delete(opportunityId); else local.add(opportunityId);
    writeFavFallback(local, token);
    return !isFaved;
  }

  if (isFaved) {
    const { error } = await supabase
      .from('favorites')
      .delete()
      .eq('device_id', deviceId)
      .eq('opportunity_id', opportunityId);
    // Re-validate AFTER the remote round-trip, before resolving EITHER
    // outcome: if identity changed while this request was in flight, the
    // remote write may have genuinely landed for the OLD identity, but a
    // caller now rendering a different account/target must never be told
    // "removed" or "here is your persistence error" (which a caller could
    // act on with a stale-context degrade write) for a result that no
    // longer belongs to it. A caller's own generation guard is
    // defense-in-depth, not the only proof.
    if (!isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();
    if (error) {
      console.warn('[ofe] favorite delete failed:', error.message);
      const local = readFavFallback();
      local.delete(opportunityId);
      writeFavFallback(local, token);
      setStorageStatus('local-only', error.message);
    } else {
      setStorageStatus('synced');
    }
    return false;
  }

  const { error } = await supabase
    .from('favorites')
    .insert({ device_id: deviceId, opportunity_id: opportunityId });
  if (!isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();
  // 23505 = unique_violation: the favorite row already exists (double-click,
  // or a retry of a request that actually landed) — an idempotent success,
  // exactly like followProfessor. The cloud row and local mirror already
  // agree, so downgrading to 'local-only' here would be a false signal.
  if (error && error.code !== '23505') {
    console.warn('[ofe] favorite insert failed:', error.message);
    const local = readFavFallback();
    local.add(opportunityId);
    writeFavFallback(local, token);
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

export type InteractionType = 'contacted' | 'applied' | 'replied' | 'rejected' | 'interviewing' | 'dismissed';

export interface InteractionRecord {
  type: InteractionType;
  notes?: string;
  remind_at?: string;
  last_contacted_at?: string;
  updated_at?: string;
}

// Thrown by every Tracker helper on a resolvable-but-unusable identity
// (Supabase unconfigured, anon sign-in failed): Tracker has no local
// fallback, so unlike favorites this must never degrade to a silent no-op.
class TrackerStorageUnavailableError extends Error {
  constructor() {
    super('interaction persistence is unavailable');
    this.name = 'TrackerStorageUnavailableError';
  }
}

export async function trackInteraction(
  opportunityId: string,
  type: InteractionType,
  token: OwnerToken,
): Promise<void> {
  return enqueuePrivateWrite(token, opportunityId, async () => {
    const deviceId = await ensureAnonSession();
    if (!isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();
    if (!deviceId) throw new TrackerStorageUnavailableError();

    const { error } = await supabase.from('interactions').upsert(
      {
        device_id: deviceId,
        opportunity_id: opportunityId,
        interaction_type: type,
        updated_at: new Date().toISOString(),
      },
      { onConflict: 'device_id,opportunity_id' },
    );
    // Re-validate AFTER the remote round-trip, before treating either
    // outcome as final: if identity changed while this request was in
    // flight, the write may have genuinely landed for the OLD identity,
    // but the current caller (now rendering a different account/target)
    // must never be told "success" or "here is your persistence error" —
    // both would be acted on by a context this result no longer belongs
    // to. A caller's own generation guard is defense-in-depth, not the
    // only proof.
    if (!isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();
    if (error) throw new Error(error.message);
  });
}

/**
 * Atomic Tracker "dismiss": sets interaction_type='dismissed' and
 * (optionally, in the SAME statement) the final notes text, in exactly
 * ONE enqueuePrivateWrite call.
 *
 * This exists because chaining two separately-awaited helpers —
 * updateInteractionDetails(notes) then trackInteraction('dismissed') — has
 * a real race: the second call is not even INVOKED (let alone enqueued)
 * until the first one's promise resolves, leaving a window between them
 * where a DIFFERENT surface acting on the SAME (owner, opportunityId) —
 * e.g. the user hits Back to /results mid-flush and clicks a different
 * status there — can enqueue its own write and land BETWEEN the two,
 * ending up overridden by the stale dismiss's second call once it finally
 * gets its turn. Worse, trackInteraction UPSERTs: if that intervening
 * action was a REMOVE (a real DELETE), the stale dismiss's late upsert
 * would silently resurrect the row.
 *
 * A single atomic call closes both holes: it reserves its ONE queue slot
 * the instant it's invoked (nothing can be interleaved inside it), and it
 * uses UPDATE, not upsert — so if the row is gone by the time this runs
 * (a REMOVE beat it into the queue), it fails closed on the exact-one
 * check below instead of inserting a fresh row.
 *
 * Requires an EXACT one-row, matching-id match (like
 * updateInteractionDetails, unlike removeInteraction's DELETE-is-
 * idempotent stance) — a Tracker row being dismissed is known to already
 * exist; zero rows means something else (a concurrent REMOVE) beat this
 * to the row, and resurrecting it via upsert would be exactly the bug
 * this helper exists to prevent.
 */
export async function dismissInteraction(
  opportunityId: string,
  /** undefined = leave notes untouched; string | null = set it in the
   *  SAME statement as the status change. */
  notes: string | null | undefined,
  token: OwnerToken,
): Promise<void> {
  return enqueuePrivateWrite(token, opportunityId, async () => {
    const deviceId = await ensureAnonSession();
    if (!isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();
    if (!deviceId) throw new TrackerStorageUnavailableError();

    const patch: { interaction_type: InteractionType; updated_at: string; notes?: string | null } = {
      interaction_type: 'dismissed',
      updated_at: new Date().toISOString(),
    };
    if (notes !== undefined) patch.notes = notes;

    const { data, error } = await supabase
      .from('interactions')
      .update(patch)
      .eq('device_id', deviceId)
      .eq('opportunity_id', opportunityId)
      .select('opportunity_id');

    if (!isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();
    if (error) throw new Error(error.message);
    if (!data || data.length !== 1 || data[0].opportunity_id !== opportunityId) {
      throw new Error('dismissInteraction: expected exactly one matching interaction row');
    }
  });
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
  token: OwnerToken,
): Promise<void> {
  return enqueuePrivateWrite(token, opportunityId, async () => {
    const deviceId = await ensureAnonSession();
    if (!isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();
    if (!deviceId) throw new TrackerStorageUnavailableError();

    // .select() turns the UPDATE into a RETURNING query — without it, an
    // UPDATE that matches ZERO rows (the interaction was deleted, or the
    // device_id/opportunity_id pair never existed) succeeds with
    // {error: null}, indistinguishable from a real update. A caller
    // treating that as success would show "Saved" for a write that never
    // touched anything.
    const { data, error } = await supabase
      .from('interactions')
      .update({ ...patch, updated_at: new Date().toISOString() })
      .eq('device_id', deviceId)
      .eq('opportunity_id', opportunityId)
      .select('opportunity_id');

    if (!isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();
    if (error) throw new Error(error.message);
    // Exactly one row, matching the requested id — not merely "at least
    // one". (device_id, opportunity_id) is a unique key, so a correct
    // update can only ever affect one row; anything else (zero, more than
    // one, or a returned id that doesn't match what was asked for) is a
    // contract violation on the anomaly path, never the normal one, and
    // must fail closed rather than be waved through as "some rows came
    // back so it must be fine." Unlike removeInteraction, this is NOT
    // idempotent-safe to treat a mismatch as success: new data with
    // nowhere confirmed to have landed is a real failure.
    if (!data || data.length !== 1 || data[0].opportunity_id !== opportunityId) {
      throw new Error('updateInteractionDetails: expected exactly one matching interaction row');
    }
  });
}

// !deviceId (Supabase unconfigured / anon sign-in permanently failed) is a
// confirmed local-only degrade: there is no device_id a server row could be
// scoped to, so "no interactions" is true, not a guess. A query error is
// the opposite — a row may well exist and we simply failed to read it — so
// it throws rather than silently degrading to the same empty result. A
// caller that swallowed this into "no interactions" would let a mutation
// built on that map (track/remove) blindly overwrite a real status it
// simply failed to see (see use-opportunity-detail.ts's interactionError).
export async function getInteractions(): Promise<Map<string, InteractionType>> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return new Map();

  const { data, error } = await supabase
    .from('interactions')
    .select('opportunity_id, interaction_type')
    .eq('device_id', deviceId);

  if (error) throw new Error(error.message);
  return new Map(
    (data ?? []).map((r: { opportunity_id: string; interaction_type: InteractionType }) => [
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

  if (error) throw new Error(error.message);
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

  if (error) throw new Error(error.message);
  if (!data) return null; // confirmed absence — maybeSingle found no row, not a failure to look
  return {
    type: data.interaction_type,
    notes: data.notes ?? undefined,
    remind_at: data.remind_at ?? undefined,
    last_contacted_at: data.last_contacted_at ?? undefined,
    updated_at: data.updated_at ?? undefined,
  };
}

export async function removeInteraction(opportunityId: string, token: OwnerToken): Promise<void> {
  return enqueuePrivateWrite(token, opportunityId, async () => {
    const deviceId = await ensureAnonSession();
    if (!isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();
    if (!deviceId) throw new TrackerStorageUnavailableError();
    const { error } = await supabase
      .from('interactions')
      .delete()
      .eq('device_id', deviceId)
      .eq('opportunity_id', opportunityId);
    if (!isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();
    if (error) throw new Error(error.message);
    // Deliberately NOT checking for a zero-row match the way
    // updateInteractionDetails does — deletion is idempotent, and a
    // zero-row DELETE (query succeeded, nothing matched) most likely means
    // an EARLIER attempt's request already landed but its response was
    // lost (a network timeout, say) before the caller ever learned it
    // succeeded. The target state — this row absent — is already true
    // either way. Treating it as a failure would strand a Retry on a row
    // that can never reappear, looping forever on a delete that already
    // happened. An UPDATE has no such idempotent reading: a zero-row match
    // there means the caller's new data was silently dropped nowhere, a
    // real failure, not a no-op.
  });
}

// Atomic replacement for the old client read (getInteractionDetail) ->
// conditional upsert (trackInteraction) -> metadata update
// (updateInteractionDetails) Cold Email confirm flow, which was TOCTOU: two
// concurrent confirms (or a confirm racing a manual status change) could
// interleave their reads and writes and silently downgrade an advanced
// status back to 'applied'. See supabase/migrations/027_confirm_interaction_
// contact.sql — one INSERT ... ON CONFLICT DO UPDATE that only ever creates
// the row as 'contacted' (NOT 'applied': a confirmed cold-email send is an
// outreach contact, never an application claim made on the user's behalf) or
// refreshes last_contacted_at (+ an explicitly supplied remind_at); it can
// never touch interaction_type or notes, so an existing further-along status
// and any notes survive byte-for-byte.
//
// That preservation is why callers must read the RETURNED status rather than
// assume 'contacted': a row already marked rejected or dismissed comes back
// unchanged, and the reminders cron selects neither.
export async function confirmInteractionContact(
  opportunityId: string,
  token: OwnerToken,
  remindAt?: string | null,
): Promise<InteractionRecord> {
  return enqueuePrivateWrite(token, opportunityId, async () => {
    const deviceId = await ensureAnonSession();
    if (!isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();
    if (!deviceId) throw new TrackerStorageUnavailableError();

    const { data, error } = await supabase.rpc('confirm_interaction_contact', {
      p_expected_device_id: deviceId,
      p_opportunity_id: opportunityId,
      p_remind_at: remindAt ?? null,
    });
    if (!isOwnerTokenValid(token, deviceId)) throw new OwnerMismatchError();
    if (error) throw new Error(error.message);
    const row = (Array.isArray(data) ? data[0] : data) as {
      interaction_type: InteractionType;
      notes: string | null;
      remind_at: string | null;
      last_contacted_at: string | null;
      updated_at: string | null;
    } | undefined;
    if (!row) throw new Error('confirm_interaction_contact returned no row');
    return {
      type: row.interaction_type,
      notes: row.notes ?? undefined,
      remind_at: row.remind_at ?? undefined,
      last_contacted_at: row.last_contacted_at ?? undefined,
      updated_at: row.updated_at ?? undefined,
    };
  });
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
