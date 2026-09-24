import { act, renderHook, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MatchViewRequestState } from '@/lib/api';
import type { ProfileData } from '@/lib/types';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { readResultSession, resultRequestKey, writeResultSession, type ResultCursorState } from '@/lib/result-session';
import { useResultsSession } from './use-results-session';

const profile: ProfileData = { institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore', is_international: false, research_interests: 'robots', skills: [] };
const view: MatchViewRequestState = { tab: 'all', search_query: 'robotics', paid: '', intl: '', source: '', on_campus: '', deadline: '', min_score: 0, scope: '', sort_by: 'score', show_dismissed: false, favorite_ids: [], dismissed_ids: [], today: '2026-09-24' };
const key = resultRequestKey(profile, false, view);
const first: ResultCursorState = { requestKey: key, page: 1, cursors: [[1, null], [2, 'server-cursor']] };
function seed(overrides = {}) {
  return writeResultSession({ ...first, page: 2, returnUrl: '/results?q=robotics', showDismissed: false,
    anchorId: 'robot', anchorOffset: 120, scrollY: 1800, viewedIds: ['robot'], ...overrides })!;
}
function useHarness({ arrivalId = null, ready = true, failed = false, currentProfile = profile, currentView = view }:
  { arrivalId?: string | null; ready?: boolean; failed?: boolean; currentProfile?: ProfileData; currentView?: MatchViewRequestState }) {
  const [page, setPage] = useState(1);
  const [showDismissed, setShowDismissed] = useState(false);
  const session = useResultsSession({ arrivalId, profile: currentProfile, semantic: false, view: { ...currentView, show_dismissed: showDismissed }, ready, failed,
    publicUrl: '/results?q=robotics', page, setPage, setShowDismissed });
  return { ...session, page, showDismissed, setPage };
}
let frames: FrameRequestCallback[];
beforeEach(async () => {
  window.history.replaceState({ next: 'preserved' }, '', '/results?q=robotics');
  advanceOwnerEpoch('return-a');
  await syncLocalIdentityOwner('return-a');
  frames = [];
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => { frames.push(callback); return frames.length; });
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  Object.defineProperty(window, 'scrollY', { configurable: true, value: 0 });
});
function paintFrames() { while (frames.length) frames.shift()!(0); }

describe('results session hydration and accepted request lifetime', () => {
  it('waits for successful private reads, then restores page and hidden-row toggle without restoring data', () => {
    const saved = seed({ showDismissed: true, requestKey: resultRequestKey(profile, false, { ...view, show_dismissed: true }) });
    const { result, rerender } = renderHook(useHarness, { initialProps: { arrivalId: saved.id, ready: false } });
    expect(result.current.settled).toBe(false);
    expect(result.current.page).toBe(1);
    rerender({ arrivalId: saved.id, ready: true });
    expect(result.current.page).toBe(2);
    expect(result.current.showDismissed).toBe(true);
    expect(result.current.restore?.cursors).toContainEqual([2, 'server-cursor']);
    expect(result.current.viewedIds.has('robot')).toBe(true);
    expect(window.scrollTo).not.toHaveBeenCalled();
    expect(result.current).not.toHaveProperty('data');
  });

  it('does not mistake failed reads for successfully empty private collections', () => {
    const saved = seed();
    const { result } = renderHook(useHarness, { initialProps: { arrivalId: saved.id, ready: false, failed: true } });
    expect(result.current.settled).toBe(true);
    expect(result.current.page).toBe(1);
    expect(result.current.restore).toBeNull();
    expect(result.current.resetNotice).toBe(true);
  });

  it('persists an early successful match only when delayed private reads settle for that same view', async () => {
    const { result, rerender } = renderHook(useHarness, { initialProps: { ready: false } });
    act(() => result.current.onValidated(first));
    expect(sessionStorage.length).toBe(0);
    rerender({ ready: true });
    await waitFor(() => expect(result.current.sessionId).not.toBeNull());
    expect(readResultSession(result.current.sessionId)?.cursors).toEqual(first.cursors);
  });

  it('does not persist an early answer when the eventual private collections change its view', () => {
    const { result, rerender } = renderHook(useHarness, { initialProps: { ready: false, currentView: view } });
    act(() => result.current.onValidated(first));
    rerender({ ready: true, currentView: { ...view, favorite_ids: ['new-favorite'] } });
    expect(result.current.sessionId).toBeNull();
  });

  it.each(['profile', 'favorites', 'day'])('rejects an old ticket after %s changes', (kind) => {
    const saved = seed();
    const { result } = renderHook(useHarness, { initialProps: { arrivalId: saved.id,
      currentProfile: kind === 'profile' ? { ...profile, research_interests: 'chemistry' } : profile,
      currentView: kind === 'favorites' ? { ...view, favorite_ids: ['changed'] } : kind === 'day' ? { ...view, today: '2026-09-25' } : view,
    } });
    expect(result.current.page).toBe(1);
    expect(result.current.restore).toBeNull();
    expect(result.current.resetNotice).toBe(true);
  });

  it('restores position only after the cursor response validates, then uses the anchor offset', () => {
    const saved = seed();
    const anchor = document.createElement('div'); anchor.id = 'match-card-robot'; document.body.append(anchor);
    vi.spyOn(anchor, 'getBoundingClientRect').mockReturnValue({ top: 640 } as DOMRect);
    const { result } = renderHook(useHarness, { initialProps: { arrivalId: saved.id } });
    expect(window.scrollTo).not.toHaveBeenCalled();
    act(() => result.current.onValidated({ ...first, page: 2 }));
    act(paintFrames);
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 520, behavior: 'instant' });
    anchor.remove();
  });

  it.each(['input', 'identity', 'page', 'route', 'unmount'])('cancels late restoration on %s change', async (kind) => {
    const saved = seed();
    const { result, unmount } = renderHook(useHarness, { initialProps: { arrivalId: saved.id } });
    act(() => result.current.onValidated({ ...first, page: 2 }));
    if (kind === 'input') window.dispatchEvent(new Event('wheel'));
    if (kind === 'identity') {
      advanceOwnerEpoch('return-b'); await syncLocalIdentityOwner('return-b');
      act(() => result.current.resetForIdentity());
    }
    if (kind === 'page') act(() => result.current.setPage(3));
    if (kind === 'route') window.history.replaceState({}, '', '/opportunities/robot');
    if (kind === 'unmount') unmount();
    act(paintFrames);
    expect(window.scrollTo).not.toHaveBeenCalled();
    if (kind === 'identity') expect(result.current.viewedIds.size).toBe(0);
  });

  it('resets an expired cursor to page one with notice, never replaying its scroll', () => {
    const saved = seed();
    const { result } = renderHook(useHarness, { initialProps: { arrivalId: saved.id } });
    act(() => result.current.cursorExpired());
    expect(result.current.page).toBe(1);
    expect(result.current.resetNotice).toBe(true);
    expect(result.current.restore).toBeNull();
    act(paintFrames);
    expect(window.scrollTo).not.toHaveBeenCalled();
  });

  it('marks viewed independently and flushes immediate reload position without waiting for debounce', () => {
    const { result } = renderHook(useHarness, { initialProps: {} });
    act(() => result.current.onValidated(first));
    const anchor = document.createElement('div'); anchor.id = 'match-card-robot'; document.body.append(anchor);
    vi.spyOn(anchor, 'getBoundingClientRect').mockReturnValue({ top: 120 } as DOMRect);
    act(() => result.current.rememberOpportunity('robot'));
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 2100 });
    window.dispatchEvent(new Event('scroll'));
    window.dispatchEvent(new Event('pagehide'));
    expect(readResultSession(result.current.sessionId)).toMatchObject({ scrollY: 2100, viewedIds: ['robot'], anchorId: 'robot' });
    expect(result.current.viewedIds.has('robot')).toBe(true);
    anchor.remove();
  });

  it('keeps the in-memory viewed mark if sessionStorage refuses persistence', () => {
    vi.spyOn(sessionStorage, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    const { result } = renderHook(useHarness, { initialProps: {} });
    act(() => result.current.onValidated(first));
    expect(result.current.sessionId).toBeNull();
    act(() => result.current.rememberOpportunity('robot'));
    expect(result.current.viewedIds.has('robot')).toBe(true);
    expect(result.current.sessionId).toBeNull();
  });

  it('does not overwrite remembered results coordinates after navigation removes the list', () => {
    const { result, unmount } = renderHook(useHarness, { initialProps: {} });
    act(() => result.current.onValidated(first));
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 1600 });
    const anchor = document.createElement('div'); anchor.id = 'match-card-robot'; document.body.append(anchor);
    vi.spyOn(anchor, 'getBoundingClientRect').mockReturnValue({ top: 120 } as DOMRect);
    act(() => result.current.rememberOpportunity('robot'));
    const id = result.current.sessionId;
    anchor.remove();
    window.history.replaceState({}, '', '/opportunities/robot');
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 0 });
    unmount();
    expect(readResultSession(id)).toMatchObject({ scrollY: 1600, anchorOffset: 120 });
  });
});
