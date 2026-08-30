/*
 * OnboardingIntro: accepted-release product tour. First-visit gate (localStorage),
 * Back/Next paging, and "Try it" completion. analytics is mocked; i18n returns
 * the key verbatim. localStorage is real in jsdom and cleared between tests.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockTrack = vi.fn();

vi.mock('@/lib/analytics', () => ({ track: (...args: unknown[]) => mockTrack(...args) }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key }) }));

// Real profile-sync everywhere except where a test needs to control WHEN the
// hydration resolves — the bug this file now covers is entirely about that
// timing, and it cannot be reproduced with a read that settles immediately.
let hydrateOverride: (() => Promise<unknown>) | null = null;
vi.mock('@/lib/profile-sync', async (importActual) => {
  const actual = await importActual<typeof import('@/lib/profile-sync')>();
  return {
    ...actual,
    hydrateProfile: () => (hydrateOverride ? hydrateOverride() : actual.hydrateProfile()),
  };
});

// Everything real except a handle on the readiness notification, so a test can
// fire the same-identity transition a real page load fires while a read is
// still in flight. That transition is the whole bug.
const ownerListeners = new Set<() => void>();
const notifyOwnerChange = () => { ownerListeners.forEach((fn) => fn()); };
vi.mock('@/lib/identity-owner', async (importActual) => {
  const actual = await importActual<typeof import('@/lib/identity-owner')>();
  return {
    ...actual,
    onLocalOwnerStateChange: (cb: () => void) => {
      const off = actual.onLocalOwnerStateChange(cb);
      ownerListeners.add(cb);
      return () => { ownerListeners.delete(cb); off(); };
    },
  };
});

import OnboardingIntro from './OnboardingIntro';
import { enterLocalOnlyMode } from '@/lib/identity-owner';

// welcome, generate, favorites, tracker, dashboard, school. Compare and
// Roadmap stay implemented but are absent from the MVP tour while hidden.
const SLIDE_COUNT = 6;

beforeEach(() => {
  localStorage.clear();
  // jsdom has no Web Locks. The campus is written through the coordinator,
  // which serializes every change to shared local state through one — without
  // a fake the write reports a device failure and the gate correctly refuses
  // to close, which would make this a test about the environment.
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
  // persistHomeSchool/recordSchoolConfirmation now preflight-check the
  // owner token before writing — this narrow component test never mounts
  // anything that resolves a real (or confirmed-local-only) identity, so
  // establish the local-only realm directly (this app has no configured
  // Supabase in tests, matching the real unconfigured-degrade path).
  enterLocalOnlyMode();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  hydrateOverride = null;
  ownerListeners.clear();
});

describe('OnboardingIntro', () => {
  it('shows on first visit when no seen flag is set', async () => {
    render(<OnboardingIntro />);
    await waitFor(() => expect(screen.getByTestId('onboarding-intro')).toBeInTheDocument());
  });

  it('stays hidden once the seen flag is set', async () => {
    localStorage.setItem('ofe_onboarding_seen', '1');
    const { container } = render(<OnboardingIntro />);
    await new Promise((r) => setTimeout(r, 0));
    expect(container.querySelector('[data-testid="onboarding-intro"]')).toBeNull();
  });

  it('keeps Skip available through the feature slides and reveals Back only after the first', async () => {
    render(<OnboardingIntro />);
    await waitFor(() => screen.getByTestId('onboarding-skip'));
    expect(screen.queryByTestId('onboarding-back')).toBeNull();
    fireEvent.click(screen.getByTestId('onboarding-primary'));
    // Skip stays put once advanced; Back now appears alongside it.
    expect(screen.getByTestId('onboarding-skip')).toBeInTheDocument();
    expect(screen.getByTestId('onboarding-back')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('onboarding-back'));
    expect(screen.getByTestId('onboarding-skip')).toBeInTheDocument();
    expect(screen.queryByTestId('onboarding-back')).toBeNull();
  });

  it('omits hidden Compare, Roadmap and Fellowship claims from the tour', async () => {
    render(<OnboardingIntro />);
    await waitFor(() => screen.getByTestId('onboarding-intro'));
    expect(screen.getByText(`1 / ${SLIDE_COUNT}`)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('onboarding-primary'));
    expect(screen.getByText('onboarding.exResearch')).toBeInTheDocument();
    expect(screen.queryByText('onboarding.exFellowship')).not.toBeInTheDocument();
  });

  it('pages through to the end and completes via the school gate (default UIUC: seen + tracked + persisted)', async () => {
    const { container } = render(<OnboardingIntro />);
    await waitFor(() => screen.getByTestId('onboarding-primary'));
    // Advance to the final (school) slide, then one more click confirms the default.
    for (let k = 0; k < SLIDE_COUNT; k += 1) {
      fireEvent.click(screen.getByTestId('onboarding-primary'));
    }
    await waitFor(() =>
      expect(container.querySelector('[data-testid="onboarding-intro"]')).toBeNull(),
    );
    expect(localStorage.getItem('ofe_onboarding_seen')).toBe('1');
    expect(mockTrack).toHaveBeenCalledWith('onboarding_completed', { school: 'uiuc' });
    expect(JSON.parse(localStorage.getItem('ofe_profile') ?? '{}').home_school).toBe('uiuc');
  });

  it('accepts a hydration that a same-identity readiness change raced past', async () => {
    /*
     * The tour accepted its baseline only if no further accept() had STARTED
     * since — a monotonic counter. But accept() re-runs on every
     * onLocalOwnerStateChange, and a plain page load fires two of those for
     * the SAME identity while ownership settles. So the read that succeeded
     * was discarded for having a stale counter ("hydrate ok seq 1 cur 3 ...
     * valid true"), the later ones failed because ownership was not confirmed
     * yet, and nothing retried. `view` stayed null, which disabled the CTA on
     * the last step of a tour that cannot be dismissed: every first-time
     * visitor was trapped. Live on production from #708 until this.
     *
     * Identity, not call count, is what makes a read stale — and
     * isOwnerTokenValid already proves it, because a switch bumps the owner
     * epoch the token carries.
     */
    const actual = await vi.importActual<typeof import('@/lib/profile-sync')>('@/lib/profile-sync');
    let release: (() => void) | null = null;
    hydrateOverride = () => {
      if (release) {
        // Exactly production's shape: every LATER attempt runs before
        // ownership is confirmed and fails, so the only baseline available is
        // the one the counter was throwing away.
        return Promise.reject(new Error('ownership not confirmed'));
      }
      const pending = actual.hydrateProfile();
      return new Promise((resolve, reject) => {
        release = () => pending.then(resolve, reject);
      });
    };
    render(<OnboardingIntro />);
    await waitFor(() => screen.getByTestId('onboarding-primary'));

    // A readiness transition for the same identity, exactly as a real load
    // emits — this is what used to invalidate the in-flight read.
    act(() => { notifyOwnerChange(); notifyOwnerChange(); });
    await waitFor(() => expect(release).not.toBeNull());
    await act(async () => { release?.(); await Promise.resolve(); });

    for (let k = 0; k < SLIDE_COUNT; k += 1) {
      fireEvent.click(screen.getByTestId('onboarding-primary'));
      await act(async () => { await Promise.resolve(); });
    }
    await waitFor(() => expect(localStorage.getItem('ofe_onboarding_seen')).toBe('1'));
    expect(screen.queryByTestId('onboarding-error')).toBeNull();
  });

  it('retries a hydration that failed because ownership was not confirmed yet', async () => {
    /*
     * The read that fails here almost always resolves on its own moments
     * later. Without a retry the tour depends on an owner-state notification
     * that, on a real load, has already been and gone.
     */
    vi.useFakeTimers();
    let attempts = 0;
    hydrateOverride = () => {
      attempts += 1;
      if (attempts === 1) return Promise.reject(new Error('ownership not confirmed'));
      return vi.importActual<typeof import('@/lib/profile-sync')>('@/lib/profile-sync')
        .then((m) => m.hydrateProfile());
    };
    try {
      render(<OnboardingIntro />);
      await vi.waitFor(() => expect(attempts).toBe(1));
      await act(async () => { await vi.advanceTimersByTimeAsync(1200); });
      expect(attempts).toBeGreaterThan(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps a baseline that is still valid while a fresh read is in flight', async () => {
    /*
     * accept() used to clear the baseline the moment it STARTED, before its
     * own read had resolved. With retries that means every attempt throws away
     * a baseline that already landed, and a student who clicks in that window
     * is told the save failed when nothing was wrong.
     */
    render(<OnboardingIntro />);
    await waitFor(() => screen.getByTestId('onboarding-primary'));
    // A baseline has landed by now. Start a read that never resolves, exactly
    // as a slow retry would, and confirm the tour still completes.
    hydrateOverride = () => new Promise(() => {});
    act(() => { notifyOwnerChange(); });
    await act(async () => { await Promise.resolve(); });

    for (let k = 0; k < SLIDE_COUNT; k += 1) {
      fireEvent.click(screen.getByTestId('onboarding-primary'));
      await act(async () => { await Promise.resolve(); });
    }
    await waitFor(() => expect(localStorage.getItem('ofe_onboarding_seen')).toBe('1'));
    expect(screen.queryByTestId('onboarding-error')).toBeNull();
  });

  it('never leaves the final CTA dead: an unusable baseline says so and stays retryable', async () => {
    /*
     * `disabled` also required an accepted baseline, so a read that never
     * landed produced a grey button with no explanation and no way out.
     * finish() already refuses to write without a baseline; the button now
     * lets it say so.
     */
    hydrateOverride = () => Promise.reject(new Error('ownership not confirmed'));
    render(<OnboardingIntro />);
    await waitFor(() => screen.getByTestId('onboarding-primary'));
    for (let k = 0; k < SLIDE_COUNT - 1; k += 1) {
      fireEvent.click(screen.getByTestId('onboarding-primary'));
    }
    const cta = screen.getByTestId('onboarding-primary');
    expect(cta).not.toBeDisabled();
    fireEvent.click(cta);
    await waitFor(() => expect(screen.getByTestId('onboarding-error')).toBeInTheDocument());
    expect(localStorage.getItem('ofe_onboarding_seen')).toBeNull();
  });

  it('Skip routes to the forced school gate (does not close until a campus is confirmed)', async () => {
    const { container } = render(<OnboardingIntro />);
    await waitFor(() => screen.getByTestId('onboarding-skip'));

    // Skip jumps straight to the gate rather than dismissing.
    fireEvent.click(screen.getByTestId('onboarding-skip'));
    expect(screen.getByTestId('onboarding-school-list')).toBeInTheDocument();
    expect(container.querySelector('[data-testid="onboarding-intro"]')).not.toBeNull();
    expect(screen.queryByTestId('onboarding-skip')).toBeNull();
    expect(mockTrack).not.toHaveBeenCalled();

    // Pick a non-default campus, then confirm.
    fireEvent.click(screen.getByTestId('onboarding-school-ucb'));
    fireEvent.click(screen.getByTestId('onboarding-primary'));
    await waitFor(() =>
      expect(container.querySelector('[data-testid="onboarding-intro"]')).toBeNull(),
    );
    expect(localStorage.getItem('ofe_onboarding_seen')).toBe('1');
    expect(mockTrack).toHaveBeenCalledWith('onboarding_completed', { school: 'ucb' });
    expect(JSON.parse(localStorage.getItem('ofe_profile') ?? '{}').home_school).toBe('ucb');
  });
});
