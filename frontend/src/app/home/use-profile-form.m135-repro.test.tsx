// Checklist M135. The live check of 2026-10-18 22:47Z (X3 m113, a guest on
// joinalab.com, production df1289b4), through the form itself: two tabs of
// one browser, both at revision 1 showing Grainger / Computer Science /
// Junior. Offline, tab 1 picks LAS (the major clears) and Mathematics; tab 2
// picks Gies (the major clears), Finance and Senior: five journal operations.
// Back online tab 2 is asked, and one "Keep what I typed" there stores Gies /
// Finance / Senior in one commit — but all five operations stayed in the
// journal of both tabs, and the next college edit in tab 1 was asked about
// again although no other device exists.
//
// Why: each tab's college switch also clears the additional majors, which
// the answer does not decide, so two tabs' operations held that field and
// nothing counted them as finished although both wanted what the row held.
// The answer then stayed a chain of its own, and the next college edit was
// asked against it. Only an acknowledgement settles such a closure, unless
// the tab's own lineage answered: nothing else can tell whether an answer's
// response is still on its way. What an earlier build already left that way
// therefore stays when the row loads: the next edit of such a field is asked
// once, and that answer settles it all.
//
// Each tab is its own module realm (vi.resetModules, as in
// profile-sync.question-grouping.test.ts): its own form, coordinator, journal
// lane, lineage and owner capability, over the one localStorage and the one
// set of Web Locks, with the one window's online, offline and focus events.
// A reload is a new realm of the same tab: it keeps the tab's lineage, as a
// browser reload keeps the tab's session storage (jsdom has one for both).
// Only the transport is mocked; the server is one row with a compare-and-set
// on its revision. What an earlier build's tabs left is written as that
// build wrote it, through a realm with no form.
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { OwnerToken } from '@/lib/identity-owner';
import type { JournalField, JournalOp } from '@/lib/profile-journal';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from '@/lib/supabase';
import type { ProfileData } from '@/lib/types';
import type { UseProfileFormResult } from './use-profile-form';
import { DEFAULT_PROFILE } from './types';

type Observe = (state: { user: { id: string } | null }) => void;
/** One tab's copy of the transport: what it reads is answered with its own
 *  owner token, and what it sends is filed under its name. `test`: the test
 *  that opened the tab. */
interface Transport { label: string; test: number; capture: (() => OwnerToken) | null; observe: Observe | null }

const service = vi.hoisted(() => ({
  load: vi.fn<(label: string, token: OwnerToken | undefined) => Promise<LoadedProfile>>(),
  commit: vi.fn<(label: string, intent: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>(),
  params: new URLSearchParams(), router: { push: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() },
}));
vi.mock('next/navigation', () => ({ useRouter: () => service.router, useSearchParams: () => service.params }));
vi.mock('@/lib/api', () => ({ parseGitHubProfile: vi.fn() }));
vi.mock('@/lib/match-cache', () => ({ clearMatchCache: vi.fn(() => true) }));
// The transport is mocked per tab (vi.doMock in openTab): a vi.mock factory's
// module is kept across vi.resetModules, so every realm would share one. A
// tab a finished test left behind (its unmount flush, a request a failing
// test never released) reaches no later test's server.
function mockTransport(transport: Transport) {
  const current = () => transport.test === sequence;
  vi.doMock('@/lib/supabase', () => ({
    loadProfile: () => (current() ? service.load(transport.label, transport.capture?.())
      : Promise.reject(new Error('net::ERR_INTERNET_DISCONNECTED'))),
    getDeviceId: async () => transport.capture?.().uid ?? null,
    commitProfilePatch: (intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> => (current()
      ? service.commit(transport.label, intent)
      : Promise.resolve({ status: 'transport-error', message: 'net::ERR_INTERNET_DISCONNECTED' })),
    getStorageStatus: () => ({ status: 'synced', error: null }),
    onAuthChange: (observe: Observe) => {
      transport.observe = observe;
      return () => { if (transport.observe === observe) transport.observe = null; };
    },
  }));
}

const GRAINGER = 'Grainger College of Engineering';
const LAS = 'Liberal Arts & Sciences (LAS)';
const GIES = 'Gies College of Business';
const START: ProfileData = {
  ...DEFAULT_PROFILE, name: 'Synthetic guest', college: GRAINGER, major: 'Computer Science', grade: 'Junior',
  research_interests: 'robotics',
};
const KEPT = { college: GIES, major: 'Finance', grade: 'Senior' };
const t = (key: string) => key;

let sequence = 0;
let uid: string;
let row: { revision: number; profile: Record<string, unknown> };
let offline: boolean;
/** The server is reachable for reads and refuses every write in transit. */
let writesFail: boolean;
/** Every request the tabs sent, as the live check's commit log has them. */
interface Sent {
  tab: string; expected: number; keys: string[]; values: Record<string, unknown>;
  status: 'failed' | 'conflict' | 'applied'; revision?: number;
  /** The journal operations the outbox entry being sent had captured. */
  carried: string[];
}
let sent: Sent[];

interface Tab {
  label: string;
  identity: typeof import('@/lib/identity-owner');
  sync: typeof import('@/lib/profile-sync');
  journal: typeof import('@/lib/profile-journal');
  transport: Transport;
  form: () => UseProfileFormResult;
  unmount: () => void;
}
const tabs = new Map<string, Tab>();

// Each way of a request takes this long, so requests issued together are in
// flight together: back online, production's resend and both tabs' profile
// reads went out in the same moment (the resend still carrying the year and
// the cleared additional majors).
const LEG_MS = 60;
const leg = () => new Promise<void>((resolve) => { setTimeout(resolve, LEG_MS); });

// A request still on its way when its test ends (the unmount flush runs
// after it, on real timers) reaches no later test's row.
async function read(_label: string, token: OwnerToken | undefined): Promise<LoadedProfile> {
  const test = sequence;
  if (offline) throw new Error('net::ERR_INTERNET_DISCONNECTED');
  await leg();
  if (test !== sequence) throw new Error('net::ERR_INTERNET_DISCONNECTED');
  const loaded: LoadedProfile = { source: 'cloud', profile: structuredClone(row.profile), revision: row.revision, token: token! };
  await leg();
  return loaded;
}
async function serve(label: string, intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> {
  const test = sequence;
  const pending = tabs.get(label)?.sync.readProfileSyncEnvelope()?.pending ?? null;
  const entry: Sent = {
    tab: label, expected: intent.expectedRevision, keys: Object.keys(intent.patch).sort(),
    values: structuredClone(intent.patch), status: 'failed',
    carried: pending?.mutationId === intent.mutationId ? [...pending.journalOpIds] : [],
  };
  sent.push(entry);
  if (offline) return { status: 'transport-error', message: 'net::ERR_INTERNET_DISCONNECTED' };
  if (writesFail) return { status: 'transport-error', message: 'net::ERR_CONNECTION_RESET' };
  await leg();
  if (test !== sequence) return { status: 'transport-error', message: 'net::ERR_INTERNET_DISCONNECTED' };
  let outcome: ProfilePatchOutcome;
  if (intent.expectedRevision !== row.revision) {
    entry.status = 'conflict';
    outcome = { status: 'conflict', revision: row.revision, profile: structuredClone(row.profile) };
  } else {
    const next = { ...row.profile };
    for (const [k, v] of Object.entries(intent.patch)) { if (v === undefined) delete next[k]; else next[k] = structuredClone(v); }
    row = { revision: row.revision + 1, profile: next };
    entry.status = 'applied'; entry.revision = row.revision;
    outcome = { status: 'saved', revision: row.revision, profile: structuredClone(next) };
  }
  await leg();
  return outcome;
}

async function drain() {
  for (let pass = 0; pass < 4; pass += 1) {
    await act(async () => { for (let i = 0; i < 40; i += 1) await Promise.resolve(); });
  }
}
async function tick(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); await drain();
}

/** A tab opened on Home: a new module realm, signed in as the guest. With
 *  `reloadOf`, the same tab reloaded: its session storage still names its
 *  lineage and that lineage's last sequence number. */
async function openTab(label: string, reloadOf?: { lineage: string; seq: number }): Promise<Tab> {
  vi.resetModules();
  const transport: Transport = { label, test: sequence, capture: null, observe: null };
  mockTransport(transport);
  const identity = await import('@/lib/identity-owner');
  identity.advanceOwnerEpoch(uid);
  expect(await identity.syncLocalIdentityOwner(uid)).toBe(true);
  transport.capture = identity.captureOwnerToken;
  const journal = await import('@/lib/profile-journal');
  if (reloadOf) {
    sessionStorage.setItem('ofe_profile_journal_v1_lineage', reloadOf.lineage);
    sessionStorage.setItem('ofe_profile_journal_v1_lineage_seq', String(reloadOf.seq));
    journal.startDocumentForTests('reload');
    expect(journal.getJournalLineageId(), `${label} reloaded keeps its lineage`).toBe(reloadOf.lineage);
  }
  const sync = await import('@/lib/profile-sync');
  const { useProfileForm } = await import('./use-profile-form');
  const hook = renderHook(() => useProfileForm(t));
  const tab: Tab = {
    label, identity, sync, journal, transport, form: () => hook.result.current, unmount: () => hook.unmount(),
  };
  tabs.set(label, tab);
  expect(transport.observe, `${label} listens to the session`).not.toBeNull();
  act(() => { transport.observe!({ user: { id: uid } }); });
  await drain(); await tick(3000);
  expect(tab.form().hydrationState, `${label} loaded the row`).toBe('ready');
  return tab;
}

/** The tab reloaded: the page goes, and the same tab loads Home again. */
async function reloadTab(tab: Tab): Promise<Tab> {
  const lineage = tab.journal.getJournalLineageId();
  const seq = Math.max(0, ...outstanding(tab).filter((op) => op.lineage === lineage).map((op) => op.seq));
  tab.unmount();
  await drain();
  return openTab(tab.label, { lineage, seq });
}

/** The browser goes off or on line: every tab hears it, as in a browser. */
function network(on: boolean) {
  offline = !on;
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: on });
  act(() => { window.dispatchEvent(new Event(on ? 'online' : 'offline')); });
}
/** A select on the form, then the live check's 600 ms pause. */
async function choose(tab: Tab, key: 'college' | 'major' | 'grade', value: string) {
  act(() => { tab.form().update(key, value); });
  await tick(600);
}

const academic = (p: Partial<ProfileData> | Record<string, unknown>) => {
  const r = p as Record<string, unknown>;
  return { college: r.college, major: r.major, grade: r.grade };
};
const asked = (tab: Tab) => tab.form().conflicts.map((c) => c.key).sort();
/** This browser's outstanding operations, through the tab's own reader. */
function outstanding(tab: Tab): JournalOp[] {
  const ops = tab.journal.readOutstandingOps();
  if (!ops.ok) throw new Error(`${tab.label} could not read the journal: ${ops.reason}`);
  return ops.value;
}
/** The keys the tab's form still has to get confirmed, from its own coordinator. */
function owedKeys(tab: Tab): string[] | string {
  const dirty = tab.sync.getDirtyProfileKeys(tab.identity.captureOwnerToken(), tab.sync.HOME_FORM_WRITER);
  return dirty.ok ? [...dirty.value].sort() : `unreadable: ${dirty.reason}`;
}
/** One line per operation: whose, what kind, which fields. */
function described(ops: readonly JournalOp[]): string[] {
  const whose = (lineage: string) => {
    for (const tab of tabs.values()) if (tab.journal.getJournalLineageId() === lineage) return tab.label;
    return 'another lineage';
  };
  return ops.map((op) => `${whose(op.lineage)} ${op.mode === 'resolve' ? 'answer' : 'edit'} of ${
    op.fields.map((f) => f.key).sort().join(' + ')}`).sort();
}
/** Operation keys in storage, counted as the live check counts them. */
function opKeysInStorage(): number {
  let n = 0;
  for (let i = 0; i < localStorage.length; i += 1) {
    if (localStorage.key(i)?.includes('ofe_profile_journal_v1_op_')) n += 1;
  }
  return n;
}
/** What the journal's keys in storage are, by kind, and the version of each
 *  rebase receipt: what an earlier build reading this storage meets. */
function journalStorage(): { kinds: string[]; receiptVersions: unknown[] } {
  const kinds = new Set<string>();
  const receiptVersions: unknown[] = [];
  for (let i = 0; i < localStorage.length; i += 1) {
    const key = localStorage.key(i) ?? '';
    const rest = key.split('ofe_profile_journal_v1_')[1];
    if (rest === undefined) continue;
    const kind = rest.startsWith('op_') ? 'op' : rest.startsWith('rebase_') ? 'rebase receipt' : rest;
    kinds.add(kind);
    if (kind === 'rebase receipt') receiptVersions.push((JSON.parse(localStorage.getItem(key)!) as { v: unknown }).v);
  }
  return { kinds: [...kinds].sort(), receiptVersions };
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  service.params = new URLSearchParams();
  tabs.clear();
  sequence += 1;
  uid = `m135-repro-guest-${sequence}`;
  row = { revision: 1, profile: structuredClone(START) as unknown as Record<string, unknown> };
  offline = false;
  writesFail = false;
  sent = [];
  service.load.mockReset().mockImplementation(read);
  service.commit.mockReset().mockImplementation(serve);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

/**
 * The live check up to the answer, with its checks: both tabs at revision 1;
 * offline edits in both; back online tab 2 is asked and its year goes out; one
 * answer in tab 2 ("Keep what I typed" stores Gies / Finance / Senior in one
 * commit; "Use the other version" sends nothing); both tabs reloaded and 65 s
 * later neither is asked and both show the stored row. Returns the reloaded
 * tabs.
 */
async function answeredOnceInTab2(answer: 'keep' | 'other' = 'keep') {
  const tab1 = await openTab('tab 1');
  const tab2 = await openTab('tab 2');
  // Two realms, two transports, two lineages: the harness really has two tabs.
  expect(tab2.transport.observe).not.toBe(tab1.transport.observe);
  expect(tab2.journal).not.toBe(tab1.journal);
  expect(tab2.journal.getJournalLineageId()).not.toBe(tab1.journal.getJournalLineageId());
  for (const tab of [tab1, tab2]) {
    expect({ revision: tab.form().viewSnapshot?.revision, ...academic(tab.form().profile), asked: asked(tab) }, `start, ${tab.label}`)
      .toEqual({ revision: 1, college: GRAINGER, major: 'Computer Science', grade: 'Junior', asked: [] });
  }
  expect(outstanding(tab1), 'start: nothing pending').toEqual([]);

  network(false);
  await tick(1500);
  await choose(tab1, 'college', LAS);
  expect(tab1.form().profile.major, 'tab 1: the college change clears the major').toBe('');
  await choose(tab1, 'major', 'Mathematics');
  await choose(tab2, 'college', GIES);
  expect(tab2.form().profile.major, 'tab 2: the college change clears the major').toBe('');
  await choose(tab2, 'major', 'Finance');
  await choose(tab2, 'grade', 'Senior');
  await tick(4000);
  // Tab 1's own screen and sends here are another tab's read (M117, since
  // production c10e5db7), which this file is not about.
  expect({
    ops: opKeysInStorage(),
    tab1: { asked: asked(tab1) },
    tab2: { form: academic(tab2.form().profile), status: tab2.form().saveStatus },
    sent: sent.filter((s) => s.tab === 'tab 2').map((s) => [s.tab, s.expected, s.keys, s.status]),
  }, 'offline').toEqual({
    ops: 5,
    tab1: { asked: ['college', 'major'] },
    tab2: { form: KEPT, status: 'cloud-failed' },
    sent: [['tab 2', 1, ['additional_majors', 'grade'], 'failed']],
  });

  const atOnline = sent.length;
  network(true);
  await tick(1000);
  expect({
    tab1: asked(tab1), tab2: asked(tab2),
    sent: sent.slice(atOnline).map((s) => [s.tab, s.expected, s.keys, s.status, s.revision]),
  }, 'back online').toEqual({
    tab1: ['college', 'major'], tab2: ['college', 'major'],
    sent: [['tab 2', 1, ['additional_majors', 'grade'], 'applied', 2]],
  });

  const atAnswer = sent.length;
  act(() => { if (answer === 'keep') tab2.form().keepMyChanges(); else tab2.form().useCloudVersion(); });
  await tick(3000);
  const sentAnswer = sent.slice(atAnswer);
  const stored = answer === 'keep' ? KEPT : { college: GRAINGER, major: 'Computer Science', grade: 'Senior' };
  expect({
    sent: sentAnswer.map((s) => [s.tab, s.expected, s.keys, s.values.college, s.values.major, s.status, s.revision]),
    asked: asked(tab2), form: academic(tab2.form().profile),
  }, `one "${answer === 'keep' ? 'Keep what I typed' : 'Use the other version'}" in tab 2`).toEqual({
    sent: answer === 'keep' ? [['tab 2', 2, ['college', 'major'], GIES, 'Finance', 'applied', 3]] : [],
    asked: [], form: stored,
  });

  // As the live check went on: both tabs reloaded (the asker first), then 65 s.
  const reloaded2 = await reloadTab(tab2);
  const reloaded1 = await reloadTab(tab1);
  await tick(65_000);
  const revision = answer === 'keep' ? 3 : 2;
  for (const tab of [reloaded1, reloaded2]) {
    expect({ asked: asked(tab), form: academic(tab.form().profile), revision: tab.form().viewSnapshot?.revision }, `${tab.label}, reloaded and 65 s later`)
      .toEqual({ asked: [], form: stored, revision });
  }
  expect({ revision: row.revision, ...academic(row.profile) }, 'the stored row').toEqual({ revision, ...stored });
  return { tab1: reloaded1, tab2: reloaded2, carried: sentAnswer[0]?.carried ?? [] };
}

/** The live check's restore: the tab puts the college back, which clears the
 *  major, and picks the major again. */
async function restoreCollege(tab: Tab) {
  const before = sent.length;
  await choose(tab, 'college', GRAINGER);
  await choose(tab, 'major', 'Computer Science');
  await tick(4000);
  return {
    asked: asked(tab),
    status: tab.form().saveStatus,
    stored: academic(row.profile),
    sent: sent.slice(before).map((s) => [s.expected, s.keys, s.status]),
    journal: described(outstanding(tab)),
  };
}

/**
 * Tabs of the build before M135, as far as storage goes: a realm with no
 * form reads the row (the envelope its last acknowledgement recorded) and
 * appends what those tabs left after the answer, as they wrote it (the live
 * check's journal): each tab's college switch, which clears the major and the
 * additional majors, and its major, then tab 2's answer deciding college and
 * major for all four. `extra` is appended after them, by tab 2.
 */
async function earlierBuildLeftovers(
  lineages: { tab1: string; tab2: string },
  { majorsBefore = [] as string[], extra = null as null | { supersedesCollege: boolean; fields: JournalField[] } } = {},
): Promise<void> {
  vi.resetModules();
  const transport: Transport = { label: 'earlier build', test: sequence, capture: null, observe: null };
  mockTransport(transport);
  const identity = await import('@/lib/identity-owner');
  identity.advanceOwnerEpoch(uid);
  expect(await identity.syncLocalIdentityOwner(uid)).toBe(true);
  transport.capture = identity.captureOwnerToken;
  const journal = await import('@/lib/profile-journal');
  const sync = await import('@/lib/profile-sync');
  const loaded = sync.hydrateProfile();
  await tick(1000);
  await loaded;
  const token = identity.captureOwnerToken();
  const append = (lineage: string, op: Omit<JournalOp, 'opId' | 'seq' | 'clock' | 'originId' | 'lineage'>) => {
    const written = journal.appendJournalOp({ ...op, lineage, originId: `${lineage}-document` }, token);
    expect(written, 'the earlier build\'s operation is on disk').not.toBeNull();
    return written!.opId;
  };
  const field = (key: string, from: unknown, to: unknown): JournalField => (
    { key, base: { present: true, value: from }, desired: { present: true, value: to } });
  const edit = (lineage: string, fields: JournalField[], supersedes?: string) => append(lineage, {
    fields, baseRevision: 1, writer: sync.HOME_FORM_WRITER, mode: 'set', ...(supersedes ? { supersedes: [supersedes] } : {}),
  });
  const college1 = edit(lineages.tab1, [field('college', GRAINGER, LAS), field('major', 'Computer Science', ''), field('additional_majors', majorsBefore, [])]);
  const major1 = edit(lineages.tab1, [field('major', 'Computer Science', 'Mathematics')], college1);
  const college2 = edit(lineages.tab2, [field('college', GRAINGER, GIES), field('major', 'Computer Science', ''), field('additional_majors', majorsBefore, [])]);
  const major2 = edit(lineages.tab2, [field('major', 'Computer Science', 'Finance')], college2);
  append(lineages.tab2, {
    fields: [field('college', GRAINGER, GIES), field('major', 'Computer Science', 'Finance')],
    baseRevision: 2, writer: 'default', mode: 'resolve', resolves: [college1, major1, college2, major2],
    decisions: { college: 'local', major: 'local' },
  });
  if (extra) edit(lineages.tab2, extra.fields, extra.supersedesCollege ? college2 : undefined);
}

/** Two tabs at revision 1. Offline, tab 1 picks LAS and Mathematics, tab 2
 *  Gies, Finance and Senior; back online both are asked about the college
 *  and the major, and tab 2's resend has stored the year (revision 2). */
async function disagreeOffline() {
  const tab1 = await openTab('tab 1');
  const tab2 = await openTab('tab 2');
  network(false);
  await tick(1500);
  await choose(tab1, 'college', LAS);
  await choose(tab1, 'major', 'Mathematics');
  await choose(tab2, 'college', GIES);
  await choose(tab2, 'major', 'Finance');
  await choose(tab2, 'grade', 'Senior');
  await tick(4000);
  network(true);
  await tick(1000);
  expect({ tab1: asked(tab1), tab2: asked(tab2), stored: { revision: row.revision, ...academic(row.profile) } }, 'back online')
    .toEqual({ tab1: ['college', 'major'], tab2: ['college', 'major'], stored: { revision: 2, college: GRAINGER, major: 'Computer Science', grade: 'Senior' } });
  return { tab1, tab2 };
}

/** The response to tab 2's "Keep what I typed" (Gies / Finance) is held after
 *  the server stored it, until `release`. */
function holdAnswerResponse() {
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  let stored = false;
  service.commit.mockImplementation(async (label, intent) => {
    const outcome = await serve(label, intent);
    if (label === 'tab 2' && intent.patch.college === GIES) { stored = true; await held; }
    return outcome;
  });
  return { release: () => release(), stored: () => stored };
}

/** Two reads of the row, each tab's (a focus reaches every tab here). */
async function twoLoads() {
  for (let i = 0; i < 2; i += 1) {
    act(() => { window.dispatchEvent(new Event('focus')); });
    await tick(1000);
  }
}

// Every test opens two to four module realms of the coordinator and the
// form, the first of them while the worker still compiles them: 1.3 s on a
// busy machine, and once over the default 5 s.
describe('two tabs offline each change college and major; one "Keep what I typed" settles it (M135, production X3 m113)', { timeout: 20_000 }, () => {
  it('leaves no operation of either tab pending for the answered fields, nor any the answer\'s commit carried', async () => {
    const { tab1, tab2, carried } = await answeredOnceInTab2();
    expect(carried.length, 'the answer\'s commit carried journal operations').toBeGreaterThan(0);
    for (const tab of [tab1, tab2]) {
      const ops = outstanding(tab);
      expect({
        forCollegeOrMajor: described(ops.filter((op) => op.fields.some((f) => f.key === 'college' || f.key === 'major'))),
        carriedByTheAnswer: described(ops.filter((op) => carried.includes(op.opId))),
        owedByTheForm: owedKeys(tab),
      }, `${tab.label} reads its journal after the answer was confirmed`).toEqual({
        forCollegeOrMajor: [], carriedByTheAnswer: [], owedByTheForm: [],
      });
    }
  });

  it('saves a later college edit in tab 1 (and the major it clears, picked again) without a question', async () => {
    const { tab1 } = await answeredOnceInTab2();
    expect(await restoreCollege(tab1), 'tab 1 after the later college edit').toEqual({
      asked: [],
      status: expect.stringMatching(/^(saved|idle)$/),
      stored: { college: GRAINGER, major: 'Computer Science', grade: 'Senior' },
      sent: expect.anything(),
      journal: expect.anything(),
    });
  });

  it('leaves nothing pending after "Use the other version" in tab 2, which sends nothing', async () => {
    const { tab1, tab2 } = await answeredOnceInTab2('other');
    for (const tab of [tab1, tab2]) {
      expect({ journal: described(outstanding(tab)), owed: owedKeys(tab) }, `${tab.label} after the answer`)
        .toEqual({ journal: [], owed: [] });
    }
  });

  it('settles everything when both tabs picked Gies and only the major was asked (check 0)', async () => {
    const tab1 = await openTab('tab 1');
    const tab2 = await openTab('tab 2');
    network(false);
    await tick(1500);
    await choose(tab1, 'college', GIES);
    await choose(tab1, 'major', 'Accountancy');
    await choose(tab2, 'college', GIES);
    await choose(tab2, 'major', 'Finance');
    await tick(4000);
    network(true);
    await tick(1000);
    expect({ tab1: asked(tab1), tab2: asked(tab2) }, 'back online: the major alone is asked').toEqual({
      tab1: ['major'], tab2: ['major'],
    });
    // Both tabs resend the college and the cleared additional majors; the
    // answer is given in the tab whose resend was stored. (The other tab's
    // question stays bound to the revision it was asked at, checklist M134's
    // family, which is not this one.)
    const stored = sent.filter((s) => s.status === 'applied');
    expect(stored.map((s) => [s.expected, s.keys, s.revision]), 'the resend stored').toEqual([
      [1, ['additional_majors', 'college'], 2],
    ]);
    const answering = stored[0].tab === 'tab 1' ? tab1 : tab2;
    const kept = answering === tab1 ? 'Accountancy' : 'Finance';
    const atAnswer = sent.length;
    act(() => { answering.form().keepMyChanges(); });
    await tick(3000);
    expect(sent.slice(atAnswer).map((s) => [s.tab, s.expected, s.keys, s.status, s.revision]), 'the answer')
      .toEqual([[answering.label, 2, ['major'], 'applied', 3]]);
    const reloaded2 = await reloadTab(tab2);
    const reloaded1 = await reloadTab(tab1);
    await tick(65_000);
    for (const tab of [reloaded1, reloaded2]) {
      expect({ journal: described(outstanding(tab)), owed: owedKeys(tab), asked: asked(tab) }, `${tab.label}, reloaded and 65 s later`)
        .toEqual({ journal: [], owed: [], asked: [] });
    }
    expect(academic(row.profile)).toEqual({ college: GIES, major: kept, grade: 'Junior' });
    expect(await restoreCollege(reloaded1), 'tab 1 after the later college edit').toMatchObject({
      asked: [], stored: { college: GRAINGER, major: 'Computer Science', grade: 'Junior' }, journal: [],
    });
  });

  for (const editing of ['tab 1', 'tab 2'] as const) {
    it(`leaves at load what the build before left after the answer, and asks the next college edit in ${editing === 'tab 1' ? 'the other tab' : 'the answering tab'} once, after which nothing is left`, async () => {
      // As the live check left the browser: the answer stored at revision 3,
      // and both tabs' college and major edits and the answer still journaled.
      row = { revision: 3, profile: { ...structuredClone(START), ...KEPT } as unknown as Record<string, unknown> };
      const lineages = { tab1: `m135-tab-1-${sequence}`, tab2: `m135-tab-2-${sequence}` };
      await earlierBuildLeftovers(lineages);
      expect(opKeysInStorage(), 'what the build before left').toBe(5);
      // The deploy: both tabs reloaded onto this build (the asker first), then 65 s.
      const tab2 = await openTab('tab 2', { lineage: lineages.tab2, seq: 5 });
      const tab1 = await openTab('tab 1', { lineage: lineages.tab1, seq: 2 });
      await tick(65_000);
      for (const tab of [tab1, tab2]) {
        expect({ ops: outstanding(tab).length, asked: asked(tab), form: academic(tab.form().profile) },
          `${tab.label}, reloaded and 65 s later: no load settles them`).toEqual({ ops: 5, asked: [], form: KEPT });
      }
      expect(sent, 'nothing is sent').toEqual([]);
      // What they cost: the next college edit is asked once, and nothing is stored.
      const tab = editing === 'tab 1' ? tab1 : tab2;
      expect(await restoreCollege(tab), `${editing}'s next college edit`).toMatchObject({
        asked: ['college', 'major'], stored: KEPT,
      });
      const atKeep = sent.length;
      act(() => { tab.form().keepMyChanges(); });
      await tick(4000);
      expect({
        asked: asked(tab), journal: described(outstanding(tab)), owed: owedKeys(tab),
        stored: { revision: row.revision, ...academic(row.profile) },
        stores: sent.slice(atKeep).filter((s) => s.status === 'applied').map((s) => [s.expected, s.keys]),
      }, `one "Keep what I typed" in ${editing}`).toEqual({
        asked: [], journal: [], owed: [],
        stored: { revision: 4, college: GRAINGER, major: 'Computer Science', grade: 'Senior' },
        stores: [[3, ['college', 'major']]],
      });
      const atNext = sent.length;
      await choose(tab, 'college', LAS);
      await choose(tab, 'major', 'Mathematics');
      await tick(4000);
      expect({
        asked: asked(tab), journal: described(outstanding(tab)), stored: academic(row.profile),
        sent: sent.slice(atNext).map((s) => [s.expected, s.status]),
      }, `${editing}'s edit after that`).toEqual({
        asked: [], journal: [], stored: { college: LAS, major: 'Mathematics', grade: 'Senior' }, sent: [[4, 'applied']],
      });
    });
  }

  it('leaves at an open tab\'s next load what an older-build tab left after its answer, and asks that tab\'s next college edit once (mixed builds)', async () => {
    // This build's tab is open at the revision tab 2's resend stored.
    row = { revision: 2, profile: { ...structuredClone(START), grade: 'Senior' } as unknown as Record<string, unknown> };
    const tab3 = await openTab('tab 3');
    // Two tabs of the build before: the answer is stored at revision 3, and
    // that build's acknowledgement leaves all five operations.
    row = { revision: 3, profile: { ...structuredClone(START), ...KEPT } as unknown as Record<string, unknown> };
    await earlierBuildLeftovers({ tab1: `m135-older-1-${sequence}`, tab2: `m135-older-2-${sequence}` });
    // The next load of this build's tab: the window comes back into focus.
    act(() => { window.dispatchEvent(new Event('focus')); });
    await tick(3000);
    expect({
      ops: outstanding(tab3).length, asked: asked(tab3),
      form: academic(tab3.form().profile), revision: tab3.form().viewSnapshot?.revision, sent,
    }, 'tab 3 after its next load').toEqual({ ops: 5, asked: [], form: KEPT, revision: 3, sent: [] });
    expect(await restoreCollege(tab3), 'tab 3\'s next college edit').toMatchObject({
      asked: ['college', 'major'], stored: KEPT, sent: [],
    });
    act(() => { tab3.form().keepMyChanges(); });
    await tick(4000);
    expect({ asked: asked(tab3), journal: described(outstanding(tab3)), stored: academic(row.profile) }, 'one answer in tab 3')
      .toEqual({ asked: [], journal: [], stored: { college: GRAINGER, major: 'Computer Science', grade: 'Senior' } });
    // At most v1 rebase receipts are left, which the older build's tabs read.
    const left = journalStorage();
    expect({ kinds: left.kinds.filter((k) => k !== 'rebase receipt'), versions: [...new Set(left.receiptVersions)].filter((v) => v !== 1) },
      'the journal in storage').toEqual({ kinds: [], versions: [] });
  });

  it('leaves to a write in flight what it carries: a load meanwhile settles none of it, and the next edit is sent, not asked (a guard; already so before M135)', async () => {
    // Passes before M135 too, whose loads settle nothing: kept so a settle at
    // load stays caught.
    const tab1 = await openTab('tab 1');
    // The year is stored at once and its answer is held.
    let answer!: () => void;
    const answered = new Promise<void>((resolve) => { answer = resolve; });
    service.commit.mockImplementation(async (label, intent) => {
      const outcome = await serve(label, intent);
      if (intent.patch.grade === 'Senior') await answered;
      return outcome;
    });
    await choose(tab1, 'grade', 'Senior');
    await tick(2000);
    expect(sent.map((s) => [s.expected, s.keys, s.status, s.revision]), 'in flight').toEqual([[1, ['grade'], 'applied', 2]]);
    // Meanwhile the tab reads the row, which already holds the year.
    act(() => { window.dispatchEvent(new Event('focus')); });
    await tick(1000);
    expect({ revision: tab1.form().viewSnapshot?.revision, journal: described(outstanding(tab1)) }, 'read while in flight')
      .toEqual({ revision: 2, journal: ['tab 1 edit of grade'] });
    await choose(tab1, 'grade', 'Masters');
    act(() => { answer(); });
    await tick(4000);
    expect({
      asked: asked(tab1), status: tab1.form().saveStatus, journal: described(outstanding(tab1)),
      sent: sent.map((s) => [s.expected, s.keys, s.status, s.revision]), stored: row.profile.grade,
    }, 'after the answer and the next edit').toEqual({
      asked: [], status: expect.stringMatching(/^(saved|idle)$/), journal: [],
      sent: [[1, ['grade'], 'applied', 2], [2, ['grade'], 'applied', 3]], stored: 'Masters',
    });
  });

  it('never settles operations that want what the row does not hold: the cleared additional majors are sent first', async () => {
    // The student had an additional major, which both college switches
    // clear; the answer reached the row and the cleared additional majors did
    // not.
    row = {
      revision: 3,
      profile: { ...structuredClone(START), additional_majors: ['Statistics'], ...KEPT } as unknown as Record<string, unknown>,
    };
    const lineages = { tab1: `m135-tab-1-${sequence}`, tab2: `m135-tab-2-${sequence}` };
    await earlierBuildLeftovers(lineages, { majorsBefore: ['Statistics'] });
    writesFail = true;
    const tab2 = await openTab('tab 2', { lineage: lineages.tab2, seq: 5 });
    await tick(4000);
    expect({
      journal: described(outstanding(tab2)), owed: owedKeys(tab2),
      stored: row.profile.additional_majors, status: tab2.form().saveStatus,
      sent: sent.map((s) => [s.keys, s.status]),
    }, 'loaded while the write cannot reach the row').toEqual({
      journal: [
        'tab 2 answer of college + major',
        'tab 2 edit of additional_majors + college + major',
        'tab 2 edit of major',
        'another lineage edit of additional_majors + college + major',
        'another lineage edit of major',
      ].sort(),
      owed: ['additional_majors', 'college', 'major'],
      stored: ['Statistics'],
      status: 'cloud-failed',
      sent: [[['additional_majors', 'college', 'major'], 'failed']],
    });
    writesFail = false;
    network(true);
    await tick(4000);
    expect({
      journal: described(outstanding(tab2)), owed: owedKeys(tab2), asked: asked(tab2),
      stored: { ...academic(row.profile), additional_majors: row.profile.additional_majors },
    }, 'once the cleared additional majors are stored').toEqual({
      journal: [], owed: [], asked: [], stored: { ...KEPT, additional_majors: [] },
    });
  });

  it('never settles a field one of whose several owners wants another value: it stays a question (a guard; already so before M135)', async () => {
    // Passes before M135 too, which settled no field several operations
    // owned: kept so a settle of one that is still disputed stays caught.
    // As above, but tab 2 put the additional major back after its college
    // switch, which the answer does not decide: tab 1 still wants it cleared.
    row = {
      revision: 3,
      profile: { ...structuredClone(START), additional_majors: ['Statistics'], ...KEPT } as unknown as Record<string, unknown>,
    };
    const lineages = { tab1: `m135-tab-1-${sequence}`, tab2: `m135-tab-2-${sequence}` };
    await earlierBuildLeftovers(lineages, {
      majorsBefore: ['Statistics'],
      extra: { supersedesCollege: true, fields: [{ key: 'additional_majors', base: { present: true, value: ['Statistics'] }, desired: { present: true, value: ['Statistics'] } }] },
    });
    const tab2 = await openTab('tab 2', { lineage: lineages.tab2, seq: 6 });
    await tick(65_000);
    expect({
      journal: described(outstanding(tab2)).length, asked: asked(tab2), sent,
      stored: row.profile.additional_majors,
    }, 'tab 2, loaded and 65 s later').toEqual({
      journal: 6, asked: ['additional_majors'], sent: [], stored: ['Statistics'],
    });
  });
});

// A load settles nothing, and another tab settles an answered closure only
// in an acknowledgement. An operation can belong to a tab that is still open
// — inside its 1.5 s autosave pause, or with its write in flight — and that
// tab goes on from the edit base it holds in memory; and an answer's response
// can still be on its way when a load has already dropped its outbox entry,
// or when another tab's save finds nothing left to send (review of M135,
// rounds 1 and 2). Another tab's acknowledgement can still settle it while
// that response is out, which these tests do not cover.
describe('no load settles an open tab\'s edit, nor a load or another tab\'s save with nothing to send an answer whose response is still out (M135)', { timeout: 20_000 }, () => {
  it('leaves a pick another tab\'s load meets inside the autosave pause, so the next pick of the year is sent, not asked (a guard; already so before M135)', async () => {
    // Passes before M135 too, whose loads settle nothing: kept so a settle at
    // load stays caught.
    const tabA = await openTab('tab A');
    const tabB = await openTab('tab B');
    // Another device stores the year tab A is about to pick.
    row = { revision: 2, profile: { ...structuredClone(row.profile), grade: 'Senior' } };
    act(() => { tabA.form().update('grade', 'Senior'); });
    // Tab B's own read of the row (its focus or its 60 s read) while tab A's
    // autosave waits.
    const loading = tabB.sync.hydrateProfile();
    await tick(300);
    await loading;
    expect(described(outstanding(tabA)), 'tab A\'s pick after tab B\'s load').toEqual(['tab A edit of grade']);
    await tick(4000);
    const before = sent.length;
    await choose(tabA, 'grade', 'Masters');
    await tick(4000);
    expect({
      asked: asked(tabA), status: tabA.form().saveStatus, stored: row.profile.grade,
      sent: sent.slice(before).map((s) => [s.tab, s.expected, s.keys, s.status]),
    }, 'tab A\'s next pick').toEqual({
      asked: [], status: expect.stringMatching(/^(saved|idle)$/), stored: 'Masters', sent: [['tab A', 2, ['grade'], 'applied']],
    });
  });

  it('leaves a pick a third tab\'s load meets inside the autosave pause, so another tab\'s later change of the year is asked about, not written over (a guard; already so before M135)', async () => {
    // Passes before M135 too, whose loads settle nothing: kept so a settle at
    // load stays caught.
    const tabA = await openTab('tab A');
    const tabB = await openTab('tab B');
    await choose(tabB, 'grade', 'Senior');
    await tick(3000);
    // Tab A, which has not read since, picks the year tab B stored; a third
    // tab opens inside its autosave pause.
    act(() => { tabA.form().update('grade', 'Senior'); });
    await tick(100);
    await openTab('tab C');
    // Tab B puts the year back (revision 3), which tab A has not seen.
    await choose(tabB, 'grade', 'Junior');
    await tick(3000);
    const before = sent.length;
    await choose(tabA, 'grade', 'Masters');
    await tick(4000);
    expect({
      asked: asked(tabA), stored: { revision: row.revision, grade: row.profile.grade },
      sent: sent.slice(before).map((s) => [s.tab, s.expected, s.keys, s.status]),
    }, 'tab A\'s next pick').toEqual({
      asked: ['grade'], stored: { revision: 3, grade: 'Junior' }, sent: [['tab A', 2, ['grade'], 'conflict']],
    });
  });

  it('leaves a write in flight to its answer through two loads, the first of which drops its outbox entry, so an edit made before the answer is sent, not asked (a guard; already so before M135)', async () => {
    // Passes before M135 too, whose loads settle nothing: kept so a settle at
    // load stays caught.
    const tab1 = await openTab('tab 1');
    // The year is stored at once and its answer is held.
    let answer!: () => void;
    const answered = new Promise<void>((resolve) => { answer = resolve; });
    service.commit.mockImplementation(async (label, intent) => {
      const outcome = await serve(label, intent);
      if (intent.patch.grade === 'Senior') await answered;
      return outcome;
    });
    await choose(tab1, 'grade', 'Senior');
    await tick(2000);
    expect(sent.map((s) => [s.expected, s.keys, s.status, s.revision]), 'in flight').toEqual([[1, ['grade'], 'applied', 2]]);
    // Two reads of the row meanwhile. The first finds the year stored and
    // drops the outbox entry; the second finds the operation with nothing in
    // the outbox capturing it.
    for (let i = 0; i < 2; i += 1) {
      act(() => { window.dispatchEvent(new Event('focus')); });
      await tick(1000);
    }
    expect({
      outbox: tab1.sync.readProfileSyncEnvelope()?.pending ?? null, journal: described(outstanding(tab1)),
    }, 'read twice while in flight').toEqual({ outbox: null, journal: ['tab 1 edit of grade'] });
    await choose(tab1, 'grade', 'Masters');
    act(() => { answer(); });
    await tick(4000);
    expect({
      asked: asked(tab1), status: tab1.form().saveStatus, journal: described(outstanding(tab1)),
      sent: sent.map((s) => [s.expected, s.keys, s.status, s.revision]), stored: row.profile.grade,
    }, 'after the answer and the next edit').toEqual({
      asked: [], status: expect.stringMatching(/^(saved|idle)$/), journal: [],
      sent: [[1, ['grade'], 'applied', 2], [2, ['grade'], 'applied', 3]], stored: 'Masters',
    });
  });

  it('leaves an answer to its own response through two loads, the first of which drops its outbox entry, so the answering tab\'s edit made meanwhile is sent, not asked', async () => {
    const { tab1, tab2 } = await disagreeOffline();
    const hold = holdAnswerResponse();
    const atAnswer = sent.length;
    act(() => { tab2.form().keepMyChanges(); });
    await tick(500);
    await twoLoads();
    expect({
      stored: hold.stored(), outbox: tab2.sync.readProfileSyncEnvelope()?.pending ?? null,
      ops: outstanding(tab2).length, asked1: asked(tab1),
    }, 'the answer stored, its response still out, two loads made').toEqual({ stored: true, outbox: null, ops: 5, asked1: [] });
    // Tab 2 picks LAS and Statistics before the response is back.
    act(() => { tab2.form().update('college', LAS); });
    await tick(100);
    act(() => { tab2.form().update('major', 'Statistics'); });
    await tick(100);
    hold.release();
    await tick(6000);
    // Either tab may send the edit: they share the outbox. Neither aims a
    // write at revision 1, where tab 1's offline edits, which the answer
    // settled, began.
    expect({
      asked2: asked(tab2), asked1: asked(tab1), journal: described(outstanding(tab2)),
      stored: { revision: row.revision, ...academic(row.profile) },
      stores: sent.slice(atAnswer).filter((s) => s.status === 'applied').map((s) => [s.expected, s.keys, s.revision]),
      atRevision1: sent.slice(atAnswer).filter((s) => s.expected === 1).map((s) => s.tab),
    }, 'after the response and the edit').toEqual({
      asked2: [], asked1: [], journal: [],
      stored: { revision: 4, college: LAS, major: 'Statistics', grade: 'Senior' },
      stores: [[2, ['college', 'major'], 3], [3, ['additional_majors', 'college', 'major'], 4]],
      atRevision1: [],
    });
  });

  it('leaves an answer to its own response through two loads, so the other open tab is asked about a college another device put back after it, and sends nothing over it (a guard; already so before M135)', async () => {
    // Before M135 the tab asks too, with no request, from the operations the
    // answer left outstanding: kept so this case stays covered once they go.
    const { tab1, tab2 } = await disagreeOffline();
    const hold = holdAnswerResponse();
    act(() => { tab2.form().keepMyChanges(); });
    await tick(500);
    await twoLoads();
    expect({ outbox: tab2.sync.readProfileSyncEnvelope()?.pending ?? null, ops: outstanding(tab1).length },
      'two loads while the response is out').toEqual({ outbox: null, ops: 5 });
    hold.release();
    await tick(4000);
    expect({ asked1: asked(tab1), stored: { revision: row.revision, ...academic(row.profile) } },
      'the response is back').toEqual({ asked1: [], stored: { revision: 3, ...KEPT } });
    // Another device puts the college and the major back.
    row = { revision: 4, profile: { ...row.profile, college: GRAINGER, major: 'Computer Science' } };
    tab2.unmount();
    await drain();
    const before = sent.length;
    await choose(tab1, 'college', LAS);
    await choose(tab1, 'major', 'Mathematics');
    await tick(4000);
    expect({
      asked1: asked(tab1), stored: { revision: row.revision, ...academic(row.profile) },
      stores: sent.slice(before).filter((s) => s.status === 'applied').map((s) => [s.tab, s.expected, s.keys]),
    }, 'tab 1\'s next college edit').toEqual({
      asked1: ['college', 'major'], stored: { revision: 4, college: GRAINGER, major: 'Computer Science', grade: 'Senior' },
      stores: [],
    });
  });

  it('leaves an answer to its own response while a third tab opens and tab 1 saves what it has left, so the answering tab\'s edit made meanwhile is sent, not asked', async () => {
    const { tab1, tab2 } = await disagreeOffline();
    const hold = holdAnswerResponse();
    act(() => { tab2.form().keepMyChanges(); });
    await tick(500);
    // Tab 1 still owes its cleared additional majors and saves them while
    // the third tab opens; the row already holds everything it would send.
    const tab3 = await openTab('tab 3');
    act(() => { window.dispatchEvent(new Event('focus')); });
    await tick(1000);
    expect({ stored: hold.stored(), journal: outstanding(tab2).length, saves1: sent.filter((s) => s.tab === 'tab 1').length },
      'the answer stored, its response still out, tab 3 open').toEqual({ stored: true, journal: 5, saves1: 0 });
    act(() => { tab2.form().update('college', LAS); });
    await tick(100);
    act(() => { tab2.form().update('major', 'Statistics'); });
    await tick(100);
    hold.release();
    await tick(6000);
    expect({
      asked: [asked(tab1), asked(tab2), asked(tab3)], journal: described(outstanding(tab2)),
      stored: { revision: row.revision, ...academic(row.profile) },
    }, 'after the response and the edit').toEqual({
      asked: [[], [], []], journal: [], stored: { revision: 4, college: LAS, major: 'Statistics', grade: 'Senior' },
    });
  });

  it('leaves an answer to its own response while the other tab repairs a question of its own, so the answering tab\'s edit made meanwhile is sent, not asked about its answer', async () => {
    const { tab1, tab2 } = await disagreeOffline();
    const hold = holdAnswerResponse();
    act(() => { tab2.form().keepMyChanges(); });
    await tick(500);
    act(() => { window.dispatchEvent(new Event('focus')); });
    await tick(1000);
    // Another device changes the year after tab 1's read, and tab 1 changes
    // it too: a real question about the year, which tab 1's repair handles
    // while the answer's response is still out.
    row = { revision: row.revision + 1, profile: { ...row.profile, grade: 'Masters' } };
    act(() => { tab1.form().update('grade', 'Sophomore'); });
    await tick(600);
    await tick(3000);
    expect({ stored: hold.stored(), asked1: asked(tab1), journal: outstanding(tab2).length },
      'tab 1 asked about the year, the answer\'s response still out').toEqual({ stored: true, asked1: ['grade'], journal: 6 });
    act(() => { tab2.form().update('college', LAS); });
    await tick(100);
    act(() => { tab2.form().update('major', 'Statistics'); });
    await tick(100);
    hold.release();
    await tick(6000);
    // Only tab 1's year is still a question; college and major were tab 2's
    // own answer and its edit after it.
    expect({ asked2: asked(tab2), stored: { revision: row.revision, ...academic(row.profile) } }, 'after the response and the edit')
      .toEqual({ asked2: ['grade'], stored: { revision: 5, college: LAS, major: 'Statistics', grade: 'Masters' } });
  });
});

/** localStorage refuses, once, the rebase receipt of the operation `which`
 *  picks out (QuotaExceededError): the origin had room for the ones before
 *  it. */
function refuseReceipt(which: (opId: string) => boolean) {
  const storage = window.localStorage;
  const original = storage.setItem.bind(storage);
  const refused: string[] = [];
  const spy = vi.spyOn(storage, 'setItem').mockImplementation((key: string, value: string) => {
    const at = key.indexOf('ofe_profile_journal_v1_rebase_');
    if (at >= 0 && refused.length === 0 && which(key.slice(at + 'ofe_profile_journal_v1_rebase_'.length))) {
      refused.push(key);
      throw new DOMException('The quota has been exceeded.', 'QuotaExceededError');
    }
    return original(key, value);
  });
  return { refused, restore: () => spy.mockRestore() };
}

/** Every operation id minted from here on sorts before every one minted
 *  earlier, so the journal reads newest first. */
function idsSortNewestFirst() {
  let n = 9_000_000_000;
  return vi.spyOn(globalThis.crypto, 'randomUUID').mockImplementation(() => {
    n -= 1;
    return `${String(n).padStart(10, '0')}-0000-4000-8000-000000000000` as `${string}-${string}-${string}-${string}-${string}`;
  });
}

// A settle writes one rebase receipt per operation, and a receipt hides its
// operation from every reader. One that did not fit used to leave the
// receipts before it: half the closure hidden, the answer or what it decided
// gone while an edit it decided against was outstanding again (review of
// M135, round 1).
describe('a settle whose receipt does not fit takes back the receipts it wrote (M135)', { timeout: 20_000 }, () => {
  it('in the answer\'s acknowledgement: the major the answer decided against is never sent over it', async () => {
    // Newest first: the acknowledgement writes tab 1's major edit's receipt
    // after the answer's and tab 2's major edit's.
    const ids = idsSortNewestFirst();
    try {
      const tab1 = await openTab('tab 1');
      const tab2 = await openTab('tab 2');
      network(false);
      await tick(1500);
      await choose(tab1, 'major', 'Mathematics');
      await choose(tab2, 'major', 'Finance');
      await choose(tab2, 'grade', 'Senior');
      await tick(4000);
      network(true);
      await tick(1000);
      expect({ tab1: asked(tab1), tab2: asked(tab2), journal: described(outstanding(tab1)), stored: { revision: row.revision, ...academic(row.profile) } }, 'back online')
        .toEqual({
          tab1: ['major'], tab2: ['major'], journal: ['tab 1 edit of major', 'tab 2 edit of major'],
          stored: { revision: 2, college: GRAINGER, major: 'Computer Science', grade: 'Senior' },
        });
      const mathematics = outstanding(tab1).find((op) => op.fields[0].desired.value === 'Mathematics')!;
      const quota = refuseReceipt((opId) => opId === mathematics.opId);
      const atAnswer = sent.length;
      act(() => { tab2.form().keepMyChanges(); });
      await tick(3000);
      quota.restore();
      expect({
        refused: quota.refused.length, stored: { revision: row.revision, ...academic(row.profile) },
        sent: sent.slice(atAnswer).map((s) => [s.tab, s.expected, s.keys, s.values.major, s.status, s.revision]),
      }, 'the answer, its acknowledgement refused the receipt of tab 1\'s major').toEqual({
        refused: 1, stored: { revision: 3, college: GRAINGER, major: 'Finance', grade: 'Senior' },
        sent: [['tab 2', 2, ['major'], 'Finance', 'applied', 3]],
      });
      // Tab 1 showed its own major while asked (M132), so the answer reaches
      // it only now, beside its edit the refused receipt left outstanding: it
      // says that is not saved, and its Retry settles it, sending nothing.
      // Before M132 tab 1 drew tab 2's major while asked and autosaved it,
      // which settled the same closure.
      expect({ form: academic(tab1.form().profile), asked: asked(tab1), status: tab1.form().saveStatus, retry: tab1.form().canRetrySync },
        'tab 1 after the answer').toEqual({ form: { college: GRAINGER, major: 'Finance', grade: 'Senior' }, asked: [], status: 'cloud-failed', retry: true });
      act(() => { tab1.form().retryCloudSave(); });
      await tick(4000);
      const reloaded1 = await reloadTab(tab1);
      await tick(65_000);
      expect({
        journal: described(outstanding(reloaded1)), receipts: journalStorage().receiptVersions.length,
        asked: asked(reloaded1), form: academic(reloaded1.form().profile),
        stored: { revision: row.revision, ...academic(row.profile) }, sent: sent.length - atAnswer,
      }, 'tab 1 reloaded, 65 s later').toEqual({
        journal: [], receipts: 0, asked: [], form: { college: GRAINGER, major: 'Finance', grade: 'Senior' },
        stored: { revision: 3, college: GRAINGER, major: 'Finance', grade: 'Senior' }, sent: 1,
      });
    } finally {
      ids.mockRestore();
    }
  });
});

/** The live check up to the answer in tab 2, with tab 1 left open and not
 *  reloaded: both tabs show the answer at revision 3. Tab 2 is closed.
 *  Returns tab 1. */
async function answeredWithTab1Open() {
  const { tab1, tab2 } = await disagreeOffline();
  act(() => { tab2.form().keepMyChanges(); });
  await tick(3000);
  await tick(5000);
  expect({
    stored: { revision: row.revision, ...academic(row.profile) },
    tab1: { asked: asked(tab1), form: academic(tab1.form().profile), revision: tab1.form().viewSnapshot?.revision },
  }, 'after the answer, tab 1 open').toEqual({
    stored: { revision: 3, ...KEPT }, tab1: { asked: [], form: KEPT, revision: 3 },
  });
  tab2.unmount();
  await drain();
  return tab1;
}

// A tab open through another tab's answer still holds in memory the base its
// own edits started from (revision 1). The answer's settle made it old: it
// must not be what the tab's next edit is measured against (review of M135,
// round 2, P4). Nor a base the tab took from another tab's edit, which that
// tab's save has settled.
describe('a tab open through another tab\'s answer measures its next edit against what it shows (M135)', { timeout: 20_000 }, () => {
  it('asks about a college another device put back after the answer, and sends nothing over it (a guard; already so before M135)', async () => {
    // Before M135 the tab asks too, with no request, from the operations the
    // answer left outstanding: kept so this case stays covered once they go.
    const tab1 = await answeredWithTab1Open();
    row = { revision: 4, profile: { ...row.profile, college: GRAINGER, major: 'Computer Science' } };
    const before = sent.length;
    await choose(tab1, 'college', LAS);
    await choose(tab1, 'major', 'Mathematics');
    await tick(4000);
    expect({
      asked: asked(tab1), stored: { revision: row.revision, ...academic(row.profile) },
      stores: sent.slice(before).filter((s) => s.status === 'applied').map((s) => [s.tab, s.expected, s.keys]),
    }, 'tab 1 picks LAS and Mathematics').toEqual({
      asked: ['college', 'major'], stored: { revision: 4, college: GRAINGER, major: 'Computer Science', grade: 'Senior' },
      stores: [],
    });
  });

  it('saves its next college edit without a question when nothing changed after the answer', async () => {
    const tab1 = await answeredWithTab1Open();
    const before = sent.length;
    await choose(tab1, 'college', LAS);
    await choose(tab1, 'major', 'Mathematics');
    await tick(4000);
    expect({
      asked: asked(tab1), status: tab1.form().saveStatus, journal: described(outstanding(tab1)),
      stored: { revision: row.revision, ...academic(row.profile) },
      sent: sent.slice(before).map((s) => [s.tab, s.expected, s.keys, s.status]),
    }, 'tab 1 picks LAS and Mathematics').toEqual({
      asked: [], status: expect.stringMatching(/^(saved|idle)$/), journal: [],
      stored: { revision: 4, college: LAS, major: 'Mathematics', grade: 'Senior' },
      sent: [['tab 1', 3, ['additional_majors', 'college', 'major'], 'applied']],
    });
  });

  it('asks about a college another device put back after another tab\'s save, when the tab read that tab\'s edit while it was outstanding', async () => {
    const tab1 = await openTab('tab 1');
    const tab2 = await openTab('tab 2');
    // Tab 2's college switch is stored at once and its response is held;
    // meanwhile both tabs read the row, tab 1 taking tab 2's edit (based on
    // Grainger at revision 1) into what it holds in memory.
    let release!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    service.commit.mockImplementation(async (label, intent) => {
      const outcome = await serve(label, intent);
      if (label === 'tab 2' && intent.patch.college === GIES) await held;
      return outcome;
    });
    await choose(tab2, 'college', GIES);
    await tick(2000);
    act(() => { window.dispatchEvent(new Event('focus')); });
    await tick(1000);
    act(() => { release(); });
    await tick(4000);
    expect({
      stored: { revision: row.revision, ...academic(row.profile) },
      tab1: { form: academic(tab1.form().profile), revision: tab1.form().viewSnapshot?.revision, journal: described(outstanding(tab1)) },
    }, 'tab 2\'s save, read by tab 1').toEqual({
      stored: { revision: 2, college: GIES, major: '', grade: 'Junior' },
      tab1: { form: { college: GIES, major: '', grade: 'Junior' }, revision: 2, journal: [] },
    });
    tab2.unmount();
    await drain();
    // Another device puts the college and the major back.
    row = { revision: 3, profile: { ...row.profile, college: GRAINGER, major: 'Computer Science' } };
    const before = sent.length;
    await choose(tab1, 'college', LAS);
    await choose(tab1, 'major', 'Mathematics');
    await tick(4000);
    expect({
      asked: asked(tab1), stored: { revision: row.revision, ...academic(row.profile) },
      sent: sent.slice(before).map((s) => [s.tab, s.expected, s.keys, s.status]),
    }, 'tab 1 picks LAS and Mathematics').toEqual({
      asked: ['college', 'major'], stored: { revision: 3, college: GRAINGER, major: 'Computer Science', grade: 'Junior' },
      sent: [['tab 1', 2, ['additional_majors', 'college', 'major'], 'conflict']],
    });
  });
});

/** localStorage refuses every write to `key` (QuotaExceededError) until
 *  `restore`: the origin has no room for that copy, and still has room for
 *  the journal's small operations. */
function refuseWrites(key: string) {
  const storage = window.localStorage;
  const original = storage.setItem.bind(storage);
  const refused: string[] = [];
  const spy = vi.spyOn(storage, 'setItem').mockImplementation((name: string, value: string) => {
    if (name.endsWith(key)) {
      refused.push(name);
      throw new DOMException('The quota has been exceeded.', 'QuotaExceededError');
    }
    return original(name, value);
  });
  return { refused, restore: () => spy.mockRestore() };
}

/** Two tabs at revision 1. Tab 1 picks Senior and this device refuses the
 *  stage's write of `refusedKey`, so tab 1 shows the save error with Retry;
 *  tab 2 then saves its research interests, which carries tab 1's year
 *  (revision 2) and settles tab 1's operation. */
async function refusedYearCarriedByTab2(refusedKey: string) {
  const tab1 = await openTab('tab 1');
  const tab2 = await openTab('tab 2');
  const full = refuseWrites(refusedKey);
  act(() => { tab1.form().update('grade', 'Senior'); });
  await tick(2500);
  full.restore();
  expect({
    refused: full.refused.length, status: tab1.form().saveStatus, retry: tab1.form().canRetrySync,
    journal: described(outstanding(tab1)), sent: sent.length,
  }, 'tab 1\'s pick, refused on this device').toEqual({
    refused: 1, status: 'error', retry: true, journal: ['tab 1 edit of grade'], sent: 0,
  });
  act(() => { tab2.form().update('research_interests', 'robotics and control'); });
  await tick(4000);
  expect({
    journal: described(outstanding(tab1)), stored: { revision: row.revision, grade: row.profile.grade },
    sent: sent.map((s) => [s.tab, s.expected, s.keys, s.status]),
  }, 'tab 2\'s save').toEqual({
    journal: [], stored: { revision: 2, grade: 'Senior' },
    sent: [['tab 2', 1, ['grade', 'research_interests'], 'applied']],
  });
  return { tab1, tab2 };
}

// An edit whose stage this device could not write stays in the tab's memory
// until Retry stages it again. Another tab's save can carry its operation
// meanwhile and settle it; Retry still measures the edit against the base it
// began from, so a year stored after it is asked about, not written over
// (review of M135, round 3: the origin's quota was reached in production on
// 2026-08-31). All four pass before M135 too, which held that base: kept so
// a change that drops it stays caught.
describe('Retry of an edit this device could not store measures it against the base it began from (M135)', { timeout: 20_000 }, () => {
  for (const [what, refusedKey] of [['the profile copy', 'ofe_profile'], ['the outbox', 'ofe_profile_sync_v1']] as const) {
    it(`asks about a year another tab stored after it, and sends nothing over it (${what} refused) (a guard; already so before M135)`, async () => {
      const { tab1, tab2 } = await refusedYearCarriedByTab2(refusedKey);
      await choose(tab2, 'grade', 'Masters');
      await tick(4000);
      expect({ revision: row.revision, grade: row.profile.grade }, 'tab 2 picks Masters').toEqual({ revision: 3, grade: 'Masters' });
      const before = sent.length;
      act(() => { tab1.form().retryCloudSave(); });
      await tick(4000);
      expect({
        asked: asked(tab1), stored: { revision: row.revision, grade: row.profile.grade }, shows2: tab2.form().profile.grade,
        sent: sent.slice(before).map((s) => [s.tab, s.expected, s.keys, s.status]),
      }, 'Retry in tab 1').toEqual({
        asked: ['grade'], stored: { revision: 3, grade: 'Masters' }, shows2: 'Masters',
        sent: [['tab 1', 1, ['grade'], 'conflict']],
      });
    });
  }

  it('asks about a year another device stored after it, which the tab has read, and sends nothing over it (a guard; already so before M135)', async () => {
    const { tab1 } = await refusedYearCarriedByTab2('ofe_profile');
    row = { revision: 3, profile: { ...row.profile, grade: 'Masters' } };
    act(() => { window.dispatchEvent(new Event('focus')); });
    await tick(3000);
    const before = sent.length;
    act(() => { tab1.form().retryCloudSave(); });
    await tick(4000);
    expect({
      asked: asked(tab1), stored: { revision: row.revision, grade: row.profile.grade },
      sent: sent.slice(before).map((s) => [s.tab, s.expected, s.keys, s.status]),
    }, 'Retry in tab 1').toEqual({
      asked: ['grade'], stored: { revision: 3, grade: 'Masters' }, sent: [['tab 1', 1, ['grade'], 'conflict']],
    });
  });

  it('asks nothing and sends nothing when the row still holds the year another tab carried (a guard; already so before M135)', async () => {
    const { tab1 } = await refusedYearCarriedByTab2('ofe_profile');
    const before = sent.length;
    act(() => { tab1.form().retryCloudSave(); });
    await tick(4000);
    expect({
      asked: asked(tab1), status: tab1.form().saveStatus, shows: tab1.form().profile.grade,
      stored: { revision: row.revision, grade: row.profile.grade }, sent: sent.length - before,
    }, 'Retry in tab 1').toEqual({
      asked: [], status: expect.stringMatching(/^(saved|idle)$/), shows: 'Senior', stored: { revision: 2, grade: 'Senior' }, sent: 0,
    });
  });
});

/** Another device saves: the row moves on, and no tab hears of it until it
 *  reads the row or a response of its own brings the row back. */
function anotherDevice(patch: Record<string, unknown>) {
  row = { revision: row.revision + 1, profile: { ...row.profile, ...patch } };
}

/** The tab types its research interests and their save goes out: met by the
 *  revision another tab or device stored, it is sent again on top of it, and
 *  its response brings that revision back. */
async function saveResearchInterests(tab: Tab) {
  const before = sent.length;
  act(() => { tab.form().update('research_interests', 'robotics and vision'); });
  await tick(600);
  await tick(4000);
  return sent.slice(before).map((s) => [s.tab, s.keys, s.status]);
}

/** What the tab shows of the fields the student is about to change, the
 *  change, and what came of it. */
async function changeShown(tab: Tab, picks: ['college' | 'major' | 'grade', string][]) {
  const shown = Object.fromEntries(picks.map(([key]) => [key, tab.form().profile[key]]));
  const before = sent.length;
  for (const [key, value] of picks) await choose(tab, key, value);
  await tick(4000);
  return {
    shown, asked: asked(tab), stored: { revision: row.revision, ...academic(row.profile) },
    sent: sent.slice(before).map((s) => [s.tab, s.expected, s.keys, s.status]),
  };
}

/** The campus gate's write (persistHomeSchool's): the one key, from the view
 *  the tab shows, under the gate's own writer. Its receipt and window event
 *  are left out, since the tabs here share one window. Returns the status. */
async function pickCampus(tab: Tab, slug: string): Promise<string | undefined> {
  const view = tab.form().viewSnapshot!;
  const outcome = await tab.sync.commitProfileAction({
    keys: ['home_school'], view, desiredAfter: { ...view.renderedProfile, home_school: slug } as ProfileData,
    writer: tab.sync.SCHOOL_WRITER,
  });
  return outcome.result?.status ?? outcome.reason;
}

// A response that moves the tab's base on to a row another tab or device
// wrote, the tab's own save's included, used to leave the form as it was:
// the next edit of a field was measured against that row, so a value the tab
// never showed was written over without a question. The tab now shows the
// row wherever no edit or question holds the field (review of M135, round 4).
describe('a base that moves on brings what another tab or device stored onto the form before the student changes it (M135)', { timeout: 20_000 }, () => {
  it('one tab: its own save brings back the college another device stored', async () => {
    const tab1 = await openTab('tab 1');
    anotherDevice({ college: GIES, major: 'Finance' });
    expect(await saveResearchInterests(tab1), 'the research interests\' save')
      .toEqual([['tab 1', ['research_interests'], 'conflict'], ['tab 1', ['research_interests'], 'applied']]);
    expect(await changeShown(tab1, [['college', LAS], ['major', 'Mathematics']]), 'tab 1 picks LAS and Mathematics').toEqual({
      shown: { college: GIES, major: 'Finance' }, asked: [],
      stored: { revision: 4, college: LAS, major: 'Mathematics', grade: 'Junior' },
      sent: [['tab 1', 3, ['additional_majors', 'college', 'major'], 'applied']],
    });
  });

  it('one tab: a later save brings back the year another device stored after the tab\'s own', async () => {
    const tab1 = await openTab('tab 1');
    await choose(tab1, 'grade', 'Senior');
    await tick(4000);
    anotherDevice({ grade: 'Masters' });
    await saveResearchInterests(tab1);
    expect(await changeShown(tab1, [['grade', 'Freshman']]), 'tab 1 picks Freshman').toEqual({
      shown: { grade: 'Masters' }, asked: [],
      stored: { revision: 5, college: GRAINGER, major: 'Computer Science', grade: 'Freshman' },
      sent: [['tab 1', 4, ['grade'], 'applied']],
    });
  });

  it('two tabs: a tab that has not read since another tab\'s save gets it back from its own', async () => {
    const tab1 = await openTab('tab 1');
    const tab2 = await openTab('tab 2');
    await choose(tab2, 'college', GIES);
    await choose(tab2, 'major', 'Finance');
    await tick(4000);
    expect({ revision: row.revision, ...academic(row.profile) }, 'tab 2\'s save').toEqual({ revision: 2, college: GIES, major: 'Finance', grade: 'Junior' });
    await saveResearchInterests(tab1);
    expect(await changeShown(tab1, [['college', LAS], ['major', 'Mathematics']]), 'tab 1 picks LAS and Mathematics').toEqual({
      shown: { college: GIES, major: 'Finance' }, asked: [],
      stored: { revision: 4, college: LAS, major: 'Mathematics', grade: 'Junior' },
      sent: [['tab 1', 3, ['additional_majors', 'college', 'major'], 'applied']],
    });
  });

  it('a tab open through another tab\'s answer: its next save brings back the college another device put back', async () => {
    const tab1 = await answeredWithTab1Open();
    anotherDevice({ college: GRAINGER, major: 'Computer Science' });
    await saveResearchInterests(tab1);
    expect(await changeShown(tab1, [['college', LAS], ['major', 'Mathematics']]), 'tab 1 picks LAS and Mathematics').toEqual({
      shown: { college: GRAINGER, major: 'Computer Science' }, asked: [],
      stored: { revision: 6, college: LAS, major: 'Mathematics', grade: 'Senior' },
      sent: [['tab 1', 5, ['additional_majors', 'college', 'major'], 'applied']],
    });
  });

  it('a tab that read another tab\'s edit while it was outstanding: its next save brings back the college another device stored after it', async () => {
    const tab1 = await openTab('tab 1');
    const tab2 = await openTab('tab 2');
    let release!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    service.commit.mockImplementation(async (label, intent) => {
      const outcome = await serve(label, intent);
      if (label === 'tab 2' && intent.patch.college === GIES) await held;
      return outcome;
    });
    await choose(tab2, 'college', GIES);
    await tick(2000);
    act(() => { window.dispatchEvent(new Event('focus')); });
    await tick(1000);
    act(() => { release(); });
    await tick(4000);
    tab2.unmount();
    await drain();
    act(() => { window.dispatchEvent(new Event('focus')); });
    await tick(3000);
    expect({ form: academic(tab1.form().profile), revision: tab1.form().viewSnapshot?.revision }, 'tab 1 after tab 2\'s save')
      .toEqual({ form: { college: GIES, major: '', grade: 'Junior' }, revision: 2 });
    anotherDevice({ college: LAS, major: 'Statistics' });
    await saveResearchInterests(tab1);
    expect(await changeShown(tab1, [['college', GRAINGER], ['major', 'Physics']]), 'tab 1 picks Grainger and Physics').toEqual({
      shown: { college: LAS, major: 'Statistics' }, asked: [],
      stored: { revision: 5, college: GRAINGER, major: 'Physics', grade: 'Junior' },
      sent: [['tab 1', 4, ['additional_majors', 'college', 'major'], 'applied']],
    });
  });

  for (const [what, refusedKey] of [['the profile copy', 'ofe_profile'], ['the outbox', 'ofe_profile_sync_v1']] as const) {
    it(`a tab whose year this device could not store (${what} refused) and another tab carried: its next save brings back the year another device stored`, async () => {
      const { tab1, tab2 } = await refusedYearCarriedByTab2(refusedKey);
      tab2.unmount();
      await drain();
      act(() => { window.dispatchEvent(new Event('focus')); });
      await tick(3000);
      anotherDevice({ grade: 'Masters' });
      await saveResearchInterests(tab1);
      expect(await changeShown(tab1, [['grade', 'Freshman']]), 'tab 1 picks Freshman').toEqual({
        shown: { grade: 'Masters' }, asked: [],
        stored: { revision: 5, college: GRAINGER, major: 'Computer Science', grade: 'Freshman' },
        sent: [['tab 1', 4, ['grade'], 'applied']],
      });
    });
  }

  it('starts no save by showing what its own save brought back', async () => {
    const tab1 = await openTab('tab 1');
    anotherDevice({ college: GIES, major: 'Finance', name: 'Named on the phone' });
    await saveResearchInterests(tab1);
    await tick(10_000);
    expect({
      form: { ...academic(tab1.form().profile), name: tab1.form().profile.name }, status: tab1.form().saveStatus,
      sent: sent.map((s) => [s.tab, s.expected, s.keys, s.status]),
    }, 'tab 1, 10 s after the research interests\' save').toEqual({
      form: { college: GIES, major: 'Finance', grade: 'Junior', name: 'Named on the phone' }, status: 'idle',
      sent: [['tab 1', 1, ['research_interests'], 'conflict'], ['tab 1', 2, ['research_interests'], 'applied']],
    });
  });

  it('keeps a year in question when another save moves the base on, beside the college it shows from there, and starts no save', async () => {
    const tab1 = await openTab('tab 1');
    anotherDevice({ grade: 'Masters' });
    await choose(tab1, 'grade', 'Senior');
    await tick(4000);
    expect({ asked: asked(tab1), stored: row.profile.grade }, 'tab 1 picks Senior').toEqual({ asked: ['grade'], stored: 'Masters' });
    anotherDevice({ grade: 'Sophomore', college: GIES, major: 'Finance' });
    await saveResearchInterests(tab1);
    const at = sent.length;
    await tick(10_000);
    expect({
      asked: asked(tab1), form: academic(tab1.form().profile), status: tab1.form().saveStatus,
      stored: { revision: row.revision, ...academic(row.profile) }, sentSince: sent.length - at,
    }, 'tab 1 after its research interests\' save').toEqual({
      asked: ['grade'], form: { college: GIES, major: 'Finance', grade: 'Senior' }, status: 'conflict',
      stored: { revision: 4, college: GIES, major: 'Finance', grade: 'Sophomore' }, sentSince: 0,
    });
  });

  it('keeps research interests typed while its save was out when that save\'s response moves the base on (a guard; already so before M135)', async () => {
    // Passes before M135 too, which redrew no such field: kept so a redraw
    // over an edit in progress stays caught.
    const tab1 = await openTab('tab 1');
    let release!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    service.commit.mockImplementation(async (label, intent) => {
      const outcome = await serve(label, intent);
      if (intent.patch.grade === 'Senior') await held;
      return outcome;
    });
    await choose(tab1, 'grade', 'Senior');
    await tick(2000);
    expect(sent.map((s) => [s.expected, s.keys, s.status]), 'the year stored, its response held').toEqual([[1, ['grade'], 'applied']]);
    act(() => { tab1.form().update('research_interests', 'typed while the year was saved'); });
    await tick(100);
    act(() => { release(); });
    await tick(200);
    expect({ shows: tab1.form().profile.research_interests, revision: tab1.form().viewSnapshot?.revision, stored: row.profile.research_interests },
      'the year\'s response').toEqual({ shows: 'typed while the year was saved', revision: 2, stored: 'robotics' });
    await tick(4000);
    expect({
      asked: asked(tab1), shows: tab1.form().profile.research_interests, stored: row.profile.research_interests,
      sent: sent.map((s) => [s.expected, s.keys, s.status]),
    }, 'after the interests\' save').toEqual({
      asked: [], shows: 'typed while the year was saved', stored: 'typed while the year was saved',
      sent: [[1, ['grade'], 'applied'], [1, ['research_interests'], 'conflict'], [2, ['research_interests'], 'applied']],
    });
  });

  it('keeps a slider move made offline, which another device\'s weight put in question, when its own save moves the base on, and stores it on "Keep what I typed"', async () => {
    const tab1 = await openTab('tab 1');
    const slider = () => ({ shows: tab1.form().searchWeight, holds: tab1.form().profile.search_weight });
    const question = () => tab1.form().conflicts.map((c) => [c.key, c.candidates.map((x) => x.value), c.remote]);
    network(false);
    await tick(1500);
    act(() => { tab1.form().setSearchWeight(30); });
    await tick(4000);
    expect({ slider: slider(), status: tab1.form().saveStatus, sent: sent.map((s) => [s.expected, s.keys, s.values.search_weight, s.status]) },
      'the slider moved offline').toEqual({ slider: { shows: 30, holds: 30 }, status: 'cloud-failed', sent: [[1, ['search_weight'], 30, 'failed']] });
    anotherDevice({ search_weight: 80 });
    network(true);
    await tick(4000);
    expect({ slider: slider(), question: question(), revision: tab1.form().viewSnapshot?.revision }, 'back online')
      .toEqual({ slider: { shows: 30, holds: 30 }, question: [['search_weight', [30], 80]], revision: 2 });
    // Another device then stores the college and the major, and the response
    // to the research interests' save brings that revision back.
    anotherDevice({ college: GIES, major: 'Finance' });
    await saveResearchInterests(tab1);
    expect({
      slider: slider(), question: question(), form: academic(tab1.form().profile), revision: tab1.form().viewSnapshot?.revision,
      stored: { revision: row.revision, search_weight: row.profile.search_weight },
    }, 'tab 1 after its research interests\' save').toEqual({
      slider: { shows: 30, holds: 30 }, question: [['search_weight', [30], 80]], form: { college: GIES, major: 'Finance', grade: 'Junior' },
      revision: 4, stored: { revision: 4, search_weight: 80 },
    });
    const before = sent.length;
    act(() => { tab1.form().keepMyChanges(); });
    await tick(3000);
    expect({
      slider: slider(), asked: asked(tab1), stored: { revision: row.revision, search_weight: row.profile.search_weight },
      sent: sent.slice(before).map((s) => [s.expected, s.keys, s.values.search_weight, s.status]),
    }, '"Keep what I typed"').toEqual({
      slider: { shows: 30, holds: 30 }, asked: [], stored: { revision: 5, search_weight: 30 }, sent: [[4, ['search_weight'], 30, 'applied']],
    });
  });

  it('keeps a campus another tab\'s school gate picked and could not send when its own save moves the base on, beside the name it shows from there, until the gate sends it', async () => {
    const tab1 = await openTab('tab 1');
    const tab2 = await openTab('tab 2');
    // The pick is journaled, and this device refuses the outbox's copy, so
    // nothing is sent and no save of another writer's carries it.
    const full = refuseWrites('ofe_profile_sync_v1');
    const picked = await pickCampus(tab2, 'jhu');
    full.restore();
    expect({ picked, refused: full.refused.length, journal: described(outstanding(tab1)), sent: sent.length }, 'the gate\'s pick in tab 2')
      .toEqual({ picked: 'device-failed', refused: 1, journal: ['tab 2 edit of home_school'], sent: 0 });
    act(() => { window.dispatchEvent(new Event('focus')); });
    await tick(3000);
    expect(tab1.form().profile.home_school, 'tab 1 after its read').toBe('jhu');
    anotherDevice({ name: 'Named on the phone' });
    expect(await saveResearchInterests(tab1), 'the research interests\' save')
      .toEqual([['tab 1', ['research_interests'], 'conflict'], ['tab 1', ['research_interests'], 'applied']]);
    expect({
      shows: { home_school: tab1.form().profile.home_school, name: tab1.form().profile.name }, revision: tab1.form().viewSnapshot?.revision,
      stored: { revision: row.revision, home_school: row.profile.home_school }, journal: described(outstanding(tab1)),
    }, 'tab 1 after its research interests\' save').toEqual({
      shows: { home_school: 'jhu', name: 'Named on the phone' }, revision: 3,
      stored: { revision: 3, home_school: 'uiuc' }, journal: ['tab 2 edit of home_school'],
    });
    const again = pickCampus(tab2, 'jhu');
    await tick(3000);
    expect(await again, 'the gate\'s pick again').toBe('saved');
    act(() => { window.dispatchEvent(new Event('focus')); });
    await tick(3000);
    expect({ shows: tab1.form().profile.home_school, asked: asked(tab1), stored: { revision: row.revision, home_school: row.profile.home_school } },
      'tab 1 once the gate sent it').toEqual({ shows: 'jhu', asked: [], stored: { revision: 4, home_school: 'jhu' } });
  });
});

// Checklist M153 (review of M135, round 5, probe p7): a question is open in
// tab 1 about the college and the major it picked offline, which another
// device changed meanwhile. Tab 1 then picks a year, and that save fails in
// transit. The save had staged the question's fields again, which unlocked
// them in the outbox, so the question left the screen with the save's
// "Couldn't save", nothing could answer it, and the edits stayed in the
// journal. Now the year's save leaves the question's fields alone.
describe('a save that fails while a question is open (M153)', { timeout: 20_000 }, () => {
  /** Back online tab 1 is asked; its year then goes out while the network
   *  refuses every write (`how` 'reset'), or with the browser offline. */
  async function askedThenYearFails(how: 'reset' | 'offline') {
    const tab1 = await openTab('tab 1');
    network(false);
    await tick(1500);
    await choose(tab1, 'college', LAS);
    await choose(tab1, 'major', 'Mathematics');
    await tick(3000);
    anotherDevice({ college: GIES, major: 'Finance' });
    network(true);
    await tick(5000);
    expect({ asked: asked(tab1), status: tab1.form().saveStatus }, 'back online').toEqual({ asked: ['college', 'major'], status: 'conflict' });
    if (how === 'reset') writesFail = true; else network(false);
    const before = sent.length;
    await choose(tab1, 'grade', 'Senior');
    await tick(4000);
    writesFail = false;
    expect({
      asked: asked(tab1), form: academic(tab1.form().profile), stored: { revision: row.revision, ...academic(row.profile) },
      sent: sent.slice(before).map((s) => [s.expected, s.keys, s.status]),
    }, 'after the year\'s save failed').toEqual({
      asked: ['college', 'major'], form: { college: LAS, major: 'Mathematics', grade: 'Senior' },
      stored: { revision: 2, college: GIES, major: 'Finance', grade: 'Junior' },
      sent: [[1, ['additional_majors', 'grade'], 'failed']],
    });
    return tab1;
  }

  for (const answer of ['keep', 'other'] as const) {
    it(`keeps the question on screen, and "${answer === 'keep' ? 'Keep what I typed' : 'Use the other version'}" stores the answer and the year`, async () => {
      const tab1 = await askedThenYearFails('reset');
      act(() => { if (answer === 'keep') tab1.form().keepMyChanges(); else tab1.form().useCloudVersion(); });
      await tick(6000);
      const stored = answer === 'keep' ? { college: LAS, major: 'Mathematics', grade: 'Senior' } : { college: GIES, major: 'Finance', grade: 'Senior' };
      expect({ asked: asked(tab1), form: academic(tab1.form().profile), stored: academic(row.profile), journal: described(outstanding(tab1)) }, 'answered')
        .toEqual({ asked: [], form: stored, stored, journal: [] });
      await changeShown(tab1, [['college', GRAINGER], ['major', 'Computer Science']]);
      expect({ asked: asked(tab1), stored: academic(row.profile), journal: described(outstanding(tab1)) }, 'tab 1 then picks Grainger and Computer Science')
        .toEqual({ asked: [], stored: { college: GRAINGER, major: 'Computer Science', grade: 'Senior' }, journal: [] });
    });
  }

  // Review of M153 (flows, SF6/F2b): "Use the other version" there left the
  // answer and the edits it decided against in the journal (the answer's
  // write went out beside the year at the older revision, and the rebase
  // dropped the fields the row held without settling them). A college and
  // major another device stored later stayed off the screen; the next edit,
  // a reload or a second tab sent the answer's fields again, was refused and
  // asked about the values the answer took as this tab's own, which "Keep
  // what I typed" then wrote over the device's.
  const DEVICE = { college: GRAINGER, major: 'Physics', grade: 'Senior' };
  async function otherVersionThenDevice() {
    const tab1 = await askedThenYearFails('reset');
    act(() => { tab1.form().useCloudVersion(); });
    await tick(6000);
    anotherDevice({ college: GRAINGER, major: 'Physics' });
    return tab1;
  }

  it('settles what "Use the other version" decided, so another device\'s later change shows and the next edit sends only itself', async () => {
    const tab1 = await otherVersionThenDevice();
    act(() => { window.dispatchEvent(new Event('focus')); });
    await tick(4000);
    expect({ asked: asked(tab1), form: academic(tab1.form().profile) }, 'tab 1 after a focus check')
      .toEqual({ asked: [], form: DEVICE });
    const before = sent.length;
    await choose(tab1, 'grade', 'Freshman');
    await tick(4000);
    expect({
      asked: asked(tab1), stored: { revision: row.revision, ...academic(row.profile) },
      sent: sent.slice(before).map((s) => [s.expected, s.keys, s.status]),
    }, 'tab 1 then picks a year').toEqual({
      asked: [], stored: { revision: 5, ...DEVICE, grade: 'Freshman' }, sent: [[4, ['grade'], 'applied']],
    });
  });

  it('asks nothing about what "Use the other version" decided in the tab reloaded, nor in a second tab, after another device changed it', async () => {
    const tab1 = await otherVersionThenDevice();
    const before = sent.length;
    const reloaded = await reloadTab(tab1);
    await tick(4000);
    const tab2 = await openTab('tab 2');
    await tick(4000);
    const shows = (tab: Tab) => ({ asked: asked(tab), form: academic(tab.form().profile) });
    expect({ tab1: shows(reloaded), tab2: shows(tab2), sent: sent.slice(before).map((s) => [s.tab, s.expected, s.keys, s.status]) },
      'tab 1 reloaded, and tab 2 opened').toEqual({ tab1: { asked: [], form: DEVICE }, tab2: { asked: [], form: DEVICE }, sent: [] });
    await choose(tab2, 'grade', 'Freshman');
    await tick(4000);
    expect({ tab1: asked(reloaded), tab2: asked(tab2), sent: sent.slice(before).map((s) => [s.tab, s.expected, s.keys, s.status]) },
      'tab 2 then picks a year').toEqual({ tab1: [], tab2: [], sent: [['tab 2', 4, ['grade'], 'applied']] });
  });

  it('lets "Keep what I typed" be given offline, and stores it with the year once the network is back', async () => {
    const tab1 = await askedThenYearFails('offline');
    act(() => { tab1.form().keepMyChanges(); });
    await tick(3000);
    expect({ stored: academic(row.profile), form: academic(tab1.form().profile) }, 'answered offline')
      .toEqual({ stored: { college: GIES, major: 'Finance', grade: 'Junior' }, form: { college: LAS, major: 'Mathematics', grade: 'Senior' } });
    network(true);
    await tick(6000);
    const stored = { college: LAS, major: 'Mathematics', grade: 'Senior' };
    expect({ asked: asked(tab1), form: academic(tab1.form().profile), stored: academic(row.profile), journal: described(outstanding(tab1)) }, 'back online')
      .toEqual({ asked: [], form: stored, stored, journal: [] });
  });
});

// Checklist M132 (seen during M113): two tabs pick different values offline,
// and both are asked once back online. A tab's screen showed the other tab's
// value in an asked field, while "Keep what I typed" there keeps its own. A
// tab with a question open shows what it typed in the asked fields, which is
// what "Keep what I typed" keeps; the question shows the other side. M137
// (2e7f1e85) kept it so after another tab's write and a load; a save's
// refresh still drew the working copy, which another tab's save can write.
describe('a question two tabs are asked shows each tab what it typed in the asked fields (M132)', { timeout: 20_000 }, () => {
  const shows = (tab: Tab) => ({ asked: asked(tab), form: { college: tab.form().profile.college, major: tab.form().profile.major } });
  const OWN1 = { college: LAS, major: 'Mathematics' };
  const OWN2 = { college: GIES, major: 'Finance' };

  it('back online, after a focus check, and after each tab saves another field (a guard; so since M137)', async () => {
    const { tab1, tab2 } = await disagreeOffline();
    expect({ tab1: shows(tab1), tab2: shows(tab2) }, 'back online').toEqual({
      tab1: { asked: ['college', 'major'], form: OWN1 }, tab2: { asked: ['college', 'major'], form: OWN2 },
    });
    act(() => { window.dispatchEvent(new Event('focus')); });
    await tick(3000);
    expect({ tab1: shows(tab1), tab2: shows(tab2) }, 'after a focus check').toEqual({
      tab1: { asked: ['college', 'major'], form: OWN1 }, tab2: { asked: ['college', 'major'], form: OWN2 },
    });
    await saveResearchInterests(tab2);
    expect({ tab1: shows(tab1), tab2: shows(tab2) }, 'after tab 2 saves its research interests').toEqual({
      tab1: { asked: ['college', 'major'], form: OWN1 }, tab2: { asked: ['college', 'major'], form: OWN2 },
    });
    act(() => { tab1.form().update('research_interests', 'robotics and control'); });
    await tick(600);
    await tick(4000);
    expect({ tab1: shows(tab1), tab2: shows(tab2) }, 'after tab 1 saves its research interests').toEqual({
      tab1: { asked: ['college', 'major'], form: OWN1 }, tab2: { asked: ['college', 'major'], form: OWN2 },
    });
    act(() => { tab1.form().keepMyChanges(); });
    await tick(4000);
    expect({ tab1: shows(tab1), stored: academic(row.profile) }, '"Keep what I typed" in tab 1')
      .toEqual({ tab1: { asked: [], form: OWN1 }, stored: { ...OWN1, grade: 'Senior' } });
  });

  it('in a tab opened after a closed tab left its pick unsent (the M113 sequence), after a focus check (a guard; already so before M137)', async () => {
    const tab1 = await openTab('tab 1');
    writesFail = true;
    await choose(tab1, 'college', GIES);
    await choose(tab1, 'major', 'Finance');
    await tick(4000);
    tab1.unmount();
    await drain();
    const tab2 = await openTab('tab 2');
    await choose(tab2, 'college', LAS);
    await choose(tab2, 'major', 'Mathematics');
    await choose(tab2, 'grade', 'Senior');
    await tick(4000);
    writesFail = false;
    act(() => { window.dispatchEvent(new Event('focus')); });
    await tick(4000);
    expect(shows(tab2), 'tab 2 after a focus check').toEqual({ asked: ['college', 'major'], form: OWN1 });
    act(() => { tab2.form().keepMyChanges(); });
    await tick(4000);
    expect({ tab2: shows(tab2), stored: academic(row.profile) }, '"Keep what I typed" in tab 2')
      .toEqual({ tab2: { asked: [], form: OWN1 }, stored: { ...OWN1, grade: 'Senior' } });
  });

  it('when only the major differs, back online, and shows the answer once the other tab keeps its own', async () => {
    const tab1 = await openTab('tab 1');
    const tab2 = await openTab('tab 2');
    network(false);
    await tick(1500);
    await choose(tab1, 'major', 'Mathematics');
    await choose(tab2, 'major', 'Finance');
    await choose(tab2, 'grade', 'Senior');
    await tick(4000);
    network(true);
    await tick(1000);
    await tick(4000);
    const major = (tab: Tab) => ({ asked: asked(tab), major: tab.form().profile.major });
    expect({ tab1: major(tab1), tab2: major(tab2), stored: row.profile.major }, 'back online').toEqual({
      tab1: { asked: ['major'], major: 'Mathematics' }, tab2: { asked: ['major'], major: 'Finance' }, stored: 'Computer Science',
    });
    const before = sent.length;
    act(() => { tab2.form().keepMyChanges(); });
    await tick(4000);
    act(() => { window.dispatchEvent(new Event('focus')); });
    await tick(4000);
    expect({
      tab1: major(tab1), tab2: major(tab2), stored: row.profile.major, journal: described(outstanding(tab1)),
      sent: sent.slice(before).map((s) => [s.tab, s.keys, s.values.major, s.status]),
    }, '"Keep what I typed" in tab 2').toEqual({
      tab1: { asked: [], major: 'Finance' }, tab2: { asked: [], major: 'Finance' }, stored: 'Finance', journal: [],
      sent: [['tab 2', ['major'], 'Finance', 'applied']],
    });
  });
});
