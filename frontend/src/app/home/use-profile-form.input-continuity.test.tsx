import { useEffect } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  auth: null as null | ((state: { user: { id: string } | null }) => void),
  load: vi.fn(), commit: vi.fn(),
  params: new URLSearchParams(), router: { push: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() },
}));
vi.mock('next/navigation', () => ({ useRouter: () => mocks.router, useSearchParams: () => mocks.params }));
vi.mock('@/lib/api', () => ({ parseGitHubProfile: vi.fn() }));
vi.mock('@/lib/match-cache', () => ({ clearMatchCache: vi.fn(() => true) }));
vi.mock('@/lib/catalogs', () => ({ loadCatalog: () => new Promise(() => {}) }));
vi.mock('@/i18n/client', () => ({ useLocale: () => 'en', useT: () => ({ t: (key: string) => key, locale: 'en' }) }));
vi.mock('@/lib/supabase', () => ({
  loadProfile: () => mocks.load(), commitProfilePatch: (...args: unknown[]) => mocks.commit(...args),
  getStorageStatus: () => ({ status: 'local-only', error: null }),
  onAuthChange: (callback: typeof mocks.auth) => { mocks.auth = callback; return () => { mocks.auth = null; }; },
}));
import { useProfileForm, type UseProfileFormResult } from './use-profile-form';
import { DEFAULT_PROFILE } from './types';
import { AcademicProfileCard } from './AcademicProfileCard';
import { advanceOwnerEpoch, captureOwnerToken, enterLocalOnlyMode, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { resetProfileDirtyLedger } from '@/lib/profile-sync';
import { resetJournalLaneForTests } from '@/lib/profile-journal';
const t = (key: string) => key;
let currentForm: UseProfileFormResult;
function HomeInputs() {
  const form = useProfileForm(t);
  useEffect(() => { currentForm = form; });
  // This is the actual page.tsx identity key, with the real hook and card.
  return <AcademicProfileCard key={form.academicIdentityGeneration} profile={form.profile}
    update={form.update} viewSnapshot={form.viewSnapshot} identityGeneration={form.identityGeneration} t={t} />;
}
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  resetProfileDirtyLedger(); resetJournalLaneForTests(); advanceOwnerEpoch(null);
  expect(enterLocalOnlyMode()).toBe(true);
  mocks.auth = null; mocks.load.mockReset().mockReturnValue(new Promise(() => {})); mocks.commit.mockReset();
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

describe('Home input continuity during the first auth observation', () => {
  it('keeps the focused research field attached when the first no-user observation arrives', () => {
    const view = render(<HomeInputs />);
    const name = view.container.querySelector('#student_name') as HTMLInputElement;
    const interests = view.container.querySelector('#research_interests') as HTMLTextAreaElement;
    fireEvent.change(name, { target: { value: 'Unsaved name 王' } });
    interests.focus();
    expect(document.activeElement).toBe(interests);
    const priorGeneration = currentForm.identityGeneration;
    const priorOwner = captureOwnerToken();
    // The browser can resolve its first INITIAL_SESSION/null while text is
    // being entered. No other account or stored row has owned this screen.
    act(() => mocks.auth?.({ user: null }));
    expect(captureOwnerToken()).toEqual(priorOwner);
    expect(currentForm.identityGeneration).toBe(priorGeneration + 1);
    expect(view.container.querySelector('#student_name')).toHaveValue('Unsaved name 王');
    expect(view.container.querySelector('#research_interests'),
      'the first null observation must not detach an active typing target').toBe(interests);
    expect(document.activeElement).toBe(interests);
    fireEvent.input(interests, { target: { value: 'Existing research draft stays in the form.' } });
    expect(view.container.querySelector('#research_interests')).toHaveValue('Existing research draft stays in the form.');
    expect(mocks.commit).not.toHaveBeenCalled();
  });
  it('keeps focused research while the first anonymous UID adopts the virgin draft', async () => {
    const view = render(<HomeInputs />);
    const interests = view.container.querySelector('#research_interests') as HTMLTextAreaElement;
    fireEvent.change(interests, { target: { value: 'Before auth' } });
    act(() => mocks.auth?.({ user: null }));
    interests.focus();
    const generation = currentForm.identityGeneration;
    await act(async () => {
      advanceOwnerEpoch('first-anonymous'); await syncLocalIdentityOwner('first-anonymous');
      mocks.auth?.({ user: { id: 'first-anonymous' } });
    });
    expect(currentForm.identityGeneration).toBe(generation + 1);
    expect(view.container.querySelector('#research_interests')).toBe(interests);
    expect(document.activeElement).toBe(interests);
    fireEvent.input(interests, { target: { value: 'Before auth, after auth' } });
    expect(view.container.querySelector('#research_interests')).toHaveValue('Before auth, after auth');
  });

  it('keeps an untouched focused field through null then the first UID before its first character', async () => {
    const view = render(<HomeInputs />);
    const interests = view.container.querySelector('#research_interests') as HTMLTextAreaElement;
    interests.focus();
    act(() => mocks.auth?.({ user: null }));
    expect(document.activeElement).toBe(interests);
    const generation = currentForm.identityGeneration;
    await act(async () => {
      advanceOwnerEpoch('first-empty-anonymous'); await syncLocalIdentityOwner('first-empty-anonymous');
      mocks.auth?.({ user: { id: 'first-empty-anonymous' } });
    });
    expect(currentForm.identityGeneration).toBe(generation + 1);
    expect(view.container.querySelector('#research_interests')).toBe(interests);
    expect(document.activeElement).toBe(interests);
    fireEvent.compositionStart(interests);
    fireEvent.input(interests, { target: { value: '研' }, isComposing: true });
    fireEvent.compositionEnd(interests, { data: '研' });
    expect(view.container.querySelector('#research_interests')).toHaveValue('研');
    expect(mocks.commit).not.toHaveBeenCalled();
  });

  it('keeps an untouched field when the first callback confirms the same already-known account', async () => {
    advanceOwnerEpoch('returning-owner'); await syncLocalIdentityOwner('returning-owner');
    const view = render(<HomeInputs />);
    const interests = view.container.querySelector('#research_interests') as HTMLTextAreaElement;
    interests.focus(); const owner = captureOwnerToken();
    act(() => mocks.auth?.({ user: { id: 'returning-owner' } }));
    expect(captureOwnerToken()).toEqual(owner);
    expect(currentForm.identityGeneration).toBe(1);
    expect(view.container.querySelector('#research_interests')).toBe(interests);
    expect(document.activeElement).toBe(interests);
    fireEvent.input(interests, { target: { value: 'First character' } });
    expect(view.container.querySelector('#research_interests')).toHaveValue('First character');
    expect(mocks.commit).not.toHaveBeenCalled();
  });

  it('does not reuse input DOM after an owner epoch changed before the first callback', async () => {
    const view = render(<HomeInputs />);
    const field = view.container.querySelector('#research_interests');
    await act(async () => {
      advanceOwnerEpoch('intervening-account'); await syncLocalIdentityOwner('intervening-account');
      advanceOwnerEpoch(null); mocks.auth?.({ user: null });
    });
    expect(view.container.querySelector('#research_interests')).not.toBe(field);
  });

  it('does not preserve untouched input DOM after an intervening account before the first UID callback', async () => {
    const view = render(<HomeInputs />);
    const interests = view.container.querySelector('#research_interests') as HTMLTextAreaElement;
    interests.focus();
    await act(async () => {
      advanceOwnerEpoch('intervening-first'); await syncLocalIdentityOwner('intervening-first');
      advanceOwnerEpoch('observed-second'); await syncLocalIdentityOwner('observed-second');
      mocks.auth?.({ user: { id: 'observed-second' } });
    });
    expect(view.container.querySelector('#research_interests')).not.toBe(interests);
    expect(mocks.commit).not.toHaveBeenCalled();
  });

  it('does not preserve untouched input DOM when a known mount account changes before its first callback', async () => {
    advanceOwnerEpoch('mount-owner'); await syncLocalIdentityOwner('mount-owner');
    const view = render(<HomeInputs />);
    const interests = view.container.querySelector('#research_interests') as HTMLTextAreaElement;
    interests.focus();
    await act(async () => {
      advanceOwnerEpoch('different-owner'); await syncLocalIdentityOwner('different-owner');
      mocks.auth?.({ user: { id: 'different-owner' } });
    });
    expect(view.container.querySelector('#research_interests')).not.toBe(interests);
    expect(mocks.commit).not.toHaveBeenCalled();
  });

  it.each(['anonymous-owner', 'registered-owner'])('keeps carried input but clears private picker for the first real %s', async uid => {
    const view = render(<HomeInputs />);
    const name = view.container.querySelector('#student_name') as HTMLInputElement;
    fireEvent.change(name, { target: { value: 'Visitor input' } });
    fireEvent.click(screen.getByText('home.form.changeSchool'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await act(async () => { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); mocks.auth?.({ user: { id: uid } }); });
    expect(view.container.querySelector('#student_name')).toBe(name);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(view.container.querySelector('#student_name')).toHaveValue('Visitor input');
  });

  it.each(['registered-owner', null])('clears academic private state when an anonymous owner changes to %s', async next => {
    await act(async () => { advanceOwnerEpoch('anonymous-owner'); await syncLocalIdentityOwner('anonymous-owner'); });
    const view = render(<HomeInputs />);
    act(() => mocks.auth?.({ user: { id: 'anonymous-owner' } }));
    const field = view.container.querySelector('#research_interests') as HTMLTextAreaElement;
    fireEvent.change(field, { target: { value: 'Previous owner draft' } });
    fireEvent.click(screen.getByText('home.form.changeSchool'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await act(async () => { advanceOwnerEpoch(next); if (next) await syncLocalIdentityOwner(next); mocks.auth?.({ user: next ? { id: next } : null }); });
    expect(view.container.querySelector('#research_interests')).not.toBe(field);
    expect(view.container.querySelector('#research_interests')).toHaveValue('');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it.each([null, 'first-after-stored-row'])('still remounts after a stored row was accepted before the first %s observation', async uid => {
    mocks.load.mockImplementation(async () => ({ source: 'local-only', revision: 0,
      profile: { ...DEFAULT_PROFILE, name: 'Stored profile' }, token: captureOwnerToken() }));
    const view = render(<HomeInputs />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(currentForm.hydrationState).toBe('ready');
    const field = view.container.querySelector('#student_name');
    expect(field).toHaveValue('Stored profile');
    await act(async () => {
      if (uid) { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); }
      mocks.auth?.({ user: uid ? { id: uid } : null });
    });
    expect(view.container.querySelector('#student_name')).not.toBe(field);
  });

});
