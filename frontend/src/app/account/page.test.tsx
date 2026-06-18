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

vi.mock('@/lib/supabase', () => ({
  getAuthState: () => mockGetAuthState(),
  onAuthChange: () => () => {},
  loadProfile: () => mockLoadProfile(),
  getFavorites: () => mockGetFavorites(),
  getInteractionsFull: () => mockGetInteractions(),
  joinWaitlist: (...args: unknown[]) => mockJoinWaitlist(...args),
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
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
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
