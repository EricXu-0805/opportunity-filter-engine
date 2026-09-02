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

// The gate drives the REAL school-confirmation helper, which drives the real
// profile coordinator. Only the service layer is faked, so the ordering these
// tests are about — patch lands -> receipt -> cache clear -> broadcast ->
// track -> close — is exercised for real.
let serverRow: Record<string, unknown> | null = null;
let serverRevision = 0;
let commitFails = false;
vi.mock('@/lib/supabase', () => ({
  loadProfile: async () => (serverRow
    ? { source: 'cloud' as const, profile: serverRow, revision: serverRevision, token: captureOwnerToken() }
    : { source: 'cloud-absent' as const, profile: null, revision: 0, token: captureOwnerToken() }),
  commitProfilePatch: async (intent: { patch: Record<string, unknown> }) => {
    if (commitFails) return { status: 'transport-error' as const, message: 'offline' };
    serverRow = { ...(serverRow ?? {}), ...intent.patch };
    serverRevision += 1;
    return { status: 'saved' as const, revision: serverRevision, profile: serverRow };
  },
}));

const trackMock = vi.fn();
vi.mock('@/lib/analytics', () => ({
  track: (...args: unknown[]) => trackMock(...args),
}));

import SchoolConfirmGate from './SchoolConfirmGate';
import { HOME_SCHOOL_EVENT, STORAGE_KEYS } from '@/lib/storage-keys';
import * as schoolConfirmation from '@/lib/school-confirmation';
import {
  advanceOwnerEpoch, captureOwnerToken, readUserScopedRaw, syncLocalIdentityOwner, writeUserScopedRaw,
  type OwnerToken,
} from '@/lib/identity-owner';
import { resetProfileDirtyLedger } from '@/lib/profile-sync';
import { displayCoverageCount } from '@/lib/school-coverage';
import { SCHOOL_STATS, SCHOOLS } from '@/lib/schools';

/** Seed a PRIVATE key the way the app writes one. A raw `localStorage.setItem`
 *  targets an unprefixed name that belongs to whoever first claimed this
 *  browser — after an identity switch the live owner reads somewhere else
 *  entirely, and the seed is invisible. */
function seedPrivate(key: string, value: string): void {
  expect(writeUserScopedRaw(key, value, captureOwnerToken())).toBe(true);
}

/** Read one back the same way — see seedPrivate. */
function readPrivate(key: string): string | null {
  return readUserScopedRaw(key);
}

const DEFER_KEY = 'ofe_school_confirm_deferred';

function seedExistingUser(homeSchool: string | null = 'uiuc') {
  localStorage.setItem(STORAGE_KEYS.ONBOARDING_SEEN, '1');
  const profile: Record<string, unknown> = { major: 'CS' };
  if (homeSchool) profile.home_school = homeSchool;
  seedPrivate(STORAGE_KEYS.PROFILE, JSON.stringify(profile));
}

// Every read/write this component makes now goes through the local-owner
// readiness barrier — establish a ready owner before each test so the
// existing "positive path" assertions still reflect a CONFIRMED identity,
// not a blocked one (which would make every "shows" test observe null).
let token: OwnerToken;
beforeEach(async () => {
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
  serverRow = { major: 'CS', home_school: 'uiuc' };
  serverRevision = 1;
  commitFails = false;
  resetProfileDirtyLedger();
  trackMock.mockReset();
  advanceOwnerEpoch('school-confirm-gate-test-uid');
  await syncLocalIdentityOwner('school-confirm-gate-test-uid');
  token = captureOwnerToken();
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
    seedPrivate(STORAGE_KEYS.PROFILE, JSON.stringify({ home_school: 'uiuc' }));
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

  it('stays hidden while local ownership is blocked, even if a stale campus sits in raw storage', () => {
    // Simulate a mid-transition browser: a REAL prior write sits at the
    // fixed PROFILE key, but no owner has been confirmed ready yet — the
    // tri-state read must treat this exactly like "no profile," never
    // surface the stale value.
    localStorage.setItem(STORAGE_KEYS.ONBOARDING_SEEN, '1');
    seedPrivate(STORAGE_KEYS.PROFILE, JSON.stringify({ home_school: 'ucb' }));
    advanceOwnerEpoch('school-confirm-gate-blocked-uid'); // marks the realm blocked, no sync yet
    render(<SchoolConfirmGate />);
    expect(screen.queryByText('schoolConfirm.title')).not.toBeInTheDocument();
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
      // The broadcast comes AFTER the patch lands, so the listener has to
      // outlive the click.
      await waitFor(() => {
        expect(screen.queryByText('schoolConfirm.title')).not.toBeInTheDocument();
      });
    } finally {
      window.removeEventListener(HOME_SCHOOL_EVENT, listener);
    }
    const receipt = JSON.parse(localStorage.getItem(STORAGE_KEYS.SCHOOL_CONFIRMED)!);
    expect(receipt.slug).toBe('uiuc');
    expect(JSON.parse(readPrivate(STORAGE_KEYS.PROFILE)!).home_school).toBe('uiuc');
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
    expect(JSON.parse(readPrivate(STORAGE_KEYS.PROFILE)!).home_school).toBe('ucb');
    expect(trackMock).toHaveBeenCalledWith('school_confirmed', {
      school: 'ucb',
      changed: true,
    });
  });

  it('a STALE owner (identity moved on while the modal sat open) fails closed: no receipt, no profile write, no cache clear, no event, no track — modal stays open', async () => {
    seedExistingUser('uiuc');
    render(<SchoolConfirmGate />);
    const confirmButton = await screen.findByText('schoolConfirm.confirm');

    // U2 takes over AFTER the modal opened (and thus captured U1's origin
    // token) but before confirming. U2 has real data that must survive
    // untouched.
    advanceOwnerEpoch('school-confirm-gate-u2');
    await syncLocalIdentityOwner('school-confirm-gate-u2');
    seedPrivate(STORAGE_KEYS.PROFILE, JSON.stringify({ home_school: 'u2-school' }));
    localStorage.setItem(
      STORAGE_KEYS.MATCH_RESULTS,
      JSON.stringify({ version: 'sentinel', contract_version: 'sentinel' }),
    );

    const events: string[] = [];
    const listener = (e: Event) => events.push((e as CustomEvent<string>).detail);
    window.addEventListener(HOME_SCHOOL_EVENT, listener);
    try {
      fireEvent.click(confirmButton);
    } finally {
      window.removeEventListener(HOME_SCHOOL_EVENT, listener);
    }

    // U2's real data is completely untouched, regardless of whether the
    // click reached the (now-stale) onConfirm handler or the modal had
    // already unmounted via the owner-change listener.
    expect(JSON.parse(readPrivate(STORAGE_KEYS.PROFILE)!)).toEqual({ home_school: 'u2-school' });
    expect(localStorage.getItem(STORAGE_KEYS.SCHOOL_CONFIRMED)).toBeNull();
    expect(localStorage.getItem(STORAGE_KEYS.MATCH_RESULTS)).not.toBeNull();
    expect(events).toEqual([]);
    expect(trackMock).not.toHaveBeenCalled();
  });

  it('onConfirm reuses the ORIGIN token captured when the modal opened — it never re-captures a fresh one at click time', async () => {
    // Mutation-proof for the P0 race: a "fix" that moves captureOwnerToken()
    // back inside onConfirm would pass every other test here (the owner
    // never actually changes in THIS test) but would still be wrong. This
    // checks the actual token VALUE handed to the write helpers rather than
    // counting captureOwnerToken() calls globally — evaluate() itself
    // legitimately re-invokes (and re-captures) on the 'storage'/
    // HOME_SCHOOL_EVENT dispatches this very confirm triggers, so a global
    // call count is not a clean signal; the token identity passed to the
    // writers is.
    seedExistingUser('uiuc');
    render(<SchoolConfirmGate />);
    await screen.findByText('schoolConfirm.confirm');
    const originToken = captureOwnerToken(); // same owner the modal captured on open

    const persistSpy = vi.spyOn(schoolConfirmation, 'persistHomeSchool');
    fireEvent.click(screen.getByText('schoolConfirm.confirm'));
    await waitFor(() => {
      expect(screen.queryByText('schoolConfirm.title')).not.toBeInTheDocument();
    });
    // ONE ordered helper now owns the receipt as well: the gate hands it the
    // ORIGIN token and nothing else writes on its own.
    expect(persistSpy).toHaveBeenCalledWith(
      'uiuc',
      expect.objectContaining({ token: originToken }),
      { confirm: true },
    );
    persistSpy.mockRestore();
  });
});

describe('the rendered baseline belongs to the view actually on screen', () => {
  // The pair the gate confirms against — the row it showed a slug from, and
  // the revision that row IS — has to come from the SAME acceptance that
  // decided what to display. A pair captured once at mount belongs to
  // whoever owned the browser then; a pair re-read at click time belongs to
  // whatever another tab has since written. Neither is what the person saw.
  function seedConfirmedRow(profile: Record<string, unknown>, revision: number) {
    localStorage.setItem(STORAGE_KEYS.ONBOARDING_SEEN, '1');
    seedPrivate(STORAGE_KEYS.PROFILE, JSON.stringify(profile));
    localStorage.setItem(
      STORAGE_KEYS.PROFILE_SYNC,
      JSON.stringify({ v: 1, confirmed: { revision, profile } }),
    );
  }

  it('U1 -> U2 while the gate stays mounted: U2\'s confirm never carries U1\'s row or revision', async () => {
    seedConfirmedRow({ major: 'CS', home_school: 'uiuc' }, 7);
    render(<SchoolConfirmGate />);
    await screen.findByText('schoolConfirm.confirm');

    // U2 takes over the browser. This component is NOT unmounted — only the
    // DocumentsCard is keyed by identity, so in production this gate lives
    // straight through an account switch.
    advanceOwnerEpoch('gate-baseline-u2');
    await syncLocalIdentityOwner('gate-baseline-u2');
    seedConfirmedRow({ major: 'Physics', home_school: 'mit' }, 9);
    window.dispatchEvent(new Event('storage'));

    const persistSpy = vi.spyOn(schoolConfirmation, 'persistHomeSchool');
    fireEvent.click(await screen.findByText('schoolConfirm.confirm'));
    await waitFor(() => expect(persistSpy).toHaveBeenCalled());
    const sent = persistSpy.mock.calls.at(-1)![1];
    // U1's revision 7 as U2's base would CAS straight over U2's revision 9,
    // and U1's row as the patch base would carry U1's fields into it.
    expect(sent.revision).not.toBe(7);
    expect(sent.baseProfile).not.toMatchObject({ major: 'CS' });
    expect(sent.token.uid).toBe('gate-baseline-u2');
    persistSpy.mockRestore();
  });

  it('another tab writes a newer row that this gate never re-accepted: the confirm still carries the pair it displayed', async () => {
    seedConfirmedRow({ major: 'CS', home_school: 'uiuc' }, 7);
    render(<SchoolConfirmGate />);
    await screen.findByText('schoolConfirm.confirm');

    // Same owner, another tab, no notification reaches this one: the gate is
    // still showing the campus it read at revision 7. Re-reading storage when
    // Confirm is clicked would hand this untouched view revision 9 and send
    // the person's old choice as though it had been made against the new row.
    localStorage.setItem(
      STORAGE_KEYS.PROFILE_SYNC,
      JSON.stringify({
        v: 1,
        confirmed: { revision: 9, profile: { major: 'Physics', home_school: 'mit' } },
      }),
    );

    const persistSpy = vi.spyOn(schoolConfirmation, 'persistHomeSchool');
    fireEvent.click(screen.getByText('schoolConfirm.confirm'));
    await waitFor(() => expect(persistSpy).toHaveBeenCalled());
    const sent = persistSpy.mock.calls.at(-1)![1];
    expect(sent.revision).toBe(7);
    expect(sent.baseProfile).toMatchObject({ major: 'CS', home_school: 'uiuc' });
    persistSpy.mockRestore();
  });
});

describe('soft dismissal', () => {
  it('a STALE cancel (U1\'s modal, dismissed after U2 already took over) closes the modal but writes ZERO session defer flag — U2\'s own gate must not be suppressed', async () => {
    seedExistingUser('uiuc');
    render(<SchoolConfirmGate />);
    const cancelButton = await screen.findByText('common.cancel');

    advanceOwnerEpoch('school-confirm-gate-cancel-u2');
    await syncLocalIdentityOwner('school-confirm-gate-cancel-u2');

    fireEvent.click(cancelButton);

    expect(sessionStorage.getItem(DEFER_KEY)).toBeNull();
  });

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

describe('coverage count — same number as the University Switcher', () => {
  /* The gate and the switcher are the same picker with different copy, and this
   * asserts the consequence: for one school they state one size. They used to
   * agree on a wrong number (both read the listings half of the coverage
   * response); agreeing is necessary, not sufficient, so the value itself is
   * checked against the registry's listings + faculty contacts total. */
  it('shows the listings + faculty contacts total, identical to the switcher', async () => {
    seedExistingUser('jhu');
    render(<SchoolConfirmGate />);
    expect(await screen.findByText('schoolConfirm.title')).toBeInTheDocument();

    const jhu = SCHOOLS.find((s) => s.slug === 'jhu')!;
    const stat = SCHOOL_STATS.jhu!;
    // The registry number is both halves — the bug showed listing_count alone.
    expect(jhu.coverage.campusOpportunities).toBe(
      stat.listing_count + stat.faculty_contact_count,
    );
    expect(jhu.coverage.campusOpportunities).not.toBe(stat.listing_count);

    const expected = displayCoverageCount(jhu.coverage.campusOpportunities as number);
    expect(
      screen.getAllByText(`universitySwitcher.coverageCampus:${expected.toLocaleString()}`).length,
    ).toBeGreaterThanOrEqual(1);
  });
});
