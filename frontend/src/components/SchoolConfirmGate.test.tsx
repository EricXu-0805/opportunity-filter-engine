import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('@/i18n/client', () => {
  const stableT = (key: string, vars?: Record<string, string | number>) => {
    if (!vars) return key;
    const parts = Object.entries(vars).map(([, v]) => String(v));
    return parts.length > 0 ? `${key}:${parts.join('|')}` : key;
  };
  return {
    useT: () => ({ t: stableT, locale: 'en' as const, setLocale: () => {} }),
    useLocale: () => 'en' as const,
  };
});

const trackMock = vi.fn();
vi.mock('@/lib/analytics', () => ({
  track: (...args: unknown[]) => trackMock(...args),
}));

import SchoolConfirmGate from './SchoolConfirmGate';
import { HOME_SCHOOL_EVENT, STORAGE_KEYS } from '@/lib/storage-keys';

const DEFER_KEY = 'ofe_school_confirm_deferred';

function seedExistingUser(homeSchool: string | null = 'uiuc') {
  localStorage.setItem(STORAGE_KEYS.ONBOARDING_SEEN, '1');
  const profile: Record<string, unknown> = { major: 'CS' };
  if (homeSchool) profile.home_school = homeSchool;
  localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify(profile));
}

beforeEach(() => {
  trackMock.mockReset();
});

describe('gate visibility', () => {
  it('shows once for an existing user with an unconfirmed school, pre-selected', async () => {
    seedExistingUser('ucb');
    render(<SchoolConfirmGate />);
    expect(await screen.findByText('schoolConfirm.title')).toBeInTheDocument();
    expect(screen.getByTestId('university-card-ucb')).toHaveAttribute('aria-pressed', 'true');
  });

  it('defaults pre-school-gate profiles (no home_school) to uiuc', async () => {
    seedExistingUser(null);
    render(<SchoolConfirmGate />);
    expect(await screen.findByText('schoolConfirm.title')).toBeInTheDocument();
    expect(screen.getByTestId('university-card-uiuc')).toHaveAttribute('aria-pressed', 'true');
  });

  it('stays hidden for brand-new users (the tour owns them)', () => {
    localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({ home_school: 'uiuc' }));
    render(<SchoolConfirmGate />);
    expect(screen.queryByText('schoolConfirm.title')).not.toBeInTheDocument();
  });

  it('stays hidden when there is no profile to confirm', () => {
    localStorage.setItem(STORAGE_KEYS.ONBOARDING_SEEN, '1');
    render(<SchoolConfirmGate />);
    expect(screen.queryByText('schoolConfirm.title')).not.toBeInTheDocument();
  });

  it('stays hidden once the current school is confirmed', () => {
    seedExistingUser('uiuc');
    localStorage.setItem(
      STORAGE_KEYS.SCHOOL_CONFIRMED,
      JSON.stringify({ slug: 'uiuc', ts: '2026-01-01T00:00:00Z' }),
    );
    render(<SchoolConfirmGate />);
    expect(screen.queryByText('schoolConfirm.title')).not.toBeInTheDocument();
  });

  it('re-asks when the profile school no longer matches the confirmation', async () => {
    seedExistingUser('ucb');
    localStorage.setItem(
      STORAGE_KEYS.SCHOOL_CONFIRMED,
      JSON.stringify({ slug: 'uiuc', ts: '2026-01-01T00:00:00Z' }),
    );
    render(<SchoolConfirmGate />);
    expect(await screen.findByText('schoolConfirm.title')).toBeInTheDocument();
  });
});

describe('confirming', () => {
  it('one click writes the receipt + profile, broadcasts, tracks, and closes', async () => {
    seedExistingUser('uiuc');
    const events: string[] = [];
    const listener = (e: Event) => events.push((e as CustomEvent<string>).detail);
    window.addEventListener(HOME_SCHOOL_EVENT, listener);
    try {
      render(<SchoolConfirmGate />);
      fireEvent.click(await screen.findByText('schoolConfirm.confirm'));
    } finally {
      window.removeEventListener(HOME_SCHOOL_EVENT, listener);
    }
    await waitFor(() => {
      expect(screen.queryByText('schoolConfirm.title')).not.toBeInTheDocument();
    });
    const receipt = JSON.parse(localStorage.getItem(STORAGE_KEYS.SCHOOL_CONFIRMED)!);
    expect(receipt.slug).toBe('uiuc');
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!).home_school).toBe('uiuc');
    expect(events).toEqual(['uiuc']);
    expect(trackMock).toHaveBeenCalledWith('school_confirmed', {
      school: 'uiuc',
      changed: false,
    });
  });

  it('changing the school in the gate confirms the NEW school', async () => {
    seedExistingUser('uiuc');
    render(<SchoolConfirmGate />);
    fireEvent.click(await screen.findByTestId('university-card-ucb'));
    fireEvent.click(screen.getByText('schoolConfirm.confirm'));
    await waitFor(() => {
      expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.SCHOOL_CONFIRMED)!).slug).toBe('ucb');
    });
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!).home_school).toBe('ucb');
    expect(trackMock).toHaveBeenCalledWith('school_confirmed', {
      school: 'ucb',
      changed: true,
    });
  });
});

describe('soft dismissal', () => {
  it('cancel defers for the session — no confirmation written, no re-show', async () => {
    seedExistingUser('uiuc');
    const { unmount } = render(<SchoolConfirmGate />);
    fireEvent.click(await screen.findByText('common.cancel'));
    await waitFor(() => {
      expect(screen.queryByText('schoolConfirm.title')).not.toBeInTheDocument();
    });
    expect(localStorage.getItem(STORAGE_KEYS.SCHOOL_CONFIRMED)).toBeNull();
    expect(sessionStorage.getItem(DEFER_KEY)).toBe('1');
    unmount();
    // Same session: stays parked (matching keeps running on the unconfirmed
    // school — soft gate, not a hostage-taking).
    render(<SchoolConfirmGate />);
    expect(screen.queryByText('schoolConfirm.title')).not.toBeInTheDocument();
  });

  it('a new session (defer flag gone) asks again', async () => {
    seedExistingUser('uiuc');
    sessionStorage.removeItem(DEFER_KEY);
    render(<SchoolConfirmGate />);
    expect(await screen.findByText('schoolConfirm.title')).toBeInTheDocument();
  });
});
