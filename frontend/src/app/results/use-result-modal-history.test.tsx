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


describe('editor Back requests', () => {
  function useEditor() {
    const [open, setOpen] = useState(false);
    const [confirming, setConfirming] = useState(false);
    const [draft, setDraft] = useState('Unsaved exact text');
    const [dirty, setDirty] = useState(true);
    useResultModalHistory(false, () => {}, 'modal-a');
    useResultModalHistory(open, () => setOpen(false), 'modal-a', () => {
      if (dirty) { setConfirming(true); return false; }
      setOpen(false); return true;
    });
    useResultModalHistory(false, () => {}, 'modal-a');
    return { open, setOpen, confirming, setConfirming, draft, setDraft, setDirty };
  }
  it('restores the same marker and Next state on refusal; cancel and repeated Back keep the buffer', () => {
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
    const scroll = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    const { result } = renderHook(useEditor);
    act(() => result.current.setOpen(true));
    const id = window.history.state[marker];
    for (let i = 0; i < 2; i++) {
      act(() => popTo({ __NA: true, nextTree: ['results'], other: 'kept' }));
      expect(result.current.open).toBe(true); expect(result.current.confirming).toBe(true);
      expect(result.current.draft).toBe('Unsaved exact text');
      expect(window.history.state).toEqual({ __NA: true, nextTree: ['results'], other: 'kept', [marker]: id });
      expect(window.location.search).toBe('?q=robots');
      act(() => result.current.setConfirming(false));
    }
    expect(back).not.toHaveBeenCalled(); expect(scroll).not.toHaveBeenCalled();
    // The editor's explicit discard uses its normal onClose, consuming exactly
    // the restored entry. It does not ask a second time.
    act(() => result.current.setOpen(false));
    expect(back).toHaveBeenCalledTimes(1);
  });
  it('an accepted clean request closes itself without restoring or consuming another entry', () => {
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
    const { result } = renderHook(useEditor);
    act(() => { result.current.setOpen(true); result.current.setDirty(false); });
    const push = vi.spyOn(window.history, 'pushState');
    act(() => popTo({ __NA: true }));
    expect(result.current.open).toBe(false); expect(push).not.toHaveBeenCalled(); expect(back).not.toHaveBeenCalled();
  });
  it('owner invalidation bypasses a dirty guard on Back', async () => {
    const request = vi.fn(() => false); const close = vi.fn();
    renderHook(() => useResultModalHistory(true, close, 'modal-a', request));
    advanceOwnerEpoch('modal-b'); await syncLocalIdentityOwner('modal-b');
    const push = vi.spyOn(window.history, 'pushState');
    act(() => popTo({ __NA: true }));
    expect(request).not.toHaveBeenCalled(); expect(close).toHaveBeenCalledTimes(1); expect(push).not.toHaveBeenCalled();
  });
  it('retirement on a changed owner prop closes directly and never asks to keep private text', async () => {
    const request = vi.fn(() => false); const close = vi.fn();
    const { rerender } = renderHook(({ owner }) => useResultModalHistory(true, close, owner, request), { initialProps: { owner: 'modal-a' } });
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
    advanceOwnerEpoch('modal-b'); await syncLocalIdentityOwner('modal-b');
    rerender({ owner: 'modal-b' });
    expect(request).not.toHaveBeenCalled(); expect(close).toHaveBeenCalledOnce(); expect(back).not.toHaveBeenCalled();
    expect(window.history.state[marker]).toBeUndefined();
  });
  it('does not discard the editor if its request or history restoration fails', () => {
    const close = vi.fn(); const request = vi.fn(() => { throw new Error('editor not ready'); });
    renderHook(() => useResultModalHistory(true, close, 'modal-a', request));
    vi.spyOn(window.history, 'pushState').mockImplementation(() => { throw new Error('history denied'); });
    act(() => popTo({ __NA: true }));
    expect(request).toHaveBeenCalledOnce(); expect(close).not.toHaveBeenCalled();
  });
  it('never restores an editor marker onto another route', () => {
    const close = vi.fn(); const request = vi.fn(() => false);
    renderHook(() => useResultModalHistory(true, close, 'modal-a', request));
    window.history.replaceState({ __NA: true }, '', '/opportunities/other');
    act(() => window.dispatchEvent(new PopStateEvent('popstate')));
    expect(close).toHaveBeenCalledOnce(); expect(request).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe('/opportunities/other'); expect(window.history.state[marker]).toBeUndefined();
  });
});
