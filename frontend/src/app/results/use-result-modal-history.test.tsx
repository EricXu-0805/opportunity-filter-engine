import { act, renderHook } from '@testing-library/react';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { useResultModalHistory } from './use-result-modal-history';

const marker = '__ofeResultsModal';
beforeEach(async () => {
  window.history.replaceState({ __NA: true, nextTree: ['results'], other: 'kept' }, '', '/results?q=robots');
  advanceOwnerEpoch('modal-a');
  await syncLocalIdentityOwner('modal-a');
});
function useHarness({ owner = 'modal-a', siblings = false } = {}) {
  const [open, setOpen] = useState(false);
  // A real list mounts closed hooks both before and after the selected card.
  useResultModalHistory(false, () => { throw new Error('closed card cannot close another card'); }, siblings ? owner : null);
  useResultModalHistory(open, () => setOpen(false), owner);
  useResultModalHistory(false, () => { throw new Error('closed card cannot close another card'); }, siblings ? owner : null);
  return { open, setOpen };
}
function popTo(state: Record<string, unknown>) {
  window.history.replaceState(state, '', '/results?q=robots');
  window.dispatchEvent(new PopStateEvent('popstate', { state }));
}

describe('results modal history ownership', () => {
  it('pushes one overlay entry, preserving Next state and the public URL', () => {
    const push = vi.spyOn(window.history, 'pushState');
    const { result, rerender } = renderHook(useHarness);
    act(() => result.current.setOpen(true));
    expect(push).toHaveBeenCalledTimes(1);
    expect(window.history.state).toMatchObject({ __NA: true, nextTree: ['results'], other: 'kept', [marker]: expect.any(String) });
    expect(window.location.search).toBe('?q=robots');
    rerender();
    expect(push).toHaveBeenCalledTimes(1);
  });

  it('Back closes only the open overlay; closed sibling hooks cannot strip a live marker', () => {
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
    const { result } = renderHook(useHarness, { initialProps: { siblings: true } });
    act(() => result.current.setOpen(true));
    const liveState = window.history.state;
    act(() => window.dispatchEvent(new PopStateEvent('popstate', { state: liveState })));
    expect(window.history.state[marker]).toBe(liveState[marker]);
    expect(result.current.open).toBe(true);
    act(() => popTo({ __NA: true, nextTree: ['results'] }));
    expect(result.current.open).toBe(false);
    expect(back).not.toHaveBeenCalled();
  });

  it('Close consumes its own history entry exactly once, including repeated open/close', () => {
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
    const { result, rerender } = renderHook(useHarness);
    for (let i = 0; i < 2; i++) {
      act(() => result.current.setOpen(true));
      act(() => result.current.setOpen(false));
      rerender();
      expect(back).toHaveBeenCalledTimes(i + 1);
      act(() => popTo({ __NA: true, nextTree: ['results'] }));
    }
  });

  it('Forward to an already closed overlay preserves Next state without reopening a draft', () => {
    const { result } = renderHook(useHarness);
    act(() => result.current.setOpen(true));
    const overlayState = window.history.state;
    act(() => popTo({ __NA: true }));
    expect(result.current.open).toBe(false);
    act(() => popTo(overlayState));
    expect(window.history.state).toMatchObject({ __NA: true, nextTree: ['results'], other: 'kept' });
    expect(window.history.state[marker]).toBeUndefined();
    expect(result.current.open).toBe(false);
  });

  it('identity changes revoke the owned marker without navigating another account backwards', async () => {
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
    const { result, rerender } = renderHook(useHarness, { initialProps: { owner: 'modal-a' } });
    act(() => result.current.setOpen(true));
    advanceOwnerEpoch('modal-b');
    await syncLocalIdentityOwner('modal-b');
    rerender({ owner: 'modal-b' });
    expect(window.history.state[marker]).toBeUndefined();
    expect(back).not.toHaveBeenCalled();
  });

  it('unmounting strips only its marker and never goes back', () => {
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
    const { result, unmount } = renderHook(useHarness);
    act(() => result.current.setOpen(true));
    unmount();
    expect(window.history.state).toMatchObject({ __NA: true, nextTree: ['results'], other: 'kept' });
    expect(window.history.state[marker]).toBeUndefined();
    expect(back).not.toHaveBeenCalled();
  });

  it('does not consume a history entry installed by another navigation', () => {
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
    const { result } = renderHook(useHarness);
    act(() => result.current.setOpen(true));
    window.history.replaceState({ __NA: true, page: 'new' }, '', '/opportunities/robot');
    act(() => result.current.setOpen(false));
    expect(back).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe('/opportunities/robot');
  });
});
