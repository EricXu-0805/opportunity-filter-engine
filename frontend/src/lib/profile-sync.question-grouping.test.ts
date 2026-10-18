// Checklist M113 and M116. A question about a field is published from the
// journal's chains of edits (one per tab, its latest value), and an answer is
// accepted only while the question it answers is still the current one. Both
// must read the journal the same way, recorded answers included, or a
// question no tab can answer is published again on every load.
import { beforeEach, expect, it, vi } from 'vitest';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from './supabase';
import type { ProfileData } from './types';

const service = vi.hoisted(() => ({
  load: vi.fn<() => Promise<LoadedProfile>>(),
  commit: vi.fn<(intent: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>(),
}));
vi.mock('./supabase', () => ({
  loadProfile: () => service.load(),
  commitProfilePatch: (intent: ProfilePatchIntent) => service.commit(intent),
}));

const UID = 'question-grouping-owner';
const base: ProfileData = {
  name: 'Synthetic student', institution: 'UIUC', home_school: 'uiuc', college: 'Gies',
  major: 'Finance', grade: 'Sophomore', is_international: false,
  research_interests: 'initial research', skills: [], search_weight: 50,
};

// One row, its revision and a compare-and-set on it. While `offline` every
// request fails like a dropped network.
const server = { revision: 7, profile: { ...base } as Record<string, unknown>, offline: false, sent: [] as ProfilePatchIntent[] };
function serverCommit(intent: ProfilePatchIntent): ProfilePatchOutcome {
  server.sent.push(intent);
  if (server.offline) return { status: 'transport-error', message: 'offline' };
  if (intent.expectedRevision !== server.revision) {
    return { status: 'conflict', revision: server.revision, profile: { ...server.profile } };
  }
  const next = { ...server.profile };
  for (const [k, v] of Object.entries(intent.patch)) {
    if (v === undefined) delete next[k]; else next[k] = v;
  }
  server.profile = next;
  server.revision += 1;
  return { status: 'saved', revision: server.revision, profile: { ...next } };
}
/** Another device (the phone) saves straight to the server. */
function phoneSaves(patch: Partial<ProfileData>) {
  server.profile = { ...server.profile, ...patch };
  server.revision += 1;
}

// Each module graph is one tab (own coordinator, journal lane and lineage)
// over the same localStorage and Web Locks; its screen is the view it holds.
async function openTab() {
  vi.resetModules();
  const identity = await import('./identity-owner');
  identity.advanceOwnerEpoch(UID);
  expect(await identity.syncLocalIdentityOwner(UID)).toBe(true);
  const sync = await import('./profile-sync');
  const journal = await import('./profile-journal');
  return { identity, sync, journal, token: identity.captureOwnerToken(), view: null as unknown as ReturnType<typeof sync.makeProfileViewSnapshot> };
}
type Tab = Awaited<ReturnType<typeof openTab>>;
type Conflicts = readonly import('./profile-sync').ProfileConflict[];

/** A page load (or the periodic profile check). */
async function load(tab: Tab) {
  service.load.mockImplementationOnce(async () => ({
    source: 'cloud', profile: { ...server.profile }, revision: server.revision, token: tab.token,
  }));
  const h = await tab.sync.hydrateProfile();
  tab.view = tab.sync.makeProfileViewSnapshot({
    renderedProfile: h.profile!, baseProfile: h.baseProfile, revision: h.revision,
    token: tab.token, identityGeneration: tab.token.epoch, source: 'hydration',
  });
  return h;
}

/** One user action in a tab, written against what that tab shows. */
function edit(tab: Tab, patch: Partial<ProfileData>) {
  const keys = Object.keys(patch) as Array<keyof ProfileData>;
  const desiredAfter = { ...tab.view.renderedProfile, ...patch } as ProfileData;
  const done = tab.sync.commitProfileAction({ view: tab.view, desiredAfter, keys, writer: 'home-form', allowCreate: false });
  tab.view = tab.sync.withRenderedProfile(tab.view, desiredAfter);
  return done;
}

function answer(tab: Tab, conflicts: Conflicts, choice: 'local' | 'cloud') {
  return tab.sync.resolveProfileConflict({ prompt: tab.sync.makeConflictPrompt(tab.view, conflicts), actionView: tab.view, choice });
}

function summary(conflicts: Conflicts) {
  // Candidate order follows random op ids; sorted so a summary is stable.
  return conflicts.map((c) => ({ key: c.key, candidates: c.candidates.map((x) => ({ v: x.value, n: x.opIds.length }))
    .sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))) }));
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  server.revision = 7; server.profile = { ...base }; server.offline = false; server.sent = [];
  service.load.mockReset();
  service.commit.mockReset();
  service.commit.mockImplementation(async (intent) => serverCommit(intent));
});

/** Two visits offline each switch college (which clears the major) and then
 *  pick a major; the second also changes the year. */
async function collegeAndMajorFromTwoVisits() {
  server.offline = true;
  const first = await openTab();
  await load(first);
  await edit(first, { college: 'Grainger', major: '' });
  await edit(first, { major: 'Computer Science' });
  const second = await openTab();
  await load(second);
  await edit(second, { college: 'LAS', major: '' });
  await edit(second, { major: 'Mathematics' });
  await edit(second, { grade: 'Junior' });
  server.offline = false;
  return { first, second };
}

it.each([
  ['second', 'local', { college: 'LAS', major: 'Mathematics' }],
  ['second', 'cloud', { college: 'Gies', major: 'Finance' }],
  ['first', 'local', { college: 'Grainger', major: 'Computer Science' }],
  ['first', 'cloud', { college: 'Gies', major: 'Finance' }],
] as const)('M113: the college/major question from two visits is answered in the %s tab with %s, and goes away', async (who, choice, kept) => {
  const { first, second } = await collegeAndMajorFromTwoVisits();
  const tab = who === 'first' ? first : second;
  const h = await load(tab);
  // One candidate per visit, its latest value, every one of its edits.
  expect(summary(h.conflicts)).toEqual([
    { key: 'college', candidates: [{ v: 'Grainger', n: 1 }, { v: 'LAS', n: 1 }] },
    { key: 'major', candidates: [{ v: 'Computer Science', n: 2 }, { v: 'Mathematics', n: 2 }] },
  ]);
  // The question the answer is checked against is the one published.
  expect(summary(tab.sync.readCurrentConflicts(h.conflictKeys, tab.token))).toEqual(summary(h.conflicts));
  // Saved either way: the unasked year goes out with the answer.
  expect((await answer(tab, h.conflicts, choice)).status).toBe('saved');
  expect(server.profile).toMatchObject({ ...kept, grade: 'Junior' });
  for (const t of [first, second]) expect((await load(t)).conflicts).toEqual([]);
});

it.each(['local', 'cloud'] as const)('M113: a question about a field typed continuously in one tab is answered with %s', async (choice) => {
  server.offline = true;
  const first = await openTab();
  await load(first);
  await edit(first, { research_interests: 'robot' });
  await edit(first, { research_interests: 'robotics' });
  const second = await openTab();
  await load(second);
  await edit(second, { research_interests: 'ecology' });
  server.offline = false;
  const h = await load(second);
  expect(summary(h.conflicts)).toEqual([
    { key: 'research_interests', candidates: [{ v: 'ecology', n: 1 }, { v: 'robotics', n: 2 }] },
  ]);
  const r = await answer(second, h.conflicts, choice);
  expect(r.status).toBe(choice === 'local' ? 'saved' : 'already-saved');
  expect(server.profile.research_interests).toBe(choice === 'local' ? 'ecology' : 'initial research');
  expect((await load(first)).conflicts).toEqual([]);
});

it('M113 control: a question where each tab typed one value is published as before and answered', async () => {
  server.offline = true;
  const first = await openTab();
  await load(first);
  await edit(first, { research_interests: 'robotics' });
  const second = await openTab();
  await load(second);
  await edit(second, { research_interests: 'ecology' });
  server.offline = false;
  const h = await load(second);
  expect(summary(h.conflicts)).toEqual([
    { key: 'research_interests', candidates: [{ v: 'ecology', n: 1 }, { v: 'robotics', n: 1 }] },
  ]);
  expect((await answer(second, h.conflicts, 'local')).status).toBe('saved');
  expect(server.profile.research_interests).toBe('ecology');
});

/** Tab A's year edit is refused (the phone saved first); tab B is asked about
 *  it and answers, and the phone saves `phonePatch` before B's answer lands. */
async function answerOvertakenByPhone(phonePatch: Partial<ProfileData>) {
  const a = await openTab();
  await load(a);
  const b = await openTab();
  await load(b);
  phoneSaves({ grade: 'Senior' });
  expect((await edit(a, { grade: 'Junior' })).result?.status).toBe('conflict');
  const asked = await load(b);
  expect(summary(asked.conflicts)).toEqual([{ key: 'grade', candidates: [{ v: 'Junior', n: 1 }] }]);
  service.commit.mockImplementationOnce(async (intent) => { phoneSaves(phonePatch); return serverCommit(intent); });
  const kept = await answer(b, asked.conflicts, 'local');
  return { a, b, kept: kept.status };
}

it.each([
  ['b', 'local', 'saved', [10, 'Junior']],
  ['b', 'cloud', 'already-saved', [9, 'Freshman']],
  ['a', 'local', 'saved', [10, 'Junior']],
  ['a', 'cloud', 'already-saved', [9, 'Freshman']],
] as const)('M116: after an answer is overtaken by a phone save, the next answer (tab %s, %s) decides the question', async (who, choice, status, final) => {
  const { a, b, kept } = await answerOvertakenByPhone({ grade: 'Freshman' });
  expect(kept).toBe('conflict');
  const tab = who === 'a' ? a : b;
  const h = await load(tab);
  // The earlier answer is the candidate: it is what is asked about.
  expect(summary(h.conflicts)).toEqual([{ key: 'grade', candidates: [{ v: 'Junior', n: 1 }] }]);
  expect(h.conflicts[0].remote).toBe('Freshman');
  const sentBefore = server.sent.length;
  const r = await answer(tab, h.conflicts, choice);
  expect(r.status).toBe(status);
  expect(server.sent.slice(sentBefore).map((x) => [x.expectedRevision, x.patch.grade]))
    .toEqual(status === 'saved' ? [[9, 'Junior']] : []);
  expect([server.revision, server.profile.grade]).toEqual(final);
  for (const t of [a, b]) expect((await load(t)).conflicts).toEqual([]);
  const left = b.journal.readOutstandingOps();
  expect(left.ok && left.value).toEqual([]);
});

it('M116 control: a phone save on another field does not stop the answer', async () => {
  const { a, b, kept } = await answerOvertakenByPhone({ name: 'Phone name' });
  expect(kept).toBe('saved');
  expect(server.profile).toMatchObject({ grade: 'Junior', name: 'Phone name' });
  for (const t of [a, b]) expect((await load(t)).conflicts).toEqual([]);
});
