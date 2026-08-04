// W6 account isolation: bind browser-local private data to the auth uid.
//
// One marker key records which uid owns the user-scoped localStorage values.
// When a different uid shows up at any auth choke point, the previous
// identity's values are cleared before the new identity can read them
// (shared computer, account switch). The data values themselves stay in
// their existing raw formats — the marker sits BESIDE them, never wraps
// them — so shipping this cannot invalidate any existing user's storage:
// the first sync after deploy finds no marker and claims the values for
// the current uid untouched.
//
// Deliberately small: no generations, nonces, envelopes, or Web Locks.
// Multi-tab races and delayed writes from a session that just ended are
// accepted residual risk — clearing twice and claiming twice are both
// idempotent, and every uid observation re-runs the sync, so a missed
// clear is repaired at the next choke point.

import { STORAGE_KEYS } from './storage-keys';

// Account-private localStorage keys, cleared when a different uid takes
// ownership. Each entry notes why it is user- rather than device-scoped.
export const USER_SCOPED_KEYS: readonly string[] = [
  STORAGE_KEYS.PROFILE, // local mirror of the user's profile (school, interests, background)
  STORAGE_KEYS.MATCH_RESULTS, // cached match set — derived entirely from the profile
  STORAGE_KEYS.SEMANTIC_RERANK, // AI-rerank opt-in — an account-level choice, not a device setting
  STORAGE_KEYS.FILTER_PRESETS, // saved result filters — reflect the account's search intent
  STORAGE_KEYS.CUSTOM_IMPORTS, // user-imported opportunities — localStorage is their ONLY copy
  STORAGE_KEYS.EMAIL_HINT, // remembered email address (PII)
  STORAGE_KEYS.ANCHOR_3FAV_DISMISSED, // "save your favorites" prompt decision — the person's, not the device's
  STORAGE_KEYS.RESULTS_CTA_DISMISSED, // concierge CTA dismissal — same
  STORAGE_KEYS.FAVORITES_FALLBACK, // offline favorites mirror — would backfill into the next uid's account
  STORAGE_KEYS.SCHOOL_CONFIRMED, // W10b school confirmation — an account-level decision; the next uid must confirm their own campus
];

// Per-opportunity keys discovered by localStorage key scan.
export const USER_SCOPED_PREFIXES: readonly string[] = [
  STORAGE_KEYS.TAILOR_DRAFT_PREFIX, // resume-tailor drafts — user-written content
];

// Deliberately NOT cleared (device-scoped, or owned by another flow):
//   LOCALE             — language is a device preference, not private data
//   ONBOARDING_SEEN    — UI education; re-running the tour on every account
//                        switch would punish switching, and it reveals nothing
//   MERGE_GRANT        — owned by the Flow B merge flow; it must survive the
//                        anon → account redirect to be redeemed on callback.
//                        W14: it defers the clear below only while fresh
//                        (see MERGE_GRANT_MAX_AGE_MS); a stale stash is
//                        removed and no longer suppresses clears
//   ofe_auth           — the Supabase session itself; clearing it = sign-out
//   JUST_SIGNED_OUT, GUEST_BANNER_DISMISSED, OAUTH_LINK_PROVIDER,
//   ofe_home_save_cta_dismissed — sessionStorage transients (per-tab, die on
//                        tab close); sign-in/out paths already reset the first
//                        two, and none of them hold private data

/**
 * Single entry point, called wherever a session uid is observed
 * (ensureAnonSession, the onAuthChange wrapper, /auth/callback):
 *   - no marker      → claim: record uid, keep all values (the migration
 *     path for pre-W6 users — first load after deploy must wipe nothing)
 *   - marker === uid → no-op
 *   - marker !== uid → clear the registry, then record uid — unless
 *     `claim` is set, which /auth/callback passes after a successful
 *     Flow B merge redemption: the grant's mint+redeem proved the same
 *     human controlled both sessions, so their local data (notably
 *     custom imports, which have no cloud copy) transfers instead.
 * Storage failures (private mode) degrade to a no-op, never a throw.
 */
export function syncLocalIdentityOwner(
  uid: string | null | undefined,
  opts?: { claim?: boolean },
): void {
  // null uid = transient signed-out state (e.g. mid sign-out, before the
  // replacement anon session exists). Ownership can't be attributed yet;
  // the next uid observation decides.
  if (!uid || typeof window === 'undefined') return;
  let marker: string | null;
  try {
    marker = window.localStorage.getItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER);
  } catch {
    return;
  }
  if (marker === uid) return;
  if (marker !== null && !opts?.claim) {
    // A stashed merge grant means a Flow B "sign in to my existing account"
    // hand-off is in flight: SIGNED_IN fires (and lands here) before
    // /auth/callback can redeem the grant, and clearing now would destroy
    // the guest's local data moments before the redemption proves both
    // sessions belong to the same human. Defer — the callback clears the
    // grant on every definitive redeem verdict (W14) and re-syncs with the
    // real claim/clear decision. Deferral is time-bounded: a grant older
    // than MERGE_GRANT_MAX_AGE_MS is an ABANDONED hand-off (the server-side
    // grant died at 15 minutes), so it is removed and the clear proceeds —
    // a stale stash must not shield the previous identity's data forever.
    try {
      const grant = window.localStorage.getItem(STORAGE_KEYS.MERGE_GRANT);
      if (grant !== null) {
        if (!isMergeGrantStale(grant)) return;
        try {
          window.localStorage.removeItem(STORAGE_KEYS.MERGE_GRANT);
        } catch { /* remove failed — still proceed with the clear */ }
      }
    } catch { /* unreadable — proceed with the clear */ }
    clearUserScopedStorage();
  }
  try {
    window.localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, uid);
  } catch { /* private mode — the next uid observation retries */ }
}

// How long a stashed Flow B merge grant may defer user-scoped clears. The
// server-side grant is single-use with a 15-minute TTL, so 60 minutes is a
// generous 4x envelope for magic-link latency + clock skew; beyond it the
// hand-off is certainly dead and deferring further only leaks the previous
// identity's local data to the next uid.
export const MERGE_GRANT_MAX_AGE_MS = 60 * 60 * 1000;

/**
 * True when the stashed grant is too old to still be redeemable. Shapes
 * (written by supabase.ts mint helpers):
 *   - JSON with numeric `minted_at` (W14+) → age check
 *   - JSON without a usable `minted_at` (pre-W14 {token,secret}) → treated
 *     as fresh; legacy stashes are consumed by the callback or sign-out
 *   - bare token string (pre-W14 email path) → treated as fresh, same reason
 *   - unparseable `{…` garbage → stale; it can never be redeemed, so it
 *     must not defer clears
 */
function isMergeGrantStale(raw: string): boolean {
  if (!raw.startsWith('{')) return false;
  try {
    const parsed = JSON.parse(raw) as { minted_at?: unknown };
    if (typeof parsed.minted_at !== 'number' || !Number.isFinite(parsed.minted_at)) return false;
    return Date.now() - parsed.minted_at > MERGE_GRANT_MAX_AGE_MS;
  } catch {
    return true;
  }
}

function clearUserScopedStorage(): void {
  const keys: string[] = [...USER_SCOPED_KEYS];
  try {
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i);
      if (key && USER_SCOPED_PREFIXES.some((p) => key.startsWith(p))) keys.push(key);
    }
  } catch { /* can't enumerate — the fixed list below still clears */ }
  for (const key of keys) {
    try {
      window.localStorage.removeItem(key);
      // Same-tab useLocalStorageJSON readers only re-read on a storage event
      // (see writeLocalStorageJSON) — notify them so mounted screens drop
      // the cleared values instead of rendering the previous account's data.
      window.dispatchEvent(new StorageEvent('storage', { key }));
    } catch { /* keep clearing the rest */ }
  }
}
