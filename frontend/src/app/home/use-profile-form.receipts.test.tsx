// Checklist M114: every landed journal operation used to leave a rebase
// receipt holding the whole row, and nothing removed one, so on one device
// saving stopped for good at the 500th. These are the form's own actions,
// through its real debounces, the real coordinator and journal, and a
// storage that enforces a 2.5M-character quota.
import { act, cleanup, render } from '@testing-library/react';
import { readFileSync } from 'fs';
import { join } from 'path';
import { useEffect } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from '@/lib/supabase';
import type { ProfileData, ResumeParseResponse } from '@/lib/types';

const service = vi.hoisted(() => ({
  auth: null as null | ((state: { user: { id: string } | null }) => void),
  load: vi.fn<(signal?: AbortSignal) => Promise<LoadedProfile>>(),
  commit: vi.fn<(intent: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>(),
  params: new URLSearchParams(), router: { push: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() },
}));
const pdf = vi.hoisted(() => ({ lines: [] as string[] }));
vi.mock('next/navigation', () => ({ useRouter: () => service.router, useSearchParams: () => service.params }));
vi.mock('@/lib/api', () => ({ parseGitHubProfile: vi.fn() }));
vi.mock('@/lib/match-cache', () => ({ clearMatchCache: vi.fn(() => true) }));
vi.mock('@/lib/supabase', () => ({
  loadProfile: (signal?: AbortSignal) => service.load(signal),
  commitProfilePatch: (intent: ProfilePatchIntent) => service.commit(intent),
  getStorageStatus: () => ({ status: 'synced', error: null }),
  onAuthChange: (callback: typeof service.auth) => { service.auth = callback; return () => { service.auth = null; }; },
}));
vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: { workerSrc: '' },
  getDocument: () => ({ promise: Promise.resolve({
    numPages: pdf.lines.length,
    destroy: async () => {},
    getPage: async (n: number) => ({ cleanup: () => {}, getTextContent: async () => ({ items: [{ str: pdf.lines[n - 1] }] }) }),
  }) }),
}));
import { useProfileForm } from './use-profile-form';
import { translate } from '@/i18n/translate';
import { courseRows, storedCourse } from '@/lib/course-status';
import { parseResumePDF } from '@/lib/pdf-parser';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { resetProfileDirtyLedger } from '@/lib/profile-sync';
import { resetJournalLaneForTests } from '@/lib/profile-journal';

let row: { profile: ProfileData; revision: number } | null;
let uid: string;
let sequence = 0;
function read(): LoadedProfile {
  const token = captureOwnerToken();
  return row
    ? { source: 'cloud', profile: structuredClone(row.profile) as unknown as Record<string, unknown>, revision: row.revision, token }
    : { source: 'cloud-absent', profile: null, revision: 0, token };
}
async function apply(intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> {
  const answer = () => structuredClone(row!.profile) as unknown as Record<string, unknown>;
  if (intent.expectedRevision !== row!.revision) return { status: 'conflict', profile: answer(), revision: row!.revision };
  row!.profile = { ...row!.profile, ...intent.patch } as ProfileData; row!.revision += 1;
  return { status: 'saved', profile: answer(), revision: row!.revision };
}
async function drain() {
  for (let pass = 0; pass < 4; pass += 1) {
    await act(async () => { for (let i = 0; i < 40; i += 1) await Promise.resolve(); });
  }
}
async function tick(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); await drain();
}
const EN = (key: string) => translate('en', key);
const live: { form: ReturnType<typeof useProfileForm> | null } = { form: null };
const form = () => live.form!;
function Home() {
  const home = useProfileForm(EN);
  useEffect(() => { live.form = home; });
  return null;
}
async function mount() {
  const view = render(<Home />);
  act(() => { service.auth?.({ user: { id: uid } }); }); await drain();
  expect(form().hydrationState).toBe('ready');
  return view;
}

// Browsers count key + value UTF-16 code units against the quota.
const writes = { receiptChars: 0 };
let quota = Infinity;
function installStorage() {
  const store = new Map<string, string>();
  const used = () => { let n = 0; for (const [k, v] of store) n += k.length + v.length; return n; };
  const storage = {
    get length() { return store.size; },
    key: (i: number) => [...store.keys()][i] ?? null,
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => {
      const before = store.get(k);
      const next = used() - (before === undefined ? 0 : k.length + before.length) + k.length + String(v).length;
      if (next > quota) throw new DOMException('quota', 'QuotaExceededError');
      store.set(k, String(v));
      if (k.includes('journal_v1_rebase_')) writes.receiptChars += k.length + String(v).length;
    },
    removeItem: (k: string) => { store.delete(k); },
    clear: () => { store.clear(); },
  };
  Object.defineProperty(window, 'localStorage', { value: storage, configurable: true });
  return { store, used };
}
let mem: ReturnType<typeof installStorage>;
const receipts = () => [...mem.store.entries()].filter(([k]) => k.includes('journal_v1_rebase_'));
const ops = () => [...mem.store.keys()].filter((k) => k.includes('journal_v1_op_')).length;

const SIGNED_UP: ProfileData = {
  name: '', institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering',
  major: 'Computer Science', grade: 'Junior', is_international: false, research_interests: 'robotics', skills: [],
  search_weight: 50,
};
const PERSONA = readFileSync(join(__dirname, '../../lib/__fixtures__/resume-pdf/persona.txt'), 'utf8').split('\n').filter(Boolean);
const SENTENCE = 'Machine learning for medical imaging and robotic perception.';

beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  mem = installStorage();
  quota = 2_500_000; writes.receiptChars = 0;
  service.auth = null; service.params = new URLSearchParams();
  resetProfileDirtyLedger(); resetJournalLaneForTests();
  uid = `receipts-${++sequence}`;
  advanceOwnerEpoch(null); advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  row = { revision: 1, profile: SIGNED_UP };
  service.load.mockReset().mockImplementation(async () => read());
  service.commit.mockReset().mockImplementation(apply);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

async function importResume() {
  pdf.lines = PERSONA;
  const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], 'resume.pdf', { type: 'application/pdf' });
  const parsed: ResumeParseResponse = await parseResumePDF(file);
  expect(parsed.success).toBe(true);
  act(() => { expect(form().handleResumeParsed(parsed)).toBe(true); });
  await tick(1600);
}
async function typeSentence(msPerChar: number, pauseAtSpace = 0) {
  const start = form().profile.research_interests ?? '';
  const base = start.length > 200 ? '' : start + ' ';
  for (let i = 0; i < SENTENCE.length; i += 1) {
    act(() => { form().update('research_interests', base + SENTENCE.slice(0, i + 1)); });
    await tick(SENTENCE[i] === ' ' && pauseAtSpace ? pauseAtSpace : msPerChar);
  }
  await tick(1600);
}
async function collegeThenMajor(n: number) {
  act(() => { form().update('college', n % 2 ? 'Gies College of Business' : 'Grainger College of Engineering'); });
  await tick(2500);
  act(() => { form().update('major', n % 2 ? 'Accountancy' : 'Computer Science'); });
  await tick(1600);
}
async function fiveStatuses(n: number) {
  const marks = ['completed', 'in_progress', 'planned'] as const;
  for (let i = 0; i < 5; i += 1) {
    const rows = courseRows(form().profile);
    const at = i % rows.length;
    const next = rows.map((r, j) => storedCourse(j === at ? { ...r, marked: marks[(n + i) % 3] } : r));
    act(() => { form().update('courses', next, 'status'); });
    await tick(1000);
  }
  await tick(1600);
}

describe('ordinary use keeps saving on one device (M114)', () => {
  it('saves every action well past the old 500-receipt cap, with receipts and storage bounded', async () => {
    await mount();
    await importResume();
    let most = 0;
    let largest = 0;
    const check = async (label: string) => {
      // The autosave can be re-armed by the status line's own timers; wait
      // for it rather than for a fixed delay.
      for (let i = 0; i < 10 && form().saveStatus === 'saving'; i += 1) await tick(1000);
      expect(['saved', 'idle'], label).toContain(form().saveStatus);
      expect(ops(), `${label}: nothing left unacknowledged`).toBe(0);
      most = Math.max(most, receipts().length);
      largest = Math.max(largest, mem.used());
    };
    // 120 rounds of five status clicks write 600 receipts, and every tenth
    // round a sentence typed with pauses and a college-then-major change add
    // 18 more. Saving used to stop in round 100.
    for (let round = 0; round < 120; round += 1) {
      await fiveStatuses(round);
      await check(`round ${round + 1}: five statuses`);
      if (round % 10 !== 9) continue;
      await typeSentence(180, 700);
      await check(`round ${round + 1}: a sentence`);
      await collegeThenMajor(round);
      await check(`round ${round + 1}: college then major`);
    }
    expect(row!.revision).toBe(2 + 120 + 12 * 3);
    // Far more than the quota was written to receipts, and almost none of it
    // is kept: nothing reaches a receipt once its own save has settled.
    expect(writes.receiptChars).toBeGreaterThan(quota);
    expect(most).toBe(0);
    expect(largest).toBeLessThan(20_000);
  }, 120_000);
});
