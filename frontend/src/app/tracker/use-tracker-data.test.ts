import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

import { useTrackerData, TRACKER_COLUMNS } from './use-tracker-data';

const trackInteraction = vi.fn((_id: string, _type: string) => Promise.resolve());
const removeInteraction = vi.fn((_id: string) => Promise.resolve());
const updateInteractionDetails = vi.fn((_id: string, _patch: unknown) => Promise.resolve());
let interactions: Map<string, { type: string; notes?: string; remind_at?: string }>;

vi.mock('@/lib/supabase', () => ({
  getInteractionsFull: () => Promise.resolve(interactions),
  trackInteraction: (id: string, type: string) => trackInteraction(id, type),
  removeInteraction: (id: string) => removeInteraction(id),
  updateInteractionDetails: (id: string, patch: unknown) => updateInteractionDetails(id, patch),
}));

vi.mock('@/lib/api', () => ({
  getOpportunitiesByIds: (ids: string[]) =>
    Promise.resolve(ids.map((id) => ({ id, title: `Opp ${id}`, lab_or_program: `Lab ${id}` }))),
}));

describe('useTrackerData', () => {
  beforeEach(() => {
    trackInteraction.mockClear();
    removeInteraction.mockClear();
    updateInteractionDetails.mockClear();
    interactions = new Map([
      ['o1', { type: 'applied', notes: 'hi' }],
      ['o2', { type: 'interviewing' }],
      ['o3', { type: 'dismissed' }],
    ]);
  });

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
    expect(TRACKER_COLUMNS).toEqual(['applied', 'replied', 'interviewing', 'rejected']);
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
});
