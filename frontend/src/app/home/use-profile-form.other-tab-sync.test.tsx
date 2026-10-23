import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from '@/lib/supabase';
import type { ProfileData } from '@/lib/types';

const service = vi.hoisted(() => ({
  identity: null as null | typeof import('@/lib/identity-owner'),
  auths: [] as Array<(state: { user: { id: string } | null }) => void>,
  load: vi.fn<(token: unknown) => Promise<LoadedProfile>>(),
  commit: vi.fn<(intent: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>(),
  params: new URLSearchParams(), router: { push: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() },
}));
vi.mock('next/navigation', () => ({ useRouter: () => service.router, useSearchParams: () => service.params }));
vi.mock('@/lib/api', () => ({ parseGitHubProfile: vi.fn() }));
vi.mock('@/lib/match-cache', () => ({ clearMatchCache: vi.fn(() => true) }));
// The owner token as the newest realm captures it. The factory runs once per
// file, and both tabs of a test hold the same owner at the same epoch, so the
// token is the same value in either tab.
vi.mock('@/lib/supabase', () => ({
  loadProfile: () => service.load(service.identity!.captureOwnerToken()),
  commitProfilePatch: (intent: ProfilePatchIntent) => service.commit(intent),
  getStorageStatus: () => ({ status: 'synced', error: null }),
  onAuthChange: (callback: (state: { user: { id: string } | null }) => void) => {
    service.auths.push(callback);
    return () => { service.auths = service.auths.filter((c) => c !== callback); };
  },
}));
import { DEFAULT_PROFILE } from './types';

// Checklist M117. Two open tabs of one account, each its own module realm
// (coordinator, journal lane, lineage) over the same localStorage and Web
// Locks. As in a browser, a tab hears about the other's writes only through
// 'storage' events, and never about its own: every write is delivered to the
// listeners of the tabs that did not make it.
const BASE = { ...DEFAULT_PROFILE, name: 'Alex', home_school: 'uiuc', institution: 'UIUC', college: 'Engineering',
  major: 'Computer Science', grade: 'Junior', research_interests: 'Original research' } as unknown as ProfileData;
const t = (key: string) => key;
let remote: ProfileData;
let revision: number;
let online: boolean;
let uid: string;
let sequence = 0;
async function apply(intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> {
  if (!online) throw new Error('offline');
  if (intent.expectedRevision !== revision) return { status: 'conflict', profile: structuredClone(remote) as unknown as Record<string, unknown>, revision };
  remote = { ...remote, ...intent.patch } as ProfileData; revision += 1;
  return { status: 'saved', profile: structuredClone(remote) as unknown as Record<string, unknown>, revision };
}
const storedKeys = () => Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i)!).sort();
async function drain() { for (let p = 0; p < 4; p += 1) await act(async () => { for (let i = 0; i < 40; i += 1) await Promise.resolve(); }); }
async function tick(ms: number) { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); await drain(); }

// Storage events, routed per tab.
type Listener = EventListenerOrEventListenerObject;
let storageListeners: Array<{ tab: string; fn: Listener }> = [];
let registering: string | null = null;
let lastRemoved: string | null = null;
let writer: string | null = null;
let deliver = true;
let unattributed: string[] = [];
let delivered: Record<string, number> = {};
const realAdd = window.addEventListener;
const realRemove = window.removeEventListener;
// The suite's storage is a plain object (see test-setup), patched directly.
const realSet = localStorage.setItem;
const realRemoveItem = localStorage.removeItem;
function route(key: string, oldValue: string | null, newValue: string | null) {
  if (oldValue === newValue) return;
  if (writer === null) { unattributed.push(key); return; }
  if (!deliver) return;
  const from = writer;
  // Queued like the browser's task: never inside the writer's own call.
  queueMicrotask(() => {
    for (const { tab, fn } of [...storageListeners]) {
      if (tab === from) continue;
      delivered[tab] = (delivered[tab] ?? 0) + 1;
      const event = new StorageEvent('storage', { key, oldValue, newValue });
      if (typeof fn === 'function') fn.call(window, event); else fn.handleEvent(event);
    }
  });
}

type Tab = { name: string; seen: string[]; hook: ReturnType<typeof renderHook<ReturnType<typeof import('./use-profile-form').useProfileForm>, unknown>> };
/** A new tab: a fresh module realm with its own document and lineage. */
async function open(name: string): Promise<Tab> {
  writer = name;
  vi.resetModules();
  const identity = await import('@/lib/identity-owner');
  identity.advanceOwnerEpoch(uid); await identity.syncLocalIdentityOwner(uid);
  service.identity = identity;
  const { useProfileForm } = await import('./use-profile-form');
  registering = name;
  // Every status the tab shows, in order.
  const seen: string[] = [];
  const hook = renderHook(() => {
    const form = useProfileForm(t);
    if (seen[seen.length - 1] !== form.saveStatus) seen.push(form.saveStatus);
    return form;
  });
  const auth = service.auths[service.auths.length - 1];
  act(() => { auth({ user: { id: uid } }); }); await drain(); await tick(3000);
  registering = null; writer = null;
  expect(hook.result.current.hydrationState).toBe('ready');
  return { name, seen, hook };
}
/** What `tab` does, with every storage write it makes delivered to the others. */
async function as(tab: Tab, fn: (form: Tab['hook']['result']['current']) => void, ms = 3000) {
  writer = tab.name;
  act(() => { fn(tab.hook.result.current); });
  await tick(ms);
  writer = null;
  await drain();
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  service.auths = []; service.params = new URLSearchParams();
  localStorage.clear(); sessionStorage.clear();
  sequence += 1; uid = `other-tab-sync-${sequence}`;
  remote = structuredClone(BASE); revision = 7; online = true;
  service.load.mockReset().mockImplementation(async (token) => ({ source: 'cloud', profile: structuredClone(remote) as unknown as Record<string, unknown>, revision, token: token as LoadedProfile['token'] }));
  service.commit.mockReset().mockImplementation(apply);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
  storageListeners = []; registering = null; lastRemoved = null; writer = null; deliver = true; unattributed = []; delivered = {};
  window.addEventListener = function (this: Window, type: string, fn: Listener, opts?: boolean | AddEventListenerOptions) {
    if (type !== 'storage') return realAdd.call(this, type, fn, opts);
    const tab = registering ?? lastRemoved;
    if (!tab) throw new Error('a storage listener registered outside any tab');
    storageListeners.push({ tab, fn });
  } as typeof window.addEventListener;
  window.removeEventListener = function (this: Window, type: string, fn: Listener, opts?: boolean | EventListenerOptions) {
    if (type !== 'storage') return realRemove.call(this, type, fn, opts);
    const found = storageListeners.find((l) => l.fn === fn);
    if (found) lastRemoved = found.tab;
    storageListeners = storageListeners.filter((l) => l.fn !== fn);
  } as typeof window.removeEventListener;
  localStorage.setItem = (key: string, value: string) => {
    const old = localStorage.getItem(key); realSet(key, value); route(key, old, localStorage.getItem(key));
  };
  localStorage.removeItem = (key: string) => {
    const old = localStorage.getItem(key); realRemoveItem(key); route(key, old, null);
  };
});
afterEach(async () => {
  writer = null; deliver = false;
  cleanup();
  // Lets every locked section a closed tab left finish, so none holds a lock into the next test.
  await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
  vi.clearAllTimers(); vi.useRealTimers();
  window.addEventListener = realAdd; window.removeEventListener = realRemove;
  localStorage.setItem = realSet; localStorage.removeItem = realRemoveItem;
});

/** Both tabs typed different research interests offline; each has the question. */
async function twoTabsDisagree() {
  const a = await open('A');
  const b = await open('B');
  online = false;
  await as(a, (f) => f.update('research_interests', 'From tab A'));
  await as(b, (f) => f.update('research_interests', 'From tab B'));
  online = true;
  // Each tab's own retry asks it the question the journal holds.
  await as(a, (f) => f.retryCloudSave());
  await as(b, (f) => f.retryCloudSave());
  expect(a.hook.result.current.conflicts.map((q) => q.key)).toEqual(['research_interests']);
  expect(b.hook.result.current.conflicts.map((q) => q.key)).toEqual(['research_interests']);
  return { a, b };
}

describe('another tab\'s answer and saves reach this tab without a reload (M117)', () => {
  it('(a) this tab\'s own saved edit says saved, not "NOT saved", after the other tab answered the question', async () => {
    const { a, b } = await twoTabsDisagree();
    // Not even the storage events are needed: the save itself must not be
    // judged against a question the shared state no longer holds.
    deliver = false;
    await as(a, (f) => f.keepMyChanges());
    expect(remote.research_interests).toBe('From tab A');
    const from = b.seen.length;
    await as(b, (f) => f.update('grade', 'Senior'));
    expect(remote.grade).toBe('Senior');
    expect(b.seen.slice(from)).toContain('saved');
    expect(b.seen.slice(from)).not.toContain('conflict');
    expect(b.hook.result.current.conflicts).toEqual([]);
    expect(b.hook.result.current.profile.research_interests).toBe('From tab A');
  });

  it('(b) a question answered in the other tab leaves this tab, which shows the kept value', async () => {
    const { a, b } = await twoTabsDisagree();
    const loads = service.load.mock.calls.length;
    const commits = service.commit.mock.calls.length;
    await as(a, (f) => f.keepMyChanges());
    expect(remote.research_interests).toBe('From tab A');
    const sent = service.commit.mock.calls.length;
    await tick(1000);
    expect(b.hook.result.current.conflicts).toEqual([]);
    expect(b.hook.result.current.profile.research_interests).toBe('From tab A');
    expect(b.hook.result.current.saveStatus).not.toBe('conflict');
    // From storage alone: no read, and nothing sent by this tab.
    expect(service.load.mock.calls.length).toBe(loads);
    expect(service.commit.mock.calls.length).toBe(sent);
    expect(sent).toBeGreaterThan(commits);
  });

  it('(c) an edit the other tab already sent stops saying "Couldn\'t save"', async () => {
    const a = await open('A');
    const b = await open('B');
    online = false;
    await as(b, (f) => f.update('grade', 'Senior'));
    expect(b.hook.result.current.saveStatus).toBe('cloud-failed');
    online = true;
    await as(a, (f) => f.update('name', 'Alex Kim'));
    expect(remote).toMatchObject({ grade: 'Senior', name: 'Alex Kim' });
    const loads = service.load.mock.calls.length;
    await tick(1000);
    expect(b.hook.result.current.saveStatus).toBe('saved');
    expect(b.hook.result.current.canRetrySync).toBe(false);
    expect(service.load.mock.calls.length).toBe(loads);
    expect(unattributed).toEqual([]);
  });

  it('(d) an edit of this tab\'s still unsent keeps saying "Couldn\'t save" when the other tab writes', async () => {
    const a = await open('A');
    const b = await open('B');
    await as(b, (f) => f.update('grade', 'Senior'));
    expect(remote.grade).toBe('Senior');
    online = false;
    // The slider is not a field the form keeps among its edited fields.
    await as(b, (f) => f.setSearchWeight(90));
    expect(b.hook.result.current.saveStatus).toBe('cloud-failed');
    const from = b.seen.length;
    const heard = delivered.B ?? 0;
    await as(a, (f) => f.update('name', 'Alex Kim'));
    await tick(2000);
    expect(delivered.B ?? 0).toBeGreaterThan(heard);
    expect(remote.search_weight).toBe(50);
    expect(b.seen.slice(from)).not.toContain('saved');
    expect(b.hook.result.current.saveStatus).toBe('cloud-failed');
    expect(b.hook.result.current.canRetrySync).toBe(true);
  });

  it('(e) a slider move the other tab already sent stops saying "Couldn\'t save"', async () => {
    const a = await open('A');
    const b = await open('B');
    online = false;
    await as(b, (f) => f.setSearchWeight(90));
    expect(b.hook.result.current.saveStatus).toBe('cloud-failed');
    online = true;
    await as(a, (f) => f.update('name', 'Alex Kim'));
    expect(remote).toMatchObject({ search_weight: 90, name: 'Alex Kim' });
    const sent = service.commit.mock.calls.length;
    await tick(2000);
    expect(b.hook.result.current.saveStatus).toBe('saved');
    expect(b.hook.result.current.canRetrySync).toBe(false);
    expect(b.hook.result.current.searchWeight).toBe(b.hook.result.current.profile.search_weight);
    expect(service.commit.mock.calls.length).toBe(sent);
  });

  it('(f) a tab whose slider move was saved starts no save when the other tab moves the slider', async () => {
    const a = await open('A');
    const b = await open('B');
    await as(b, (f) => f.setSearchWeight(90));
    expect(remote.search_weight).toBe(90);
    online = false;
    await as(a, (f) => f.setSearchWeight(30));
    await tick(5000);
    expect(b.seen).toEqual(['idle', 'saving', 'saved', 'idle']);
    expect(b.hook.result.current.searchWeight).toBe(b.hook.result.current.profile.search_weight);
  });
});

/** Locked reads of the profile storage from here on. The typing tab takes the
 *  lock only when its save fires, so in the windows below every one is the
 *  listening tab's read. */
function countReads() {
  let reads = 0;
  const locks = navigator.locks.request.bind(navigator.locks) as (...args: unknown[]) => Promise<unknown>;
  vi.spyOn(navigator.locks, 'request').mockImplementation(((...args: unknown[]) => {
    if (args[0] === 'ofe-profile-local-storage') reads += 1;
    return locks(...args);
  }) as typeof navigator.locks.request);
  return () => reads;
}

describe('reads made for another tab\'s writes (M117)', () => {
  it('are bounded: a burst of the other tab\'s writes reads at most once a second, plus one', async () => {
    const { a } = await twoTabsDisagree();
    const reads = countReads();
    const before = delivered.B ?? 0;
    // Eight changes 500 ms apart, each its own journal write; the 1.5 s
    // autosave does not fire until the typing stops.
    writer = 'A';
    for (let i = 1; i <= 8; i += 1) {
      act(() => { a.hook.result.current.update('name', `Alex ${'K'.repeat(i)}`); });
      await tick(i === 8 ? 1400 : 500);
    }
    writer = null;
    const writes = (delivered.B ?? 0) - before;
    expect(writes).toBeGreaterThanOrEqual(8);
    // The writes span 3.5 s: at most ceil(3500 / 1000) + 1 reads.
    expect(reads()).toBeGreaterThanOrEqual(1);
    expect(reads()).toBeLessThanOrEqual(5);
  });

  it('are harmless for a tab of an earlier build: no request, nothing written, the question kept while it is open', async () => {
    const { a, b } = await twoTabsDisagree();
    const loads = service.load.mock.calls.length;
    const commits = service.commit.mock.calls.length;
    // A tab of the previous build appends an edit of another field, as its
    // code writes one; it has no listener of its own.
    writer = 'older';
    const opId = crypto.randomUUID();
    const journalKey = storedKeys().find((k) => k.includes('ofe_profile_journal_v1_op_'))!;
    const prefix = journalKey.slice(0, journalKey.indexOf('op_'));
    localStorage.setItem(`${prefix}op_${opId}`, JSON.stringify({
      opId, originId: 'older-document', lineage: 'older-tab', seq: 1, clock: 99, baseRevision: 7, writer: 'home-form', mode: 'set',
      fields: [{ key: 'major', base: { present: true, value: 'Computer Science' }, desired: { present: true, value: 'Physics' } }],
    }));
    writer = null;
    const stored = JSON.stringify(storedKeys().map((k) => [k, localStorage.getItem(k)]));
    const reads = countReads();
    writer = 'B';
    await tick(1500);
    writer = null;
    // One read in each of the two open tabs, which both heard the write.
    expect(reads()).toBe(2);
    expect(JSON.stringify(storedKeys().map((k) => [k, localStorage.getItem(k)]))).toBe(stored);
    expect(service.load.mock.calls.length).toBe(loads);
    expect(service.commit.mock.calls.length).toBe(commits);
    for (const tab of [a, b]) {
      expect(tab.hook.result.current.conflicts.map((q) => q.key)).toEqual(['research_interests']);
      expect(tab.hook.result.current.saveStatus).toBe('conflict');
    }
  });
});

describe('a question still open when another tab writes (M137)', () => {
  it('keeps the value this tab typed in the field, and this tab starts no save of the other tab\'s value', async () => {
    const a = await open('A');
    const b = await open('B');
    online = false;
    await as(a, (f) => f.update('research_interests', 'From tab A'));
    expect(a.hook.result.current.saveStatus).toBe('cloud-failed');
    const seenFrom = a.seen.length;
    // Tab B types its own value; its writes reach tab A, which reads the
    // question again and finds it open.
    await as(b, (f) => f.update('research_interests', 'From tab B'));
    await tick(2000);
    expect({
      field: a.hook.result.current.profile.research_interests,
      asked: a.hook.result.current.conflicts.map((q) => q.key),
      seen: a.seen.slice(seenFrom),
    }).toEqual({ field: 'From tab A', asked: ['research_interests'], seen: [] });
    expect(b.hook.result.current.profile.research_interests).toBe('From tab B');
  });

  /** The browser going off or on line, as every tab's window hears it. */
  function network(on: boolean, who: string | null) {
    online = on;
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: on });
    writer = who;
    act(() => { window.dispatchEvent(new Event(on ? 'online' : 'offline')); });
    writer = null;
  }
  /** Time passing, with `who` as the tab behind anything written meanwhile. */
  async function wait(ms: number, who: string | null = null) { writer = who; await tick(ms); writer = null; await drain(); }
  async function close(tab: Tab) { writer = tab.name; act(() => { tab.hook.unmount(); }); await tick(500); writer = null; await drain(); }
  const course = (name: string, status?: string) => ({ name, source: 'manual', ...(status ? { status } : {}) });
  const names = (list: unknown) => ((list ?? []) as Array<{ name: string }>).map((c) => c.name);
  const RESUME_AND_COURSES = ['courses', 'coursework', 'experience_entries', 'resume_master', 'resume_text'];
  const withCourses = () => {
    remote = { ...remote, coursework: ['CS 124'], courses: [course('CS 124')], resume_text: '' } as unknown as ProfileData;
  };
  const experience = { id: 'exp-1', revision: 1, status: 'confirmed', text: 'Built a robot arm controller', source: { kind: 'manual' } };
  /** An entry added on the Experience Library card: the whole résumé is sent with it, from the form. */
  function addExperience(form: Tab['hook']['result']['current']) {
    const p = form.profile;
    return form.handleExperienceChange([experience] as never, { resumeText: p.resume_text ?? '', entriesJson: JSON.stringify(p.experience_entries ?? []) });
  }

  it('offline, a course-list question learned from the other tab is asked whole, and the first "Keep what I typed" answers it', async () => {
    withCourses();
    const a = await open('A');
    const b = await open('B');
    network(false, null);
    await wait(1500);
    await as(a, (f) => f.update('courses', [course('CS 124'), course('CS 173')] as never));
    await as(b, (f) => f.update('courses', [course('CS 124'), course('CS 225')] as never));
    await wait(2000);
    // The course names are one unit with the résumé, so the question holds
    // all of it, as the answer will write it; the list stays as tab A drew it.
    expect(a.hook.result.current.conflicts.map((q) => q.key).sort()).toEqual(RESUME_AND_COURSES);
    expect(names(a.hook.result.current.profile.courses)).toEqual(['CS 124', 'CS 173']);
    await as(a, (f) => f.keepMyChanges());
    await wait(2000);
    expect({ shown: names(a.hook.result.current.profile.courses), askedInB: b.hook.result.current.conflicts })
      .toEqual({ shown: ['CS 124', 'CS 173'], askedInB: [] });
    network(true, 'A');
    await wait(4000, 'A');
    expect(names(remote.courses)).toEqual(['CS 124', 'CS 173']);
  });

  it('after the other tab keeps its résumé and course list, this tab shows all of it, and its next experience edit sends nothing it drew before', async () => {
    withCourses();
    const a = await open('A');
    const b = await open('B');
    network(false, null);
    await wait(1500);
    // Tab A marks a status, which writes the course list alone; tab B puts in
    // a résumé and a course from it.
    await as(a, (f) => f.update('courses', [course('CS 124', 'completed')] as never, 'status'));
    await as(b, (f) => f.update('resume_text', 'NEW RESUME: CS 124, CS 225'));
    await as(b, (f) => f.update('courses', [course('CS 124'), { name: 'CS 225', source: 'resume' }] as never));
    await wait(2000);
    // The network returns while neither tab is in front: no load, no resend.
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    network(true, null);
    await wait(1000);
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    await as(b, (f) => f.retryCloudSave());
    await as(b, (f) => f.keepMyChanges());
    await wait(3000);
    expect(remote.resume_text).toBe('NEW RESUME: CS 124, CS 225');
    const p = a.hook.result.current.profile;
    expect({ resume: p.resume_text, coursework: p.coursework, courses: names(p.courses) })
      .toEqual({ resume: 'NEW RESUME: CS 124, CS 225', coursework: ['CS 124', 'CS 225'], courses: ['CS 124', 'CS 225'] });
    let accepted = false;
    await as(a, (f) => { accepted = addExperience(f); });
    await wait(3000);
    expect({ accepted, resume: remote.resume_text, coursework: remote.coursework, entries: (remote.experience_entries ?? []).length })
      .toEqual({ accepted: true, resume: 'NEW RESUME: CS 124, CS 225', coursework: ['CS 124', 'CS 225'], entries: 1 });
  });

  it('a second "Keep what I typed" made offline, with the other tab closed, leaves the answer to send when the network returns', async () => {
    const a = await open('A');
    const b = await open('B');
    network(false, null);
    await wait(1500);
    await as(a, (f) => f.update('research_interests', 'From tab A'));
    await as(b, (f) => f.update('research_interests', 'From tab B'));
    await wait(2000);
    await close(b);
    // Offline, the answer is written down and not sent, and the question
    // stays on screen; pressed again, it is found answered.
    await as(a, (f) => f.keepMyChanges());
    expect(a.hook.result.current.conflicts.map((q) => q.key)).toEqual(['research_interests']);
    await as(a, (f) => f.keepMyChanges());
    await wait(2000);
    expect({ status: a.hook.result.current.saveStatus, retry: a.hook.result.current.canRetrySync, asked: a.hook.result.current.conflicts })
      .toEqual({ status: 'cloud-failed', retry: true, asked: [] });
    expect(remote.research_interests).toBe('Original research');
    network(true, 'A');
    await wait(4000, 'A');
    expect({ stored: remote.research_interests, retry: a.hook.result.current.canRetrySync })
      .toEqual({ stored: 'From tab A', retry: false });
  });

  it('an answer refused because the other tab answered first does not say "Couldn\'t save" for that tab\'s unsent edit', async () => {
    const a = await open('A');
    const b = await open('B');
    online = false;
    await as(a, (f) => f.update('research_interests', 'From tab A'));
    await as(b, (f) => f.update('research_interests', 'From tab B'));
    online = true;
    await as(a, (f) => f.retryCloudSave());
    await wait(3000, 'A');
    await as(b, (f) => f.retryCloudSave());
    await wait(3000, 'B');
    // Tab A hears nothing more, so its question stays on screen.
    deliver = false;
    await as(b, (f) => f.keepMyChanges());
    expect(remote.research_interests).toBe('From tab B');
    online = false;
    await as(b, (f) => f.update('grade', 'Senior'));
    await as(a, (f) => f.keepMyChanges());
    expect({ status: a.hook.result.current.saveStatus, retry: a.hook.result.current.canRetrySync, asked: a.hook.result.current.conflicts })
      .toEqual({ status: 'conflict-gone', retry: false, asked: [] });
  });

  it('beside its own unsent course edit, shows the other tab\'s résumé once it is saved and not before, and its next experience edit keeps it', async () => {
    withCourses();
    const a = await open('A');
    const b = await open('B');
    network(false, null);
    await wait(1500);
    await as(a, (f) => f.update('courses', [course('CS 124', 'completed')] as never, 'status'));
    const seenFrom = a.seen.length;
    await as(b, (f) => f.update('resume_text', 'From tab B'));
    await wait(2000);
    // Unsent, it is tab B's alone: nothing of it is drawn here, and no save starts.
    expect({ resume: a.hook.result.current.profile.resume_text, seen: a.seen.slice(seenFrom) })
      .toEqual({ resume: '', seen: [] });
    // Back online with no event: tab B's next edit sends everything unsent.
    online = true;
    await as(b, (f) => f.update('grade', 'Senior'));
    await wait(3000, 'B');
    expect(remote.resume_text).toBe('From tab B');
    expect(a.hook.result.current.profile.resume_text).toBe('From tab B');
    await as(a, (f) => { addExperience(f); });
    await wait(3000, 'A');
    expect({ resume: remote.resume_text, entries: (remote.experience_entries ?? []).length })
      .toEqual({ resume: 'From tab B', entries: 1 });
  });

  describe('with nothing of the résumé unsent or asked in this tab, after the other tab saves one (M147)', () => {
    /** Offline, tab A leaves `unsent` outside the résumé; back online with no
     *  event, tab B saves a résumé, then tab A adds an experience entry. */
    async function addAfterOtherTabsResume(unsent: (a: Tab, b: Tab) => Promise<void>, resume = 'Resume saved by B', withEntry = false) {
      withCourses();
      const a = await open('A');
      const b = await open('B');
      online = false;
      await unsent(a, b);
      await wait(2000);
      online = true;
      await as(b, (f) => f.update('resume_text', resume), withEntry ? 100 : 3000);
      // In the same save, tab B adds an experience entry of its own.
      if (withEntry) await as(b, (f) => { f.handleExperienceChange([{ ...experience, id: 'exp-B' }] as never, { resumeText: resume, entriesJson: '[]' }); });
      await wait(3000, 'B');
      expect(remote.resume_text).toBe(resume);
      let accepted = false;
      // Added to the entries the card shows.
      await as(a, (f) => {
        const shown = f.profile.experience_entries ?? [];
        accepted = f.handleExperienceChange([...shown, experience] as never, { resumeText: f.profile.resume_text ?? '', entriesJson: JSON.stringify(shown) });
      });
      await wait(3000, 'A');
      const p = a.hook.result.current.profile;
      return { accepted, stored: remote.resume_text, entries: (remote.experience_entries ?? []).length, shown: p.resume_text };
    }
    const kept = (resume = 'Resume saved by B') => ({ accepted: true, stored: resume, entries: 1, shown: resume });

    it('an open research-interests question: the experience edit keeps the other tab\'s résumé', async () => {
      expect(await addAfterOtherTabsResume(async (a, b) => {
        await as(a, (f) => f.update('research_interests', 'From tab A'));
        await as(b, (f) => f.update('research_interests', 'From tab B'));
      })).toEqual(kept());
    });

    it('an unsent slider move: the experience edit keeps the other tab\'s résumé', async () => {
      expect(await addAfterOtherTabsResume(async (a) => {
        await as(a, (f) => f.setSearchWeight(30));
      })).toEqual(kept());
    });

    it('an unsent grade: the experience edit keeps the other tab\'s résumé', async () => {
      expect(await addAfterOtherTabsResume(async (a) => {
        await as(a, (f) => f.update('grade', 'Senior'));
      })).toEqual(kept());
    });

    it('an unsent course status: the experience edit keeps the other tab\'s résumé', async () => {
      expect(await addAfterOtherTabsResume(async (a) => {
        await as(a, (f) => f.update('courses', [course('CS 124', 'completed')] as never, 'status'));
      })).toEqual(kept());
    });

    it('a grade the other tab sent with its résumé: the experience edit keeps the résumé', async () => {
      expect(await addAfterOtherTabsResume(async (a) => {
        await as(a, (f) => f.update('grade', 'Senior'));
        await wait(2000, 'A');
        expect(a.hook.result.current.saveStatus).toBe('cloud-failed');
      }, 'From tab B')).toEqual(kept('From tab B'));
      expect(remote.grade).toBe('Senior');
    });

    it('an unsent grade, and an experience entry saved with the other tab\'s résumé: this tab\'s entry is added beside it', async () => {
      expect(await addAfterOtherTabsResume(async (a) => {
        await as(a, (f) => f.update('grade', 'Senior'));
      }, 'Resume saved by B', true)).toEqual({ ...kept(), entries: 2 });
      expect((remote.experience_entries ?? []).map((e) => e.id).sort()).toEqual(['exp-1', 'exp-B']);
    });
  });
});
