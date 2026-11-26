import { act, render, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import PushOwnerSync from './PushOwnerSync';

const { onAuthStateChange, sync } = vi.hoisted(() => ({ onAuthStateChange: vi.fn(), sync: vi.fn() }));
vi.mock('@/lib/push', () => ({ isPushSupported: () => true, synchronizePushOwner: sync }));
vi.mock('@/lib/supabase', () => ({ supabase: { auth: { onAuthStateChange } } }));

it('handles initial identity, direct sign-in and expired sessions outside the auth callback', async () => {
  const unsubscribe = vi.fn();
  onAuthStateChange.mockReturnValue({ data: { subscription: { unsubscribe } } });
  sync.mockResolvedValue(undefined);
  const view = render(<PushOwnerSync />);
  const observe = onAuthStateChange.mock.calls[0][0];
  for (const [index, event] of ['INITIAL_SESSION', 'SIGNED_IN', 'SIGNED_OUT'].entries()) {
    act(() => observe(event, null));
    expect(sync).toHaveBeenCalledTimes(index);
    await waitFor(() => expect(sync).toHaveBeenCalledTimes(index + 1));
  }
  sync.mockRejectedValueOnce(new Error('offline'));
  act(() => observe('SIGNED_IN', null));
  await waitFor(() => expect(sync).toHaveBeenCalledTimes(4));
  window.dispatchEvent(new Event('online'));
  await waitFor(() => expect(sync).toHaveBeenCalledTimes(5));
  view.unmount();
  expect(unsubscribe).toHaveBeenCalledOnce();
});
