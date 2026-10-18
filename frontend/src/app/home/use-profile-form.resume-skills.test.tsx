import { act, cleanup, render } from '@testing-library/react';
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
// Only transport is replaced: the coordinator, the journal, the owner
// capabilities and Home's save handling are the real ones.
vi.mock('@/lib/supabase', () => ({
  loadProfile: (signal?: AbortSignal) => service.load(signal),
  commitProfilePatch: (intent: ProfilePatchIntent) => service.commit(intent),
  getStorageStatus: () => ({ status: 'synced', error: null }),
  onAuthChange: (callback: typeof service.auth) => { service.auth = callback; return () => { service.auth = null; }; },
}));
// A résumé whose every line is one PDF text item, read by the real parser.
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
import { parseResumePDF } from '@/lib/pdf-parser';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { resetProfileDirtyLedger } from '@/lib/profile-sync';
import { resetJournalLaneForTests, startDocumentForTests } from '@/lib/profile-journal';

// Checklist M18: the skills a résumé brought, after that résumé is replaced
// or removed, in the form, the cloud row and the request an email is written
// from, including the writes of a tab still on the previous build.

let row: { profile: ProfileData; revision: number } | null;
let uid: string;
let sequence = 0;
function read(): LoadedProfile {
  const token = captureOwnerToken();
  return row
    ? { source: 'cloud', profile: structuredClone(row.profile) as unknown as Record<string, unknown>, revision: row.revision, token }
    : { source: 'cloud-absent', profile: null, revision: 0, token };
}
function completeCreate(patch: Record<string, unknown>): boolean {
  const filled = (k: string) => typeof patch[k] === 'string' && (patch[k] as string).trim() !== '';
  return 'home_school' in patch && filled('college') && filled('major') && filled('grade')
    && typeof patch.search_weight === 'number' && patch.search_weight >= 0 && patch.search_weight <= 100;
}
async function apply(intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> {
  if (!row) {
    if (intent.expectedRevision !== 0) return { status: 'missing', reason: 'absent' };
    if (!completeCreate(intent.patch)) {
      return { status: 'transport-error', message: 'commit_profile_patch_cas: incomplete_create' };
    }
    row = { profile: structuredClone(intent.patch) as unknown as ProfileData, revision: 1 };
    return { status: 'saved', profile: structuredClone(row.profile) as unknown as Record<string, unknown>, revision: 1 };
  }
  const answer = () => structuredClone(row!.profile) as unknown as Record<string, unknown>;
  if (intent.expectedRevision !== row.revision) return { status: 'conflict', profile: answer(), revision: row.revision };
  row.profile = { ...row.profile, ...intent.patch } as ProfileData; row.revision += 1;
  return { status: 'saved', profile: answer(), revision: row.revision };
}
/** A tab on the previous build writes its patch the same way: per key, merged. */
function previousBuildWrites(patch: Partial<ProfileData>) {
  row = { profile: { ...row!.profile, ...patch }, revision: row!.revision + 1 };
}
const sends = () => service.commit.mock.calls.map(([intent]) => ({ expected: intent.expectedRevision, patch: intent.patch }));
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
async function reload(view: ReturnType<typeof render>) {
  view.unmount();
  cleanup(); await drain(); startDocumentForTests('reload'); resetProfileDirtyLedger();
  return mount();
}
async function edit<K extends keyof ProfileData>(key: K, value: ProfileData[K]) {
  act(() => { form().update(key, value); });
  await tick(1600);
}
async function importResume(...lines: string[]) {
  pdf.lines = lines;
  const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], 'resume.pdf', { type: 'application/pdf' });
  const parsed: ResumeParseResponse = await parseResumePDF(file);
  expect(parsed.success).toBe(true);
  act(() => { expect(form().handleResumeParsed(parsed)).toBe(true); });
  await tick(1600);
}
async function removeResume() {
  await act(async () => { expect(form().handleResumeRemoved()).toBe(true); });
  await tick(1600);
}

const SIGNED_UP: ProfileData = {
  name: '', institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering',
  major: 'Computer Science', grade: 'Junior', is_international: false, research_interests: 'robotics', skills: [],
  search_weight: 50,
};

beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  service.auth = null; service.params = new URLSearchParams();
  resetProfileDirtyLedger(); resetJournalLaneForTests();
  uid = `home-resume-skills-${++sequence}`;
  advanceOwnerEpoch(null); advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  row = null;
  service.load.mockReset().mockImplementation(async () => read());
  service.commit.mockReset().mockImplementation(apply);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

const A = ['Skills: Python, MATLAB, Java, Docker, Linux'];
const B = ['Built a Python and Java web app for the lab'];
const names = () => form().profile.skills.map((skill) => skill.name);
const stored = (name: string) => row?.profile.skills.find((skill) => skill.name === name);
/** The skills every email, draft and match request is written from. */
async function requested(): Promise<string[]> {
  const { toProfileRequest } = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return toProfileRequest(form().profile).hard_skills.map((skill) => skill.name);
}

describe('a replaced résumé takes the skills only it named with it', () => {
  it('drops a skill the new résumé does not name and gives one it does name the new line (live 2026-10-17)', async () => {
    row = { revision: 1, profile: SIGNED_UP };
    await mount();
    await importResume(...A);
    expect(names()).toEqual(['Python', 'Java', 'MATLAB', 'Linux', 'Docker']);
    await importResume(...B);
    expect(names()).toEqual(['Python', 'Java']);
    expect(row?.profile.skills).toEqual([
      { name: 'Python', level: 'beginner', source: 'resume', evidence: B[0] },
      { name: 'Java', level: 'beginner', source: 'resume', evidence: B[0] },
    ]);
    expect(JSON.stringify(row?.profile)).not.toContain(A[0]);
  });

  it('writes the email request from the new résumé\'s skills only, and a tab on the previous build does not bring the old ones back', async () => {
    row = { revision: 1, profile: SIGNED_UP };
    const view = await mount();
    await importResume(...A);
    await importResume(...B);
    expect(await requested()).toEqual(['Python', 'Java']);
    previousBuildWrites({ research_interests: 'controls' });
    await reload(view);
    expect(form().profile.research_interests).toBe('controls');
    expect(await requested()).toEqual(['Python', 'Java']);
  });

  it('keeps a skill the student confirmed, without the old résumé\'s line, and gives one the new résumé names its line', async () => {
    row = { revision: 1, profile: SIGNED_UP };
    await mount();
    await importResume(...A);
    await edit('skills', form().profile.skills.map((skill) => (
      skill.name === 'MATLAB' ? { ...skill, level: 'experienced', confirmed: true }
        : skill.name === 'Java' ? { ...skill, confirmed: true } : skill)));
    await importResume(...B);
    expect(row?.profile.skills).toEqual([
      { name: 'Python', level: 'beginner', source: 'resume', evidence: B[0] },
      { name: 'Java', level: 'beginner', source: 'resume', confirmed: true, evidence: B[0] },
      { name: 'MATLAB', level: 'experienced', source: 'resume', confirmed: true },
    ]);
    expect(await requested()).toEqual(['Python', 'Java', 'MATLAB']);
  });

  it('keeps a skill from GitHub and a skill the student typed, though the old résumé named them too', async () => {
    const github = { name: 'Docker', level: 'beginner' as const, source: 'github' as const, evidence: 'repo lab-tools: language Dockerfile' };
    const typed = { name: 'Linux', level: 'beginner' as const };
    row = { revision: 1, profile: { ...SIGNED_UP, skills: [github, typed] } };
    await mount();
    await importResume(...A);
    expect(names()).toEqual(['Docker', 'Linux', 'Python', 'Java', 'MATLAB']);
    await importResume(...B);
    expect(row?.profile.skills).toEqual([
      github, typed,
      { name: 'Python', level: 'beginner', source: 'resume', evidence: B[0] },
      { name: 'Java', level: 'beginner', source: 'resume', evidence: B[0] },
    ]);
  });
});

describe('a replacement meeting a skill list another tab changed', () => {
  it('asks which list to keep rather than merging the new skills into one that still holds the old résumé\'s', async () => {
    row = { revision: 1, profile: SIGNED_UP };
    await mount();
    await importResume(...A);
    // The student deletes Docker in a tab on the previous build; this tab has not read it.
    const olderTab = row!.profile.skills.filter((skill) => skill.name !== 'Docker');
    previousBuildWrites({ skills: olderTab });
    await importResume(...B);
    expect(row?.profile.skills).toEqual(olderTab);
    expect(row?.profile.resume_text).toBe(B[0]);
    expect(form().conflicts.map((question) => question.key)).toEqual(['skills']);
  });
});

describe('a removed résumé takes the skills only it named with it', () => {
  it('drops every résumé skill the student did not confirm and keeps the rest without the résumé\'s lines', async () => {
    const github = { name: 'Docker', level: 'beginner' as const, source: 'github' as const, evidence: 'repo lab-tools: language Dockerfile' };
    const typed = { name: 'Linux', level: 'beginner' as const };
    row = { revision: 1, profile: { ...SIGNED_UP, skills: [github, typed] } };
    await mount();
    await importResume(...A);
    await edit('skills', form().profile.skills.map((skill) => (skill.name === 'Java' ? { ...skill, confirmed: true } : skill)));
    await removeResume();
    expect(row?.profile.resume_text).toBe('');
    expect(row?.profile.skills).toEqual([github, typed, { name: 'Java', level: 'beginner', source: 'resume', confirmed: true }]);
    expect(names()).toEqual(['Docker', 'Linux', 'Java']);
    expect(await requested()).toEqual(['Docker', 'Linux', 'Java']);
    expect(JSON.stringify(row?.profile)).not.toContain(A[0]);
  });
});
