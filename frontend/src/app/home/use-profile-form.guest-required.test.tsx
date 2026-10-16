import { act, cleanup, render, screen, within } from '@testing-library/react';
import { useEffect } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from '@/lib/supabase';
import type { ProfileData } from '@/lib/types';

const service = vi.hoisted(() => ({
  auth: null as null | ((state: { user: { id: string } | null }) => void),
  load: vi.fn<(signal?: AbortSignal) => Promise<LoadedProfile>>(),
  commit: vi.fn<(intent: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>(),
  params: new URLSearchParams(), router: { push: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() },
}));
vi.mock('next/navigation', () => ({ useRouter: () => service.router, useSearchParams: () => service.params }));
vi.mock('@/lib/api', () => ({ parseGitHubProfile: vi.fn() }));
vi.mock('@/lib/match-cache', () => ({ clearMatchCache: vi.fn(() => true) }));
// Only transport is replaced: the coordinator, the journal, the owner
// capabilities, Home's save handling and the status row are the real ones.
vi.mock('@/lib/supabase', () => ({
  loadProfile: (signal?: AbortSignal) => service.load(signal),
  commitProfilePatch: (intent: ProfilePatchIntent) => service.commit(intent),
  getStorageStatus: () => ({ status: 'synced', error: null }),
  onAuthChange: (callback: typeof service.auth) => { service.auth = callback; return () => { service.auth = null; }; },
}));
import { useProfileForm } from './use-profile-form';
import { SubmitRow } from './SubmitRow';
import { translate } from '@/i18n/translate';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { HOME_FORM_WRITER, readProfileSyncEnvelope, resetProfileDirtyLedger } from '@/lib/profile-sync';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { readOutstandingOps, resetJournalLaneForTests, startDocumentForTests } from '@/lib/profile-journal';

// A brand-new guest: the cloud has no row for them, and the server creates
// one only from a COMPLETE revision-0 patch (migration 20261011230618):
// anything else raises incomplete_create, which reaches the client as a
// transport error.
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
const ZH = (key: string) => translate('zh', key);
const live: { form: ReturnType<typeof useProfileForm> | null } = { form: null };
const form = () => live.form!;
/** The form with the status row wired as app/page.tsx wires it, once per locale. */
function Home() {
  const home = useProfileForm(EN);
  useEffect(() => { live.form = home; });
  return (
    <>
      {([['en', EN], ['zh', ZH]] as const).map(([locale, t]) => (
        <div key={locale} data-testid={`row-${locale}`}>
          <SubmitRow
            isValid={home.isValid}
            shareCopied={home.shareCopied}
            saveStatus={home.saveStatus}
            hydrationState={home.hydrationState}
            isSubmitting={home.isSubmitting}
            hasConflict={home.conflicts.length > 0}
            canRetrySync={home.canRetrySync}
            onRetrySync={home.retryCloudSave}
            onKeepMyChanges={home.keepMyChanges}
            onUseCloudVersion={home.useCloudVersion}
            onSubmit={home.handleSubmit}
            onShare={home.handleShare}
            t={t as never}
          />
        </div>
      ))}
    </>
  );
}
async function mount() {
  const view = render(<Home />);
  act(() => { service.auth?.({ user: { id: uid } }); }); await drain();
  expect(form().hydrationState).toBe('ready');
  return view;
}
async function edit<K extends keyof ProfileData>(key: K, value: ProfileData[K]) {
  act(() => { form().update(key, value); });
  await tick(1600);
}
function statusRow(locale: 'en' | 'zh') {
  return within(screen.getByTestId(`row-${locale}`)).getByRole('status');
}

beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  service.auth = null; service.params = new URLSearchParams();
  resetProfileDirtyLedger(); resetJournalLaneForTests();
  uid = `home-guest-required-${++sequence}`;
  advanceOwnerEpoch(null); advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  row = null;
  service.load.mockReset().mockImplementation(async () => read());
  service.commit.mockReset().mockImplementation(apply);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

describe('a fresh guest who has not filled in college, major and grade yet', () => {
  it('is told the edit is kept and what the save is waiting for — grey, no Retry, nothing sent — and the first complete create carries it', async () => {
    await mount();
    await edit('research_interests', 'robotics and control');

    expect(form().saveStatus).toBe('awaiting-required');
    expect(form().canRetrySync, 'nothing failed, so there is nothing to retry').toBe(false);
    expect(statusRow('en').textContent).toBe(
      'Your entries are kept in this browser. Fill in your college, major, and grade to save your profile.',
    );
    expect(statusRow('zh').textContent).toBe('已输入的内容保留在这个浏览器里。填好学院、专业和年级后，档案就会保存。');
    expect(screen.queryByTestId('retry-sync')).toBeNull();
    expect(screen.queryByText("Couldn't save your profile — please retry.")).toBeNull();
    expect(sends(), 'no save request').toEqual([]);

    // College alone, then major: still waiting, still nothing sent.
    await edit('college', 'Grainger College of Engineering');
    expect(form().saveStatus).toBe('awaiting-required');
    await edit('major', 'Computer Science');
    expect(form().saveStatus).toBe('awaiting-required');
    expect(sends()).toEqual([]);

    await edit('grade', 'Junior');
    expect(sends(), 'ONE create').toHaveLength(1);
    expect(sends()[0].expected).toBe(0);
    expect(sends()[0].patch).toMatchObject({
      research_interests: 'robotics and control',
      college: 'Grainger College of Engineering',
      major: 'Computer Science',
      grade: 'Junior',
    });
    expect(form().saveStatus).toBe('saved');
    expect(row).toMatchObject({ revision: 1, profile: { research_interests: 'robotics and control' } });
    expect(readProfileSyncEnvelope()?.pending ?? null).toBeNull();
    expect(readOutstandingOps()).toEqual({ ok: true, value: [] });
  });
});

// A new browser session is a new journal lineage (sessionStorage is empty),
// and nothing before the row exists ever drains: so one person's edits from
// two visits used to stay "Changed on another device" forever, the older
// value on screen and the newer one lost.
describe('a guest who comes back in a new browser session before the row exists', () => {
  const skills = (...names: string[]) => names.map((name) => ({ name, level: 'beginner' as const }));
  async function newSession() {
    cleanup(); await drain();
    resetJournalLaneForTests(); resetProfileDirtyLedger();
  }

  it("keeps the newer session's edit of a field the older one also edited, with no question, and creates the row with it", async () => {
    let view = await mount();
    await edit('skills', skills('Rust'));
    expect(form().saveStatus).toBe('awaiting-required');
    view.unmount();

    await newSession();
    view = await mount();
    expect(form().profile.skills.map((s) => s.name), 'the first visit is on screen').toEqual(['Rust']);
    expect(form().saveStatus).toBe('awaiting-required');
    await edit('skills', skills('Rust', 'Julia'));
    view.unmount();

    // A reload of that session.
    cleanup(); await drain();
    startDocumentForTests('reload'); resetProfileDirtyLedger();
    view = await mount();
    // The newer edit REPLACES the list: it is the whole list that session
    // showed (the first visit's Rust) plus Julia, not a merge of the two.
    expect(form().profile.skills.map((s) => s.name)).toEqual(['Rust', 'Julia']);
    expect(form().conflictKeys, 'no question about the person\'s own two visits').toEqual([]);
    expect(form().conflicts).toEqual([]);
    expect(form().saveStatus).toBe('awaiting-required');
    expect(screen.queryByText(/Changed on another device/)).toBeNull();
    expect(sends()).toEqual([]);

    await edit('college', 'Grainger College of Engineering');
    await edit('major', 'Computer Science');
    await edit('grade', 'Junior');
    expect(sends(), 'ONE create').toHaveLength(1);
    expect(sends()[0].patch.skills).toEqual(skills('Rust', 'Julia'));
    expect(form().saveStatus).toBe('saved');
    expect(readOutstandingOps(), 'both visits\' edits are settled by it').toEqual({ ok: true, value: [] });
    expect(readProfileSyncEnvelope()?.pending ?? null).toBeNull();
  });

  it('creates the row with the college picked last, never a create without one', async () => {
    let view = await mount();
    await edit('college', 'Grainger College of Engineering');
    view.unmount();

    await newSession();
    view = await mount();
    expect(form().profile.college).toBe('Grainger College of Engineering');
    await edit('college', 'College of Liberal Arts & Sciences');
    await edit('major', 'Mathematics');
    await edit('grade', 'Sophomore');

    expect(sends(), 'ONE create, complete').toHaveLength(1);
    expect(sends()[0].patch).toMatchObject({
      college: 'College of Liberal Arts & Sciences', major: 'Mathematics', grade: 'Sophomore',
    });
    expect(form().saveStatus).toBe('saved');
    expect(form().conflictKeys).toEqual([]);
    expect(row?.profile.college).toBe('College of Liberal Arts & Sciences');
    expect(readOutstandingOps()).toEqual({ ok: true, value: [] });
  });
});

// College, major and grade all filled in, and still no create: either nothing
// can reach a server this visit, or a question holds one of them back.
// Neither is "fill in your college, major, and grade".
describe('a guest whose college, major and grade are all filled in, two visits apart', () => {
  const FILL_IN = 'Fill in your college, major, and grade';
  async function newSession() {
    cleanup(); await drain();
    resetJournalLaneForTests(); resetProfileDirtyLedger();
  }

  it('with no backend this visit (anonymous sign-in failed): kept on this device and Generate goes ahead, as before', async () => {
    service.load.mockReset().mockImplementation(async () => (
      { source: 'local-only', profile: null, revision: 0, token: captureOwnerToken() }));
    service.commit.mockReset().mockImplementation(async () => ({ status: 'local-only' }));
    let view = await mount();
    await edit('college', 'Grainger College of Engineering');
    await edit('major', 'Computer Science');
    await edit('grade', 'Junior');
    expect(form().saveStatus).toBe('device-only');
    view.unmount();

    await newSession();
    view = await mount();
    await edit('college', 'College of Liberal Arts & Sciences');
    await edit('major', 'Mathematics');
    expect([form().profile.college, form().profile.major, form().profile.grade])
      .toEqual(['College of Liberal Arts & Sciences', 'Mathematics', 'Junior']);
    expect(form().saveStatus).toBe('device-only');
    expect(statusRow('en').textContent).not.toContain(FILL_IN);

    service.router.push.mockClear();
    await act(async () => { await form().handleSubmit(); }); await drain();
    expect(service.router.push, 'Generate is not refused').toHaveBeenCalledTimes(1);
  });

  it('with the cloud reachable: the question about the earlier visit is asked, with its buttons, and once answered Generate creates the row', async () => {
    // The earlier visit was served by the previous build: its operations
    // carry no clock, so they are never ranked against this visit's.
    for (const [key, value] of [['college', 'Grainger College of Engineering'], ['grade', 'Junior']] as const) {
      const opId = crypto.randomUUID();
      localStorage.setItem(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_${opId}`, JSON.stringify({
        opId, originId: 'doc-visit-1', lineage: 'visit-1',
        fields: [{ key, base: { present: false }, desired: { present: true, value } }],
        baseRevision: 0, writer: HOME_FORM_WRITER, mode: 'set', seq: 1,
      }));
    }
    await mount();
    expect(form().profile.college).toBe('Grainger College of Engineering');
    await edit('college', 'College of Liberal Arts & Sciences');
    // Major really is blank here, so that is what the status says.
    expect(form().saveStatus).toBe('awaiting-required');
    await edit('major', 'Mathematics');

    expect([form().profile.college, form().profile.major, form().profile.grade])
      .toEqual(['College of Liberal Arts & Sciences', 'Mathematics', 'Junior']);
    expect(form().saveStatus).toBe('conflict');
    expect(form().conflictKeys).toEqual(['college']);
    expect(statusRow('en').textContent).not.toContain(FILL_IN);
    expect(screen.getAllByTestId('conflict-keep-mine').length).toBeGreaterThan(0);
    expect(sends(), 'no create without college').toEqual([]);

    act(() => { form().keepMyChanges(); }); await tick(1600);
    expect(form().conflictKeys).toEqual([]);
    service.router.push.mockClear();
    await act(async () => { await form().handleSubmit(); }); await drain();
    expect(sends(), 'ONE create, complete').toHaveLength(1);
    expect(sends()[0].patch).toMatchObject({
      college: 'College of Liberal Arts & Sciences', major: 'Mathematics', grade: 'Junior',
    });
    expect(service.router.push).toHaveBeenCalledTimes(1);
  });
});
