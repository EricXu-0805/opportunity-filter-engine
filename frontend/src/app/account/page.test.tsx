/*
 * /account hub — verifies the identity state machine (permanent vs guest),
 * the profile snapshot (present vs empty), and the activity links. It reuses
 * existing supabase helpers, all mocked here.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockOpenModal = vi.fn();
const mockGetAuthState = vi.fn();
const mockLoadProfile = vi.fn();
const mockGetFavorites = vi.fn();
const mockGetInteractions = vi.fn();
const mockJoinWaitlist = vi.fn();
const mockTrack = vi.fn();

// Captures the REAL callback AccountPage subscribes with, so tests can
// fire live identity-change events exactly like a real onAuthChange
// stream would — a mock that swallows the callback (the old `() => ()
// => {}`) can never exercise the reset/generation/rehydrate logic at all.
let authCallback: ((s: { user: { id: string } | null; isAnonymous: boolean; email: string | null }) => void) | null = null;

vi.mock('@/lib/supabase', () => ({
  getAuthState: () => mockGetAuthState(),
  onAuthChange: (cb: typeof authCallback) => {
    authCallback = cb;
    return () => { authCallback = null; };
  },
  loadProfile: () => mockLoadProfile(),
  getFavorites: () => mockGetFavorites(),
  getInteractionsFull: () => mockGetInteractions(),
  joinWaitlist: (...args: unknown[]) => mockJoinWaitlist(...args),
}));

// AccountPage reads the profile through the sync coordinator now. These
// tests are about ITS generation/reset/rehydrate logic, so the coordinator is
// faked at its own boundary and `mockLoadProfile` keeps meaning "what the
// cloud row read returns" — including its rejections.
vi.mock('@/lib/profile-sync', () => ({
  hydrateProfile: async () => ({
    profile: await mockLoadProfile(),
    revision: 1,
    source: 'cloud' as const,
    token: { uid: null, epoch: 0 },
    hasPending: false,
    conflictKeys: [],
    quarantineFailed: false,
  }),
}));

vi.mock('@/lib/analytics', () => ({
  track: (...args: unknown[]) => mockTrack(...args),
}));

vi.mock('@/lib/auth-modal-context', () => ({
  useAuthModal: () => ({ openModal: mockOpenModal, closeModal: vi.fn() }),
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({ t: (key: string) => key }),
}));

import AccountPage from './page';

beforeEach(() => {
  authCallback = null;
  mockGetFavorites.mockResolvedValue(new Set(['a', 'b', 'c']));
  mockGetInteractions.mockResolvedValue(new Map([['x', {}], ['y', {}]]));
  mockLoadProfile.mockResolvedValue(null);
  mockJoinWaitlist.mockResolvedValue(true);
});

afterEach(() => {
  cleanup();
  // resetAllMocks (not clearAllMocks): also drops any QUEUED
  // mockResolvedValueOnce/mockRejectedValueOnce a test left unconsumed
  // (e.g. a component that short-circuited before making every expected
  // call) — clearAllMocks only wipes call history, so a leftover queued
  // value would otherwise leak into and corrupt the NEXT test's mocks.
  vi.resetAllMocks();
  vi.unstubAllEnvs();
});

function authState(uid: string | null, opts: { anon?: boolean; email?: string | null } = {}) {
  const email = 'email' in opts ? opts.email! : (uid ? `${uid}@x.com` : null);
  return {
    session: uid ? {} : null,
    user: uid ? { id: uid, is_anonymous: opts.anon ?? false } : null,
    isAnonymous: opts.anon ?? false,
    email,
  };
}

describe('AccountPage — identity', () => {
  it('shows the email + sign-out for a permanent user; sign-out opens the confirm modal', async () => {
    mockGetAuthState.mockResolvedValue({
      session: {}, user: { id: 'u1', is_anonymous: false }, isAnonymous: false,
      email: 'eric@example.com',
    });
    render(<AccountPage />);
    await waitFor(() => expect(screen.getByText('eric@example.com')).toBeInTheDocument());
    expect(screen.getByText('account.signedInBadge')).toBeInTheDocument();
    fireEvent.click(screen.getByText('account.signOut'));
    expect(mockOpenModal).toHaveBeenCalledWith({ reason: 'header', phase: 'signout-confirm' });
  });

  it('shows the guest prompt for an anonymous session', async () => {
    mockGetAuthState.mockResolvedValue({
      session: {}, user: { id: 'anon', is_anonymous: true }, isAnonymous: true, email: null,
    });
    render(<AccountPage />);
    await waitFor(() => expect(screen.getByText('account.saveAccount')).toBeInTheDocument());
    expect(screen.getByText('account.guestHint')).toBeInTheDocument();
    fireEvent.click(screen.getByText('account.saveAccount'));
    expect(mockOpenModal).toHaveBeenCalledWith({ reason: 'header' });
  });

  it('does not strand on the loading spinner when a load promise rejects — surfaces as unknown/error, NOT a confirmed guest/anonymous state', async () => {
    mockGetAuthState.mockRejectedValue(new Error('network down'));
    render(<AccountPage />);
    // The loading text must clear (finally) — no infinite "Loading…".
    await waitFor(() => expect(screen.queryByText('account.loading')).not.toBeInTheDocument());
    // A rejected auth fetch means "identity unknown," not "confirmed
    // anonymous" — asserting the guest CTA here would treat a genuine
    // failure to determine identity as if it had been positively resolved.
    expect(screen.getByText('account.loadError')).toBeInTheDocument();
    expect(screen.queryByText('account.guestBadge')).not.toBeInTheDocument();
    expect(screen.queryByText('account.saveAccount')).not.toBeInTheDocument();
    expect(screen.getByText('common.retry')).toBeInTheDocument();
  });
});

describe('AccountPage — profile snapshot', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue({
      session: {}, user: { id: 'u1', is_anonymous: false }, isAnonymous: false, email: 'e@x.com',
    });
  });

  it('renders saved profile fields when a profile exists', async () => {
    mockLoadProfile.mockResolvedValue({
      major: 'ECE', research_interests: 'machine learning', institution: 'UIUC',
      grade: 'sophomore', skills: [{ name: 'Python', level: 'expert' }],
    });
    render(<AccountPage />);
    await waitFor(() => expect(screen.getByText('ECE')).toBeInTheDocument());
    expect(screen.getByText('machine learning')).toBeInTheDocument();
    expect(screen.getByText('UIUC')).toBeInTheDocument();
    // does NOT show the empty-profile CTA
    expect(screen.queryByText('account.createProfile')).not.toBeInTheDocument();
  });

  it('prompts to build a profile when none exists', async () => {
    mockLoadProfile.mockResolvedValue(null);
    render(<AccountPage />);
    await waitFor(() => expect(screen.getByText('account.createProfile')).toBeInTheDocument());
    expect(screen.getByText('account.noProfile')).toBeInTheDocument();
  });
});

describe('AccountPage — activity links', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue({
      session: {}, user: { id: 'u1', is_anonymous: false }, isAnonymous: false, email: 'e@x.com',
    });
  });

  it('shows favorites + tracker counts and links out to the real pages', async () => {
    render(<AccountPage />);
    await waitFor(() => expect(screen.getByText('account.activityTitle')).toBeInTheDocument());
    expect(screen.getByText('3')).toBeInTheDocument(); // favorites
    expect(screen.getByText('2')).toBeInTheDocument(); // tracker
    const links = screen.getAllByRole('link').map((a) => a.getAttribute('href'));
    expect(links).toEqual(expect.arrayContaining(['/favorites', '/tracker', '/dashboard']));
  });
});

describe('AccountPage — paid-intent CTA', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue({
      session: {}, user: { id: 'u1', is_anonymous: false }, isAnonymous: false,
      email: 'eric@example.com',
    });
  });

  it('records intent on click and writes a waitlist row (prefilled email) on submit', async () => {
    render(<AccountPage />);
    await waitFor(() => expect(screen.getByText('account.intentCta')).toBeInTheDocument());

    fireEvent.click(screen.getByText('account.intentCta'));
    expect(mockTrack).toHaveBeenCalledWith('intent_clicked', { source: 'account' });

    const input = screen.getByLabelText('account.intentEmailPlaceholder') as HTMLInputElement;
    expect(input.value).toBe('eric@example.com');

    fireEvent.submit(input.closest('form')!);
    await waitFor(() =>
      expect(mockJoinWaitlist).toHaveBeenCalledWith('eric@example.com', { source: 'account' }),
    );
    await waitFor(() => expect(screen.getByText('account.intentDone')).toBeInTheDocument());
  });
});

describe('AccountPage — payments flag OFF (regression)', () => {
  beforeEach(() => {
    mockGetAuthState.mockResolvedValue({
      session: {}, user: { id: 'u1', is_anonymous: false }, isAnonymous: false,
      email: 'eric@example.com',
    });
  });

  it('renders exactly the waitlist CTA — no order flow, no orders fetch', async () => {
    render(<AccountPage />);
    await waitFor(() => expect(screen.getByText('account.intentCta')).toBeInTheDocument());
    expect(screen.queryByText('account.choosePackage')).not.toBeInTheDocument();
    expect(screen.queryByText('account.paidClaimCta')).not.toBeInTheDocument();
    expect(screen.getByText('account.freePlan')).toBeInTheDocument();
  });
});

describe('AccountPage — pre-LLC payment hard-close', () => {
  beforeEach(() => {
    vi.stubEnv('NEXT_PUBLIC_PAYMENTS', 'true');
    vi.stubEnv('NEXT_PUBLIC_PAY_QR', 'true');
    mockGetAuthState.mockResolvedValue({
      session: {}, user: { id: 'u1', is_anonymous: false }, isAnonymous: false,
      email: 'eric@example.com',
    });
  });

  it('ignores stale payment flags and keeps only the no-price request CTA', async () => {
    render(<AccountPage />);
    await waitFor(() => expect(screen.getByText('account.intentCta')).toBeInTheDocument());
    expect(screen.queryByText('account.choosePackage')).not.toBeInTheDocument();
    expect(screen.queryByText('account.paidClaimCta')).not.toBeInTheDocument();
    expect(screen.queryByAltText('account.payWechat')).not.toBeInTheDocument();
    expect(screen.queryByAltText('account.payAlipay')).not.toBeInTheDocument();
  });
});

describe('AccountPage — live identity change mid-session', () => {
  it('clears the previous owner\'s email/profile/counts in the SAME tick as a live switch, before the new owner\'s fetch resolves', async () => {
    mockGetAuthState.mockResolvedValueOnce(authState('u1'));
    mockLoadProfile.mockResolvedValueOnce({ major: 'CS', home_school: 'uiuc' });
    render(<AccountPage />);
    await waitFor(() => expect(screen.getByText('u1@x.com')).toBeInTheDocument());
    expect(screen.getByText('CS')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument(); // favorites count

    // U2 takes over — hold the new fetch pending so the intermediate,
    // same-tick state can be inspected before it resolves.
    let resolveU2!: (v: unknown) => void;
    mockGetAuthState.mockReturnValueOnce(new Promise((r) => { resolveU2 = r; }));
    act(() => { authCallback?.(authState('u2')); });

    expect(screen.queryByText('u1@x.com')).not.toBeInTheDocument();
    expect(screen.queryByText('CS')).not.toBeInTheDocument();
    expect(screen.getByText('account.loading')).toBeInTheDocument();

    resolveU2(authState('u2'));
    await waitFor(() => expect(screen.getByText('u2@x.com')).toBeInTheDocument());
  });

  it('the FIRST live event, arriving before the mount\'s own deferred fetch resolves, invalidates it — a late U1 resolution never backfills over U2', async () => {
    let resolveU1!: (v: unknown) => void;
    mockGetAuthState.mockReturnValueOnce(new Promise((r) => { resolveU1 = r; }));
    mockLoadProfile.mockResolvedValueOnce({ major: 'U1-STALE' });
    render(<AccountPage />);
    expect(screen.getByText('account.loading')).toBeInTheDocument();

    // The FIRST-ever live event this component observes reports a
    // DIFFERENT identity than whatever the mount fetch is loading —
    // must be treated as authoritative, not "harmless first report."
    mockGetAuthState.mockResolvedValueOnce(authState('u2'));
    mockLoadProfile.mockResolvedValueOnce({ major: 'U2-FRESH' });
    act(() => { authCallback?.(authState('u2')); });
    await waitFor(() => expect(screen.getByText('U2-FRESH')).toBeInTheDocument());

    // The original mount fetch (generation 0, for U1) finally resolves —
    // it must never overwrite U2's already-committed, correct state.
    resolveU1(authState('u1'));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText('U1-STALE')).not.toBeInTheDocument();
    expect(screen.getByText('U2-FRESH')).toBeInTheDocument();
    expect(screen.getByText('u2@x.com')).toBeInTheDocument();
  });

  it('a load\'s OWN getAuthState() returning a stale/mismatched uid within the SAME (current) generation must not commit — shows Retry, never a mixed identity or a false "no profile"', async () => {
    mockGetAuthState.mockResolvedValueOnce(authState('u1'));
    render(<AccountPage />);
    await waitFor(() => expect(screen.getByText('u1@x.com')).toBeInTheDocument());

    // Live switch to U2 — but THIS reload's own getAuthState() call
    // (a separate network/cache layer from the component's generation
    // counter) resolves back to U1, an internally inconsistent result.
    mockGetAuthState.mockResolvedValueOnce(authState('u1'));
    mockLoadProfile.mockResolvedValueOnce({ major: 'u2-profile-mixed-in' });
    act(() => { authCallback?.(authState('u2')); });

    await waitFor(() => expect(screen.queryByText('account.loading')).not.toBeInTheDocument());

    // Never U1's stale identity, never a mixed U1-auth/U2-profile commit,
    // never a confirmed-empty "no profile" / zero counts — a visible,
    // retryable error instead.
    expect(screen.queryByText('u1@x.com')).not.toBeInTheDocument();
    expect(screen.queryByText('u2-profile-mixed-in')).not.toBeInTheDocument();
    expect(screen.queryByText('account.noProfile')).not.toBeInTheDocument();
    expect(screen.getAllByText('account.loadError').length).toBeGreaterThan(0);
    expect(screen.getByText('common.retry')).toBeInTheDocument();

    // Retrying with a now-consistent U2 resolution succeeds.
    mockGetAuthState.mockResolvedValueOnce(authState('u2'));
    mockLoadProfile.mockResolvedValueOnce({ major: 'u2-profile-real' });
    fireEvent.click(screen.getByText('common.retry'));
    await waitFor(() => expect(screen.getByText('u2@x.com')).toBeInTheDocument());
    expect(screen.getByText('u2-profile-real')).toBeInTheDocument();
    expect(screen.queryByText('account.loadError')).not.toBeInTheDocument();
  });

  it.each([
    ['getAuthState', () => { mockGetAuthState.mockRejectedValueOnce(new Error('down')); }],
    ['loadProfile', () => {
      mockGetAuthState.mockResolvedValueOnce(authState('u1'));
      mockLoadProfile.mockRejectedValueOnce(new Error('down'));
    }],
    ['getFavorites', () => {
      mockGetAuthState.mockResolvedValueOnce(authState('u1'));
      mockGetFavorites.mockRejectedValueOnce(new Error('down'));
    }],
    ['getInteractionsFull', () => {
      mockGetAuthState.mockResolvedValueOnce(authState('u1'));
      mockGetInteractions.mockRejectedValueOnce(new Error('down'));
    }],
  ])('%s rejecting shows a visible retryable error — never "no profile" / zero counts / a confirmed guest identity', async (_name, setup) => {
    setup();
    render(<AccountPage />);

    await waitFor(() => expect(screen.getByText('account.loadError')).toBeInTheDocument());
    // auth never resolved — the page must not render as if it had
    // (guest badge / "save my account" CTA / the intent widget all imply
    // a CONFIRMED identity this error never actually established).
    expect(screen.queryByText('account.guestBadge')).not.toBeInTheDocument();
    expect(screen.queryByText('account.saveAccount')).not.toBeInTheDocument();
    expect(screen.queryByText('account.intentCta')).not.toBeInTheDocument();
    expect(screen.queryByText('account.noProfile')).not.toBeInTheDocument();
    expect(screen.queryByText('3')).not.toBeInTheDocument(); // no fabricated favorites count
    expect(screen.queryByText('2')).not.toBeInTheDocument(); // no fabricated tracker count
    expect(screen.getByText('common.retry')).toBeInTheDocument();
    expect(screen.getAllByText('account.loadError')).toHaveLength(1);

    mockGetAuthState.mockResolvedValueOnce(authState('u1'));
    fireEvent.click(screen.getByText('common.retry'));
    await waitFor(() => expect(screen.queryByText('common.retry')).not.toBeInTheDocument());
    expect(screen.getByText('u1@x.com')).toBeInTheDocument();
  });

  it('a confirmed-empty result (no error anywhere — profile null, favorites/interactions genuinely empty) shows noProfile + zero counts, with NO error banner', async () => {
    mockGetAuthState.mockResolvedValueOnce(authState('u1'));
    mockLoadProfile.mockResolvedValueOnce(null);
    mockGetFavorites.mockResolvedValueOnce(new Set());
    mockGetInteractions.mockResolvedValueOnce(new Map());
    render(<AccountPage />);

    await waitFor(() => expect(screen.getByText('account.noProfile')).toBeInTheDocument());
    expect(screen.queryByText('account.loadError')).not.toBeInTheDocument();
    expect(screen.queryByText('common.retry')).not.toBeInTheDocument();
    // Genuinely zero, both tiles — not merely "no error" but the actual
    // resolved counts, distinguishing this from the error case's absence.
    expect(screen.getAllByText('0')).toHaveLength(2);
  });

  it('rejecting DURING a live U2 rehydrate never resurrects U1\'s profile/counts — they stay hidden, not just replaced by a fabricated empty state', async () => {
    mockGetAuthState.mockResolvedValueOnce(authState('u1'));
    mockLoadProfile.mockResolvedValueOnce({ major: 'U1-PROFILE' });
    render(<AccountPage />);
    await waitFor(() => expect(screen.getByText('U1-PROFILE')).toBeInTheDocument());
    expect(screen.getByText('3')).toBeInTheDocument(); // favorites
    expect(screen.getByText('2')).toBeInTheDocument(); // tracker

    mockGetAuthState.mockResolvedValueOnce(authState('u2'));
    mockGetFavorites.mockRejectedValueOnce(new Error('down'));
    act(() => { authCallback?.(authState('u2')); });

    await waitFor(() => expect(screen.getByText('account.loadError')).toBeInTheDocument());
    expect(screen.queryByText('U1-PROFILE')).not.toBeInTheDocument();
    expect(screen.queryByText('3')).not.toBeInTheDocument();
    expect(screen.queryByText('2')).not.toBeInTheDocument();
    expect(screen.queryByText('u1@x.com')).not.toBeInTheDocument();
  });

  it('U1\'s original mount fetch REJECTING after U2 has ALREADY succeeded must not set loadError or hide U2\'s already-committed data', async () => {
    let rejectU1!: (e: Error) => void;
    mockGetAuthState.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectU1 = reject; }));
    mockLoadProfile.mockResolvedValueOnce({ major: 'U1-NEVER-SHOWN' });
    render(<AccountPage />);
    expect(screen.getByText('account.loading')).toBeInTheDocument();

    mockGetAuthState.mockResolvedValueOnce(authState('u2'));
    mockLoadProfile.mockResolvedValueOnce({ major: 'U2-FRESH' });
    act(() => { authCallback?.(authState('u2')); });
    await waitFor(() => expect(screen.getByText('U2-FRESH')).toBeInTheDocument());

    // U1's original mount fetch (generation 0) finally rejects — it must
    // never retroactively mark the page as errored, hiding U2's real,
    // already-committed and rendered data.
    await act(async () => { rejectU1(new Error('u1 down')); });
    expect(screen.getByText('U2-FRESH')).toBeInTheDocument();
    expect(screen.getByText('u2@x.com')).toBeInTheDocument();
    expect(screen.queryByText('account.loadError')).not.toBeInTheDocument();
  });

  it('U1\'s original mount fetch settling while U2\'s OWN fetch is STILL pending must not end loading early — must not flash "no profile" before U2 actually resolves', async () => {
    let resolveU1!: (v: unknown) => void;
    mockGetAuthState.mockReturnValueOnce(new Promise((r) => { resolveU1 = r; }));
    mockLoadProfile.mockResolvedValueOnce({ major: 'U1-STALE' });
    render(<AccountPage />);
    expect(screen.getByText('account.loading')).toBeInTheDocument();

    // Live switch to U2 — U2's OWN getAuthState() call also stays pending,
    // so gen1's load cannot possibly have committed anything yet. Queued
    // BEFORE the trigger: loadProfile() is invoked synchronously inside
    // the authCallback handler, so queuing its value any later would miss
    // that call entirely and silently fall back to the default mock.
    let resolveU2!: (v: unknown) => void;
    mockGetAuthState.mockReturnValueOnce(new Promise((r) => { resolveU2 = r; }));
    mockLoadProfile.mockResolvedValueOnce({ major: 'U2-FRESH' });
    act(() => { authCallback?.(authState('u2')); });
    expect(screen.getByText('account.loading')).toBeInTheDocument();

    // U1's original (now-superseded) fetch finally resolves while U2's own
    // fetch is still in flight — the page must still read as loading, not
    // flash a confirmed-empty/no-profile state built from the reset.
    resolveU1(authState('u1'));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.getByText('account.loading')).toBeInTheDocument();
    expect(screen.queryByText('U1-STALE')).not.toBeInTheDocument();
    expect(screen.queryByText('account.noProfile')).not.toBeInTheDocument();

    resolveU2(authState('u2'));
    await waitFor(() => expect(screen.getByText('U2-FRESH')).toBeInTheDocument());
  });

  it('ABA: U1 (gen0, deferred) -> null (gen1) -> U1 again (gen2, SAME uid as gen0 but a genuinely later generation) — gen0\'s late resolution must never overwrite gen2\'s fresh state, proving the guard is the GENERATION counter, not merely a uid comparison', async () => {
    let resolveGen0!: (v: unknown) => void;
    mockGetAuthState.mockReturnValueOnce(new Promise((r) => { resolveGen0 = r; }));
    mockLoadProfile.mockResolvedValueOnce({ major: 'GEN0-STALE' });
    render(<AccountPage />);

    act(() => { authCallback?.(authState(null)); }); // -> gen1 (null)
    mockGetAuthState.mockResolvedValueOnce(authState('u1'));
    mockLoadProfile.mockResolvedValueOnce({ major: 'GEN2-FRESH' });
    act(() => { authCallback?.(authState('u1')); }); // -> gen2 (u1 again — same uid as gen0)
    await waitFor(() => expect(screen.getByText('GEN2-FRESH')).toBeInTheDocument());

    // gen0's original (U1) fetch finally resolves — same uid as gen2, but
    // it must still be dropped as stale by generation alone.
    resolveGen0(authState('u1'));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText('GEN0-STALE')).not.toBeInTheDocument();
    expect(screen.getByText('GEN2-FRESH')).toBeInTheDocument();
  });
});

describe('AccountPage — PremiumIntent resets on identity change (not just a prop update)', () => {
  it('permanent U1 -> permanent U2: the form never carries U1\'s typed email into U2\'s session', async () => {
    mockGetAuthState.mockResolvedValueOnce(authState('u1', { email: 'u1@x.com' }));
    render(<AccountPage />);
    await waitFor(() => expect(screen.getByText('account.intentCta')).toBeInTheDocument());
    fireEvent.click(screen.getByText('account.intentCta'));
    const u1Input = screen.getByLabelText('account.intentEmailPlaceholder') as HTMLInputElement;
    expect(u1Input.value).toBe('u1@x.com');
    fireEvent.change(u1Input, { target: { value: 'u1-typed-override@x.com' } });

    mockGetAuthState.mockResolvedValueOnce(authState('u2', { email: 'u2@x.com' }));
    act(() => { authCallback?.(authState('u2', { email: 'u2@x.com' })); });
    await waitFor(() => expect(screen.getByText('u2@x.com')).toBeInTheDocument());

    // The remount collapses the form back to its closed 'idle' phase —
    // U1's typed override must not still be sitting in a live input.
    expect(screen.queryByDisplayValue('u1-typed-override@x.com')).not.toBeInTheDocument();
    expect(screen.getByText('account.intentCta')).toBeInTheDocument();

    // If U2 opens the form fresh, it is seeded with U2's OWN email.
    fireEvent.click(screen.getByText('account.intentCta'));
    const u2Input = screen.getByLabelText('account.intentEmailPlaceholder') as HTMLInputElement;
    expect(u2Input.value).toBe('u2@x.com');
  });

  it('permanent U1 -> anonymous: the form resets to a blank/closed state, never U1\'s email', async () => {
    mockGetAuthState.mockResolvedValueOnce(authState('u1', { email: 'u1@x.com' }));
    render(<AccountPage />);
    await waitFor(() => expect(screen.getByText('account.intentCta')).toBeInTheDocument());
    fireEvent.click(screen.getByText('account.intentCta'));
    expect((screen.getByLabelText('account.intentEmailPlaceholder') as HTMLInputElement).value).toBe('u1@x.com');

    mockGetAuthState.mockResolvedValueOnce(authState('anon-1', { anon: true, email: null }));
    act(() => { authCallback?.(authState('anon-1', { anon: true, email: null })); });
    await waitFor(() => expect(screen.getByText('account.saveAccount')).toBeInTheDocument());

    expect(screen.queryByDisplayValue('u1@x.com')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('account.intentCta'));
    expect((screen.getByLabelText('account.intentEmailPlaceholder') as HTMLInputElement).value).toBe('');
  });
});
