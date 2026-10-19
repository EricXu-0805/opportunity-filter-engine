import * as React from 'react';
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { OwnerToken } from '@/lib/identity-owner';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from '@/lib/supabase';
import type { ProfileData } from '@/lib/types';

const nav = vi.hoisted(() => ({
  params: new URLSearchParams(), router: { push: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() },
}));
vi.mock('next/navigation', () => ({ useRouter: () => nav.router, useSearchParams: () => nav.params }));
vi.mock('@/lib/api', () => ({ parseGitHubProfile: vi.fn() }));
vi.mock('@/lib/match-cache', () => ({ clearMatchCache: vi.fn(() => true) }));
// Every tab gets its own transport (see open()); nothing may reach a shared one.
vi.mock('@/lib/supabase', () => ({}));
import { DEFAULT_PROFILE } from './types';

// Checklist M136, from the live guest check of 2026-10-19 ~01:50Z on production
// c10e5db7 (live/x3/m117.mjs, cases d and d2, `backOnline`). Two tabs of one
// browser, each taken offline and back online on its own page: B's own edit
// fails offline, A's name edit fails offline too (its save carries B's edit,
// one shared outbox). B comes back first and its resend saves both; A comes
// back ~0.4 s later, sends nothing, and shows "Couldn't save your profile —
// please retry." with Retry sync, although its name is stored.
//
// A's reconnect resend, the same replay Retry makes, flushes the outbox and
// finds nothing left to send: B's answer has emptied it and acknowledged
// every journal operation. The coordinator says that with a bare 'blocked',
// and the replay showed it as an error. With B answered 180 ms after it left,
// that is A back 180 to 1179 ms after B; any later, M117's read (1 s after A
// hears B's answer) has already said saved. A's flush can also find the entry
// still in the outbox, wait for the lock while B records its answer, and find
// it gone. The second describe holds what must still show an error, or still
// be sent.
//
// The other-tab-sync harness (use-profile-form.other-tab-sync.test.tsx), with
// each tab also its own page on the network side:
//   - a module realm per tab, imported with `?tab=<name>`, so every stack frame
//     of the hook, profile-sync and identity-owner names the tab it runs in;
//   - per tab: the transport (requests fail at once while that tab is
//     offline, otherwise answered after LATENCY_MS), navigator.onLine (read
//     from the stack), and its own online/offline/focus/visibility listeners;
//   - storage events go to every tab but the writer, the writer told apart by
//     the stack; the synthetic same-tab 'storage' event writeLocalStorageJSON
//     dispatches goes to the writer only, as in a browser;
//   - the server answers a patch whose values are already stored, at the
//     expected revision or one past it, 'unchanged' (029's rule), which the
//     client reads as already-saved.
const BASE = { ...DEFAULT_PROFILE, name: 'Alex', home_school: 'uiuc', institution: 'UIUC', college: 'Engineering',
  major: 'Computer Science', grade: 'Junior', research_interests: 'Original research' } as unknown as ProfileData;
const t = (key: string) => key;
const NAME = 'Jamie Park';
// Live: B's resend was answered 177-218 ms after it left.
const LATENCY_MS = Number(process.env.M136_LATENCY ?? 180);

let remote: ProfileData;
let revision: number;
let uid: string;
let sequence = 0;
let clock = 0;

type Note = { at: number; tab: string; what: string; detail: string; stack?: string };
let notes: Note[] = [];
function note(tab: string, what: string, detail: string, stack?: string) { notes.push({ at: clock, tab, what, detail, stack }); }

const TAG = /\?tab=([A-Z])\b/;
function stackNow(): string {
  const limit = Error.stackTraceLimit;
  Error.stackTraceLimit = 200;
  const stack = new Error().stack ?? '';
  Error.stackTraceLimit = limit;
  return stack;
}
/** The tab whose code is running: the innermost frame of a tagged module. */
function tabOfStack(): string | null { return TAG.exec(stackNow())?.[1] ?? null; }
function taggedFrames(): string {
  return stackNow().split('\n').filter((line) => TAG.test(line))
    .map((line) => line.trim().replace(/\/[^\s()]*\/src\//, 'src/')).join('\n        ');
}

async function drain() { for (let p = 0; p < 4; p += 1) await act(async () => { for (let i = 0; i < 40; i += 1) await Promise.resolve(); }); }
async function tick(ms: number, step = ms) {
  for (let done = 0; done < ms; done += step) {
    const d = Math.min(step, ms - done);
    // What happens inside a step is noted at the step's end.
    clock += d;
    await act(async () => { await vi.advanceTimersByTimeAsync(d); });
  }
  await drain();
}

// ---- the server ------------------------------------------------------------
function apply(intent: ProfilePatchIntent): ProfilePatchOutcome {
  const row = remote as unknown as Record<string, unknown>;
  const stored = Object.entries(intent.patch).every(([k, v]) => JSON.stringify(row[k]) === JSON.stringify(v));
  if (stored && (revision === intent.expectedRevision || revision === intent.expectedRevision + 1)) {
    return { status: 'already-saved', profile: structuredClone(row), revision };
  }
  if (intent.expectedRevision !== revision) return { status: 'conflict', profile: structuredClone(row), revision };
  remote = { ...remote, ...intent.patch } as ProfileData;
  revision += 1;
  return { status: 'saved', profile: structuredClone(remote) as unknown as Record<string, unknown>, revision };
}

// ---- per tab: network, navigator.onLine, auth, identity, coordinator --------
const net: Record<string, boolean> = {};
const onLine: Record<string, boolean> = {};
const auths: Record<string, ((state: { user: { id: string } | null }) => void) | null> = {};
const identities: Record<string, typeof import('@/lib/identity-owner')> = {};
const syncs: Record<string, typeof import('@/lib/profile-sync')> = {};

async function request<T>(tab: string, what: string, answer: () => T, offline: () => T): Promise<T> {
  const entry: Note = { at: clock, tab, what, detail: 'no answer yet' };
  notes.push(entry);
  if (!net[tab]) { entry.detail = 'failed: offline'; return offline(); }
  await new Promise((resolve) => { setTimeout(resolve, LATENCY_MS); });
  const out = answer() as unknown as { status?: string; revision?: number };
  entry.detail = `${out.status ?? 'row'}${typeof out.revision === 'number' ? ` rev ${out.revision}` : ''}, answered at +${LATENCY_MS} ms`;
  return out as unknown as T;
}
function transportFor(tab: string) {
  return {
    loadProfile: () => {
      const token = identities[tab].captureOwnerToken();
      return request<LoadedProfile>(tab, 'GET /rest/v1/profiles',
        () => ({ source: 'cloud', profile: structuredClone(remote) as unknown as Record<string, unknown>, revision, token }) as LoadedProfile,
        () => { throw new TypeError('Failed to fetch'); });
    },
    commitProfilePatch: (intent: ProfilePatchIntent) => request<ProfilePatchOutcome>(tab,
      `POST commit_profile_patch_cas {${Object.keys(intent.patch).sort().join(',')}} expected ${intent.expectedRevision}`,
      () => apply(intent), () => ({ status: 'transport-error', message: 'Failed to fetch' })),
    getStorageStatus: () => ({ status: 'synced', error: null }),
    onAuthChange: (callback: (state: { user: { id: string } | null }) => void) => {
      auths[tab] = callback;
      return () => { if (auths[tab] === callback) auths[tab] = null; };
    },
  };
}
/** React for one tab: unchanged, except that the save status and the profile
 *  check's status are noted every time they are set, with the call that set
 *  'error'. Setter identities stay stable. */
function reactFor(tab: string) {
  const wrapped = new WeakMap<object, (next: unknown) => void>();
  function useState(initial: unknown) {
    const [value, set] = React.useState(initial) as [unknown, (next: unknown) => void];
    const what = initial === 'idle' ? 'status' : initial === 'ready' ? 'check' : null;
    if (!what) return [value, set];
    let logged = wrapped.get(set);
    if (!logged) {
      logged = (next: unknown) => {
        if (typeof next === 'string') note(tab, what, next, what === 'status' && next === 'error' ? taggedFrames() : undefined);
        set(next);
      };
      wrapped.set(set, logged);
    }
    return [value, logged];
  }
  return { ...React, useState };
}

// ---- events and storage, routed per tab -------------------------------------
type Listener = EventListenerOrEventListenerObject;
const WINDOW_ROUTED = new Set(['storage', 'online', 'offline', 'focus']);
let listeners: Array<{ tab: string; type: string; fn: Listener }> = [];
let writer: string | null = null;
let deliver = true;
let logHeard = false;
let unattributed: string[] = [];
let strayOnLineReads = 0;
/** The tab whose reads of the journal's acknowledgements fail (a device failure). */
let journalUnreadableFor: string | null = null;
const realWinAdd = window.addEventListener;
const realWinRemove = window.removeEventListener;
const realDispatch = window.dispatchEvent;
const realDocAdd = document.addEventListener;
const realDocRemove = document.removeEventListener;
const realSet = localStorage.setItem;
const realGet = localStorage.getItem;
const realRemoveItem = localStorage.removeItem;
const call = (fn: Listener, event: Event) => { if (typeof fn === 'function') fn.call(window, event); else fn.handleEvent(event); };
const kindOf = (key: string | null) => (key === null ? 'cleared' : key.includes('ofe_profile_sync_v1') ? 'outbox'
  : key.includes('ofe_profile_journal_v1') ? 'journal' : 'other');
function route(key: string, oldValue: string | null, newValue: string | null) {
  if (oldValue === newValue) return;
  const from = tabOfStack() ?? writer;
  if (from === null) { unattributed.push(key); return; }
  if (!deliver) return;
  // Queued like the browser's task: never inside the writer's own call.
  queueMicrotask(() => {
    for (const { tab, type, fn } of [...listeners]) {
      if (type !== 'storage' || tab === from) continue;
      if (logHeard) note(tab, 'heard', `${from}'s ${kindOf(key)} write`);
      call(fn, new StorageEvent('storage', { key, oldValue, newValue }));
    }
  });
}
function fire(tab: Tab, type: 'online' | 'offline') {
  note(tab.name, 'event', type);
  act(() => { for (const l of [...listeners]) if (l.tab === tab.name && l.type === type) call(l.fn, new Event(type)); });
}

// Web Locks as the test setup supplies them: one lock manager for every tab,
// as in one browser.
type LockRequest = (name: string, optsOrFn: unknown, maybeFn?: unknown) => Promise<unknown>;
let realLockRequest: LockRequest | null = null;
/** Calls `granted` as each lock is granted, before its holder's code runs,
 *  with the tab that asked and the stack it asked from. */
function onLockGranted(granted: (tab: string | null, askedFrom: string) => void) {
  const locks = navigator.locks as unknown as { request: LockRequest };
  const real = locks.request;
  realLockRequest = real;
  locks.request = (name, optsOrFn, maybeFn) => {
    const fn = (typeof optsOrFn === 'function' ? optsOrFn : maybeFn) as () => unknown;
    const tab = tabOfStack();
    const askedFrom = stackNow();
    const run = () => { granted(tab, askedFrom); return fn(); };
    return typeof optsOrFn === 'function' ? real(name, run) : real(name, optsOrFn, run);
  };
}

type Form = ReturnType<typeof import('./use-profile-form').useProfileForm>;
type Tab = { name: string; seen: string[]; hook: ReturnType<typeof renderHook<Form, unknown>> };
/** A new tab: a fresh module realm with its own document, lineage and network. */
async function open(name: string): Promise<Tab> {
  writer = name;
  net[name] = true; onLine[name] = true;
  vi.resetModules();
  vi.doMock('react', () => reactFor(name));
  vi.doMock('@/lib/identity-owner', () => import(/* @vite-ignore */ `@/lib/identity-owner.ts?tab=${name}`));
  vi.doMock('@/lib/supabase', () => transportFor(name));
  vi.doMock('@/lib/profile-sync', async () => {
    const real = await import(/* @vite-ignore */ `@/lib/profile-sync.ts?tab=${name}`) as typeof import('@/lib/profile-sync');
    syncs[name] = real;
    return {
      ...real,
      flushPendingProfileWrite: (token: OwnerToken) => {
        // What storage holds as the flush starts: the shared outbox entry and the journal's operations.
        const outbox = real.readProfileSyncEnvelopeStrict();
        const ops = Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i)!)
          .filter((k) => k.includes('ofe_profile_journal_v1_op_')).length;
        const held = `outbox pending ${outbox.ok ? (outbox.value?.pending ? 'yes' : 'none') : 'unreadable'}, journal ops ${ops}`;
        const sent = real.flushPendingProfileWrite(token);
        sent.then((r) => note(name, 'flushPendingProfileWrite', `(${held}) -> ${JSON.stringify(r).slice(0, 60)}`),
          (e) => note(name, 'flushPendingProfileWrite', `threw ${String(e)}`));
        return sent;
      },
      refreshConflictQuestion: (...args: Parameters<typeof real.refreshConflictQuestion>) => {
        const read = real.refreshConflictQuestion(...args);
        read.then((r) => note(name, 'refreshConflictQuestion', `(${args[2] ?? 'repair'}) [${args[0].join(',')}] -> ${r.status}`
          + ('pendingKeys' in r ? `, pending [${(r.pendingKeys as string[]).join(',')}]` : '')), () => {});
        return read;
      },
    };
  });
  const identity = await import('@/lib/identity-owner');
  identity.advanceOwnerEpoch(uid); await identity.syncLocalIdentityOwner(uid);
  identities[name] = identity;
  const { useProfileForm } = await import(/* @vite-ignore */ `./use-profile-form.ts?tab=${name}`) as typeof import('./use-profile-form');
  // Every status the tab shows, in order.
  const seen: string[] = [];
  const hook = renderHook(() => {
    const form = useProfileForm(t);
    if (seen[seen.length - 1] !== form.saveStatus) seen.push(form.saveStatus);
    return form;
  });
  act(() => { auths[name]!({ user: { id: uid } }); }); await drain(); await tick(3000);
  writer = null;
  expect(hook.result.current.hydrationState).toBe('ready');
  return { name, seen, hook };
}
/** What `tab` does; its storage writes are told apart by the stack. */
async function as(tab: Tab, fn: (form: Form) => void, ms = 3000, step = ms) {
  writer = tab.name;
  act(() => { fn(tab.hook.result.current); });
  await tick(ms, step);
  writer = null;
  await drain();
}
/** That tab's page alone loses the network (CDP emulation in the live check). */
async function goOffline(tab: Tab) {
  net[tab.name] = false; onLine[tab.name] = false;
  fire(tab, 'offline');
  await tick(400);
}
function goOnline(tab: Tab) {
  net[tab.name] = true; onLine[tab.name] = true;
  fire(tab, 'online');
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  nav.params = new URLSearchParams();
  localStorage.clear(); sessionStorage.clear();
  sequence += 1; uid = `m136-repro-${sequence}`;
  remote = structuredClone(BASE); revision = 7; clock = 0; notes = [];
  for (const k of Object.keys(net)) delete net[k];
  for (const k of Object.keys(onLine)) delete onLine[k];
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', {
    configurable: true,
    get() {
      const tab = tabOfStack();
      if (tab === null) { strayOnLineReads += 1; return Object.values(onLine).every(Boolean); }
      return onLine[tab] ?? true;
    },
  });
  listeners = []; writer = null; deliver = true; logHeard = false; unattributed = []; strayOnLineReads = 0;
  journalUnreadableFor = null;
  window.addEventListener = function (this: Window, type: string, fn: Listener, opts?: boolean | AddEventListenerOptions) {
    if (!WINDOW_ROUTED.has(type)) return realWinAdd.call(this, type, fn, opts);
    const tab = tabOfStack();
    if (!tab) {
      if (type === 'storage') throw new Error('a storage listener registered outside any tab');
      return realWinAdd.call(this, type, fn, opts);
    }
    listeners.push({ tab, type, fn });
  } as typeof window.addEventListener;
  window.removeEventListener = function (this: Window, type: string, fn: Listener, opts?: boolean | EventListenerOptions) {
    const before = listeners.length;
    listeners = listeners.filter((l) => !(l.type === type && l.fn === fn));
    if (listeners.length === before) realWinRemove.call(this, type, fn, opts);
  } as typeof window.removeEventListener;
  // writeLocalStorageJSON's own 'storage' event reaches the writing tab only.
  window.dispatchEvent = function (this: Window, event: Event) {
    if (event.type !== 'storage') return realDispatch.call(this, event);
    const tab = tabOfStack();
    if (!tab) { unattributed.push(`synthetic ${(event as StorageEvent).key}`); return true; }
    for (const l of [...listeners]) if (l.type === 'storage' && l.tab === tab) call(l.fn, event);
    return true;
  } as typeof window.dispatchEvent;
  document.addEventListener = function (this: Document, type: string, fn: Listener, opts?: boolean | AddEventListenerOptions) {
    const tab = type === 'visibilitychange' ? tabOfStack() : null;
    if (!tab) return realDocAdd.call(this, type, fn, opts);
    listeners.push({ tab, type, fn });
  } as typeof document.addEventListener;
  document.removeEventListener = function (this: Document, type: string, fn: Listener, opts?: boolean | EventListenerOptions) {
    const before = listeners.length;
    listeners = listeners.filter((l) => !(l.type === type && l.fn === fn));
    if (listeners.length === before) realDocRemove.call(this, type, fn, opts);
  } as typeof document.removeEventListener;
  localStorage.setItem = (key: string, value: string) => {
    const old = realGet.call(localStorage, key); realSet(key, value); route(key, old, realGet.call(localStorage, key));
  };
  localStorage.getItem = (key: string) => {
    if (journalUnreadableFor !== null && key.includes('ofe_profile_journal_v1_ack') && tabOfStack() === journalUnreadableFor) {
      throw new DOMException('m136: storage read refused', 'SecurityError');
    }
    return realGet.call(localStorage, key);
  };
  localStorage.removeItem = (key: string) => {
    const old = realGet.call(localStorage, key); realRemoveItem(key); route(key, old, null);
  };
});
afterEach(async () => {
  writer = null; deliver = false; journalUnreadableFor = null;
  cleanup();
  // Lets every locked section a closed tab left finish, so none holds a lock into the next test.
  await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
  vi.clearAllTimers(); vi.useRealTimers();
  window.addEventListener = realWinAdd; window.removeEventListener = realWinRemove; window.dispatchEvent = realDispatch;
  document.addEventListener = realDocAdd; document.removeEventListener = realDocRemove;
  localStorage.setItem = realSet; localStorage.getItem = realGet; localStorage.removeItem = realRemoveItem;
  if (realLockRequest) { (navigator.locks as unknown as { request: LockRequest }).request = realLockRequest; realLockRequest = null; }
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});

function story(from: number, t0: number): string {
  return notes.slice(from).map((n) => `  ${String(n.at - t0).padStart(5)} ms  ${n.tab}  ${n.what} ${n.detail}`
    + (n.stack ? `\n        set by:\n        ${n.stack}` : '')).join('\n');
}
const posts = (tab: string, from: number) => notes.slice(from)
  .filter((n) => n.tab === tab && n.what.startsWith('POST')).map((n) => `${n.what}: ${n.detail}`);
const flushes = (tab: string, from: number) => notes.slice(from)
  .filter((n) => n.tab === tab && n.what === 'flushPendingProfileWrite').map((n) => n.detail);

type Kind = 'slider' | 'year';
/** Cases d and d2 up to the reconnect: both tabs offline, B's own edit fails,
 *  then A's name fails too, its save carrying B's edit. */
async function bothFailOffline(kind: Kind) {
  const a = await open('A');
  const b = await open('B');
  await goOffline(b);
  await goOffline(a);
  const edit = kind === 'slider' ? { search_weight: 30 } : { grade: 'Senior' };
  await as(b, (f) => (kind === 'slider' ? f.setSearchWeight(30) : f.update('grade', 'Senior')));
  expect(b.hook.result.current.saveStatus).toBe('cloud-failed');
  expect(b.hook.result.current.canRetrySync).toBe(true);
  await tick(2000);
  const fromOffline = notes.length;
  await as(a, (f) => f.update('name', NAME));
  expect(a.hook.result.current.saveStatus).toBe('cloud-failed');
  expect(a.hook.result.current.canRetrySync).toBe(true);
  // As live: A's failed save carried B's edit with its name (one shared outbox).
  const keys = Object.keys({ name: NAME, ...edit }).sort().join(',');
  expect(posts('A', fromOffline)).toEqual([`POST commit_profile_patch_cas {${keys}} expected 7: failed: offline`]);
  expect(b.hook.result.current.saveStatus).toBe('cloud-failed');
  await tick(6000);
  expect(remote).toMatchObject({ name: 'Alex', search_weight: 50, grade: 'Junior' });
  return { a, b, edit, keys };
}
/** As live: B's resend carried both tabs' edits and was applied. */
function expectBSavedBoth(b: Tab, from: number, keys: string, edit: Record<string, unknown>, told: string) {
  expect(posts('B', from), told).toEqual([`POST commit_profile_patch_cas {${keys}} expected 7: saved rev 8, answered at +${LATENCY_MS} ms`]);
  expect(remote, told).toMatchObject({ name: NAME, ...edit });
  expect(b.hook.result.current.canRetrySync, told).toBe(false);
}
/** What A shows now, and has shown and asked the server since `fromA` / `from`. */
function aNow(a: Tab, fromA: number, from: number) {
  return {
    aStatusAtEnd: a.hook.result.current.saveStatus,
    aRetrySync: a.hook.result.current.canRetrySync,
    aStatusesAfterReconnect: a.seen.slice(fromA),
    aRequestsAfterReconnect: notes.slice(from).filter((n) => n.tab === 'A' && /^(GET|POST)/.test(n.what)).map((n) => n.what),
  };
}
/** A's name is stored, so A says saved and offers no Retry. */
function expectASaved(end: ReturnType<typeof aNow>, told: string) {
  expect(end, `A after reconnecting (times from B's 'online'):\n${told}`).toEqual({
    aStatusAtEnd: expect.stringMatching(/^(saved|idle)$/),
    aRetrySync: false,
    aStatusesAfterReconnect: expect.not.arrayContaining(['error']),
    aRequestsAfterReconnect: expect.anything(),
  });
}
/** A says "Couldn't save your profile" with Retry sync, and never said saved. */
function expectAError(a: Tab, fromA: number, told: string) {
  const end = a.hook.result.current;
  expect({ status: end.saveStatus, retry: end.canRetrySync, shown: a.seen.slice(fromA) }, told)
    .toEqual({ status: 'error', retry: true, shown: expect.arrayContaining(['error']) });
  expect(a.seen.slice(fromA), told).not.toContain('saved');
}

/** A's network comes back the moment B's answer to its resend is granted the
 *  lock to be recorded, before B's code runs: A's reconnect resend reads the
 *  outbox while B's entry is still in it, then waits for the lock. */
function aOnlineWhileBRecordsItsAnswer(a: Tab, before?: () => void): () => boolean {
  let fired = false;
  onLockGranted((tab, askedFrom) => {
    if (fired || tab !== 'B' || !askedFrom.includes('withProfileReceiptState')) return;
    fired = true;
    before?.();
    net[a.name] = true; onLine[a.name] = true;
    note(a.name, 'event', "online (while B's answer holds the lock)");
    for (const l of listeners.filter((x) => x.tab === a.name && x.type === 'online')) call(l.fn, new Event('online'));
  });
  return () => fired;
}

describe('M136: a tab that reconnects after the other tab already sent its edit', () => {
  for (const [id, kind] of [['d', 'slider'], ['d2', 'year']] as const) {
    for (const gapMs of (process.env.M136_GAPS ?? '0,400,1179,2000').split(',').map(Number)) {
      it(`(${id}) B's ${kind} and A's name, both offline; B back first, A ${gapMs} ms later: A ends saved, no Retry`, async () => {
        const { a, b, edit, keys } = await bothFailOffline(kind);

        // Back online: B first, then A `gapMs` later.
        const from = notes.length; const fromA = a.seen.length; const t0 = clock;
        logHeard = true;
        // Each 'online' is followed by its own microtasks before time moves on;
        // with no gap both events come first, as near to one instant as two
        // pages get.
        goOnline(b);
        if (gapMs > 0) { await drain(); await tick(gapMs, 10); }
        goOnline(a);
        await drain();
        await tick(8000, 10);
        logHeard = false;
        const told = story(from, t0);
        const end = aNow(a, fromA, from);
        if (process.env.M136_STORY) {
          console.log(`(${id}) gap ${gapMs} ms\n${told}\nA shown: ${a.seen.slice(fromA).join(' > ')}`);
          if (end.aRetrySync) {
            const before = notes.length; const shown = a.seen.length;
            await as(a, (f) => f.retryCloudSave());
            console.log(`(${id}) gap ${gapMs} ms, then A presses Retry sync:\n${story(before, t0)}\nA shown: ${a.seen.slice(shown).join(' > ')}`);
          }
        }
        expectBSavedBoth(b, from, keys, edit, told);
        expect({ unattributed, strayOnLineReads }, told).toEqual({ unattributed: [], strayOnLineReads: 0 });
        expectASaved(end, told);
      });
    }
  }

  it("(d) A's 'online' while B's answer is being recorded: A's flush finds the entry, waits for B's lock, finds it gone; A ends saved", async () => {
    const { a, b, edit, keys } = await bothFailOffline('slider');
    const from = notes.length; const fromA = a.seen.length; const t0 = clock;
    const fired = aOnlineWhileBRecordsItsAnswer(a);
    logHeard = true;
    goOnline(b);
    await drain();
    await tick(8000, 10);
    logHeard = false;
    const told = story(from, t0);
    expect(fired(), told).toBe(true);
    expectBSavedBoth(b, from, keys, edit, told);
    expect({ unattributed, strayOnLineReads }, told).toEqual({ unattributed: [], strayOnLineReads: 0 });
    // The entry was still in the outbox when A's flush started, and A sent
    // nothing: the flush found it gone only once it had the lock, after B's
    // answer had emptied the outbox.
    expect(flushes('A', from), told).toEqual([expect.stringMatching(/^\(outbox pending yes, journal ops \d+\) -> \{"status":"blocked"\}$/)]);
    expect(posts('A', from), told).toEqual([]);
    expectASaved(aNow(a, fromA, from), told);
  });

  it("(d) A presses Retry sync, still offline, after B's resend saved both edits: A ends saved", async () => {
    const { a, b, edit, keys } = await bothFailOffline('slider');
    const from = notes.length; const t0 = clock;
    goOnline(b);
    await drain();
    await tick(400, 10);
    // B's answer is recorded; A has heard it, and M117's read is still to come.
    expect(a.hook.result.current.saveStatus).toBe('cloud-failed');
    expect(a.hook.result.current.canRetrySync).toBe(true);
    const fromA = a.seen.length;
    await as(a, (f) => f.retryCloudSave(), 5000, 10);
    const told = story(from, t0);
    expectBSavedBoth(b, from, keys, edit, told);
    expect(flushes('A', from), told).toEqual([expect.stringMatching(/^\(outbox pending none, journal ops \d+\) -> \{"status":"blocked"\}$/)]);
    expect(posts('A', from), told).toEqual([]);
    expectASaved(aNow(a, fromA, from), told);
  });
});

describe('M136: what still shows an error, or is still sent', () => {
  it("a device failure: A's journal cannot be read when it reconnects 400 ms after B, so its flush cannot read it either", async () => {
    const { a, b, edit, keys } = await bothFailOffline('slider');
    const from = notes.length; const t0 = clock;
    goOnline(b);
    await drain();
    await tick(400, 10);
    const fromA = a.seen.length;
    journalUnreadableFor = 'A';
    goOnline(a);
    await drain();
    await tick(8000, 10);
    const told = story(from, t0);
    expectBSavedBoth(b, from, keys, edit, told);
    expect(flushes('A', from), told).toEqual([expect.stringMatching(/-> \{"status":"device-failed","phase":"stage"\}$/)]);
    expectAError(a, fromA, told);
  });

  it("a device failure: A's journal cannot be read when its flush, having waited for B's lock, finds nothing to send", async () => {
    const { a, b, edit, keys } = await bothFailOffline('slider');
    const from = notes.length; const fromA = a.seen.length; const t0 = clock;
    const fired = aOnlineWhileBRecordsItsAnswer(a, () => { journalUnreadableFor = 'A'; });
    goOnline(b);
    await drain();
    await tick(8000, 10);
    const told = story(from, t0);
    expect(fired(), told).toBe(true);
    expectBSavedBoth(b, from, keys, edit, told);
    // The flush never reads the journal on this route: only what reads it
    // after the flush can tell that nothing is left to send, and it cannot.
    expect(flushes('A', from), told).toEqual([expect.stringMatching(/^\(outbox pending yes, journal ops \d+\) -> \{"status":"blocked"\}$/)]);
    expectAError(a, fromA, told);
  });

  it("every field in dispute between two tabs' school gates: A's Retry still shows an error, with nothing of the home form's left", async () => {
    const { a, b, edit, keys } = await bothFailOffline('slider');
    const from = notes.length; const t0 = clock;
    goOnline(b);
    await drain();
    await tick(300, 10);
    // B's resend saved both edits. Then each tab's school gate records a
    // different campus, neither staged: the journal holds only those two
    // operations, of another writer than the home form, and they disagree.
    for (const [tab, campus] of [['A', 'mit'], ['B', 'stanford']] as const) {
      const sync = syncs[tab];
      const row = sync.readProfileSyncEnvelope()!.confirmed!.profile;
      expect(sync.recordProfileIntent({ ...row, home_school: campus }, ['home_school'], identities[tab].captureOwnerToken(),
        { writer: sync.SCHOOL_WRITER })).toBe(true);
    }
    await tick(100, 10);
    const homeForm = syncs.A.getDirtyProfileKeys(identities.A.captureOwnerToken(), syncs.A.HOME_FORM_WRITER);
    expect(homeForm).toEqual({ ok: true, value: [] });
    expect(a.hook.result.current.canRetrySync).toBe(true);
    const fromA = a.seen.length;
    await as(a, (f) => f.retryCloudSave(), 5000, 10);
    const told = story(from, t0);
    expectBSavedBoth(b, from, keys, edit, told);
    expect(flushes('A', from), told).toEqual([expect.stringMatching(/^\(outbox pending none, journal ops 2\) -> \{"status":"blocked"\}$/)]);
    expect(posts('A', from), told).toEqual([]);
    expectAError(a, fromA, told);
  });

  it("A's own edit, which no other tab sent, is still sent when A reconnects 400 ms after B", async () => {
    const a = await open('A');
    const b = await open('B');
    await goOffline(b);
    await goOffline(a);
    await as(a, (f) => f.update('name', NAME));
    expect(a.hook.result.current.saveStatus).toBe('cloud-failed');
    expect(a.hook.result.current.canRetrySync).toBe(true);
    await tick(6000);
    const from = notes.length; const fromA = a.seen.length; const t0 = clock;
    goOnline(b);
    await drain();
    await tick(400, 10);
    goOnline(a);
    await drain();
    await tick(8000, 10);
    const told = story(from, t0);
    expect(posts('B', from), told).toEqual([]);
    expect(posts('A', from), told).toEqual([`POST commit_profile_patch_cas {name} expected 7: saved rev 8, answered at +${LATENCY_MS} ms`]);
    expect(remote, told).toMatchObject({ name: NAME, search_weight: 50, grade: 'Junior' });
    expectASaved(aNow(a, fromA, from), told);
  });
});
