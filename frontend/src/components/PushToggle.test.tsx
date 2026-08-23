import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (k: string) => k }) }));

const getPushStatus = vi.fn();
const subscribeToPush = vi.fn();
const unsubscribeFromPush = vi.fn();
const isPushSupported = vi.fn();
vi.mock('@/lib/push', () => ({
  getPushStatus: (...a: unknown[]) => getPushStatus(...a),
  subscribeToPush: (...a: unknown[]) => subscribeToPush(...a),
  unsubscribeFromPush: (...a: unknown[]) => unsubscribeFromPush(...a),
  isPushSupported: (...a: unknown[]) => isPushSupported(...a),
}));

const getVapidPublicKey = vi.fn();
vi.mock('@/lib/api', () => ({
  getVapidPublicKey: (...a: unknown[]) => getVapidPublicKey(...a),
}));

import PushToggle from './PushToggle';

const SERVER_KEY = 'BServerKeyThatMatchesThePrivateOneSigningPushes';

beforeEach(() => {
  vi.clearAllMocks();
  isPushSupported.mockReturnValue(true);
  getPushStatus.mockResolvedValue('default');
  getVapidPublicKey.mockResolvedValue(SERVER_KEY);
  subscribeToPush.mockResolvedValue(true);
});

afterEach(() => vi.restoreAllMocks());

/** The key a subscription is minted with must be the one whose private half
 *  signs the pushes. Only the server knows that. A build-time copy is right
 *  only by coincidence — and wrong silently, because the browser accepts any
 *  well-formed key and only the delivery months later fails. */
describe('the subscription key comes from the server that signs the pushes', () => {
  it('asks the server rather than a build-time constant', async () => {
    render(<PushToggle />);
    await waitFor(() => expect(getVapidPublicKey).toHaveBeenCalled());
    fireEvent.click(await screen.findByRole('button'));
    await waitFor(() => expect(subscribeToPush).toHaveBeenCalledWith(SERVER_KEY));
  });

  it('offers the control even with no NEXT_PUBLIC_VAPID_PUBLIC_KEY in the build', async () => {
    // The regression this replaces: an unset Vercel variable hid the toggle
    // entirely, so nobody could subscribe, so the daily reminders cron had
    // nobody to deliver to — and reported success every night regardless.
    const prior = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY;
    delete process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY;
    try {
      render(<PushToggle />);
      expect(await screen.findByRole('button')).toBeInTheDocument();
    } finally {
      if (prior !== undefined) process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY = prior;
    }
  });

  it('renders nothing when the server says push is not configured', async () => {
    // 503 from /push/vapid-public-key. Fails closed: no server key means no
    // subscription can ever be delivered to, so offering the control lies.
    getVapidPublicKey.mockResolvedValue(null);
    const { container } = render(<PushToggle />);
    await waitFor(() => expect(getVapidPublicKey).toHaveBeenCalled());
    await waitFor(() => expect(container.querySelector('button')).toBeNull());
  });

  it('does not ask for a key when the browser cannot do push at all', async () => {
    isPushSupported.mockReturnValue(false);
    const { container } = render(<PushToggle />);
    await waitFor(() => expect(container.querySelector('button')).toBeNull());
    expect(getVapidPublicKey).not.toHaveBeenCalled();
  });

  it('unsubscribing needs no key', async () => {
    getPushStatus.mockResolvedValue('subscribed');
    unsubscribeFromPush.mockResolvedValue(true);
    render(<PushToggle />);
    fireEvent.click(await screen.findByRole('button'));
    await waitFor(() => expect(unsubscribeFromPush).toHaveBeenCalled());
    expect(subscribeToPush).not.toHaveBeenCalled();
  });
});
