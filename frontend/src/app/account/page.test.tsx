/*
 * /account hub — verifies the identity state machine (permanent vs guest),
 * the profile snapshot (present vs empty), and the activity links. It reuses
 * existing supabase helpers, all mocked here.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockOpenModal = vi.fn();
const mockGetAuthState = vi.fn();
const mockLoadProfile = vi.fn();
const mockGetFavorites = vi.fn();
const mockGetInteractions = vi.fn();
const mockJoinWaitlist = vi.fn();
const mockTrack = vi.fn();
const mockCreateOrder = vi.fn();
const mockGetMyOrders = vi.fn();
const mockClaimOrderPaid = vi.fn();

vi.mock('@/lib/supabase', () => ({
  getAuthState: () => mockGetAuthState(),
  onAuthChange: () => () => {},
  loadProfile: () => mockLoadProfile(),
  getFavorites: () => mockGetFavorites(),
  getInteractionsFull: () => mockGetInteractions(),
  joinWaitlist: (...args: unknown[]) => mockJoinWaitlist(...args),
  createOrder: (...args: unknown[]) => mockCreateOrder(...args),
  getMyOrders: () => mockGetMyOrders(),
  claimOrderPaid: (...args: unknown[]) => mockClaimOrderPaid(...args),
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
  mockGetFavorites.mockResolvedValue(new Set(['a', 'b', 'c']));
  mockGetInteractions.mockResolvedValue(new Map([['x', {}], ['y', {}]]));
  mockLoadProfile.mockResolvedValue(null);
  mockJoinWaitlist.mockResolvedValue(true);
  mockGetMyOrders.mockResolvedValue([]);
  mockClaimOrderPaid.mockResolvedValue(true);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

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

  it('does not strand on the loading spinner when a load promise rejects', async () => {
    mockGetAuthState.mockRejectedValue(new Error('network down'));
    render(<AccountPage />);
    // The loading text must clear (finally) and the page renders the guest state
    // instead of an infinite "Loading…".
    await waitFor(() => expect(screen.queryByText('account.loading')).not.toBeInTheDocument());
    expect(screen.getByText('account.saveAccount')).toBeInTheDocument();
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
    expect(mockGetMyOrders).not.toHaveBeenCalled();
    expect(mockCreateOrder).not.toHaveBeenCalled();
  });
});

describe('AccountPage — payments flag ON (order flow)', () => {
  const pendingOrder = {
    id: 'ord-1',
    package: 'single_email',
    amount_cents: 990,
    currency: 'usd',
    status: 'pending' as const,
    channel: 'manual',
    created_at: '2026-07-05T00:00:00+00:00',
    paid_at: null,
  };

  beforeEach(() => {
    vi.stubEnv('NEXT_PUBLIC_PAYMENTS', 'true');
    mockGetAuthState.mockResolvedValue({
      session: {}, user: { id: 'u1', is_anonymous: false }, isAnonymous: false,
      email: 'eric@example.com',
    });
    mockCreateOrder.mockResolvedValue(pendingOrder);
  });

  it('replaces the waitlist CTA with the package chooser', async () => {
    render(<AccountPage />);
    await waitFor(() => expect(screen.getByText('account.choosePackage')).toBeInTheDocument());
    expect(screen.queryByText('account.intentCta')).not.toBeInTheDocument();
    expect(screen.getByText('account.packageSingleEmail')).toBeInTheDocument();
    expect(screen.getByText('account.packageFullPackage')).toBeInTheDocument();
    expect(screen.getByText('$9.90')).toBeInTheDocument();
    expect(screen.getByText('$49.00')).toBeInTheDocument();
  });

  it('choose package → QR page with order id → claim paid → awaiting confirm', async () => {
    render(<AccountPage />);
    await waitFor(() => expect(screen.getByText('account.packageSingleEmail')).toBeInTheDocument());

    fireEvent.click(screen.getByText('account.packageSingleEmail'));
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'single_email', amountCents: 990 }),
    ));

    await waitFor(() => expect(screen.getByText('account.paidClaimCta')).toBeInTheDocument());
    expect(screen.getByAltText('account.payWechat')).toHaveAttribute('src', '/pay/wechat.png');
    expect(screen.getByAltText('account.payAlipay')).toHaveAttribute('src', '/pay/alipay.png');
    expect(screen.getByText(/ord-1/)).toBeInTheDocument();

    fireEvent.click(screen.getByText('account.paidClaimCta'));
    await waitFor(() => expect(mockClaimOrderPaid).toHaveBeenCalledWith('ord-1'));
    await waitFor(() =>
      expect(screen.getByText('account.orderAwaitingConfirm')).toBeInTheDocument(),
    );
  });

  it('resumes an awaiting_confirm order from the server on reload', async () => {
    mockGetMyOrders.mockResolvedValue([{ ...pendingOrder, status: 'awaiting_confirm' }]);
    render(<AccountPage />);
    await waitFor(() =>
      expect(screen.getByText('account.orderAwaitingConfirm')).toBeInTheDocument(),
    );
    expect(mockCreateOrder).not.toHaveBeenCalled();
  });

  it('shows the paid package as the current plan', async () => {
    mockGetMyOrders.mockResolvedValue([
      { ...pendingOrder, status: 'paid', paid_at: '2026-07-05T01:00:00+00:00' },
    ]);
    render(<AccountPage />);
    await waitFor(() =>
      expect(screen.getAllByText('account.packageSingleEmail').length).toBeGreaterThan(0),
    );
    expect(screen.getByText('account.paidPlanDesc')).toBeInTheDocument();
    expect(screen.queryByText('account.freePlan')).not.toBeInTheDocument();
  });
});
