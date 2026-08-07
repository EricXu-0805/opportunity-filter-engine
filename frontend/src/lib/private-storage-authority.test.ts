// Unit D1 — private-storage authority.
//
// Account-private browser state must belong to exactly one (uid, generation),
// provably, at the byte level. These fixtures are written from the outside: a
// second module realm plays the tab that has not yet heard about the switch,
// and a replaceable storage facade plays the browser. Nothing here sleeps and
// nothing here spies on a prototype — jsdom's Storage prototype is not what
// production code reaches through, so a prototype spy silently measures
// nothing (see `countingStore`).

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { ProfileData } from './types';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from './supabase';

const loadProfileMock = vi.fn<() => Promise<LoadedProfile>>();
const commitMock = vi.fn<(i: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>();
vi.mock('./supabase', () => ({
  loadProfile: () => loadProfileMock(),
  commitProfilePatch: (intent: ProfilePatchIntent) => commitMock(intent),
}));

import { STORAGE_KEYS } from './storage-keys';

const U1 = 'authority-u1';
const U2 = 'authority-u2';
const MARKER = STORAGE_KEYS.LOCAL_IDENTITY_OWNER;
const PROFILE = STORAGE_KEYS.PROFILE;
const JOURNAL = STORAGE_KEYS.PROFILE_JOURNAL_PREFIX;

// =====================================================================
// A browser we can actually observe.
//
// Production code calls `window.localStorage.getItem(...)`. Replacing the
// whole accessor is the only interception point that is guaranteed to be on
// that path — a `vi.spyOn(Storage.prototype, 'getItem')` is not, because jsdom
// serves the storage object from an internal slot that never consults the
// prototype for these calls. Fixture 12 depends on this distinction being
// real, so every fixture uses the same facade.
// =====================================================================

interface Hooks {
  beforeGet?: (key: string) => void;
  afterGet?: (key: string) => void;
  beforeSet?: (key: string, value: string) => void;
  beforeRemove?: (key: string) => void;
  afterRemove?: (key: string) => void;
}

class CountingStore {
  private data = new Map<string, string>();

  hooks: Hooks = {};

  reads = 0;

  writes = 0;

  removes = 0;

  /** Reads/writes that bypass the hooks and the counters — the test's own
   *  X-ray of the browser, never something production code can reach. */
  peek(key: string): string | null {
    return this.data.has(key) ? this.data.get(key)! : null;
  }

  poke(key: string, value: string): void {
    this.data.set(key, value);
  }

  drop(key: string): void {
    this.data.delete(key);
  }

  snapshot(): Record<string, string> {
    return Object.fromEntries([...this.data.entries()].sort());
  }

  reset(): void {
    this.data.clear();
    this.hooks = {};
    this.reads = 0;
    this.writes = 0;
    this.removes = 0;
  }

  get length(): number {
    return this.data.size;
  }

  key(i: number): string | null {
    return [...this.data.keys()][i] ?? null;
  }

  getItem(key: string): string | null {
    this.reads += 1;
    this.hooks.beforeGet?.(key);
    const out = this.data.has(key) ? this.data.get(key)! : null;
    this.hooks.afterGet?.(key);
    return out;
  }

  setItem(key: string, value: string): void {
    this.writes += 1;
    this.hooks.beforeSet?.(key, value);
    this.data.set(key, String(value));
  }

  removeItem(key: string): void {
    this.removes += 1;
    this.hooks.beforeRemove?.(key);
    this.data.delete(key);
    this.hooks.afterRemove?.(key);
  }

  clear(): void {
    this.data.clear();
  }
}

const store = new CountingStore();

/** A hook that fires exactly once, on the nth matching call. Deterministic
 *  interleaving without a timer: the "other tab" runs inside the hook, at the
 *  precise instruction the fixture names. */
function once(match: (key: string) => boolean, run: () => void): (key: string) => void {
  let fired = false;
  return (key: string) => {
    if (fired || !match(key)) return;
    fired = true;
    run();
  };
}

type Realm = {
  identity: typeof import('./identity-owner');
  journal: typeof import('./profile-journal');
};

/**
 * A second tab. Its module state — epoch, readiness, the local-only realm —
 * is genuinely independent; only `localStorage` is shared, exactly as in a
 * real browser. This is what makes "the tab that has not received its auth
 * event yet" expressible at all.
 */
async function newRealm(): Promise<Realm> {
  vi.resetModules();
  const identity = await import('./identity-owner');
  const journal = await import('./profile-journal');
  return { identity, journal };
}

/**
 * A Web Lock that runs an UNCONTENDED request immediately, and queues a
 * contended one. jsdom has none; every browser this ships to does.
 *
 * Running promptly rather than on a later microtask is what lets a fixture
 * interleave one realm's transition inside another realm's synchronous
 * storage operation — the exact "after the check, before the write" window
 * these fixtures are about. A fake that always deferred could not express it.
 */
function installLocks(): void {
  let held = false;
  const waiting: Array<() => void> = [];
  const release = (): void => {
    held = false;
    waiting.shift()?.();
  };
  const run = (fn: () => unknown, resolve: (v: unknown) => void, reject: (e: unknown) => void): void => {
    held = true;
    let out: unknown;
    try {
      out = fn();
    } catch (err) {
      release();
      reject(err);
      return;
    }
    Promise.resolve(out).then(
      (v) => { release(); resolve(v); },
      (e) => { release(); reject(e); },
    );
  };
  Object.defineProperty(navigator, 'locks', {
    configurable: true,
    value: {
      request: (_n: string, _o: unknown, fn: () => unknown) => new Promise((resolve, reject) => {
        if (held) waiting.push(() => run(fn, resolve, reject));
        else run(fn, resolve, reject);
      }),
    },
  });
}

function removeLocks(): void {
  Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined });
}

let realLocalStorage: PropertyDescriptor | undefined;

beforeEach(() => {
  realLocalStorage ??= Object.getOwnPropertyDescriptor(window, 'localStorage');
  store.reset();
  Object.defineProperty(window, 'localStorage', { configurable: true, value: store });
  installLocks();
  loadProfileMock.mockReset();
  commitMock.mockReset();
});

afterEach(() => {
  if (realLocalStorage) Object.defineProperty(window, 'localStorage', realLocalStorage);
  installLocks();
});

/** Bring a realm to "U owns this browser and its local data is confirmed".
 *  The epoch fence is synchronous; the namespace transition is not, because it
 *  runs inside the same exclusive lock every private mutation takes. */
function claim(realm: Realm, uid: string): Promise<boolean> {
  realm.identity.advanceOwnerEpoch(uid);
  return realm.identity.syncLocalIdentityOwner(uid);
}

// =====================================================================
// A. Cross-realm transition and late writes
// =====================================================================

describe('D1-A private namespace survives a concurrent transition', () => {
  it('sweep-late-fixed-write: a write released after U2 passed the PROFILE slot is unreadable by U2', async () => {
    const a = await newRealm();
    await claim(a, U1);
    const tokenA = a.identity.captureOwnerToken();
    expect(a.identity.writeUserScopedRaw(PROFILE, '{"major":"U1-SECRET"}', tokenA)).toBe(true);
    // A second private key, so "the sweep has moved past PROFILE" has an
    // observable instant regardless of whether the sweep walks a fixed list or
    // only what is actually there.
    expect(a.identity.writeUserScopedRaw(STORAGE_KEYS.PROFILE_SYNC, '{"v":1}', tokenA)).toBe(true);

    const b = await newRealm();
    b.identity.advanceOwnerEpoch(U2);
    // The sweep has PASSED the PROFILE slot: removed it AND read it back to
    // confirm. Reaching the next key is the proof — releasing one instruction
    // earlier only exercises that read-back, which is a different guarantee.
    let released = false;
    store.hooks.beforeRemove = once(
      (k) => k === STORAGE_KEYS.PROFILE_SYNC,
      () => {
        released = true;
        a.identity.writeUserScopedRaw(PROFILE, '{"major":"U1-LATE"}', tokenA);
      },
    );
    await b.identity.syncLocalIdentityOwner(U2);
    store.hooks = {};

    // Deliberately not asserting WHICH defence caught it. Refused at the gate,
    // and landed-but-unreachable, are both correct answers; "U2 can read it"
    // is the only wrong one.
    expect(released, 'the release point was actually reached').toBe(true);
    expect(b.identity.readUserScopedRaw(PROFILE), 'U2 reads nothing of U1\'s').toBeNull();
    expect(store.peek(PROFILE)).not.toBe('{"major":"U1-LATE"}');
  });

  it('sweep-late-prefix-append: a journal op appended after U2 enumerated is neither enumerated nor read', async () => {
    const a = await newRealm();
    await claim(a, U1);
    const tokenA = a.identity.captureOwnerToken();

    const b = await newRealm();
    b.identity.advanceOwnerEpoch(U2);
    // Enumeration happens before the fixed-key sweep, so the first PROFILE
    // removal is proof the scan is already behind us.
    store.hooks.beforeRemove = once(
      (k) => k === PROFILE,
      () => {
        a.identity.writeUserScopedRaw(`${JOURNAL}op_u1-late`, JSON.stringify({ v: 1, stolen: true }), tokenA);
      },
    );
    b.identity.syncLocalIdentityOwner(U2);
    store.hooks = {};

    const u2Sees = Object.keys(store.snapshot()).filter((k) => k.startsWith(JOURNAL));
    for (const key of u2Sees) {
      expect(b.identity.readUserScopedRaw(key)).toBeNull();
    }
    const outstanding = b.journal.readOutstandingOps();
    expect(outstanding.ok ? outstanding.value : []).toEqual([]);
  });

  it('remove-after-precheck-does-not-delete-new-owner', async () => {
    const a = await newRealm();
    await claim(a, U1);
    const tokenA = a.identity.captureOwnerToken();
    a.identity.writeUserScopedRaw(PROFILE, '{"major":"U1"}', tokenA);

    const b = await newRealm();
    // U1's removal has already passed its owner precheck; the switch lands in
    // the gap before the physical delete. The transition's storage effects are
    // synchronous under an uncontended lock, so this really is that gap.
    store.hooks.beforeRemove = once((k) => k === PROFILE, () => {
      b.identity.advanceOwnerEpoch(U2);
      void b.identity.syncLocalIdentityOwner(U2);
      b.identity.writeUserScopedRaw(PROFILE, '{"major":"U2-OWN"}', b.identity.captureOwnerToken());
    });
    a.identity.removeUserScopedRaw(PROFILE, tokenA);
    store.hooks = {};

    expect(b.identity.readUserScopedRaw(PROFILE)).toBe('{"major":"U2-OWN"}');
  });

  it('rollback-does-not-delete-new-owner', async () => {
    const a = await newRealm();
    await claim(a, U1);
    const tokenA = a.identity.captureOwnerToken();

    const b = await newRealm();
    // U1's write is down; between its read-back and its owner re-check the
    // browser changes hands, so U1 decides to roll its own bytes back.
    store.hooks.afterGet = once((k) => k === PROFILE, () => {
      b.identity.advanceOwnerEpoch(U2);
      void b.identity.syncLocalIdentityOwner(U2);
      b.identity.writeUserScopedRaw(PROFILE, '{"major":"U2-OWN"}', b.identity.captureOwnerToken());
    });
    a.identity.writeUserScopedRaw(PROFILE, '{"major":"U1"}', tokenA);
    store.hooks = {};

    expect(b.identity.readUserScopedRaw(PROFILE)).toBe('{"major":"U2-OWN"}');
  });

  it('cross-realm-owner-ABA: a token from before U1→U2→U1 never validates again', async () => {
    const a = await newRealm();
    await claim(a, U1);
    const tokenA = a.identity.captureOwnerToken();

    const b = await newRealm();
    await claim(b, U1);
    await claim(b, U2);
    await claim(b, U1);

    // Realm A missed every callback: its own epoch never moved and the marker
    // reads U1 again. Nothing local can tell it apart from "nothing happened"
    // — the authority has to.
    expect(a.identity.isOwnerTokenValid(tokenA, U1)).toBe(false);
    expect(a.identity.writeUserScopedRaw(PROFILE, '{"major":"REVIVED"}', tokenA)).toBe(false);
  });

  it('transition-shares-global-transaction: the marker cannot move while a private transaction is held', async () => {
    const a = await newRealm();
    await claim(a, U1);
    const tokenA = a.identity.captureOwnerToken();
    a.identity.writeUserScopedRaw(PROFILE, '{"major":"U1"}', tokenA);

    const b = await newRealm();
    b.identity.advanceOwnerEpoch(U2);

    let markerDuringHold: string | null = null;
    let dataDuringHold: string | null = null;
    let transition: Promise<boolean> | null = null;

    await a.journal.withProfileLock(tokenA, async () => {
      // Started from inside the holder's critical section. It must not be able
      // to complete any part of itself — not the marker, not the sweep —
      // until this body returns. Awaiting it HERE would deadlock, which is
      // itself the proof that the two share one lock.
      transition = b.identity.syncLocalIdentityOwner(U2);
      await Promise.resolve();
      await Promise.resolve();
      markerDuringHold = store.peek(MARKER);
      dataDuringHold = store.peek(PROFILE);
    });
    await transition;

    expect(markerDuringHold, 'the marker names U1 for as long as U1 holds the lock')
      .toContain(U1);
    expect(dataDuringHold).toBe('{"major":"U1"}');
    // And once released it really did happen — otherwise this fixture would
    // pass against a transition that simply never ran.
    expect(store.peek(MARKER)).toContain(U2);
  });

  it('no-lock-no-idb-fails-closed: with no serialization backend nothing moves', async () => {
    const a = await newRealm();
    await claim(a, U1);
    const tokenA = a.identity.captureOwnerToken();
    a.identity.writeUserScopedRaw(PROFILE, '{"major":"U1"}', tokenA);

    const before = store.snapshot();
    removeLocks();
    const realIdb = Object.getOwnPropertyDescriptor(window, 'indexedDB');
    Object.defineProperty(window, 'indexedDB', { configurable: true, value: undefined });
    try {
      const b = await newRealm();
      b.identity.advanceOwnerEpoch(U2);
      expect(await b.identity.syncLocalIdentityOwner(U2)).toBe(false);
      expect(b.identity.writeUserScopedRaw(PROFILE, '{"major":"U2"}', b.identity.captureOwnerToken())).toBe(false);
    } finally {
      if (realIdb) Object.defineProperty(window, 'indexedDB', realIdb);
      installLocks();
    }

    expect(store.snapshot()).toEqual(before);
  });

  it('local-only-marker-unavailable-is-not-absent', async () => {
    const a = await newRealm();
    a.identity.advanceOwnerEpoch(null);
    expect(a.identity.enterLocalOnlyMode()).toBe(true);
    const localOnly = a.identity.captureOwnerToken();
    expect(localOnly.uid).toBeNull();

    // A real account has since claimed this browser — and the marker read that
    // would say so is the one that fails.
    store.poke(MARKER, U2);
    const before = store.snapshot();
    store.hooks.beforeGet = (key) => {
      if (key === MARKER) throw new Error('storage unavailable');
    };
    let wrote: boolean;
    try {
      wrote = a.identity.writeUserScopedRaw(PROFILE, '{"major":"LOCAL-ONLY"}', localOnly);
    } finally {
      store.hooks = {};
    }

    expect(wrote).toBe(false);
    expect(store.snapshot()).toEqual(before);
  });
});

// =====================================================================
// B. Strict authority reads
// =====================================================================

describe('D1-B an authority read that fails is unavailable, never absent', () => {
  it('acked-key-read-throws-does-not-resurrect an acknowledged op', async () => {
    const a = await newRealm();
    // profile-sync's import registers the journal's profile-key guard. Without
    // it every read fails closed for an unrelated reason, and this fixture
    // would pass without ever exercising the ack path.
    await import('./profile-sync');
    await claim(a, U1);
    const token = a.identity.captureOwnerToken();
    const op = a.journal.appendJournalOp({
      fields: [{ key: 'major', base: { present: true, value: 'CS' }, desired: { present: true, value: 'ECE' } }],
      baseRevision: 1,
      writer: 'home-form',
      mode: 'set',
    }, token);
    expect(op).not.toBeNull();
    // Acknowledged, but its bytes are still physically present — the two-phase
    // settle's own window.
    store.poke(`${JOURNAL}ack`, JSON.stringify([op!.opId]));

    store.hooks.beforeGet = (key) => {
      if (key === `${JOURNAL}ack`) throw new Error('storage unavailable');
    };
    let outstanding: ReturnType<typeof a.journal.readOutstandingOps>;
    try {
      outstanding = a.journal.readOutstandingOps();
    } finally {
      store.hooks = {};
    }

    expect(outstanding.ok).toBe(false);
  });

  it('existing-receipt-read-throws-does-not-overwrite the receipt already there', async () => {
    const a = await newRealm();
    await claim(a, U1);
    const token = a.identity.captureOwnerToken();
    const r1 = {
      v: 1 as const,
      ancestorOpId: 'anc-1',
      ancestorLineage: 'lineage-1',
      revision: 4,
      profile: { major: { present: true as const, value: 'R1' } },
      confirmedKeys: ['major'],
    };
    expect(a.journal.appendRebaseReceipt(r1, token)).toBe(true);
    const receiptKey = Object.keys(store.snapshot()).find((k) => k.includes('anc-1'));
    expect(receiptKey).toBeDefined();
    const before = store.peek(receiptKey!);

    let firstReadOfKey = true;
    store.hooks.beforeGet = (key) => {
      if (key === receiptKey && firstReadOfKey) {
        firstReadOfKey = false;
        throw new Error('storage unavailable');
      }
    };
    let wrote: boolean;
    try {
      wrote = a.journal.appendRebaseReceipt(
        { ...r1, revision: 9, profile: { major: { present: true, value: 'R2' } } },
        token,
      );
    } finally {
      store.hooks = {};
    }

    expect(wrote).toBe(false);
    expect(store.peek(receiptKey!)).toBe(before);
  });

  it('envelope-invalid-or-read-error-is-unavailable, so no write continues on it', async () => {
    vi.resetModules();
    const identity = await import('./identity-owner');
    const sync = await import('./profile-sync');
    await claim({ identity, journal: await import('./profile-journal') }, U1);
    const token = identity.captureOwnerToken();

    store.poke(STORAGE_KEYS.PROFILE_SYNC, '{ not json at all');
    const before = store.snapshot();

    const view = sync.makeProfileViewSnapshot({
      baseProfile: { major: 'CS' } as unknown as ProfileData,
      renderedProfile: { major: 'CS' } as unknown as ProfileData,
      revision: 3,
      token,
      identityGeneration: 1,
      source: 'hydration',
    });
    const outcome = await sync.commitProfileAction({
      keys: ['major'],
      view,
      desiredAfter: { major: 'ECE' } as unknown as ProfileData,
      writer: sync.HOME_FORM_WRITER,
    });

    expect(outcome.durable).toBe(false);
    expect(store.snapshot()).toEqual(before);
  });
});

// =====================================================================
// C. Public API ownership before I/O
// =====================================================================

describe('D1-C a superseded token does no private I/O at all', () => {
  it('old-owner-public-api-zero-private-io', async () => {
    vi.resetModules();
    const identity = await import('./identity-owner');
    const journal = await import('./profile-journal');
    const sync = await import('./profile-sync');
    await claim({ identity, journal }, U1);
    const staleU1 = identity.captureOwnerToken();

    await claim({ identity, journal }, U2);
    const u2 = identity.captureOwnerToken();
    // U2 has real, staged work: this is the ledger the stale caller must not
    // be able to reach, read, or reset.
    expect(sync.recordProfileIntent(
      { major: 'U2-MAJOR' } as unknown as ProfileData,
      ['major'],
      u2,
      { writer: sync.HOME_FORM_WRITER },
    )).toBe(true);
    const u2DirtyBefore = sync.getDirtyProfileKeys(u2, sync.HOME_FORM_WRITER);
    expect(u2DirtyBefore.ok && u2DirtyBefore.value).toEqual(['major']);
    const bytesBefore = store.snapshot();

    const readsBefore = store.reads;
    const writesBefore = store.writes;
    const removesBefore = store.removes;

    const recorded = sync.recordProfileIntent(
      { major: 'U1-GHOST' } as unknown as ProfileData,
      ['major'],
      staleU1,
      { writer: sync.HOME_FORM_WRITER },
    );
    const dirty = sync.getDirtyProfileKeys(staleU1, sync.HOME_FORM_WRITER);

    expect(recorded).toBe(false);
    expect(dirty.ok).toBe(false);
    expect(store.reads - readsBefore).toBe(0);
    expect(store.writes - writesBefore).toBe(0);
    expect(store.removes - removesBefore).toBe(0);
    expect(store.snapshot()).toEqual(bytesBefore);

    // …and U2's own ledger is exactly where it was.
    const u2DirtyAfter = sync.getDirtyProfileKeys(u2, sync.HOME_FORM_WRITER);
    expect(u2DirtyAfter.ok && u2DirtyAfter.value).toEqual(['major']);
  });

  it('stale-screen-skill-action-does-not-touch-new-owner-ledger', async () => {
    vi.resetModules();
    const identity = await import('./identity-owner');
    const journal = await import('./profile-journal');
    const sync = await import('./profile-sync');
    await claim({ identity, journal }, U1);
    const staleU1 = identity.captureOwnerToken();

    await claim({ identity, journal }, U2);
    const u2 = identity.captureOwnerToken();
    // U2 imported a résumé: their skills are ADDITIVE — the import asserts
    // nothing about names it never mentioned.
    const u2Desired = { skills: [{ name: 'U2-SKILL', level: 'experienced' }] } as unknown as ProfileData;
    // A confirmed row: staging has a base to layer onto, so the outbox this
    // fixture inspects actually exists.
    loadProfileMock.mockResolvedValue({
      source: 'cloud',
      profile: { skills: [{ name: 'ROW-SKILL', level: 'beginner' }] },
      revision: 4,
      token: u2,
    });
    await sync.hydrateProfile();
    sync.markSkillAdditions([{ name: 'U2-SKILL', level: 'experienced' }], u2);
    expect(sync.recordProfileIntent(u2Desired, ['skills'], u2, { writer: sync.HOME_FORM_WRITER })).toBe(true);
    const bytesBefore = store.snapshot();

    // A U1 screen that is still mounted: the résumé parse it kicked off long
    // ago comes back, and a hand-edit follows, while the hook has not yet
    // processed the auth event.
    sync.markSkillAdditions([{ name: 'U1-GHOST-SKILL', level: 'expert' }], staleU1);
    sync.markSkillsReplaced(staleU1);

    expect(store.snapshot()).toEqual(bytesBefore);
    const stillDirty = sync.getDirtyProfileKeys(u2, sync.HOME_FORM_WRITER);
    expect(stillDirty.ok && stillDirty.value).toEqual(['skills']);

    commitMock.mockResolvedValue({ status: 'transport-error', message: 'held' });
    await sync.stageProfilePatch(u2Desired, ['skills'], u2);
    const pending = sync.readProfileSyncEnvelope()?.pending;
    // U2's own operation, and only it. A ghost 'replace' inherited from the
    // stale screen would turn their import into a whole-list overwrite and
    // delete every skill the row already had.
    expect(pending?.skillOps.map((op) => op.kind)).toEqual(['add']);
    expect(pending?.skillAdditions.map((s) => s.name)).toEqual(['U2-SKILL']);
    expect(pending?.additiveKeys).toContain('skills');
  });

  it('stale-screen-skill-action-control: the same U2 sequence, with no stale screen, stages additively', async () => {
    vi.resetModules();
    const identity = await import('./identity-owner');
    const journal = await import('./profile-journal');
    const sync = await import('./profile-sync');
    await claim({ identity, journal }, U1);
    await claim({ identity, journal }, U2);
    const u2 = identity.captureOwnerToken();
    const u2Desired = { skills: [{ name: 'U2-SKILL', level: 'experienced' }] } as unknown as ProfileData;
    // A confirmed row: staging has a base to layer onto, so the outbox this
    // fixture inspects actually exists.
    loadProfileMock.mockResolvedValue({
      source: 'cloud',
      profile: { skills: [{ name: 'ROW-SKILL', level: 'beginner' }] },
      revision: 4,
      token: u2,
    });
    await sync.hydrateProfile();
    sync.markSkillAdditions([{ name: 'U2-SKILL', level: 'experienced' }], u2);
    expect(sync.recordProfileIntent(u2Desired, ['skills'], u2, { writer: sync.HOME_FORM_WRITER })).toBe(true);

    commitMock.mockResolvedValue({ status: 'transport-error', message: 'held' });
    await sync.stageProfilePatch(u2Desired, ['skills'], u2);
    const pending = sync.readProfileSyncEnvelope()?.pending;

    expect(pending?.skillOps.map((op) => op.kind)).toEqual(['add']);
    expect(pending?.additiveKeys).toContain('skills');
  });

it('remove-targets-own-namespace: a namespaced owner deleting its own key really deletes it', async () => {
    // The other half of invariant 6. `remove-after-precheck` proves a stale
    // owner cannot reach the NEW owner's bytes; this proves the new owner can
    // still reach its own. A remove that dropped the namespace would target an
    // unprefixed name, find it already absent, and report success — the value
    // it was asked to delete surviving under the name nobody looked at.
    const a = await newRealm();
    await claim(a, U1);
    await claim(a, U2); // generation 1: the namespace is no longer the bare key
    const token = a.identity.captureOwnerToken();

    expect(a.identity.writeUserScopedRaw(PROFILE, '{"major":"MINE"}', token)).toBe(true);
    expect(a.identity.removeUserScopedRaw(PROFILE, token)).toBe(true);
    expect(a.identity.readUserScopedRaw(PROFILE), 'gone, not merely reported gone').toBeNull();
  });

  it('old-owner-public-api-preserves-ledger: a superseded caller cannot reset the live owner\'s in-memory ledger', async () => {
    vi.resetModules();
    const identity = await import('./identity-owner');
    const journal = await import('./profile-journal');
    const sync = await import('./profile-sync');
    await claim({ identity, journal }, U1);
    const staleU1 = identity.captureOwnerToken();

    await claim({ identity, journal }, U2);
    const u2 = identity.captureOwnerToken();
    loadProfileMock.mockResolvedValue({
      source: 'cloud', profile: { major: 'ROW' }, revision: 4, token: u2,
    });
    await sync.hydrateProfile();

    // TWO edits to the same field: the second continues the first's chain, so
    // the field's mutation version reaches 2.
    const once = { major: 'FIRST' } as unknown as ProfileData;
    const twice = { major: 'SECOND' } as unknown as ProfileData;
    expect(sync.recordProfileIntent(once, ['major'], u2, { writer: sync.HOME_FORM_WRITER })).toBe(true);

    // …and in between, a screen the browser has moved past acts. Every one of
    // its calls must be refused BEFORE reaching the scope reset, which would
    // drop U2's chain and make their next keystroke look like a brand new edit
    // against a base the row has already moved past. A read is no safer than a
    // write here: ensureScope mutates, so merely ASKING resets the ledger.
    expect(sync.recordProfileIntent(
      { major: 'GHOST' } as unknown as ProfileData,
      ['major'],
      staleU1,
      { writer: sync.HOME_FORM_WRITER },
    )).toBe(false);
    expect(sync.getDirtyProfileKeys(staleU1, sync.HOME_FORM_WRITER).ok).toBe(false);

    expect(sync.recordProfileIntent(twice, ['major'], u2, { writer: sync.HOME_FORM_WRITER })).toBe(true);
    commitMock.mockResolvedValue({ status: 'transport-error', message: 'held' });
    await sync.stageProfilePatch(twice, ['major'], u2);

    const pending = sync.readProfileSyncEnvelope()?.pending;
    // Two recorded edits plus the stage's own bump. A scope reset in between
    // would restart the count, which is exactly what makes this observable.
    expect(pending?.keyVersions.major, "U2's edit chain is unbroken").toBe(3);
  });

  it('optional-field-owner-fence: the gate is not limited to DEFAULT_PROFILE keys', async () => {
    vi.resetModules();
    const identity = await import('./identity-owner');
    const journal = await import('./profile-journal');
    const sync = await import('./profile-sync');
    await claim({ identity, journal }, U1);
    const staleU1 = identity.captureOwnerToken();

    await claim({ identity, journal }, U2);
    const u2 = identity.captureOwnerToken();
    expect(sync.recordProfileIntent(
      { linkedin_url: 'https://linkedin.com/in/u2' } as unknown as ProfileData,
      ['linkedin_url'],
      u2,
      { writer: sync.HOME_FORM_WRITER },
    )).toBe(true);
    const bytesBefore = store.snapshot();
    const readsBefore = store.reads;

    const recorded = sync.recordProfileIntent(
      { linkedin_url: 'https://linkedin.com/in/u1-ghost' } as unknown as ProfileData,
      ['linkedin_url'],
      staleU1,
      { writer: sync.HOME_FORM_WRITER },
    );

    expect(recorded).toBe(false);
    expect(store.reads - readsBefore).toBe(0);
    expect(store.snapshot()).toEqual(bytesBefore);
    const u2Dirty = sync.getDirtyProfileKeys(u2, sync.HOME_FORM_WRITER);
    expect(u2Dirty.ok && u2Dirty.value).toEqual(['linkedin_url']);
  });
});
