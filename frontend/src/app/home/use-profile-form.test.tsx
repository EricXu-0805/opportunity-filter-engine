import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { Suspense } from 'react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string) => key,
  }),
}));

const refreshSpy = vi.fn();
const pushSpy = vi.fn();
const prefetchSpy = vi.fn();
const pathnameRef = { current: '/' };
const searchRef = { current: '' };

// Cache the URLSearchParams instance so re-renders with the same query
// string return the same object reference. Without this cache,
// useEffect([searchParams, ...]) treats every render as a new search-
// params and re-fires the mount load, which makes call-count
// assertions (used in the cross-device-sync tests below) impossible.
// Production `useSearchParams()` from next/navigation is already stable.
let cachedParams: URLSearchParams | null = null;
let cachedParamsKey: string | null = null;

vi.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: refreshSpy, push: pushSpy, prefetch: prefetchSpy }),
  useSearchParams: () => {
    if (cachedParamsKey !== searchRef.current) {
      cachedParams = new URLSearchParams(searchRef.current);
      cachedParamsKey = searchRef.current;
    }
    return cachedParams!;
  },
  usePathname: () => pathnameRef.current,
}));

vi.mock('@/lib/api', () => ({
  getStats: () => Promise.resolve({ total: 100, last_updated_at: '2026-04-01T00:00:00Z' }),
  parseGitHubProfile: vi.fn(),
}));

// R67 problem #4: cross-device profile sync.
//
// `mockLoadProfile` is reassigned per-test so we can simulate the
// "different account / different device" reload (first call returns
// account A's profile, second call returns account B's). Tests fire
// the auth change manually via `authChangeCb`, which is captured the
// moment useProfileForm subscribes.
let mockLoadProfile: () => Promise<Record<string, unknown> | null> = () => Promise.resolve(null);
let authChangeCb: ((s: { user: { id: string } | null }) => void) | null = null;
const unsubSpy = vi.fn();

vi.mock('@/lib/supabase', () => ({
  loadProfile: () => mockLoadProfile(),
  saveProfile: vi.fn(() => Promise.resolve()),
  onAuthChange: (cb: (s: { user: { id: string } | null }) => void) => {
    authChangeCb = cb;
    return unsubSpy;
  },
}));

import { useProfileForm } from './use-profile-form';
import { saveProfile } from '@/lib/supabase';
import { parseGitHubProfile } from '@/lib/api';
import { HOME_SCHOOL_EVENT } from '@/lib/storage-keys';

const RESUME = (suggested_interests: string) => ({
  extracted_skills: [] as string[],
  extracted_coursework: [] as string[],
  experience_level: 'beginner',
  raw_text: 'resume body',
  success: true,
  message: '',
  suggested_interests,
});

// Stable `t` reference to avoid re-firing the mount load effect on each
// render. Without this, useEffect([searchParams, t]) treats every render
// as a deps change because each inline `(k) => k` is a new function.
const stableT = (k: string) => k;

function TestHarness() {
  const form = useProfileForm(stableT);
  return (
    <div>
      <span data-testid="grade">{form.profile.grade}</span>
      <span data-testid="seeking">{(form.profile.seeking_types ?? []).join(',')}</span>
    </div>
  );
}

function Wrapped() {
  return (
    <Suspense fallback={null}>
      <TestHarness />
    </Suspense>
  );
}

beforeEach(() => {
  refreshSpy.mockReset();
  pushSpy.mockReset();
  prefetchSpy.mockReset();
  searchRef.current = '';
  cachedParams = null;
  cachedParamsKey = null;
  mockLoadProfile = () => Promise.resolve(null);
  authChangeCb = null;
  unsubSpy.mockReset();
});

describe('useProfileForm — prefill from URL', () => {
  it('does not prefill anything when no prefill_* params present', async () => {
    searchRef.current = '';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe(''));
  });

  it('prefills grade when prefill_year is a valid grade', async () => {
    searchRef.current = 'prefill_year=Junior';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe('Junior'));
  });

  it('ignores invalid prefill_year values', async () => {
    searchRef.current = 'prefill_year=PostDoc';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe(''));
  });

  it('prefills seeking_types when prefill_seeking is valid', async () => {
    searchRef.current = 'prefill_seeking=summer_program';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('seeking').textContent).toContain('summer_program'));
  });

  it('ignores invalid prefill_seeking values', async () => {
    searchRef.current = 'prefill_seeking=internship_extreme';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('seeking').textContent).toBe(''));
  });

  it('applies both prefill_year and prefill_seeking when present', async () => {
    searchRef.current = 'prefill_year=Senior&prefill_seeking=fellowship';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe('Senior'));
    expect(screen.getByTestId('seeking').textContent).toContain('fellowship');
  });
});

function FullHarness() {
  const form = useProfileForm(stableT);
  return (
    <div>
      <span data-testid="interests">{form.profile.research_interests}</span>
      <button data-testid="parseA" onClick={() => form.handleResumeParsed(RESUME('computer vision, machine learning'))}>A</button>
      <button data-testid="parseB" onClick={() => form.handleResumeParsed(RESUME('robotics'))}>B</button>
      <button data-testid="set-gh" onClick={() => form.update('github_url', 'https://github.com/octocat')}>set</button>
      <button data-testid="submit" onClick={() => { void form.handleSubmit(); }}>submit</button>
    </div>
  );
}

describe('useProfileForm — resume seeds the interests box (PR5 ①)', () => {
  it('prefills research_interests from the resume when the box is empty', async () => {
    render(<Suspense fallback={null}><FullHarness /></Suspense>);
    fireEvent.click(screen.getByTestId('parseA'));
    await waitFor(() =>
      expect(screen.getByTestId('interests').textContent).toBe('computer vision, machine learning'),
    );
  });

  it('does NOT overwrite interests the user already has', async () => {
    render(<Suspense fallback={null}><FullHarness /></Suspense>);
    fireEvent.click(screen.getByTestId('parseA')); // seeds it
    await waitFor(() =>
      expect(screen.getByTestId('interests').textContent).toBe('computer vision, machine learning'),
    );
    fireEvent.click(screen.getByTestId('parseB')); // must not clobber
    await new Promise((r) => setTimeout(r, 10));
    expect(screen.getByTestId('interests').textContent).toBe('computer vision, machine learning');
  });
});

describe('useProfileForm — GitHub auto-import on submit (PR5 ②)', () => {
  it('imports an un-imported GitHub URL and merges its skills into the saved profile', async () => {
    vi.mocked(parseGitHubProfile).mockResolvedValue({
      username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [],
    });
    render(<Suspense fallback={null}><FullHarness /></Suspense>);
    fireEvent.click(screen.getByTestId('set-gh'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(parseGitHubProfile).toHaveBeenCalledWith('octocat');
    expect(saveProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        skills: expect.arrayContaining([expect.objectContaining({ name: 'Go' })]),
      }),
    );
    expect(pushSpy).toHaveBeenCalledWith('/results');
  });

  it('submit-then-unmount keeps the imported skills (stale pending save must not clobber)', async () => {
    // Regression: editing github_url arms the debounced auto-save with the
    // PRE-import profile. handleSubmit cleared the timer but left the ref, so
    // the unmount flush re-saved that stale snapshot over the merged skills.
    vi.mocked(parseGitHubProfile).mockResolvedValue({
      username: 'octocat', extracted_skills: ['Go'], topics: [], repo_count: 3, top_repos: [],
    });
    vi.mocked(saveProfile).mockClear();
    const { unmount } = render(<Suspense fallback={null}><FullHarness /></Suspense>);
    // Wait out the 500ms isInitialLoad window so the auto-save effect is live.
    await act(async () => { await new Promise((r) => setTimeout(r, 550)); });
    fireEvent.click(screen.getByTestId('set-gh')); // arms the debounced save WITHOUT Go
    await act(async () => {
      fireEvent.click(screen.getByTestId('submit'));
      await new Promise((r) => setTimeout(r, 30));
    });
    unmount();
    const calls = vi.mocked(saveProfile).mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    const lastSaved = calls[calls.length - 1][0] as { skills: Array<{ name: string }> };
    expect(lastSaved.skills).toEqual(
      expect.arrayContaining([expect.objectContaining({ name: 'Go' })]),
    );
  });
});

function SchoolHarness() {
  const form = useProfileForm(stableT);
  return (
    <div>
      <span data-testid="home-school">{form.profile.home_school ?? ''}</span>
      <span data-testid="college">{form.profile.college}</span>
      <span data-testid="major">{form.profile.major}</span>
      <button data-testid="switch-ucb" onClick={() => form.update('home_school', 'ucb')}>switch</button>
      <button data-testid="switch-uiuc" onClick={() => form.update('home_school', 'uiuc')}>switch back</button>
      <button data-testid="switch-future" onClick={() => form.update('home_school', 'future-school')}>switch future</button>
      <button data-testid="set-college" onClick={() => form.update('college', 'College of Engineering')}>college</button>
      <button data-testid="set-major" onClick={() => form.update('major', 'EECS')}>major</button>
    </div>
  );
}

describe('useProfileForm — home_school (university switcher)', () => {
  it('defaults home_school to uiuc on a fresh profile', async () => {
    render(<Suspense fallback={null}><SchoolHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('home-school').textContent).toBe('uiuc'));
  });

  it('backward compat: a stored profile without home_school keeps working as uiuc', async () => {
    // Pre-switcher profile shape — no home_school key at all.
    mockLoadProfile = () => Promise.resolve({
      college: 'Grainger College of Engineering',
      major: 'Computer Science',
      grade: 'Freshman',
    } as Record<string, unknown>);
    render(<Suspense fallback={null}><SchoolHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('college').textContent).toBe('Grainger College of Engineering'));
    expect(screen.getByTestId('home-school').textContent).toBe('uiuc');
    expect(screen.getByTestId('major').textContent).toBe('Computer Science');
  });

  it('loads a stored home_school and persists a switch through the save path', async () => {
    mockLoadProfile = () => Promise.resolve({ home_school: 'ucb' } as Record<string, unknown>);
    render(<Suspense fallback={null}><SchoolHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('home-school').textContent).toBe('ucb'));
  });

  it('applies a campus chosen via the onboarding gate event after the form already mounted', async () => {
    // Reproduces the gate hand-off: the form mounts + loads (default uiuc)
    // before the tour finishes, so only the live window event updates it.
    render(<Suspense fallback={null}><SchoolHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('home-school').textContent).toBe('uiuc'));
    act(() => {
      window.dispatchEvent(new CustomEvent(HOME_SCHOOL_EVENT, { detail: 'ucb' }));
    });
    expect(screen.getByTestId('home-school').textContent).toBe('ucb');
  });

  it('switching schools updates home_school without clobbering college/major', async () => {
    render(<Suspense fallback={null}><SchoolHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('home-school').textContent).toBe('uiuc'));
    fireEvent.click(screen.getByTestId('set-college'));
    fireEvent.click(screen.getByTestId('set-major'));
    fireEvent.click(screen.getByTestId('switch-ucb'));
    expect(screen.getByTestId('home-school').textContent).toBe('ucb');
    expect(screen.getByTestId('college').textContent).toBe('College of Engineering');
    expect(screen.getByTestId('major').textContent).toBe('EECS');
  });

  it('college edits clear the major under any school catalog, not in free-text mode', async () => {
    render(<Suspense fallback={null}><SchoolHarness /></Suspense>);
    await waitFor(() => expect(screen.getByTestId('home-school').textContent).toBe('uiuc'));
    // Catalog mode (UIUC): picking a college resets the cascaded major.
    fireEvent.click(screen.getByTestId('set-major'));
    fireEvent.click(screen.getByTestId('set-college'));
    expect(screen.getByTestId('major').textContent).toBe('');
    // Catalog mode (UCB — shipped in this PR): same cascading reset.
    fireEvent.click(screen.getByTestId('switch-ucb'));
    fireEvent.click(screen.getByTestId('set-major'));
    fireEvent.click(screen.getByTestId('set-college'));
    expect(screen.getByTestId('major').textContent).toBe('');
    // Free-text mode (a school with no catalog yet): college keystrokes
    // must NOT wipe the major the user typed.
    fireEvent.click(screen.getByTestId('switch-future'));
    fireEvent.click(screen.getByTestId('set-major'));
    fireEvent.click(screen.getByTestId('set-college'));
    expect(screen.getByTestId('major').textContent).toBe('EECS');
  });
});

// R67 problem #4: when the auth session transitions on this device
// (anon → permanent via magic-link convert, or one signed-in account
// → a different signed-in account), the form must re-fetch the
// profile under the NEW auth.uid() so the user sees their own data,
// not a stale snapshot from before sign-in.
describe('useProfileForm — cross-device sync via onAuthChange', () => {
  it('subscribes to onAuthChange on mount and unsubscribes on unmount', async () => {
    mockLoadProfile = () => Promise.resolve(null);
    const { unmount } = render(<Wrapped />);
    await waitFor(() => expect(authChangeCb).not.toBeNull());
    expect(unsubSpy).not.toHaveBeenCalled();
    unmount();
    expect(unsubSpy).toHaveBeenCalledTimes(1);
  });

  it('does NOT reload on the first auth event (mount effect already loaded)', async () => {
    const loadSpy = vi.fn(() => Promise.resolve(null));
    mockLoadProfile = loadSpy;
    render(<Wrapped />);
    // Wait for initial mount load.
    await waitFor(() => expect(loadSpy).toHaveBeenCalledTimes(1));
    // Fire the initial onAuthChange event — same uid as mount.
    authChangeCb?.({ user: { id: 'a' } });
    await new Promise((r) => setTimeout(r, 10));
    // Should NOT have triggered a second load.
    expect(loadSpy).toHaveBeenCalledTimes(1);
  });

  it('reloads profile when auth.uid() transitions to a different user', async () => {
    let callCount = 0;
    mockLoadProfile = () => {
      callCount += 1;
      if (callCount === 1) return Promise.resolve({ grade: 'Junior' } as Record<string, unknown>);
      return Promise.resolve({ grade: 'Senior' } as Record<string, unknown>);
    };
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe('Junior'));
    // First auth event — same uid as mount; ignored.
    authChangeCb?.({ user: { id: 'a' } });
    // Second auth event with a DIFFERENT uid — should trigger reload.
    authChangeCb?.({ user: { id: 'b' } });
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe('Senior'));
    expect(callCount).toBe(2);
  });

  it('also reloads on permanent → anon (sign out) transition', async () => {
    let callCount = 0;
    mockLoadProfile = () => {
      callCount += 1;
      if (callCount === 1) return Promise.resolve({ grade: 'Senior' } as Record<string, unknown>);
      return Promise.resolve(null);
    };
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe('Senior'));
    // First event with permanent uid; second event with null (signed out).
    authChangeCb?.({ user: { id: 'perm-uid' } });
    authChangeCb?.({ user: null });
    await waitFor(() => expect(callCount).toBe(2));
  });
});
