import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({ t: (key: string) => key }),
  useLocale: () => 'en',
}));
vi.mock('@/lib/analytics', () => ({ trackOnce: vi.fn(), track: vi.fn() }));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(''),
  usePathname: () => '/',
}));
vi.mock('@/lib/api', () => ({
  getStats: () => Promise.resolve({ total: 100, last_updated_at: '2026-04-01T00:00:00Z' }),
  parseGitHubProfile: vi.fn(),
  // The home page mounts FeaturedFellowships once fellowships is accepted, and
  // a partial module mock throws rather than returning undefined for a missing
  // export — so an accepted feature takes the whole page's suite down.
  getFeaturedFellowships: () => Promise.resolve([]),
}));

let authChangeCb: ((s: { user: { id: string } | null }) => void) | null = null;
// A complete, valid row so the Generate button's ONLY remaining gate is
// hydration.
const VALID_ROW = {
  college: 'Grainger College of Engineering',
  major: 'Computer Science',
  grade: 'Junior',
};
// The load answers three questions now, not one: what the row holds, which
// revision that is, and whether the cloud was asked at all. `resolveRow` takes
// the row and wraps it in that envelope so the tests stay about the button.
let resolveProfileLoad: ((v: Record<string, unknown> | null) => void) | null = null;
let rejectProfileLoad: ((e: Error) => void) | null = null;
vi.mock('@/lib/supabase', () => ({
  loadProfile: () => new Promise<LoadedProfile>((resolve, reject) => {
    resolveProfileLoad = (row) => resolve(
      row
        ? { source: 'cloud', profile: row, revision: 1, token: captureOwnerToken() }
        : { source: 'cloud-absent', profile: null, revision: 0, token: captureOwnerToken() },
    );
    rejectProfileLoad = reject;
  }),
  commitProfilePatch: vi.fn(async (intent: ProfilePatchIntent) => ({
    status: 'saved' as const, revision: 2, profile: intent.patch,
  })),
  getStorageStatus: () => ({ status: 'synced' as const, error: null }),
  getAuthState: () => Promise.resolve({ session: null, user: null, isAnonymous: true, email: null }),
  onAuthChange: (cb: (s: { user: { id: string } | null }) => void) => {
    authChangeCb = cb;
    return () => {};
  },
}));

// The real uploader keeps the chosen file's name and its "resume on file"
// badge in its OWN state, which nothing outside it ever resets. This stub
// reproduces exactly that property (and nothing else) so the assertion is
// about page.tsx's wiring, not about pdf parsing.
vi.mock('@/components/ResumeUpload', () => ({
  default: function ResumeUploadStub() {
    const [fileName, setFileName] = ReactModule.useState<string | null>(null);
    return (
      <div>
        <span data-testid="resume-filename">{fileName ?? ''}</span>
        <button data-testid="pick-resume" onClick={() => setFileName('u1-resume.pdf')}>pick</button>
      </div>
    );
  },
}));

import * as ReactModule from 'react';
import HomePage from './page';
import type { LoadedProfile, ProfilePatchIntent } from '@/lib/supabase';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';

function emitAuth(uid: string | null) {
  act(() => {
    advanceOwnerEpoch(uid);
    if (uid) syncLocalIdentityOwner(uid);
    authChangeCb?.({ user: uid ? { id: uid } : null });
  });
}

describe('HomePage — identity-private child state', () => {
  beforeEach(async () => {
    // jsdom has no Web Locks; the coordinator takes one around every write of
    // shared local state, so without a serial fake every save would report
    // device-failed and these tests would be about the environment.
    let chain: Promise<unknown> = Promise.resolve();
    Object.defineProperty(navigator, 'locks', {
      configurable: true,
      value: {
        request: (_n: string, _o: unknown, fn: () => Promise<unknown>) => {
          const run = chain.then(() => fn());
          chain = run.then(() => undefined, () => undefined);
          return run;
        },
      },
    });
    authChangeCb = null;
    resolveProfileLoad = null;
    rejectProfileLoad = null;
    localStorage.clear();
    advanceOwnerEpoch('home-page-u1');
    await syncLocalIdentityOwner('home-page-u1');
  });

  it('discards the previous identity\'s resume upload state on an account switch', async () => {
    render(<HomePage />);
    // next/dynamic({ssr:false}) resolves the (mocked) module asynchronously.
    await waitFor(() => expect(screen.getByTestId('pick-resume')).toBeTruthy());

    fireEvent.click(screen.getByTestId('pick-resume'));
    expect(screen.getByTestId('resume-filename').textContent).toBe('u1-resume.pdf');

    emitAuth('home-page-u2');

    await waitFor(() => expect(screen.getByTestId('resume-filename').textContent).toBe(''));
  });

  it('keeps the uploader mounted across a same-identity re-observation', async () => {
    render(<HomePage />);
    await waitFor(() => expect(screen.getByTestId('pick-resume')).toBeTruthy());
    emitAuth('home-page-u2');
    await waitFor(() => expect(screen.getByTestId('pick-resume')).toBeTruthy());

    fireEvent.click(screen.getByTestId('pick-resume'));
    emitAuth('home-page-u2'); // token refresh, not a switch

    expect(screen.getByTestId('resume-filename').textContent).toBe('u1-resume.pdf');
  });
});

describe('HomePage — Generate is unavailable until the profile row has loaded', () => {
  beforeEach(async () => {
    // jsdom has no Web Locks; the coordinator takes one around every write of
    // shared local state, so without a serial fake every save would report
    // device-failed and these tests would be about the environment.
    let chain: Promise<unknown> = Promise.resolve();
    Object.defineProperty(navigator, 'locks', {
      configurable: true,
      value: {
        request: (_n: string, _o: unknown, fn: () => Promise<unknown>) => {
          const run = chain.then(() => fn());
          chain = run.then(() => undefined, () => undefined);
          return run;
        },
      },
    });
    authChangeCb = null;
    resolveProfileLoad = null;
    rejectProfileLoad = null;
    localStorage.clear();
    advanceOwnerEpoch('home-page-u1');
    await syncLocalIdentityOwner('home-page-u1');
  });

  it('the real button is disabled with the loading reason, then enabled once the row lands', async () => {
    render(<HomePage />);
    await waitFor(() => expect(resolveProfileLoad).toBeTruthy());

    expect(screen.getByTestId('generate-matches')).toBeDisabled();
    expect(screen.getByTestId('hydration-note').textContent).toBe('home.actions.profileLoading');

    await act(async () => { resolveProfileLoad?.(VALID_ROW); });

    await waitFor(() => expect(screen.getByTestId('generate-matches')).not.toBeDisabled());
    expect(screen.queryByTestId('hydration-note')).toBeNull();
  });

  it('a read failure leaves the button disabled, with the failure reason rather than the loading one', async () => {
    render(<HomePage />);
    await waitFor(() => expect(resolveProfileLoad).toBeTruthy());
    await act(async () => { resolveProfileLoad?.(VALID_ROW); });
    await waitFor(() => expect(screen.getByTestId('generate-matches')).not.toBeDisabled());

    // A different account, whose row cannot be read.
    resolveProfileLoad = null;
    rejectProfileLoad = null;
    emitAuth('home-page-u3');
    await waitFor(() => expect(rejectProfileLoad).toBeTruthy());
    await act(async () => { rejectProfileLoad?.(new Error('read failed')); });

    await waitFor(() => expect(
      screen.getByTestId('hydration-note').textContent,
    ).toBe('home.actions.profileLoadFailed'));
    expect(screen.getByTestId('generate-matches')).toBeDisabled();
  });
});
