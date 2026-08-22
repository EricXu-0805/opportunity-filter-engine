// D1 account isolation: bind browser-local private data to (uid, generation).
//
// The unit of ownership is not the uid. It is a GENERATION — a number that
// only ever goes up, allocated when the browser changes hands, and baked into
// the physical name of every private key that generation owns. Two consequences
// follow, and they are the whole design:
//
//   * A write from a tab that has not heard about the switch lands in ITS
//     generation's namespace. The new owner cannot read it, and it cannot
//     delete anything the new owner wrote. It becomes unreachable garbage,
//     which is the worst it is allowed to be.
//   * A uid that comes back (sign out, sign in as someone else, sign back in)
//     comes back as a NEW generation. A token captured before the round trip
//     names a namespace that no longer belongs to anyone, so it never
//     validates again — which a uid comparison alone can never achieve.
//
// Generation 0 is the pre-D1 namespace: unprefixed, exactly the key names
// every already-shipped browser is using. A first load after deploy claims it
// as-is, so nothing anyone has stored is invalidated or moved. The moment the
// browser changes hands, generation 1 and everything after it is namespaced,
// and generation 0 is swept as hygiene rather than as the isolation boundary.
//
// The marker is versioned and carries a phase, so a crash halfway through a
// transition is readable as a crash and fails closed rather than presenting
// a half-built namespace as somebody's confirmed data.

import { STORAGE_KEYS } from './storage-keys';

// Account-private localStorage keys, cleared when a different uid takes
// ownership. Each entry notes why it is user- rather than device-scoped.
export const USER_SCOPED_KEYS: readonly string[] = [
  STORAGE_KEYS.PROFILE, // local mirror of the user's profile (school, interests, background)
  STORAGE_KEYS.PROFILE_SYNC, // that mirror's cloud revision + any unsent edit — same data, and a revision from one account must never be presented as another's
  STORAGE_KEYS.MATCH_RESULTS, // cached match set — derived entirely from the profile
  STORAGE_KEYS.SEMANTIC_RERANK, // AI-rerank opt-in — an account-level choice, not a device setting
  STORAGE_KEYS.FILTER_PRESETS, // saved result filters — reflect the account's search intent
  STORAGE_KEYS.CUSTOM_IMPORTS, // user-imported opportunities — localStorage is their ONLY copy
  // Remembered email address (PII). Nothing writes this any more — the digest
  // dialog resolves the recipient from the session instead of asking — but the
  // entry stays so values written by earlier builds are still scoped to their
  // owner and cleared on an identity switch. Deleting it orphans that PII.
  STORAGE_KEYS.EMAIL_HINT,
  STORAGE_KEYS.ANCHOR_3FAV_DISMISSED, // "save your favorites" prompt decision — the person's, not the device's
  STORAGE_KEYS.RESULTS_CTA_DISMISSED, // concierge CTA dismissal — same
  STORAGE_KEYS.FAVORITES_FALLBACK, // offline favorites mirror — would backfill into the next uid's account
  STORAGE_KEYS.SCHOOL_CONFIRMED, // W10b school confirmation — an account-level decision; the next uid must confirm their own campus
  STORAGE_KEYS.FEEDBACK_DRAFT, // W15 unsent feedback draft — user-written content, often personal; must never be inherited by the next account
];

// Per-opportunity keys discovered by localStorage key scan.
export const USER_SCOPED_PREFIXES: readonly string[] = [
  STORAGE_KEYS.TAILOR_DRAFT_PREFIX, // resume-tailor drafts — user-written content
  // One lane per tab holding that tab's unsent profile edit operations, plus
  // the shared settled/claim lane. Same data as PROFILE/PROFILE_SYNC — an
  // operation staged by one account must never be replayed under another's.
  STORAGE_KEYS.PROFILE_JOURNAL_PREFIX,
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

// =====================================================================
// The marker: who owns this browser, in which generation, and whether that
// generation is finished being built.
// =====================================================================

/** Generation 0 is the pre-D1 namespace — unprefixed, byte-identical to what
 *  every already-shipped browser is storing today. Reserved, never allocated
 *  by a transition. */
const LEGACY_GENERATION = 0;

/** A token whose generation was never established by a proven transition.
 *  Distinct from 0, which is a real (legacy) namespace. Never validates. */
const UNESTABLISHED_GENERATION = -1;

const NAMESPACE_PREFIX = 'ofe_g';
const NAMESPACE_SEPARATOR = '~';

/** Written and read back before a generation is ever published as ready.
 *  Proves the namespace is writable — a browser that accepts setItem and
 *  serves back nothing must not be handed a user's private data. */
const NAMESPACE_SENTINEL = '__ofe_ns';

interface OwnerMarker {
  v: 2;
  uid: string;
  generation: number;
  /** 'switching' = a transition started and has not proven itself. Nothing
   *  may be read or written under it. A crash leaves exactly this. */
  phase: 'switching' | 'ready';
}

/**
 * Why the marker could not be turned into an answer.
 *
 * `unavailable` is not `absent`, and the distinction is the point of this
 * whole type. "There is no marker" means this browser has never been claimed
 * and its unprefixed keys are free. "I could not read the marker" means a real
 * account may own everything here. Folding the second into the first is how a
 * local-only degrade writes into somebody's account.
 */
type MarkerRead =
  | { status: 'present'; marker: OwnerMarker }
  | { status: 'absent' }
  | { status: 'unavailable'; reason: 'storage-error' | 'corrupt' };

function namespaceFor(generation: number): string {
  return generation === LEGACY_GENERATION
    ? ''
    : `${NAMESPACE_PREFIX}${generation}${NAMESPACE_SEPARATOR}`;
}

function physicalKey(logicalKey: string, generation: number): string {
  return `${namespaceFor(generation)}${logicalKey}`;
}

/** A pre-D1 marker was the bare uid string. It names the unprefixed keys that
 *  browser is already using, which is exactly generation 0 — so the migration
 *  is a reinterpretation, not a copy. Nothing moves, nothing can be lost
 *  halfway. */
function parseMarker(raw: string): OwnerMarker | null {
  if (!raw.startsWith('{')) {
    return { v: 2, uid: raw, generation: LEGACY_GENERATION, phase: 'ready' };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object') return null;
  const m = parsed as Partial<OwnerMarker>;
  if (m.v !== 2 || typeof m.uid !== 'string' || !m.uid) return null;
  if (typeof m.generation !== 'number' || !Number.isInteger(m.generation) || m.generation < 0) return null;
  if (m.phase !== 'switching' && m.phase !== 'ready') return null;
  return { v: 2, uid: m.uid, generation: m.generation, phase: m.phase };
}

function readMarker(): MarkerRead {
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER);
  } catch {
    return { status: 'unavailable', reason: 'storage-error' };
  }
  if (raw === null) return { status: 'absent' };
  const marker = parseMarker(raw);
  // A marker this build cannot interpret is NOT an unclaimed browser. Only a
  // transition — which is authorized to quarantine — may act on it.
  return marker ? { status: 'present', marker } : { status: 'unavailable', reason: 'corrupt' };
}

/**
 * This build's transaction backend is Web Locks. IndexedDB is a legitimate
 * alternative authority and is deliberately NOT claimed here: its presence
 * would not make anything serialize, and reporting a backend nothing uses is
 * how a fail-closed rule turns into a fail-open one.
 */
export const PRIVATE_STORAGE_LOCK = 'ofe-profile-local-storage';

type LockManager = {
  request: (name: string, opts: { mode: 'exclusive' }, fn: () => Promise<unknown>) => Promise<unknown>;
};

function lockManager(): LockManager | null {
  if (typeof navigator === 'undefined') return null;
  const locks = (navigator as unknown as { locks?: LockManager }).locks;
  return locks && typeof locks.request === 'function' ? locks : null;
}

/** Without one, private persistence is blocked outright — no marker write, no
 *  data write, no sweep. An unserializable browser gets a read-only degrade,
 *  never a best-effort one. */
export function hasSerializationBackend(): boolean {
  return lockManager() !== null;
}

/**
 * Single entry point, called wherever a session uid is observed
 * (ensureAnonSession, the onAuthChange wrapper, /auth/callback). It runs
 * inside the SAME exclusive lock every private mutation uses, so a transition
 * cannot interleave with one:
 *   - no marker        → claim generation 0 as-is (the pre-D1 migration path:
 *     first load after deploy must move and wipe nothing)
 *   - marker === uid   → adopt that generation; finish it if it crashed
 *     mid-switch
 *   - marker !== uid   → allocate the NEXT generation and publish it. The old
 *     one is swept afterwards as hygiene — isolation already holds without
 *     it, because the new namespace shares no key name with the old.
 *   - `claim` (Flow B, after a redeemed merge grant) keeps the SAME
 *     generation and only re-points the uid: the grant proved one human owns
 *     both sessions, and their local data — notably custom imports, which
 *     have no cloud copy — must transfer intact rather than be copied across
 *     a boundary where half of it could be lost.
 *
 * Returns whether the marker now verifiably reflects `uid` at a ready
 * generation. Callers MUST NOT treat `false` as "safe to proceed as this
 * uid" — it means the opposite.
 */
export async function syncLocalIdentityOwner(
  uid: string | null | undefined,
  opts?: { claim?: boolean },
): Promise<boolean> {
  // null uid = transient signed-out state (e.g. mid sign-out, before the
  // replacement anon session exists). Ownership can't be attributed yet;
  // the next uid observation decides.
  if (!uid || typeof window === 'undefined') return false;
  // Every LEGITIMATE call site calls advanceOwnerEpoch/
  // advanceOwnerEpochIfUnchanged FIRST, so `uid` already equals
  // currentOwnerUid by the time this runs. A mismatch means this call is
  // stale or out-of-order and must be rejected BEFORE touching storage at
  // all: zero reads, zero sweeps, zero marker writes.
  if (uid !== currentOwnerUid) return false;
  const locks = lockManager();
  if (!locks) {
    // Invariant 8: no serialization backend, no private persistence. Nothing
    // is read, nothing is written, and the caller is told plainly.
    setLocalOwnerState(uid, 'blocked');
    return false;
  }
  const epochAtStart = currentOwnerEpoch;
  let established = false;
  await locks.request(PRIVATE_STORAGE_LOCK, { mode: 'exclusive' }, async () => {
    // The wait is unbounded. Whoever we were transitioning to may not be the
    // current owner any more.
    if (uid !== currentOwnerUid || epochAtStart !== currentOwnerEpoch) return;
    established = transitionLocked(uid, opts?.claim === true);
  });
  return established;
}

/** The whole transition, inside the lock. Split out so the lock body stays one
 *  synchronous statement — there is no await in here, and there must not be:
 *  a network round trip under this lock freezes every other tab. */
function transitionLocked(uid: string, claim: boolean): boolean {
  const read = readMarker();
  if (read.status === 'unavailable' && read.reason === 'storage-error') {
    setLocalOwnerState(uid, 'blocked');
    return false;
  }
  const existing = read.status === 'present' ? read.marker : null;

  if (existing && existing.uid === uid) {
    // Same owner. A generation left in 'switching' by a crashed transition is
    // finished here rather than trusted: its namespace is re-verified before
    // it is published, exactly as a fresh one would be.
    return publishGeneration(uid, existing.generation);
  }

  if (existing && !claim) {
    // A stashed merge grant means a Flow B "sign in to my existing account"
    // hand-off is in flight: SIGNED_IN fires (and lands here) before
    // /auth/callback can redeem the grant, and allocating a new generation
    // now would strand the guest's local data moments before the redemption
    // proves both sessions belong to the same human. Defer — the callback
    // consumes the grant on every sign-in and re-syncs with the definitive
    // claim decision, so a stale grant can suppress at most one cycle.
    // Deferral is time-bounded (W14): a grant older than
    // MERGE_GRANT_MAX_AGE_MS is an ABANDONED hand-off (the server-side grant
    // died at 15 minutes), so it is removed and the transition proceeds — a
    // stale stash must not shield the previous identity's data forever.
    try {
      const grant = window.localStorage.getItem(STORAGE_KEYS.MERGE_GRANT);
      if (grant !== null) {
        if (!isMergeGrantStale(grant)) {
          setLocalOwnerState(uid, 'blocked');
          return false;
        }
        try {
          window.localStorage.removeItem(STORAGE_KEYS.MERGE_GRANT);
        } catch { /* remove failed — still proceed with the transition */ }
      }
    } catch { /* unreadable — proceed with the transition */ }
  }

  // The grant transferred this browser to a new uid. The data is already in
  // the right namespace; only the name on it changes.
  if (existing && claim) return publishGeneration(uid, existing.generation);

  // Either a genuine change of hands, or a marker this build cannot read (a
  // corrupt one is quarantined, never inherited). Both get a fresh namespace.
  if (existing === null && read.status === 'absent') {
    // Never claimed. The unprefixed keys are this browser's own history and
    // belong to whoever is signing in — the pre-D1 migration path.
    return publishGeneration(uid, LEGACY_GENERATION);
  }
  const next = allocateGeneration(existing?.generation ?? null);
  if (next === null) {
    setLocalOwnerState(uid, 'blocked');
    return false;
  }
  const ok = publishGeneration(uid, next);
  // Hygiene, not isolation: `next` shares no key name with anything that came
  // before it, so a failed sweep leaves unreachable bytes rather than exposed
  // ones. It must never block the user.
  if (ok) sweepGenerationsBefore(next);
  return ok;
}

// How long a stashed Flow B merge grant may defer user-scoped transitions.
// The server-side grant is single-use with a 15-minute TTL, so 60 minutes is
// a generous 4x envelope for magic-link latency + clock skew; beyond it the
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
 *     must not defer transitions
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

/** One past the highest generation anyone has ever used here — from the marker
 *  AND from what is physically on disk, so a corrupt marker cannot make a new
 *  transition land on top of an existing namespace. */
function allocateGeneration(markerGeneration: number | null): number | null {
  let highest = markerGeneration ?? LEGACY_GENERATION;
  try {
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i);
      if (!key || !key.startsWith(NAMESPACE_PREFIX)) continue;
      const sep = key.indexOf(NAMESPACE_SEPARATOR);
      if (sep <= NAMESPACE_PREFIX.length) continue;
      const n = Number(key.slice(NAMESPACE_PREFIX.length, sep));
      if (Number.isInteger(n) && n > highest) highest = n;
    }
  } catch {
    // Cannot enumerate, so cannot prove the next number is unused. Refusing is
    // the only safe answer: reusing a live namespace would hand one account's
    // bytes to another under the same physical names.
    return null;
  }
  return highest + 1;
}

/**
 * Two writes, in this order, and nothing between them is trusted:
 *   'switching' → prove the namespace is writable → 'ready'.
 * A crash anywhere leaves 'switching', which every read and write refuses.
 */
function publishGeneration(uid: string, generation: number): boolean {
  const write = (phase: OwnerMarker['phase']): boolean => {
    const value = JSON.stringify({ v: 2, uid, generation, phase } satisfies OwnerMarker);
    try {
      window.localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, value);
      // setItem not throwing is NOT proof the marker holds this — read it
      // back. A silent no-op would let every future sync see a marker that
      // never changed while callers upstream already believe it did.
      return window.localStorage.getItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER) === value;
    } catch {
      return false;
    }
  };
  if (!write('switching')) {
    setLocalOwnerState(uid, 'blocked');
    return false;
  }
  const sentinel = physicalKey(NAMESPACE_SENTINEL, generation);
  try {
    window.localStorage.setItem(sentinel, String(generation));
    if (window.localStorage.getItem(sentinel) !== String(generation)) {
      setLocalOwnerState(uid, 'blocked');
      return false;
    }
  } catch {
    setLocalOwnerState(uid, 'blocked');
    return false;
  }
  if (!write('ready')) {
    setLocalOwnerState(uid, 'blocked');
    return false;
  }
  currentGeneration = generation;
  setLocalOwnerState(uid, 'ready');
  return true;
}

/** Best-effort removal of every namespace older than `keep`, including the
 *  unprefixed generation-0 keys. Its result is deliberately not reported: a
 *  caller that could act on it would be acting on hygiene as if it were
 *  isolation. */
function sweepGenerationsBefore(keep: number): void {
  const doomed: string[] = [];
  try {
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i);
      if (!key) continue;
      if (key.startsWith(NAMESPACE_PREFIX)) {
        const sep = key.indexOf(NAMESPACE_SEPARATOR);
        const n = sep > NAMESPACE_PREFIX.length
          ? Number(key.slice(NAMESPACE_PREFIX.length, sep))
          : NaN;
        if (Number.isInteger(n) && n < keep) doomed.push(key);
        continue;
      }
      // Unprefixed: generation 0's own keys, swept only once something newer
      // exists.
      if (keep > LEGACY_GENERATION
        && (isUserScopedStorageKey(key) || key === NAMESPACE_SENTINEL)) doomed.push(key);
    }
  } catch {
    return;
  }
  for (const key of doomed) {
    try {
      window.localStorage.removeItem(key);
    } catch { /* one stuck key must not stop the rest */ }
  }
  // Same-tab useLocalStorageJSON readers only re-read on a storage event —
  // the readiness transition already notified them, but a mounted screen
  // keyed on a specific value re-reads here too.
  for (const key of USER_SCOPED_KEYS) {
    try {
      window.dispatchEvent(new StorageEvent('storage', { key }));
    } catch { /* jsdom/synthetic-event edge — never worth failing a sweep */ }
  }
}

// =====================================================================
// C1-R1: owner token / epoch — bind a private write to the identity that
// was active at the moment a user invoked it, not whichever identity
// happens to be current once the write's own async work finally resolves.
//
// A React generation ref only protects UI repaint (a component can ignore
// a stale response); it does nothing to stop the write itself from landing
// on a DIFFERENT account's row once the network round-trip completes after
// a sign-out/account-switch. This primitive is the thing the actual
// Supabase write functions check before they touch anything — local
// fallback storage or a remote row — so a wrong-account mutation is
// impossible by construction, not just hidden from the UI.
// =====================================================================

export interface OwnerToken {
  /** The uid active when this token was captured, or null when no identity
   *  had been resolved yet at capture time. A null-uid token is NOT a
   *  wildcard: it only ever validates a write that ALSO resolves to null at
   *  the same epoch (Supabase unconfigured / anon sign-in failed — the
   *  confirmed local-only degrade). It must never opportunistically bind to
   *  whichever identity resolves later — that could be this browser's
   *  first-ever identity, or a late arrival racing past an intervening
   *  switch, and a write function has no way to tell the two apart. Callers
   *  must gate private actions on a known owner (see ownerReady in the
   *  detail hook) rather than invoke them into this unresolved window. */
  uid: string | null;
  epoch: number;
  /**
   * WHICH namespace this token may touch — the persistent half of the
   * authority, and the half a module-local epoch cannot supply.
   *
   * A tab that misses every callback while the browser goes U1 → U2 → U1 sees
   * its own epoch unchanged and the marker naming U1 again. By uid and epoch
   * it is indistinguishable from a tab where nothing happened. It is not: the
   * data it was captured against was swept, and the U1 sitting there now is a
   * different generation. That is the comparison this field exists for.
   */
  generation: number;
}

let currentOwnerUid: string | null = null;
let currentOwnerEpoch = 0;
/** The generation the last PROVEN transition established, or null while no
 *  namespace is confirmed for whoever is current. */
let currentGeneration: number | null = null;

// Independent of the uid/epoch pair above: bumped on EVERY live
// authoritative auth callback (onAuthChange's wrapper), including a
// same-uid TOKEN_REFRESHED/INITIAL_SESSION event that leaves uid AND epoch
// completely unchanged (advanceOwnerEpoch no-ops for a same-uid
// re-observation — see its own doc comment). ensureAnonSession's async
// resolutions capture this at the start of their own work and must treat
// ANY change to it — not merely an epoch/uid change — as proof a live
// event landed while they were in flight, since a same-uid refresh is
// still an authoritative choke-point run that may have just completed the
// FIRST successful sync for this uid (blocked -> ready) which a stale
// resolution re-running the same sync must not race past unnoticed.
let authObservationRevision = 0;

/** Called by supabase.ts's onAuthChange wrapper on every live auth event. */
export function bumpAuthObservationRevision(): number {
  authObservationRevision += 1;
  return authObservationRevision;
}

/** Captured by ensureAnonSession before its own async work begins. */
export function getAuthObservationRevision(): number {
  return authObservationRevision;
}

/**
 * Advance the shared owner epoch on a REAL identity change. Called from the
 * single onAuthChange/ensureAnonSession choke points in supabase.ts for
 * every identity this browser observes — including the very first
 * resolution and a sign-out to null — so every private-write call site
 * across the app shares one synchronously-updated source of truth for
 * "who is active right now."
 *
 * A same-uid re-observation (INITIAL_SESSION, TOKEN_REFRESHED reporting the
 * identity we already know) is NOT a transition: the epoch only advances on
 * a genuine change, so a token captured moments earlier for the same
 * identity keeps validating across it.
 */
export function advanceOwnerEpoch(uid: string | null): void {
  if (uid === currentOwnerUid) return;
  currentOwnerUid = uid;
  currentOwnerEpoch += 1;
  // No namespace is confirmed for the new owner until a transition proves
  // one. Every token captured from here until then is unestablished, and
  // unestablished never validates.
  currentGeneration = null;
  // The instant the global owner moves, this browser's local USER_SCOPED
  // data is UNKNOWN for the new uid until syncLocalIdentityOwner proves
  // otherwise — block it immediately, synchronously, before that function
  // ever runs. This closes the real-world ordering window where the global
  // epoch has already advanced but React has not yet re-rendered any
  // component with the new identity: readers must never treat a stale
  // render's "still looks like the old identity" as license to show
  // whatever is currently sitting in the fixed-name USER_SCOPED_KEYS slots.
  setLocalOwnerState(uid, 'blocked');
  // A previously-established local-only realm (see enterLocalOnlyMode) was
  // confirmed for a SPECIFIC null window — ANY real transition (including
  // a plain sign-out that produces a NEW null window, or a real uid
  // resolving) invalidates it. It must be re-confirmed via a fresh
  // enterLocalOnlyMode() call, never assumed to still hold.
  setLocalOnlyRealmStatus('blocked');
}

// =====================================================================
// Local-owner readiness barrier: the SINGLE gate every reader/writer of
// USER_SCOPED_KEYS/USER_SCOPED_PREFIXES data must check before trusting
// (or creating) a value under those fixed key names. These keys carry no
// owner tag of their own — the LOCAL_IDENTITY_OWNER marker is the only
// thing that ever said "this belongs to uid X," and that marker can only
// be trusted between the moment syncLocalIdentityOwner PROVES it (clear
// verified + marker write read back) and the moment the global owner
// changes again. Everything in between — mid-transition, a deferred
// Flow-B grant window, a failed/unverified clear — is `blocked`: readers
// must return blank/null, writers must no-op, exactly as if the value did
// not exist, rather than exposing or creating data attributed to an
// unconfirmed identity.
// =====================================================================

export type LocalOwnerStatus = 'ready' | 'blocked';

let localOwnerState: { uid: string | null; status: LocalOwnerStatus } = {
  uid: null,
  status: 'blocked',
};
const localOwnerListeners = new Set<() => void>();

function notifyLocalOwnerListeners(): void {
  localOwnerListeners.forEach((cb) => {
    try {
      cb();
    } catch {
      // One listener throwing must never stop the rest from being notified.
    }
  });
}

function setLocalOwnerState(uid: string | null, status: LocalOwnerStatus): void {
  // No-op when nothing actually changed — keeps getLocalOwnerState()'s
  // snapshot referentially stable (matters if this is ever wired into a
  // useSyncExternalStore-based hook) and avoids firing a notification for
  // a transition that never happened (e.g. a genuine same-uid
  // re-observation, which advanceOwnerEpoch already short-circuits before
  // ever calling this — but syncLocalIdentityOwner's own "marker === uid"
  // no-op path calls it unconditionally on every re-observation).
  if (localOwnerState.uid === uid && localOwnerState.status === status) return;
  localOwnerState = { uid, status };
  notifyLocalOwnerListeners();
}

/** Snapshot for tests/debugging — prefer isLocalOwnerReady for gating. */
export function getLocalOwnerState(): { uid: string | null; status: LocalOwnerStatus } {
  return localOwnerState;
}

/** Same-tab notification for readiness transitions — mirrors the 'storage'
 *  event dispatched per-key by the generation sweep, but fires for the
 *  READY/BLOCKED transition itself, which isn't tied to any single key
 *  (a `blocked` state has nothing to dispatch a per-key event for). */
export function onLocalOwnerStateChange(cb: () => void): () => void {
  localOwnerListeners.add(cb);
  return () => localOwnerListeners.delete(cb);
}

/**
 * True only when local USER_SCOPED_KEYS/prefix data is CONFIRMED to belong
 * to `uid` right now. A null uid is never ready via this function — a
 * transient signed-out window has no identity to attribute local data to
 * (see isLocalOnlyRealmReady for the SEPARATE, explicitly-established
 * local-only-device case). Requires `uid` to match the CURRENT global
 * owner, not merely the last uid syncLocalIdentityOwner happened to be
 * called with — a sync invoked with a stale/wrong uid argument (a caller
 * bug, a delayed callback) must never be able to mark itself "ready"
 * while the actual live owner is someone else.
 */
export function isLocalOwnerReady(uid: string | null): boolean {
  return (
    uid !== null
    && uid === currentOwnerUid
    && localOwnerState.uid === uid
    && localOwnerState.status === 'ready'
  );
}

// =====================================================================
// Local-only realm: the explicit, controlled analog of "ready" for the
// null-uid case — Supabase unconfigured, or ensureAnonSession's anonymous
// sign-in genuinely failed (the confirmed local-only degrade documented on
// OwnerToken/isOwnerTokenValid). A bare "no identity resolved yet" null
// (the transient window before sign-out's replacement anon session
// exists) must NEVER be treated this way — isLocalOwnerReady's null case
// stays hard-false regardless. Only enterLocalOnlyMode()'s own explicit
// call — from ensureAnonSession, at the exact points it already calls
// setStorageStatus('local-only', ...) — can establish this realm, and
// ONLY when this browser has NEVER been claimed by any account (marker is
// null). A NON-null marker means a real prior account's data — notably
// CUSTOM_IMPORTS, which may be that account's ONLY copy — is sitting here.
// A temporary local degrade (Supabase briefly unreachable/unconfigured)
// must NEVER destroy it: this is a data-preservation contract, not merely
// an isolation one, and it takes priority over ever "establishing" a
// local-only realm at all in that case. Realm stays blocked, marker/data
// untouched, until that real identity is confirmed (or genuinely
// superseded) via the normal syncLocalIdentityOwner path.
// =====================================================================

let localOnlyRealmStatus: LocalOwnerStatus = 'blocked';

export function isLocalOnlyRealmReady(): boolean {
  return localOnlyRealmStatus === 'ready';
}

function setLocalOnlyRealmStatus(status: LocalOwnerStatus): void {
  if (localOnlyRealmStatus === status) return;
  localOnlyRealmStatus = status;
  notifyLocalOwnerListeners();
}

/**
 * Called ONLY from ensureAnonSession's confirmed-local-only branches, and
 * only meaningful when currentOwnerUid is null — the local-only realm is
 * exclusively the null-uid degrade case; a real uid already being current
 * means this call simply does not apply. Returns whether the realm is now
 * established. NEVER clears or touches USER_SCOPED_KEYS/the marker: a
 * pre-existing non-null marker means a real account already claims this
 * browser, and this function's whole job is to recognize that and refuse
 * to paper over it, not to make room for a different interpretation.
 */
export function enterLocalOnlyMode(): boolean {
  if (typeof window === 'undefined' || currentOwnerUid !== null) {
    setLocalOnlyRealmStatus('blocked');
    return false;
  }
  const read = readMarker();
  // Only a marker that is genuinely, readably ABSENT establishes this realm.
  // A marker that could not be read, or one this build cannot interpret, may
  // be a real prior account — CUSTOM_IMPORTS and the rest of USER_SCOPED_KEYS
  // could be that account's only copy — and "I could not tell" must never be
  // spent as "there is nobody here."
  if (read.status !== 'absent') {
    setLocalOnlyRealmStatus('blocked');
    return false;
  }
  // Never claimed by any account: the unprefixed keys are this device's own.
  currentGeneration = LEGACY_GENERATION;
  setLocalOnlyRealmStatus('ready');
  return true;
}

/** Exported for use-local-storage-json.ts's own readiness gate and for the
 *  static contract test proving no reader/writer bypasses it. */
export function isUserScopedStorageKey(key: string): boolean {
  return USER_SCOPED_KEYS.includes(key) || USER_SCOPED_PREFIXES.some((p) => key.startsWith(p));
}

/** Convenience for callers (use-local-storage-json.ts, readUserScopedRaw)
 *  that just need "is local data ready for WHOEVER the live global owner
 *  currently is" — avoids exposing the private currentOwnerUid variable
 *  directly. Covers BOTH cases: a confirmed non-null owner via
 *  isLocalOwnerReady, and the explicitly-established local-only realm for
 *  the null-uid confirmed-degrade case — a bare transient null (no
 *  enterLocalOnlyMode call ever made) stays blocked either way. */
export function isLocalOwnerReadyNow(): boolean {
  if (currentOwnerUid === null) return isLocalOnlyRealmReady();
  return isLocalOwnerReady(currentOwnerUid);
}

/**
 * Readiness-gated read for a USER_SCOPED_KEYS/prefix key. Every reader of
 * one of these fixed key names (match-cache, SchoolConfirmGate, the
 * favorites/profile local fallbacks, EmailMeButton, the semantic-rerank/
 * results-CTA/anchor-dismiss preference flags, …) MUST call this instead
 * of `localStorage.getItem` directly — see the module-level contract test
 * that enforces this. Returns null whenever the key is genuinely absent
 * OR local ownership is not currently confirmed for the live global owner
 * (including the null/signed-out case, UNLESS the local-only realm has
 * been explicitly established) — callers cannot tell "absent" from
 * "not confirmed" apart, by design: both mean "there is nothing safe to
 * show right now."
 */
export function readUserScopedRaw(key: string): string | null {
  const entry = readUserScopedEntry(key);
  return entry.status === 'present' ? entry.value : null;
}

/**
 * The AUTHORITY read: three answers, never two.
 *
 * `readUserScopedRaw` above is the display convenience — it maps everything
 * that is not a value to null, which is exactly right for a screen that has
 * nothing to show and exactly wrong for a decision. Anything that writes,
 * settles, overwrites, or concludes "there was nothing there" must come
 * through here instead, because `absent` licenses those and `unavailable`
 * forbids them, and the two are not distinguishable downstream.
 */
export type PrivateRead =
  | { status: 'present'; value: string }
  | { status: 'absent' }
  | {
    status: 'unavailable';
    /** 'not-ready' — no namespace is confirmed for the live owner.
     *  'superseded' — the browser's marker names someone/something else.
     *  'storage-error' — the browser refused the read. */
    reason: 'not-ready' | 'superseded' | 'storage-error';
  };

export function readUserScopedEntry(key: string): PrivateRead {
  if (typeof window === 'undefined') return { status: 'unavailable', reason: 'not-ready' };
  if (!isUserScopedStorageKey(key)) {
    throw new Error(`readUserScopedEntry: "${key}" is not a registered USER_SCOPED key/prefix`);
  }
  const ns = currentNamespace();
  if (ns.status !== 'present') return ns;
  try {
    const value = window.localStorage.getItem(physicalKey(key, ns.generation));
    return value === null ? { status: 'absent' } : { status: 'present', value };
  } catch {
    return { status: 'unavailable', reason: 'storage-error' };
  }
}

/**
 * Which namespace the live owner may touch right now, decided against the
 * browser's OWN marker rather than this module's memory.
 *
 * The two are not the same thing, and the gap between them is where the whole
 * class of bugs lives. Another tab that switches accounts moves the marker
 * immediately; a tab that has not received its auth event still believes the
 * old identity is live and ready. Trusting only memory is how that tab reads
 * — or writes — under a name that belongs to somebody else.
 */
function currentNamespace():
  | { status: 'present'; generation: number }
  | { status: 'unavailable'; reason: 'not-ready' | 'superseded' | 'storage-error' } {
  if (!isLocalOwnerReadyNow()) return { status: 'unavailable', reason: 'not-ready' };
  if (currentGeneration === null) return { status: 'unavailable', reason: 'not-ready' };
  const read = readMarker();
  if (read.status === 'unavailable') {
    return { status: 'unavailable', reason: read.reason === 'storage-error' ? 'storage-error' : 'superseded' };
  }
  if (currentOwnerUid === null) {
    // The local-only realm owns the unclaimed browser and nothing else. A
    // marker of ANY kind — including one this build cannot read, handled
    // above — means a real account is here.
    return read.status === 'absent' && currentGeneration === LEGACY_GENERATION
      ? { status: 'present', generation: LEGACY_GENERATION }
      : { status: 'unavailable', reason: 'superseded' };
  }
  if (read.status === 'absent') return { status: 'unavailable', reason: 'superseded' };
  const { marker } = read;
  if (marker.phase !== 'ready') return { status: 'unavailable', reason: 'not-ready' };
  if (marker.uid !== currentOwnerUid || marker.generation !== currentGeneration) {
    return { status: 'unavailable', reason: 'superseded' };
  }
  return { status: 'present', generation: marker.generation };
}

/** Every logical key under `logicalPrefix` that exists in the live owner's
 *  namespace. Enumeration is an authority operation like any other: a partial
 *  view is `unavailable`, never a short list. */
export function enumerateUserScopedKeys(
  logicalPrefix: string,
): { status: 'present'; keys: string[] } | { status: 'unavailable'; reason: string } {
  if (typeof window === 'undefined') return { status: 'present', keys: [] };
  if (!isUserScopedStorageKey(logicalPrefix)) {
    throw new Error(`enumerateUserScopedKeys: "${logicalPrefix}" is not a registered USER_SCOPED prefix`);
  }
  const ns = currentNamespace();
  if (ns.status !== 'present') return { status: 'unavailable', reason: ns.reason };
  const prefix = physicalKey(logicalPrefix, ns.generation);
  const strip = namespaceFor(ns.generation).length;
  const out: string[] = [];
  try {
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i);
      if (key && key.startsWith(prefix)) out.push(key.slice(strip));
    }
  } catch {
    return { status: 'unavailable', reason: 'storage-error' };
  }
  return { status: 'present', keys: out.sort() };
}

/**
 * True when `token` — captured at the moment the caller STARTED its
 * write/remove intent (a click, a debounce timer's creation, a Generate/
 * Extract invocation) — is still a legitimate continuation right now.
 * Readiness alone (isLocalOwnerReadyNow) only proves storage is CURRENTLY
 * usable — it says nothing about who the caller's own pending intent
 * belongs to. A stale U1-originated write firing AFTER U2 has become
 * ready would pass a bare readiness check (U2 IS ready right now) and
 * silently land under U2's data. Binding to the token's OWN captured
 * epoch — unconditionally, the same epoch-equality check every remote
 * write already goes through via isOwnerTokenValid — is what actually
 * rejects it: nothing this specific means "the global owner has not
 * moved on since I was captured," which only a genuinely-current caller
 * can satisfy.
 */
/**
 * The namespace this token may mutate, or why it may not mutate anything.
 *
 * Every gate the read path applies, plus the token's OWN generation. That last
 * comparison is what a uid check cannot do: a browser that went U1 → U2 → U1
 * reads back as U1 and is not the U1 this token was captured against.
 */
function writableGenerationFor(token: OwnerToken): number | null {
  // Invariant 8, checked first: without a serialization backend there is no
  // private persistence at all, so nothing below it matters.
  if (!hasSerializationBackend()) return null;
  if (currentOwnerEpoch !== token.epoch) return null;
  if (token.generation === UNESTABLISHED_GENERATION) return null;
  if (token.uid === null) {
    if (!isLocalOnlyRealmReady()) return null;
  } else if (!isLocalOwnerReady(token.uid)) {
    return null;
  }
  const ns = currentNamespace();
  if (ns.status !== 'present') return null;
  return ns.generation === token.generation ? ns.generation : null;
}

function isTokenCurrentForLocalStorage(token: OwnerToken): boolean {
  return writableGenerationFor(token) !== null;
}

/**
 * Token-gated write for a USER_SCOPED_KEYS/prefix key. `token` MUST be
 * captured (via captureOwnerToken()) at the moment the caller's write
 * INTENT began — a debounced autosave timer's creation, a Generate/
 * Extract invocation, a click handler — never re-captured just before this
 * call, which would defeat the whole point (a stale intent re-capturing a
 * fresh token would look identical to a genuinely-current one). Silently
 * no-ops (never throws) when the token is no longer current: new data must
 * never be attributed to an identity the token's own owner has since moved
 * on from, even if storage is otherwise usable right now for whoever IS
 * current.
 */
export function writeUserScopedRaw(key: string, value: string, token: OwnerToken): boolean {
  if (typeof window === 'undefined') return false;
  if (!isUserScopedStorageKey(key)) {
    throw new Error(`writeUserScopedRaw: "${key}" is not a registered USER_SCOPED key/prefix`);
  }
  const generation = writableGenerationFor(token);
  if (generation === null) return false;
  // The token's OWN generation, resolved once, before the bytes go down. A
  // switch that happens from here on lands in a different namespace and
  // cannot collide with this — which is why there is no rollback below and
  // must not be one: the old code's post-write `removeItem` deleted whatever
  // occupied the same fixed name, and after a switch that was the NEW
  // owner's data.
  const physical = physicalKey(key, generation);
  try {
    window.localStorage.setItem(physical, value);
    // setItem not throwing is NOT proof the value is there — the same
    // discipline the marker write follows. A storage shim that silently
    // no-ops (or truncates) would otherwise report success to a caller that
    // goes on to invalidate a cache and navigate to a page that reads this
    // very key back.
    return window.localStorage.getItem(physical) === value;
  } catch {
    return false; // quota / private mode — degrade to a no-op
  }
}

/**
 * Token-gated removal for a USER_SCOPED_KEYS/prefix key — same contract
 * and same token-capture discipline as writeUserScopedRaw. Removal is NOT
 * exempt from this gate: a late-arriving removal from an abandoned
 * identity's own cleanup/cache-invalidation logic (e.g. a stale
 * clearMatchCache() call) would otherwise delete the CURRENT identity's
 * own same-named data the instant it happens to reuse the same fixed key
 * — a cross-account destructive write, not merely a leak. The one
 * exception is this module's OWN generation sweep, which by definition runs
 * BEFORE readiness for the new owner is established and therefore cannot go
 * through this gate itself.
 *
 * removeItem not throwing is NOT proof the key is actually gone — read it
 * back, the same discipline every other write here follows. A caller
 * (match-cache's clearMatchCache, in particular) needs to be able to tell
 * "verifiably removed" from "who knows, storage may still be serving the
 * old value" so it can fail closed rather than treat a silent no-op as a
 * successful invalidation.
 */
export function removeUserScopedRaw(key: string, token: OwnerToken): boolean {
  if (typeof window === 'undefined') return false;
  if (!isUserScopedStorageKey(key)) {
    throw new Error(`removeUserScopedRaw: "${key}" is not a registered USER_SCOPED key/prefix`);
  }
  const generation = writableGenerationFor(token);
  if (generation === null) return false;
  // Resolved to THIS token's namespace before the delete, so a switch landing
  // in the gap between the check and the removal destroys nothing: the new
  // owner's bytes live under a different physical name entirely.
  const physical = physicalKey(key, generation);
  try {
    window.localStorage.removeItem(physical);
    return window.localStorage.getItem(physical) === null;
  } catch {
    return false;
  }
}

/**
 * Guarded counterpart for an ASYNC identity observation that is NOT
 * ordered relative to the live onAuthChange event stream — specifically
 * ensureAnonSession's own getSession()/signInAnonymously() resolution,
 * which can be delayed arbitrarily by the network and arrive AFTER a live
 * auth event has already advanced the shared owner past it. Applying such
 * a stale resolution unconditionally would roll currentOwnerUid backward
 * (and spuriously bump currentOwnerEpoch again), corrupting the primitive
 * for every future action until the next live event happens to fire —
 * not just the one call that raced.
 *
 * `sinceEpoch` is the epoch the caller captured before starting its own
 * async work. The observation is applied only if nothing has advanced the
 * shared state since then; otherwise something newer (almost always the
 * authoritative live listener, which always calls advanceOwnerEpoch
 * directly, never through this guard) already happened and this stale
 * result is silently dropped.
 *
 * Returns whether the observation was accepted. The caller MUST gate any
 * OTHER side effect tied to this same observation (notably
 * syncLocalIdentityOwner) on this return value — that function has no
 * epoch awareness of its own and will happily clear/reclaim local storage
 * for a uid this guard just decided to drop as stale.
 */
export function advanceOwnerEpochIfUnchanged(uid: string | null, sinceEpoch: number): boolean {
  if (currentOwnerEpoch !== sinceEpoch) return false;
  advanceOwnerEpoch(uid);
  return true;
}

/**
 * Synchronous snapshot of the current owner — capture this at the moment of
 * a user action, before any await, so the token reflects the identity
 * active AT INVOCATION rather than whatever happens to be current once the
 * write's own async resolution completes.
 */
/** Whether `token` still names the identity that is current right now —
 *  regardless of whether this browser's local data has been CONFIRMED for it.
 *  Lets a caller tell "you were signed out / switched accounts" (nothing to
 *  report) apart from "still you, but this browser's storage is not usable"
 *  (very much something to report). */
export function isTokenOwnerStillCurrent(token: OwnerToken): boolean {
  return token.uid === currentOwnerUid && token.epoch === currentOwnerEpoch;
}

export function captureOwnerToken(): OwnerToken {
  return {
    uid: currentOwnerUid,
    epoch: currentOwnerEpoch,
    generation: currentGeneration ?? UNESTABLISHED_GENERATION,
  };
}

/**
 * True when `resolvedUid` — the device id a write actually resolved to
 * after its own internal awaits — is a legitimate continuation of `token`.
 *
 * Fail-closed and uniform, including for token.uid === null: a null-uid
 * token is NOT a wildcard. It validates ONLY a write that ALSO resolves to
 * null, at the exact same epoch it was captured at (nothing happened in
 * between — Supabase unconfigured / anon sign-in failed, the confirmed
 * local-only degrade). It must never opportunistically bind to whichever
 * identity resolves later, even the browser's first-ever resolution — a
 * write function cannot tell "this is genuinely the first identity ever"
 * apart from "this is a late arrival racing past an intervening switch."
 * Callers must gate private actions on a known owner (see ownerReady in
 * the detail hook) rather than invoke them into this unresolved window.
 *
 * Epoch+uid equality alone is NOT sufficient: it proves nothing moved on
 * at the OwnerToken layer, but says nothing about whether this browser's
 * local USER_SCOPED registry has actually been verified for that
 * identity — a write whose local fallback path (readFavFallback,
 * readLocalProfile, …) is reached while a clear/claim is still blocked
 * must not proceed as if the local data were confirmed clean. For a
 * non-null uid this requires isLocalOwnerReady(token.uid); for a null
 * uid (the confirmed local-only degrade) it requires the explicitly
 * established isLocalOnlyRealmReady() — a bare "no identity resolved
 * yet" transient null is never sufficient on its own.
 */
export function isOwnerTokenValid(token: OwnerToken, resolvedUid: string | null): boolean {
  return resolvedUid === token.uid && isTokenCurrentForLocalStorage(token);
}

/** Thrown by a private-write helper when captureOwnerToken/isOwnerTokenValid
 *  detects the acting identity changed between invocation and write —
 *  distinguishable from a genuine remote/local failure so callers can drop
 *  it silently (the UI has already moved on to a different account/target)
 *  instead of surfacing a misleading error banner. */
/** Thrown by a READ whose owner check failed: either this browser's local
 *  data is not confirmed for the identity that started the read, or the
 *  identity moved on while it was in flight. Distinct from a `null` result,
 *  which means the row is CONFIRMED absent — conflating the two lets a
 *  caller treat "we could not verify who you are" as "you have no profile"
 *  and then overwrite the row it never managed to read. */
export class OwnerNotReadyError extends Error {
  constructor() {
    super('local data ownership is not confirmed for this read');
    this.name = 'OwnerNotReadyError';
  }
}

/**
 * A read that had ALREADY resolved which identity it belongs to, and then
 * failed anyway.
 *
 * The distinction this type exists to carry is not cosmetic. A read abandoned
 * because somebody else took the browser over belongs to nobody and must be
 * silent; a read that resolved this browser's own first identity and then hit
 * the network belongs to the person looking at the screen and must be
 * REPORTED, or a first visit sits on a loading spinner forever. From the
 * outside those two are the same rejected promise — only the layer that
 * resolved the identity can tell them apart, so it says so here.
 *
 * Trust comes from the class, never from the shape. A caller acts on
 * `ownerToken` by adopting it as a screen's capability, so an object that
 * merely has the right property names must not be able to grant one — see
 * isOwnerScopedLoadError, and the brand it checks.
 */
const OWNER_SCOPED_LOAD_BRAND: unique symbol = Symbol('OwnerScopedLoadError');

export class OwnerScopedLoadError extends Error {
  /** Not the caller's object: a frozen snapshot taken at construction, so a
   *  capability cannot be edited after the failure was raised — by the
   *  thrower, by a handler, or by anything in between. */
  readonly ownerToken: Readonly<OwnerToken>;

  readonly [OWNER_SCOPED_LOAD_BRAND] = true;

  constructor(ownerToken: OwnerToken, cause?: unknown) {
    // The original complaint is what the person's own logs and error
    // reporting need; scoping it must not swallow it.
    const message = cause instanceof Error ? cause.message : String(cause ?? 'load failed');
    super(message, cause === undefined ? undefined : { cause });
    this.name = 'OwnerScopedLoadError';
    this.ownerToken = Object.freeze({
      uid: ownerToken.uid,
      epoch: ownerToken.epoch,
      generation: ownerToken.generation,
    });
  }
}

/** True only for a genuine instance. A plain object wearing the same `name`
 *  and `ownerToken` is not one, and must never be treated as proof of who a
 *  screen belongs to. */
export function isOwnerScopedLoadError(err: unknown): err is OwnerScopedLoadError {
  return err instanceof OwnerScopedLoadError
    && (err as { [OWNER_SCOPED_LOAD_BRAND]?: boolean })[OWNER_SCOPED_LOAD_BRAND] === true;
}

export class OwnerMismatchError extends Error {
  constructor() {
    super('identity changed between invocation and write — mutation aborted');
    this.name = 'OwnerMismatchError';
  }
}

// A private-write serialization queue, keyed by (owner uid, owner epoch,
// opportunityId) and shared at the MODULE level — not per-component/
// per-hook. Interaction writes for one opportunity can be invoked from more
// than one mounted component at once (the detail page's Tracker AND a
// separately-mounted Cold Email modal both write the same interactions
// row), so a per-hook-instance queue would let them race each other; this
// map is the single point every call site enqueues onto. Epoch is part of
// the key so a sign-out immediately followed by a sign-back-in-as-the-
// same-person starts a fresh queue rather than needlessly blocking behind
// a stale-epoch entry that is destined to fail its own owner check anyway.
const writeQueues = new Map<string, Promise<unknown>>();

function writeQueueKey(token: OwnerToken, opportunityId: string): string {
  return JSON.stringify([token.uid, token.epoch, opportunityId]);
}

/**
 * Runs `fn` only after every earlier-enqueued write for the SAME (owner,
 * epoch, opportunityId) has settled — success or failure — so a fast
 * response can never land before a slower, earlier-invoked one (lost
 * status/notes updates from out-of-order network resolution). A rejected
 * entry does not poison the queue: later entries still run regardless of
 * any earlier one's outcome. The map entry is cleaned up once its last
 * enqueued write settles with nothing newer queued behind it, so it never
 * grows unbounded across a long session.
 */
export function enqueuePrivateWrite<T>(
  token: OwnerToken,
  opportunityId: string,
  fn: () => Promise<T>,
): Promise<T> {
  const key = writeQueueKey(token, opportunityId);
  const prior = writeQueues.get(key) ?? Promise.resolve();
  const result = prior.then(fn);
  const settled = result.then(() => undefined, () => undefined);
  writeQueues.set(key, settled);
  void settled.then(() => {
    if (writeQueues.get(key) === settled) writeQueues.delete(key);
  });
  return result;
}
