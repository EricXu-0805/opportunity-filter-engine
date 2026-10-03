import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';

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
import { advanceOwnerEpoch, isLocalOwnerReady, OwnerMismatchError, syncLocalIdentityOwner } from '@/lib/identity-owner';

const SERVER_KEY = 'BServerKeyThatMatchesThePrivateOneSigningPushes';

// The control is bound to the account that clicks it and is offered only once
// there is one. identity-owner is real here, so claim an owner the way the
// dashboard's own data load does.
async function claimOwner(uid: string): Promise<void> {
  advanceOwnerEpoch(uid);
  await syncLocalIdentityOwner(uid);
  for (let i = 0; i < 200 && !isLocalOwnerReady(uid); i += 1) await new Promise((r) => setTimeout(r, 0));
  expect(isLocalOwnerReady(uid)).toBe(true);
}
const U1 = '11111111-1111-4111-8111-111111111111';
const U2 = '22222222-2222-4222-8222-222222222222';

beforeEach(async () => {
  vi.clearAllMocks();
  isPushSupported.mockReturnValue(true);
  getPushStatus.mockResolvedValue('default');
  getVapidPublicKey.mockResolvedValue(SERVER_KEY);
  subscribeToPush.mockResolvedValue(true);
  await claimOwner(U1);
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
    await waitFor(() => expect(subscribeToPush).toHaveBeenCalledWith(SERVER_KEY, expect.anything()));
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

describe('the control is bound to an account', () => {
  it('is disabled until an owner is established, then offered', async () => {
    // A fresh /dashboard load renders this before any identity has resolved.
    // A token captured then is the null sentinel; every write is refused; the
    // student saw a button that did nothing.
    advanceOwnerEpoch(null);
    render(<PushToggle />);
    expect(await screen.findByRole('button')).toBeDisabled();

    await claimOwner(U1);
    await waitFor(() => expect(screen.getByRole('button')).not.toBeDisabled());
  });

  it('a raced owner switch neither paints U1\'s result for U2 nor leaves U2 a dead control', async () => {
    let resolveSub: (v: boolean) => void = () => {};
    subscribeToPush.mockImplementationOnce(() => new Promise<boolean>((r) => { resolveSub = r; }));
    render(<PushToggle />);
    const button = await screen.findByRole('button');
    await waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);
    await waitFor(() => expect(subscribeToPush).toHaveBeenCalled());
    expect(button).toBeDisabled();

    await claimOwner(U2);
    resolveSub(true);
    await new Promise((r) => setTimeout(r, 20));

    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button')).not.toBeDisabled();
  });

  // The status is a fact about an account: the browser subscription survives
  // a sign-out, the account's row behind it does not.
  it('re-reads the status for each account the browser changes to', async () => {
    getPushStatus.mockResolvedValueOnce('subscribed').mockResolvedValue('default');
    render(<PushToggle />);
    await waitFor(() => expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'true'));

    await claimOwner(U2);

    await waitFor(() => expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'false'));
    expect(getPushStatus).toHaveBeenCalledTimes(2);
  });

  it('a refusal that lands after a switch paints nothing over the next account', async () => {
    let refuse: (err: Error) => void = () => {};
    subscribeToPush.mockImplementationOnce(() => new Promise((_resolve, reject) => { refuse = reject; }));
    getPushStatus.mockResolvedValueOnce('default').mockResolvedValue('subscribed');
    render(<PushToggle />);
    const button = await screen.findByRole('button');
    await waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);
    await waitFor(() => expect(subscribeToPush).toHaveBeenCalled());

    await claimOwner(U2);
    await waitFor(() => expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'true'));
    await act(async () => refuse(new OwnerMismatchError()));

    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('does not paint a status read that started under the previous account', async () => {
    let finishFirstRead: (status: string) => void = () => {};
    getPushStatus
      .mockImplementationOnce(() => new Promise((resolve) => { finishFirstRead = resolve; }))
      .mockResolvedValue('default');
    render(<PushToggle />);
    await waitFor(() => expect(getPushStatus).toHaveBeenCalledTimes(1));

    await claimOwner(U2);
    await waitFor(() => expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'false'));
    await act(async () => finishFirstRead('subscribed'));

    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'false');
  });
});

describe('a failed change is reported, not painted as done', () => {
  async function renderReady(status: 'subscribed' | 'default') {
    getPushStatus.mockResolvedValue(status);
    render(<PushToggle />);
    const button = await screen.findByRole('button');
    await waitFor(() => expect(button).not.toBeDisabled());
    await waitFor(() => expect(button).toHaveAttribute('aria-pressed', String(status === 'subscribed')));
    return button;
  }

  it('keeps "on" and says so when unsubscribing fails, and a retry can still succeed', async () => {
    unsubscribeFromPush.mockRejectedValueOnce(new Error('push unsubscribe failed')).mockResolvedValueOnce(undefined);
    const button = await renderReady('subscribed');

    fireEvent.click(button);

    expect(await screen.findByRole('alert')).toHaveTextContent('common.error');
    expect(button).toHaveAttribute('aria-pressed', 'true');
    expect(button).not.toBeDisabled();

    fireEvent.click(button);

    await waitFor(() => expect(button).toHaveAttribute('aria-pressed', 'false'));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('says so when subscribing throws, and stays off', async () => {
    subscribeToPush.mockRejectedValueOnce(new Error('push service unavailable'));
    const button = await renderReady('default');

    fireEvent.click(button);

    expect(await screen.findByRole('alert')).toHaveTextContent('common.error');
    expect(button).toHaveAttribute('aria-pressed', 'false');
  });

  it('does not show one account\'s failure to the next', async () => {
    unsubscribeFromPush.mockRejectedValueOnce(new Error('push unsubscribe failed'));
    const button = await renderReady('subscribed');
    fireEvent.click(button);
    await screen.findByRole('alert');

    await claimOwner(U2);

    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });
});
