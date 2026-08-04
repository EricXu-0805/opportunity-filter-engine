import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

import { useTrackerData, TRACKER_COLUMNS, dateInDays, isReminderDue } from './use-tracker-data';

// W14 write contracts: trackInteraction resolves only on a persisted write
// (throws otherwise); updateInteractionDetails resolves true only on success.
const trackInteraction = vi.fn((_id: string, _type: string) => Promise.resolve());
const removeInteraction = vi.fn((_id: string) => Promise.resolve());
const updateInteractionDetails = vi.fn((_id: string, _patch: unknown) => Promise.resolve(true));
const getInteractionsFull = vi.fn(() => Promise.resolve(interactions));
let interactions: Map<string, { type: string; notes?: string; remind_at?: string }>;
// Captured so tests can emit auth events (cross-tab uid switches).
let authCallback: ((s: { user: { id: string } | null }) => void) | null = null;

vi.mock('@/lib/supabase', () => ({
  getInteractionsFull: () => getInteractionsFull(),
  trackInteraction: (id: string, type: string) => trackInteraction(id, type),
  removeInteraction: (id: string) => removeInteraction(id),
  updateInteractionDetails: (id: string, patch: unknown) => updateInteractionDetails(id, patch),
  onAuthChange: (cb: (s: { user: { id: string } | null }) => void) => {
    authCallback = cb;
    return () => { authCallback = null; };
  },
}));

vi.mock('@/lib/api', () => ({
  getOpportunitiesByIds: (ids: string[]) =>
    Promise.resolve(ids.map((id) => ({ id, title: `Opp ${id}`, lab_or_program: `Lab ${id}` }))),
}));

beforeEach(() => {
  trackInteraction.mockClear().mockImplementation(() => Promise.resolve());
  removeInteraction.mockClear();
  updateInteractionDetails.mockClear().mockImplementation(() => Promise.resolve(true));
  getInteractionsFull.mockClear().mockImplementation(() => Promise.resolve(interactions));
  authCallback = null;
  interactions = new Map([
    ['o1', { type: 'applied', notes: 'hi' }],
    ['o2', { type: 'interviewing' }],
    ['o3', { type: 'dismissed' }],
  ]);
});

describe('useTrackerData', () => {

  it('joins interactions with opportunity details', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toHaveLength(3);
    const o1 = result.current.items.find((i) => i.opp.id === 'o1');
    expect(o1?.opp.title).toBe('Opp o1');
    expect(o1?.record.type).toBe('applied');
    expect(o1?.record.notes).toBe('hi');
  });

  it('excludes dismissed from the pipeline columns', () => {
    expect(TRACKER_COLUMNS).toEqual(['contacted', 'applied', 'replied', 'interviewing', 'rejected']);
    expect(TRACKER_COLUMNS).not.toContain('dismissed');
  });

  it('changeStatus optimistically moves an item and persists', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.changeStatus('o1', 'interviewing'));
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('interviewing');
    expect(trackInteraction).toHaveBeenCalledWith('o1', 'interviewing');
  });

  it('re-selecting the active status clears and removes the item', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.changeStatus('o1', 'applied')); // same as current
    expect(result.current.items.find((i) => i.opp.id === 'o1')).toBeUndefined();
    expect(removeInteraction).toHaveBeenCalledWith('o1');
  });

  it('saveNotes persists trimmed notes (null when blank)', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.saveNotes('o2', '  follow up  '));
    expect(result.current.items.find((i) => i.opp.id === 'o2')?.record.notes).toBe('  follow up  ');
    expect(updateInteractionDetails).toHaveBeenCalledWith('o2', { notes: 'follow up' });
    act(() => result.current.saveNotes('o2', '   '));
    expect(updateInteractionDetails).toHaveBeenCalledWith('o2', { notes: null });
  });

  // W14 truthful zero states: a failed load is an error, never an empty board.
  it('sets loadError on a failed load and retry() refetches', async () => {
    getInteractionsFull.mockImplementationOnce(() =>
      Promise.reject(new Error('interactions-load-failed: outage')),
    );
    const { result } = renderHook(() => useTrackerData());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.loadError).toBe(true);
    expect(result.current.items).toHaveLength(0);

    act(() => result.current.retry());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.loadError).toBe(false);
    expect(result.current.items).toHaveLength(3);
    expect(getInteractionsFull).toHaveBeenCalledTimes(2);
  });

  // W14 truthful status writes: a failed persist reverts the optimistic move.
  it('changeStatus reverts the optimistic column move when the write fails', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    trackInteraction.mockImplementationOnce(() =>
      Promise.reject(new Error('interaction-save-failed: down')),
    );
    act(() => result.current.changeStatus('o1', 'interviewing'));
    // Optimistic first…
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('interviewing');
    // …then reverted once the write failure lands.
    await waitFor(() => {
      expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('applied');
    });
  });

  it('saveNotes reverts the optimistic note when the write reports failure', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    updateInteractionDetails.mockImplementationOnce(() => Promise.resolve(false));
    act(() => result.current.saveNotes('o1', 'new note'));
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.notes).toBe('new note');
    await waitFor(() => {
      expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.notes).toBe('hi');
    });
  });

  // W14 cross-tab uid isolation: an identity switch clears the board and
  // refetches under the new auth context; the initial null→uid resolution
  // does not double-fetch.
  it('refetches on a real uid switch but not on the initial uid resolution', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(getInteractionsFull).toHaveBeenCalledTimes(1);

    // Initial resolution (null → anon uid): absorbed, no second fetch.
    act(() => authCallback?.({ user: { id: 'anon-a' } }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(getInteractionsFull).toHaveBeenCalledTimes(1);

    // Real switch (uid A → uid B): clear + refetch under the new identity.
    interactions = new Map([['o9', { type: 'contacted' }]]);
    act(() => authCallback?.({ user: { id: 'account-b' } }));
    await waitFor(() => expect(getInteractionsFull).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items.map((i) => i.opp.id)).toEqual(['o9']);
  });
});

describe('reminder helpers + setReminder', () => {
  it('isReminderDue: past/today due, future not, empty not', () => {
    const today = new Date().toISOString().slice(0, 10);
    expect(isReminderDue(today)).toBe(true);
    expect(isReminderDue('2000-01-01')).toBe(true);
    expect(isReminderDue(dateInDays(7))).toBe(false);
    expect(isReminderDue(undefined)).toBe(false);
  });

  it('dateInDays returns an ISO date N days ahead', () => {
    expect(dateInDays(0)).toBe(new Date().toISOString().slice(0, 10));
    expect(dateInDays(3)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('setReminder optimistically updates remind_at and persists', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.setReminder('o1', '2030-01-01'));
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.remind_at).toBe('2030-01-01');
    expect(updateInteractionDetails).toHaveBeenCalledWith('o1', { remind_at: '2030-01-01' });
    act(() => result.current.setReminder('o1', null));
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.remind_at).toBeUndefined();
    expect(updateInteractionDetails).toHaveBeenCalledWith('o1', { remind_at: null });
  });
});
