import { createElement, StrictMode } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, render, act, waitFor } from '@testing-library/react';

import { useTrackerData, TRACKER_COLUMNS, dateInDays, isReminderDue } from './use-tracker-data';

const mocks = vi.hoisted(() => ({
  getInteractionsFull: vi.fn(),
  trackInteraction: vi.fn(),
  removeInteraction: vi.fn(),
  updateInteractionDetails: vi.fn(),
  dismissInteraction: vi.fn(),
  getAuthState: vi.fn(),
  onAuthChange: vi.fn(),
  getShortlistOpportunities: vi.fn(),
}));

vi.mock('@/lib/supabase', () => ({
  getInteractionsFull: mocks.getInteractionsFull,
  trackInteraction: mocks.trackInteraction,
  removeInteraction: mocks.removeInteraction,
  updateInteractionDetails: mocks.updateInteractionDetails,
  dismissInteraction: mocks.dismissInteraction,
  getAuthState: mocks.getAuthState,
  onAuthChange: mocks.onAuthChange,
}));

vi.mock('@/lib/api', () => ({
  getShortlistOpportunities: mocks.getShortlistOpportunities,
}));

// identity-owner is NOT mocked — captureOwnerToken is the real primitive,
// used here only to prove a token is passed through (see
// use-results-interactions.test.ts for the same convention).

type AuthCb = (state: { session: unknown; user: { id: string } | null; isAnonymous: boolean; email: string | null }) => void;
let authChangeCallback: AuthCb | null = null;

function authState(uid: string | null) {
  return { session: null, user: uid ? { id: uid } : null, isAnonymous: false, email: null };
}

let interactions: Map<string, { type: string; notes?: string; remind_at?: string }>;

// Canonical target shapes, installed per test rather than globally. The two
// live pairs are the only ones the backend emits: a confirmed listing states
// (open, accepting); a directory page states neither, so both are unknown.
const LIVE_LISTING = {
  source_type: 'campus_program',
  record_kind: 'listing',
  target_truth: {
    listing_state: 'open', reference_only: false, actionable: true,
    accepting_state: 'accepting', reason_code: null,
    verified_at: null, expires_at: null,
  },
};

const LIVE_FACULTY = {
  source_type: 'faculty_research',
  record_kind: 'faculty_contact',
  target_truth: {
    listing_state: 'unknown', reference_only: false, actionable: true,
    accepting_state: 'unknown', reason_code: null,
    verified_at: null, expires_at: null,
  },
};

const CLOSED_LISTING = {
  source_type: 'campus_program',
  record_kind: 'listing',
  target_truth: {
    listing_state: 'closed', reference_only: false, actionable: false,
    accepting_state: 'not_accepting', reason_code: 'listing_closed',
    verified_at: null, expires_at: null,
  },
};

/** Give every resolved target the same canonical shape, for this test only. */
function installTargets(shape: Record<string, unknown>) {
  mocks.getShortlistOpportunities.mockImplementation((ids: string[]) => Promise.resolve({
    opportunities: ids.map((id) => ({
      id, title: `Opp ${id}`, lab_or_program: `Lab ${id}`, ...shape,
    })),
    unavailableIds: [] as string[],
  }));
}

beforeEach(() => {
  mocks.getInteractionsFull.mockReset();
  mocks.trackInteraction.mockReset();
  mocks.removeInteraction.mockReset();
  mocks.updateInteractionDetails.mockReset();
  mocks.dismissInteraction.mockReset();
  mocks.getAuthState.mockReset();
  mocks.onAuthChange.mockReset();
  mocks.getShortlistOpportunities.mockReset();
  authChangeCallback = null;

  interactions = new Map([
    ['o1', { type: 'applied', notes: 'hi' }],
    ['o2', { type: 'interviewing' }],
    ['o3', { type: 'dismissed' }],
  ]);
  mocks.getInteractionsFull.mockImplementation(() => Promise.resolve(interactions));
  // The default fixture carries NO truth, and that is deliberate: absent is
  // the fail-closed case, so nothing here can schedule a reminder by
  // accident. Tests that need a schedulable target install one explicitly —
  // see installTargets(liveListing) / liveFaculty below.
  mocks.getShortlistOpportunities.mockImplementation((ids: string[]) => Promise.resolve({
    opportunities: ids.map((id) => ({ id, title: `Opp ${id}`, lab_or_program: `Lab ${id}` })),
    unavailableIds: [] as string[],
  }));
  mocks.getAuthState.mockResolvedValue(authState(null));
  mocks.onAuthChange.mockImplementation((cb: AuthCb) => {
    authChangeCallback = cb;
    return () => { authChangeCallback = null; };
  });
  mocks.trackInteraction.mockResolvedValue(undefined);
  mocks.removeInteraction.mockResolvedValue(undefined);
  mocks.updateInteractionDetails.mockResolvedValue(undefined);
  mocks.dismissInteraction.mockResolvedValue(undefined);
});

describe('useTrackerData — hydration', () => {
  it('joins interactions with opportunity details', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toHaveLength(3);
    const o1 = result.current.items.find((i) => i.opp.id === 'o1');
    expect(o1?.opp.title).toBe('Opp o1');
    expect(o1?.record.type).toBe('applied');
    expect(o1?.record.notes).toBe('hi');
    expect(result.current.error).toBe(false);
  });

  it('starts the pipeline at contacted and still excludes dismissed', () => {
    // 'contacted' was missing entirely: the cold-email confirm-sent flow and
    // the follow-up chips both write it, and the reminders cron sends for it
    // — so a student who emailed a professor had a tracked row, a
    // deliverable reminder, and no card anywhere on this board. Reaching out
    // is where the funnel starts.
    expect(TRACKER_COLUMNS).toEqual([
      'contacted', 'applied', 'replied', 'interviewing', 'rejected',
    ]);
    // 'dismissed' stays out — it is the hide-from-results status, not a stage.
    expect(TRACKER_COLUMNS).not.toContain('dismissed');
  });

  it('a bulk read failure sets error, never a silent empty-tracker state; retry() recovers', async () => {
    mocks.getInteractionsFull.mockRejectedValueOnce(new Error('network down'));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.error).toBe(true));
    expect(result.current.loading).toBe(false);
    expect(result.current.items).toHaveLength(0); // caller must check error, not treat this as "confirmed empty"

    await act(async () => { result.current.retry(); });
    await waitFor(() => expect(result.current.error).toBe(false));
    expect(result.current.items).toHaveLength(3);
  });

  it('an old slow load racing a fast retry (same identity generation) never overwrites the newer result when it arrives late', async () => {
    let resolveOld: ((v: typeof interactions) => void) | undefined;
    mocks.getInteractionsFull.mockReturnValueOnce(new Promise((r) => { resolveOld = r; }));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(mocks.getInteractionsFull).toHaveBeenCalledTimes(1));

    // A fast retry (SAME identity — no generation change) starts and
    // resolves BEFORE the original slow load does.
    const fastResult = new Map([['fast-opp', { type: 'applied' as const }]]);
    mocks.getInteractionsFull.mockResolvedValueOnce(fastResult);
    await act(async () => { result.current.retry(); });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items.find((i) => i.opp.id === 'fast-opp')).toBeDefined();

    // The original slow load finally resolves, late — must not overwrite
    // the fast retry's already-applied, newer result.
    await act(async () => { resolveOld?.(interactions); });
    expect(result.current.items.find((i) => i.opp.id === 'fast-opp')).toBeDefined();
    expect(result.current.items.find((i) => i.opp.id === 'o1')).toBeUndefined();
  });
});

describe('useTrackerData — changeStatus', () => {
  it('optimistically moves an item and persists with an owner token', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.changeStatus('o1', 'interviewing'));
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('interviewing');
    expect(mocks.trackInteraction).toHaveBeenCalledWith('o1', 'interviewing', expect.anything());
  });

  it('re-selecting the active status is pessimistic: the card stays visible (pending) until removeInteraction actually succeeds, only then removed', async () => {
    let resolveRemove: (() => void) | undefined;
    mocks.removeInteraction.mockReturnValue(new Promise<void>((r) => { resolveRemove = r; }));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.changeStatus('o1', 'applied')); // same as current -> untoggle/remove
    expect(mocks.removeInteraction).toHaveBeenCalledWith('o1', expect.anything());
    // Not yet removed — filtering it out before the request even starts
    // would show an empty(-ier) tracker as though the removal had already
    // succeeded (a fake-success bug).
    expect(result.current.items.find((i) => i.opp.id === 'o1')).toBeDefined();
    expect(result.current.statusPendingIds.has('o1')).toBe(true);

    await act(async () => { resolveRemove?.(); });
    expect(result.current.items.find((i) => i.opp.id === 'o1')).toBeUndefined();
    expect(result.current.statusPendingIds.has('o1')).toBe(false);
  });

  it('rolls back and sets a visible, retryable error on a genuine failure', async () => {
    mocks.trackInteraction.mockRejectedValueOnce(new Error('write failed'));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { result.current.changeStatus('o1', 'interviewing'); });
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('applied'); // rolled back
    expect(result.current.statusErrors.has('o1')).toBe(true);

    mocks.trackInteraction.mockResolvedValueOnce(undefined);
    await act(async () => { result.current.retryStatusItem('o1'); });
    await waitFor(() => expect(result.current.statusErrors.has('o1')).toBe(false));
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('interviewing');
  });

  it('a second click on the same id while its write is in flight is a fail-closed no-op', async () => {
    let resolveTrack: (() => void) | undefined;
    mocks.trackInteraction.mockReturnValue(new Promise<void>((r) => { resolveTrack = r; }));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.changeStatus('o1', 'interviewing');
      result.current.changeStatus('o1', 'interviewing'); // same tick, same id — dropped
    });
    await waitFor(() => expect(result.current.statusPendingIds.has('o1')).toBe(true));
    expect(mocks.trackInteraction).toHaveBeenCalledTimes(1);
    await act(async () => { resolveTrack?.(); });
  });

  it('retry replays the EXACT same op (SET with the same type) rather than re-deriving from current state, and clears the error on success', async () => {
    mocks.trackInteraction.mockRejectedValueOnce(new Error('transient'));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    // o1 starts as 'applied'. Attempt to SET it to 'interviewing' — fails.
    await act(async () => { result.current.changeStatus('o1', 'interviewing'); });
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('applied'); // rolled back
    expect(result.current.statusErrors.has('o1')).toBe(true);

    // No other same-channel intent has been issued for o1 since — the
    // failure/retry is still the same attempt. Retry must call the SAME
    // helper (trackInteraction, not removeInteraction) with the SAME type.
    mocks.trackInteraction.mockResolvedValueOnce(undefined);
    await act(async () => { result.current.retryStatusItem('o1'); });
    await waitFor(() => expect(result.current.statusErrors.has('o1')).toBe(false));
    expect(mocks.trackInteraction).toHaveBeenCalledTimes(2);
    expect(mocks.trackInteraction).toHaveBeenNthCalledWith(2, 'o1', 'interviewing', expect.anything());
    expect(mocks.removeInteraction).not.toHaveBeenCalled();
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('interviewing');
  });

  it('a NEW same-channel intent (status or reminder) for an id invalidates its stale failure/retry — there is no lingering stale Retry button to click', async () => {
    mocks.trackInteraction.mockRejectedValueOnce(new Error('transient'));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { result.current.changeStatus('o1', 'interviewing'); });
    expect(result.current.statusErrors.has('o1')).toBe(true);

    // A fresh same-channel intent (a direct click, not a retry) — the old
    // failure must be invalidated immediately, before this new attempt even
    // settles.
    mocks.trackInteraction.mockImplementation(() => new Promise<void>(() => {})); // never settles
    act(() => { result.current.changeStatus('o1', 'replied'); });
    expect(result.current.statusErrors.has('o1')).toBe(false);
  });

  it('a failure on one opportunity never clobbers a concurrent successful change on a DIFFERENT one', async () => {
    let resolveA: (() => void) | undefined;
    let rejectA: ((e: Error) => void) | undefined;
    mocks.trackInteraction.mockImplementation((id: string) => {
      if (id === 'o1') return new Promise<void>((_res, rej) => { rejectA = rej; });
      return new Promise<void>((res) => { resolveA = res; });
    });
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.changeStatus('o1', 'interviewing'); // will fail
      result.current.changeStatus('o2', 'applied'); // will succeed
    });
    expect(result.current.items.find((i) => i.opp.id === 'o2')?.record.type).toBe('applied');

    await act(async () => { resolveA?.(); }); // o2 succeeds first
    await act(async () => { rejectA?.(new Error('boom')); }); // o1 fails after

    await waitFor(() => expect(result.current.statusErrors.has('o1')).toBe(true));
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('applied'); // o1 rolled back
    expect(result.current.items.find((i) => i.opp.id === 'o2')?.record.type).toBe('applied'); // o2's success survives intact
  });

  it('a REMOVE (untoggling the active status) that fails leaves the card exactly as-is, visibly retryable, and never removed', async () => {
    mocks.removeInteraction.mockRejectedValueOnce(new Error('boom'));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { result.current.changeStatus('o1', 'applied'); }); // o1 is already 'applied' -> untoggle/remove
    expect(result.current.items.find((i) => i.opp.id === 'o1')).toBeDefined(); // never removed
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('applied'); // nothing to roll back — never mutated
    expect(result.current.statusErrors.has('o1')).toBe(true);

    mocks.removeInteraction.mockResolvedValueOnce(undefined);
    await act(async () => { result.current.retryStatusItem('o1'); });
    expect(mocks.removeInteraction).toHaveBeenCalledTimes(2); // exact same op replayed, not re-derived
    await waitFor(() => expect(result.current.items.find((i) => i.opp.id === 'o1')).toBeUndefined());
    expect(result.current.statusErrors.has('o1')).toBe(false);
  });
});

describe('useTrackerData — SET to "dismissed" is pessimistic AND atomic (a single dismissInteraction call, never a two-step flush-then-track — see supabase.ts for why the two-step version was a real cross-surface race)', () => {
  it('the card stays visible with its ORIGINAL status until the server confirms — applying it optimistically would make it vanish from every pipeline column before the write is real', async () => {
    let resolveDismiss: (() => void) | undefined;
    mocks.dismissInteraction.mockReturnValue(new Promise<void>((r) => { resolveDismiss = r; }));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.changeStatus('o1', 'dismissed'); });
    // o1's draft matches its confirmed baseline ('hi') and nothing else is
    // in flight for it — no flush needed, so notes is omitted (undefined).
    expect(mocks.dismissInteraction).toHaveBeenCalledWith('o1', undefined, expect.anything());
    // Not yet applied — the card's type is untouched, still 'applied'.
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('applied');
    expect(result.current.statusPendingIds.has('o1')).toBe(true);

    await act(async () => { resolveDismiss?.(); });
    // Only now, confirmed, does it actually become dismissed.
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('dismissed');
  });

  it('a failed dismiss leaves the ORIGINAL card fully visible with its original status — no rollback needed since nothing was ever changed — and is exactly retryable', async () => {
    mocks.dismissInteraction.mockRejectedValueOnce(new Error('boom'));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { result.current.changeStatus('o1', 'dismissed'); });
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('applied'); // untouched
    expect(result.current.statusErrors.has('o1')).toBe(true);

    mocks.dismissInteraction.mockResolvedValueOnce(undefined);
    await act(async () => { result.current.retryStatusItem('o1'); });
    expect(mocks.dismissInteraction).toHaveBeenNthCalledWith(2, 'o1', undefined, expect.anything()); // exact same op, not re-derived
    await waitFor(() => expect(result.current.statusErrors.has('o1')).toBe(false));
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('dismissed');
  });

  it('a DIRTY draft (never blurred) is passed into the SAME atomic dismissInteraction call — on success, the baseline advances and the card\'s notes update to it', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setNoteDraft('o1', 'a dirty, never-blurred draft'); });
    await act(async () => { result.current.changeStatus('o1', 'dismissed'); });

    expect(mocks.dismissInteraction).toHaveBeenCalledWith('o1', 'a dirty, never-blurred draft', expect.anything());
    expect(mocks.updateInteractionDetails).not.toHaveBeenCalled(); // no separate flush call — ever
    const o1 = result.current.items.find((i) => i.opp.id === 'o1');
    expect(o1?.record.type).toBe('dismissed');
    expect(o1?.record.notes).toBe('a dirty, never-blurred draft');
  });

  it('a failed dismiss with a dirty draft leaves the ORIGINAL card, ORIGINAL status, AND the draft completely untouched — nothing was ever applied optimistically', async () => {
    mocks.dismissInteraction.mockRejectedValueOnce(new Error('boom'));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setNoteDraft('o1', 'a dirty draft'); });
    await act(async () => { result.current.changeStatus('o1', 'dismissed'); });

    expect(result.current.statusErrors.has('o1')).toBe(true);
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('applied');
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.notes).toBe('hi'); // never optimistically applied
    expect(result.current.noteDrafts.get('o1')).toBe('a dirty draft'); // draft untouched, still retryable
  });

  it('an EARLIER notes save still in flight (busyCount > 0) forces the dismiss to include the CURRENT draft, even when that draft already equals the confirmed baseline — skipping it here would let the in-flight write land AFTER dismiss with nothing left to correct it', async () => {
    let resolveN1: (() => void) | undefined;
    mocks.updateInteractionDetails.mockReturnValue(new Promise<void>((r) => { resolveN1 = r; }));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.saveNotes('o1', 'B'); }); // N1 in flight, busyCount('o1') > 0
    await waitFor(() => expect(result.current.notesPendingIds.has('o1')).toBe(true));
    act(() => { result.current.setNoteDraft('o1', 'hi'); }); // reverts to baseline, NOT blurred

    act(() => { result.current.changeStatus('o1', 'dismissed'); });
    // Even though the draft ("hi") matches the baseline, N1 is still
    // in flight — the dismiss must still include it, not pass undefined.
    expect(mocks.dismissInteraction).toHaveBeenCalledWith('o1', 'hi', expect.anything());

    await act(async () => { resolveN1?.(); });
  });
});

describe('useTrackerData — leavingPending fail-closes setNoteDraft/saveNotes/retryNotesItem at the HOOK level (not just via TrackerCard\'s disabled attribute)', () => {
  it('a REMOVE already in flight: setNoteDraft, saveNotes, and retryNotesItem are all no-ops for that id — no new updateInteractionDetails call is ever produced', async () => {
    mocks.removeInteraction.mockReturnValue(new Promise<void>(() => {})); // never resolves — stays pending
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.changeStatus('o1', 'applied'); }); // untoggle -> REMOVE, pending
    await waitFor(() => expect(result.current.leavingPendingIds.has('o1')).toBe(true));

    act(() => { result.current.setNoteDraft('o1', 'a new edit with nowhere to land'); });
    expect(result.current.noteDrafts.get('o1')).not.toBe('a new edit with nowhere to land');
    act(() => { result.current.saveNotes('o1', 'a new edit with nowhere to land'); });
    act(() => { result.current.retryNotesItem('o1'); });
    expect(mocks.updateInteractionDetails).not.toHaveBeenCalled();
  });

  it('a dismiss already in flight: setNoteDraft, saveNotes, and retryNotesItem are all no-ops for that id — no new updateInteractionDetails call is ever produced', async () => {
    mocks.dismissInteraction.mockReturnValue(new Promise<void>(() => {})); // never resolves — stays pending
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.changeStatus('o1', 'dismissed'); });
    await waitFor(() => expect(result.current.leavingPendingIds.has('o1')).toBe(true));

    act(() => { result.current.setNoteDraft('o1', 'a new edit with nowhere to land'); });
    expect(result.current.noteDrafts.get('o1')).not.toBe('a new edit with nowhere to land');
    act(() => { result.current.saveNotes('o1', 'a new edit with nowhere to land'); });
    act(() => { result.current.retryNotesItem('o1'); });
    expect(mocks.updateInteractionDetails).not.toHaveBeenCalled();
  });

  it('a FAILED REMOVE re-enables notes retry (leavingPending clears) — a previously-blocked retryNotesItem call now proceeds normally', async () => {
    mocks.removeInteraction.mockRejectedValueOnce(new Error('boom'));
    mocks.updateInteractionDetails.mockRejectedValueOnce(new Error('notes boom'));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    // A pre-existing failed notes save, so there's a real retry draft.
    await act(async () => { result.current.saveNotes('o1', 'retry me'); });
    expect(result.current.notesErrors.has('o1')).toBe(true);

    await act(async () => { result.current.changeStatus('o1', 'applied'); }); // REMOVE fails
    await waitFor(() => expect(result.current.leavingPendingIds.has('o1')).toBe(false));

    mocks.updateInteractionDetails.mockResolvedValueOnce(undefined);
    await act(async () => { result.current.retryNotesItem('o1'); });
    await waitFor(() => expect(result.current.notesErrors.has('o1')).toBe(false));
    expect(mocks.updateInteractionDetails).toHaveBeenCalledWith('o1', { notes: 'retry me' }, expect.anything());
  });
});

describe('useTrackerData — saveNotes', () => {
  it('persists trimmed notes (null when blank) with an owner token', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => { result.current.saveNotes('o2', '  follow up  '); });
    expect(result.current.items.find((i) => i.opp.id === 'o2')?.record.notes).toBe('  follow up  ');
    expect(mocks.updateInteractionDetails).toHaveBeenCalledWith('o2', { notes: 'follow up' }, expect.anything());
    await act(async () => { result.current.saveNotes('o2', '   '); });
    expect(mocks.updateInteractionDetails).toHaveBeenCalledWith('o2', { notes: null }, expect.anything());
  });

  it('N1 pending, N2 issued before N1 settles: N1 resolving does not clobber N2\'s draft, and N2 is what finally settles', async () => {
    let resolveN1: (() => void) | undefined;
    let resolveN2: (() => void) | undefined;
    mocks.updateInteractionDetails
      .mockImplementationOnce(() => new Promise<void>((r) => { resolveN1 = r; }))
      .mockImplementationOnce(() => new Promise<void>((r) => { resolveN2 = r; }));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.saveNotes('o2', 'N1 draft'); });
    await waitFor(() => expect(mocks.updateInteractionDetails).toHaveBeenCalledTimes(1));
    act(() => { result.current.saveNotes('o2', 'N2 draft'); });
    expect(result.current.items.find((i) => i.opp.id === 'o2')?.record.notes).toBe('N2 draft');

    // N1 resolves first (both allowed through — enqueued in invocation
    // order behind the shared queue in the real implementation; here we
    // control resolution order directly) — must NOT touch the visible draft.
    await act(async () => { resolveN1?.(); });
    expect(result.current.items.find((i) => i.opp.id === 'o2')?.record.notes).toBe('N2 draft');

    await act(async () => { resolveN2?.(); await waitFor(() => expect(mocks.updateInteractionDetails).toHaveBeenCalledTimes(2)); });
    expect(result.current.items.find((i) => i.opp.id === 'o2')?.record.notes).toBe('N2 draft');
    expect(result.current.notesErrors.has('o2')).toBe(false);
  });

  it('N1 fails after N2 has been issued: N1\'s failure is silently dropped, never rolling back N2\'s draft or showing an error for it', async () => {
    let rejectN1: ((e: Error) => void) | undefined;
    mocks.updateInteractionDetails
      .mockImplementationOnce(() => new Promise<void>((_res, rej) => { rejectN1 = rej; }))
      .mockImplementationOnce(() => Promise.resolve(undefined));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.saveNotes('o2', 'N1 draft'); });
    await waitFor(() => expect(mocks.updateInteractionDetails).toHaveBeenCalledTimes(1));
    act(() => { result.current.saveNotes('o2', 'N2 draft'); });

    await act(async () => { rejectN1?.(new Error('N1 failed')); });
    expect(result.current.items.find((i) => i.opp.id === 'o2')?.record.notes).toBe('N2 draft'); // untouched
    expect(result.current.notesErrors.has('o2')).toBe(false); // N1's failure is not "the" error for o2 — N2 is still pending
  });

  it('N1 succeeds then N2 fails: the display stays exactly as N2\'s draft — never rolled back to N1\'s (or any) baseline', async () => {
    let resolveN1: (() => void) | undefined;
    let rejectN2: ((e: Error) => void) | undefined;
    mocks.updateInteractionDetails
      .mockImplementationOnce(() => new Promise<void>((r) => { resolveN1 = r; }))
      .mockImplementationOnce(() => new Promise<void>((_res, rej) => { rejectN2 = rej; }));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.saveNotes('o2', 'N1 draft'); }); // o2 started with notes=undefined
    await waitFor(() => expect(mocks.updateInteractionDetails).toHaveBeenCalledTimes(1));
    act(() => { result.current.saveNotes('o2', 'N2 draft'); });

    await act(async () => { resolveN1?.(); }); // N1 succeeds — must not touch the display, already showing N2's draft
    expect(result.current.items.find((i) => i.opp.id === 'o2')?.record.notes).toBe('N2 draft');
    await act(async () => { rejectN2?.(new Error('N2 failed')); });

    await waitFor(() => expect(result.current.notesErrors.has('o2')).toBe(true));
    // A failure never rolls back the visible draft — the user's last
    // attempted text (N2's) stays exactly as shown; only the error banner
    // and the invisible retry-draft ref record that it did not persist.
    expect(result.current.items.find((i) => i.opp.id === 'o2')?.record.notes).toBe('N2 draft');
  });

  it('N1 fails AND N2 fails: the display stays exactly as N2\'s draft — N1\'s failure (superseded) is fully silent, never touches it', async () => {
    let rejectN1: ((e: Error) => void) | undefined;
    let rejectN2: ((e: Error) => void) | undefined;
    mocks.updateInteractionDetails
      .mockImplementationOnce(() => new Promise<void>((_res, rej) => { rejectN1 = rej; }))
      .mockImplementationOnce(() => new Promise<void>((_res, rej) => { rejectN2 = rej; }));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items.find((i) => i.opp.id === 'o2')?.record.notes).toBeUndefined(); // N0

    act(() => { result.current.saveNotes('o2', 'N1 draft'); });
    await waitFor(() => expect(mocks.updateInteractionDetails).toHaveBeenCalledTimes(1));
    act(() => { result.current.saveNotes('o2', 'N2 draft'); });

    await act(async () => { rejectN1?.(new Error('N1 failed')); }); // superseded — silent, no display change
    expect(result.current.items.find((i) => i.opp.id === 'o2')?.record.notes).toBe('N2 draft');
    expect(result.current.notesErrors.has('o2')).toBe(false); // N1's failure is not "the" error — N2 is still pending

    await act(async () => { rejectN2?.(new Error('N2 failed')); }); // latest — sets the visible error

    await waitFor(() => expect(result.current.notesErrors.has('o2')).toBe(true));
    expect(result.current.items.find((i) => i.opp.id === 'o2')?.record.notes).toBe('N2 draft'); // still N2's draft, never rolled back
  });

  it('a failed notes save is retryable, and the retry replays the exact original draft', async () => {
    mocks.updateInteractionDetails.mockRejectedValueOnce(new Error('boom'));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { result.current.saveNotes('o2', 'retry me'); });
    expect(result.current.notesErrors.has('o2')).toBe(true);

    mocks.updateInteractionDetails.mockResolvedValueOnce(undefined);
    await act(async () => { result.current.retryNotesItem('o2'); });
    await waitFor(() => expect(result.current.notesErrors.has('o2')).toBe(false));
    expect(result.current.items.find((i) => i.opp.id === 'o2')?.record.notes).toBe('retry me');
  });

  describe('revert-to-confirmed-baseline skip (redundant-write avoidance)', () => {
    it('a failed edit reverted back to exactly the last CONFIRMED value (o1 loads with notes="hi") fires no second write once the failed attempt has settled — the stale error also clears', async () => {
      mocks.updateInteractionDetails.mockRejectedValueOnce(new Error('boom'));
      const { result } = renderHook(() => useTrackerData());
      await waitFor(() => expect(result.current.loading).toBe(false));
      expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.notes).toBe('hi');

      await act(async () => { result.current.saveNotes('o1', 'bad edit'); });
      expect(result.current.notesErrors.has('o1')).toBe(true);
      expect(mocks.updateInteractionDetails).toHaveBeenCalledTimes(1);

      // Revert to exactly the original confirmed baseline — the failed
      // write never landed, so server truth is still "hi"; nothing changed
      // relative to it, so no network round-trip is needed.
      act(() => { result.current.saveNotes('o1', 'hi'); });
      expect(result.current.notesErrors.has('o1')).toBe(false); // stale failure invalidated
      expect(mocks.updateInteractionDetails).toHaveBeenCalledTimes(1); // no second call
      expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.notes).toBe('hi');
    });

    it('reverting to the confirmed baseline WHILE an earlier write for this id is STILL IN FLIGHT still queues a real write — skipping here would let the in-flight write land later and silently move server truth away from the revert', async () => {
      let resolveN1: (() => void) | undefined;
      mocks.updateInteractionDetails.mockImplementationOnce(() => new Promise<void>((r) => { resolveN1 = r; }));
      const { result } = renderHook(() => useTrackerData());
      await waitFor(() => expect(result.current.loading).toBe(false));
      expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.notes).toBe('hi');

      act(() => { result.current.saveNotes('o1', 'X'); }); // N1 in flight, not yet resolved
      await waitFor(() => expect(result.current.notesPendingIds.has('o1')).toBe(true));

      mocks.updateInteractionDetails.mockResolvedValueOnce(undefined);
      act(() => { result.current.saveNotes('o1', 'hi'); }); // reverts to baseline WHILE N1 is still pending
      expect(mocks.updateInteractionDetails).toHaveBeenCalledTimes(2); // queued, never skipped
      expect(mocks.updateInteractionDetails).toHaveBeenNthCalledWith(2, 'o1', { notes: 'hi' }, expect.anything());

      // N1 ("X") finally lands late — must not undo the revert the user
      // already committed to.
      await act(async () => { resolveN1?.(); });
      expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.notes).toBe('hi');
      await waitFor(() => expect(result.current.notesPendingIds.has('o1')).toBe(false));
    });
  });
});

describe('useTrackerData — noteDrafts (the live, uncommitted per-id textarea value)', () => {
  it('is independent of `items` — an optimistic status move (changeStatus) for the SAME id never touches its in-progress, unsaved draft', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setNoteDraft('o1', 'unblurred draft, never saved'); });
    expect(result.current.noteDrafts.get('o1')).toBe('unblurred draft, never saved');

    // This is the fix for the real bug: previously the draft lived in
    // TrackerCard's own local state, and moving a card to a different
    // pipeline column (a different parent <section> in page.tsx) forced
    // React to unmount/remount it, silently destroying that state before
    // the user ever blurred. Living here instead, the draft is simply
    // unaffected by whatever changeStatus does to `items`.
    act(() => { result.current.changeStatus('o1', 'interviewing'); });
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('interviewing');
    expect(result.current.noteDrafts.get('o1')).toBe('unblurred draft, never saved');
  });

  it('setNoteDraft invalidates a stale notes error/Retry THE INSTANT an edit happens — never waits for the next blur', async () => {
    mocks.updateInteractionDetails.mockRejectedValueOnce(new Error('boom'));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { result.current.saveNotes('o2', 'bad'); });
    expect(result.current.notesErrors.has('o2')).toBe(true);

    // The user starts typing again (onChange) — no blur yet.
    act(() => { result.current.setNoteDraft('o2', 'b'); });
    expect(result.current.notesErrors.has('o2')).toBe(false);
  });

  it('an OLDER in-flight notes save that fails AFTER the user has since edited (but not yet blurred) must not resurrect the error/Retry for text they have already moved past', async () => {
    let rejectN1: ((e: Error) => void) | undefined;
    mocks.updateInteractionDetails.mockImplementationOnce(() => new Promise<void>((_res, rej) => { rejectN1 = rej; }));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { result.current.saveNotes('o2', 'N1'); }); // blur -> dispatched, in flight
    expect(result.current.notesPendingIds.has('o2')).toBe(true);

    // User keeps typing (onChange only, no blur yet) WHILE N1 is still
    // in flight.
    act(() => { result.current.setNoteDraft('o2', 'N1x'); });

    // N1 now rejects — this must be recognized as superseded (the edit
    // above already bumped the shared intent counter) and dropped silently,
    // never surfacing an error for text the user has since changed.
    await act(async () => { rejectN1?.(new Error('N1 failed')); });
    expect(result.current.notesErrors.has('o2')).toBe(false);
    expect(result.current.items.find((i) => i.opp.id === 'o2')?.record.notes).toBe('N1'); // saveNotes' own optimistic write; onChange alone never touches items
  });

  it('a background reload under the SAME identity (retry after a load error) never clears an in-progress, unsaved draft', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setNoteDraft('o1', 'still typing, never blurred'); });
    // retry() re-runs load() under the SAME identity generation — unlike
    // resetForIdentity, it must not touch noteDraftsRef at all.
    await act(async () => { result.current.retry(); });
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.noteDrafts.get('o1')).toBe('still typing, never blurred');
  });

  it('a real identity switch DOES clear every draft — an id collision across two accounts must never leak U1\'s unsaved text into U2', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => { result.current.setNoteDraft('o1', "U1's unsaved draft"); });
    expect(result.current.noteDrafts.get('o1')).toBe("U1's unsaved draft");

    await act(async () => { authChangeCallback?.(authState('u2')); });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.noteDrafts.size).toBe(0);
  });
});

describe('useTrackerData — channel independence (notes vs exclusive status/reminder)', () => {
  it('a status click issued right after a notes blur (still in flight) is NOT dropped — the two channels never gate each other', async () => {
    let resolveNotes: (() => void) | undefined;
    mocks.updateInteractionDetails.mockReturnValue(new Promise<void>((r) => { resolveNotes = r; }));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.saveNotes('o1', 'typing...'); }); // notes save in flight
    await waitFor(() => expect(result.current.notesPendingIds.has('o1')).toBe(true));

    act(() => { result.current.changeStatus('o1', 'interviewing'); }); // must NOT be silently dropped
    expect(mocks.trackInteraction).toHaveBeenCalledWith('o1', 'interviewing', expect.anything());
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('interviewing');

    await act(async () => { resolveNotes?.(); });
  });

  it('a failed reminder retry survives an unrelated notes save for the SAME id — the two error channels are independent', async () => {
    installTargets(LIVE_LISTING); // scheduling requires a deliverable target
    mocks.updateInteractionDetails.mockRejectedValueOnce(new Error('reminder failed'));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { result.current.setReminder('o1', '2030-01-01'); });
    expect(result.current.statusErrors.has('o1')).toBe(true);

    mocks.updateInteractionDetails.mockResolvedValueOnce(undefined);
    await act(async () => { result.current.saveNotes('o1', 'a note'); }); // must NOT clear the reminder failure
    expect(result.current.statusErrors.has('o1')).toBe(true);

    mocks.updateInteractionDetails.mockResolvedValueOnce(undefined);
    await act(async () => { result.current.retryStatusItem('o1'); });
    await waitFor(() => expect(result.current.statusErrors.has('o1')).toBe(false));
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.remind_at).toBe('2030-01-01');
  });
});

describe('useTrackerData — setReminder', () => {
  it('optimistically updates remind_at and persists with an owner token', async () => {
    installTargets(LIVE_LISTING);
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => { result.current.setReminder('o1', '2030-01-01'); });
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.remind_at).toBe('2030-01-01');
    expect(mocks.updateInteractionDetails).toHaveBeenCalledWith('o1', { remind_at: '2030-01-01' }, expect.anything());
    await act(async () => { result.current.setReminder('o1', null); });
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.remind_at).toBeUndefined();
    expect(mocks.updateInteractionDetails).toHaveBeenCalledWith('o1', { remind_at: null }, expect.anything());
  });

  // The hook is the single write path, so the rule lives here and not only
  // in the card. Hiding the preset buttons stops a click; it does nothing
  // about a retained handler, a future caller, or a race.
  it.each([
    ['a target with no truth at all', undefined, 'applied'],
    ['a closed listing', CLOSED_LISTING, 'applied'],
    // Actionable, but in a status the cron's query never selects.
    ['a rejected row on a live listing', LIVE_LISTING, 'rejected'],
  ])('refuses to schedule a reminder for %s', async (_label, shape, status) => {
    if (shape) installTargets(shape);
    interactions = new Map([['o1', { type: status }]]);
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { result.current.setReminder('o1', '2030-01-01'); });

    expect(mocks.updateInteractionDetails).not.toHaveBeenCalled();
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.remind_at)
      .toBeUndefined();
  });

  it('schedules for a live faculty contact the student has emailed', async () => {
    // The positive control the matrix above needs, and the majority case:
    // reminders are set on professors far more than on postings, and the
    // cron does send for this exact shape.
    installTargets(LIVE_FACULTY);
    interactions = new Map([['o1', { type: 'contacted' }]]);
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { result.current.setReminder('o1', '2030-01-01'); });

    expect(mocks.updateInteractionDetails)
      .toHaveBeenCalledWith('o1', { remind_at: '2030-01-01' }, expect.anything());
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.remind_at)
      .toBe('2030-01-01');
  });

  it('a failed clear on an unresolved placeholder retries the clear, never the row deletion', async () => {
    // A placeholder used to have exactly one possible action, so retry
    // dispatched straight to clearUnavailable. It now has two — clearing its
    // reminder can fail as well — and replaying that as clearUnavailable
    // would delete the whole interaction, taking the student's status and
    // notes with it, when all they asked was to drop a date.
    mocks.getShortlistOpportunities.mockImplementation(() => Promise.resolve({
      opportunities: [],
      unavailableIds: ['o1'],
    }));
    interactions = new Map([
      ['o1', { type: 'applied', notes: 'my own note', remind_at: '2030-01-01' }],
    ]);
    mocks.updateInteractionDetails.mockRejectedValueOnce(new Error('clear failed'));

    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.unavailableItems).toHaveLength(1);

    await act(async () => { result.current.setReminder('o1', null); });
    expect(result.current.statusErrors.has('o1')).toBe(true);
    // Rolled back, so the student still sees the date they tried to drop.
    expect(result.current.unavailableItems[0].record.remind_at).toBe('2030-01-01');

    mocks.updateInteractionDetails.mockResolvedValueOnce(undefined);
    await act(async () => { result.current.retryStatusItem('o1'); });

    await waitFor(() => expect(result.current.statusErrors.has('o1')).toBe(false));
    expect(mocks.updateInteractionDetails).toHaveBeenLastCalledWith(
      'o1', { remind_at: null }, expect.anything(),
    );
    expect(mocks.removeInteraction).not.toHaveBeenCalled();
    // The row and everything on it survive; only the date is gone.
    expect(result.current.unavailableItems).toHaveLength(1);
    expect(result.current.unavailableItems[0].record.type).toBe('applied');
    expect(result.current.unavailableItems[0].record.notes).toBe('my own note');
    expect(result.current.unavailableItems[0].record.remind_at).toBeUndefined();
  });

  it('a placeholder can never be given a NEW reminder, only cleared', async () => {
    mocks.getShortlistOpportunities.mockImplementation(() => Promise.resolve({
      opportunities: [],
      unavailableIds: ['o1'],
    }));
    interactions = new Map([['o1', { type: 'applied' }]]);
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { result.current.setReminder('o1', '2030-01-01'); });

    expect(mocks.updateInteractionDetails).not.toHaveBeenCalled();
  });

  it('still clears an existing reminder on a closed listing', async () => {
    // Clearing is never what this gate prevents: the date is the student's,
    // and dropping one they can see is always allowed.
    installTargets(CLOSED_LISTING);
    interactions = new Map([['o1', { type: 'applied', remind_at: '2030-01-01' }]]);
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { result.current.setReminder('o1', null); });

    expect(mocks.updateInteractionDetails)
      .toHaveBeenCalledWith('o1', { remind_at: null }, expect.anything());
  });

  it('a failure rolls back to the prior reminder and is visibly retryable', async () => {
    installTargets(LIVE_LISTING);
    mocks.updateInteractionDetails.mockRejectedValueOnce(new Error('reminder write failed'));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { result.current.setReminder('o1', '2030-01-01'); });
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.remind_at).toBeUndefined(); // rolled back
    expect(result.current.statusErrors.has('o1')).toBe(true);

    mocks.updateInteractionDetails.mockResolvedValueOnce(undefined);
    await act(async () => { result.current.retryStatusItem('o1'); });
    await waitFor(() => expect(result.current.statusErrors.has('o1')).toBe(false));
    expect(result.current.items.find((i) => i.opp.id === 'o1')?.record.remind_at).toBe('2030-01-01');
  });
});

describe('useTrackerData — identity transitions', () => {
  it('identityGeneration increments on a real switch, not on a same-uid re-observation — used to force-remount a card sharing an opportunity id across accounts', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    const initial = result.current.identityGeneration;

    await act(async () => { authChangeCallback?.(authState(null)); }); // same identity (null) again
    expect(result.current.identityGeneration).toBe(initial);

    mocks.getInteractionsFull.mockResolvedValueOnce(new Map());
    await act(async () => { authChangeCallback?.(authState('u2')); });
    expect(result.current.identityGeneration).toBe(initial + 1);
  });

  it('a late U1 read resolving after a live U1->U2 switch never applies — only U2\'s own data shows', async () => {
    let resolveU1: ((v: typeof interactions) => void) | undefined;
    mocks.getInteractionsFull.mockReturnValueOnce(new Promise((r) => { resolveU1 = r; }));

    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(mocks.getInteractionsFull).toHaveBeenCalledTimes(1));

    const u2Interactions = new Map([['u2-opp', { type: 'replied' as const }]]);
    mocks.getInteractionsFull.mockResolvedValueOnce(u2Interactions);
    await act(async () => { authChangeCallback?.(authState('u2')); });

    await act(async () => { resolveU1?.(interactions); }); // U1's stale result arrives late

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items.find((i) => i.opp.id === 'o1')).toBeUndefined(); // U1 data never applied
    expect(result.current.items.find((i) => i.opp.id === 'u2-opp')).toBeDefined();
  });

  it('a same-uid re-observation (e.g. TOKEN_REFRESHED) does not reset the tracker', async () => {
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(mocks.getInteractionsFull).toHaveBeenCalledTimes(1);

    await act(async () => { authChangeCallback?.(authState(null)); }); // same identity (null) again
    expect(mocks.getInteractionsFull).toHaveBeenCalledTimes(1); // no re-hydration
    expect(result.current.items).toHaveLength(3);
  });

  it('a write in flight when identity switches settles silently — no rollback/error lands on the new identity\'s fresh state', async () => {
    let rejectWrite: ((e: Error) => void) | undefined;
    mocks.trackInteraction.mockReturnValue(new Promise<void>((_res, rej) => { rejectWrite = rej; }));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.changeStatus('o1', 'interviewing'); });
    await waitFor(() => expect(result.current.statusPendingIds.has('o1')).toBe(true));

    mocks.getInteractionsFull.mockResolvedValueOnce(new Map());
    await act(async () => { authChangeCallback?.(authState('u2')); }); // reset mid-flight

    await act(async () => { rejectWrite?.(new Error('stale failure')); });
    // The reset already cleared everything for U2 (empty) — the stale U1
    // failure must not resurrect o1 or set an error for it.
    expect(result.current.items).toHaveLength(0);
    expect(result.current.statusErrors.has('o1')).toBe(false);
    expect(result.current.statusPendingIds.has('o1')).toBe(false);
  });
});

describe('useTrackerData — unavailable interaction rows (opportunity no longer resolves)', () => {
  it('a PARTIALLY unavailable batch keeps the resolved items in `items` and surfaces the rest as unavailableItems — never silently dropped', async () => {
    mocks.getShortlistOpportunities.mockImplementationOnce((ids: string[]) => Promise.resolve({
      opportunities: ids.filter((id) => id !== 'o2').map((id) => ({ id, title: `Opp ${id}` })),
      unavailableIds: ['o2'],
    }));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.items.map((i) => i.opp.id).sort()).toEqual(['o1', 'o3']);
    expect(result.current.unavailableItems).toEqual([{ id: 'o2', record: interactions.get('o2') }]);
  });

  it('a dismissed interaction whose opportunity has gone unavailable is never resurfaced as a placeholder — dismissed stays invisible to the Tracker regardless of availability', async () => {
    // o3 is 'dismissed' in the shared fixture (see beforeEach) — Tracker
    // already hides it from every pipeline column (TRACKER_COLUMNS excludes
    // 'dismissed'). If its opportunity ALSO goes unavailable, the
    // unavailable-placeholder path must honor that same exclusion, not
    // resurrect it as something the user needs to look at/clear.
    mocks.getShortlistOpportunities.mockImplementationOnce((ids: string[]) => Promise.resolve({
      opportunities: ids.filter((id) => id !== 'o3').map((id) => ({ id, title: `Opp ${id}` })),
      unavailableIds: ['o3'],
    }));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.items.map((i) => i.opp.id).sort()).toEqual(['o1', 'o2']);
    expect(result.current.unavailableItems).toHaveLength(0);
  });

  it('an ENTIRELY unavailable batch must not render as the false empty-tracker state — items is empty but unavailableItems is not', async () => {
    mocks.getShortlistOpportunities.mockImplementationOnce((ids: string[]) => Promise.resolve({
      opportunities: [],
      unavailableIds: ids,
    }));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.items).toHaveLength(0);
    // o3 is 'dismissed' in the fixture — excluded even when unavailable (see
    // the dedicated dismissed test above), so only o1/o2 surface here.
    expect(result.current.unavailableItems).toHaveLength(2); // the caller must check this before showing "nothing tracked"
  });

  it('clearUnavailable is pessimistic: the placeholder stays visible/pending until removeInteraction actually succeeds', async () => {
    mocks.getShortlistOpportunities.mockImplementationOnce((ids: string[]) => Promise.resolve({
      opportunities: ids.filter((id) => id !== 'o2').map((id) => ({ id, title: `Opp ${id}` })),
      unavailableIds: ['o2'],
    }));
    let resolveRemove: (() => void) | undefined;
    mocks.removeInteraction.mockReturnValue(new Promise<void>((r) => { resolveRemove = r; }));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.clearUnavailable('o2'); });
    expect(mocks.removeInteraction).toHaveBeenCalledWith('o2', expect.anything());
    expect(result.current.unavailableItems).toHaveLength(1); // not yet cleared
    expect(result.current.statusPendingIds.has('o2')).toBe(true);

    await act(async () => { resolveRemove?.(); });
    expect(result.current.unavailableItems).toHaveLength(0);
  });

  it('a failed clearUnavailable is visible and retryable via the same exclusive-channel error/retry', async () => {
    mocks.getShortlistOpportunities.mockImplementationOnce((ids: string[]) => Promise.resolve({
      opportunities: ids.filter((id) => id !== 'o2').map((id) => ({ id, title: `Opp ${id}` })),
      unavailableIds: ['o2'],
    }));
    mocks.removeInteraction.mockRejectedValueOnce(new Error('boom'));
    const { result } = renderHook(() => useTrackerData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { result.current.clearUnavailable('o2'); });
    expect(result.current.statusErrors.has('o2')).toBe(true);
    expect(result.current.unavailableItems).toHaveLength(1); // still there — nothing to restore, nothing was removed

    mocks.removeInteraction.mockResolvedValueOnce(undefined);
    await act(async () => { result.current.retryStatusItem('o2'); });
    await waitFor(() => expect(result.current.statusErrors.has('o2')).toBe(false));
    expect(mocks.removeInteraction).toHaveBeenCalledTimes(2);
    expect(result.current.unavailableItems).toHaveLength(0);
  });
});

describe('reminder helpers', () => {
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
});

describe('useTrackerData — React StrictMode (dev double-invoke of effects)', () => {
  // @testing-library/react's renderHook does NOT reproduce StrictMode's
  // setup->cleanup->setup double-invoke in this project's test environment
  // (verified directly: a bare useEffect counter stays at 1 through
  // renderHook + a StrictMode wrapper). render()-ing a real component tree
  // DOES reproduce it. So this uses a small harness component — calls the
  // real hook, publishes its latest return value onto a plain object the
  // test can read — instead of renderHook, specifically so this test can
  // actually exercise the double-invoke and kill the mutant it's meant to.
  function HookHarness({ out }: { out: { current: ReturnType<typeof useTrackerData> | null } }) {
    out.current = useTrackerData();
    return null;
  }

  it('a deferred dismiss still completes and updates the UI after the mount-time double-invoke — a mountedRef stuck false (a bare cleanup with no reset on the second setup) would leave this pending forever', async () => {
    // Ordinary SET applies its change OPTIMISTICALLY, before any await, so
    // it can't distinguish a working mountedRef from a permanently-false
    // one. dismissInteraction only touches state AFTER its await resolves,
    // behind the exact `identityGenerationRef.current === generation &&
    // mountedRef.current` gate this test is pinning — the only kind of
    // write that can actually kill this mutant.
    let resolveDismiss: (() => void) | undefined;
    mocks.dismissInteraction.mockReturnValue(new Promise<void>((r) => { resolveDismiss = r; }));
    const out: { current: ReturnType<typeof useTrackerData> | null } = { current: null };
    render(createElement(StrictMode, null, createElement(HookHarness, { out })));
    await waitFor(() => expect(out.current?.loading).toBe(false));

    act(() => { out.current?.changeStatus('o1', 'dismissed'); });
    // Pending, unconfirmed — pessimistic, exactly as designed.
    expect(out.current?.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('applied');
    expect(out.current?.statusPendingIds.has('o1')).toBe(true);
    expect(out.current?.leavingPendingIds.has('o1')).toBe(true);

    await act(async () => { resolveDismiss?.(); });
    // With mountedRef stuck false (the buggy cleanup-only version), every
    // check below fails: the type never flips, and BOTH pending sets are
    // stuck holding 'o1' forever, since removeStatusPending/
    // removeLeavingPending in the `finally` block are gated by the SAME
    // condition.
    expect(out.current?.items.find((i) => i.opp.id === 'o1')?.record.type).toBe('dismissed');
    expect(out.current?.statusPendingIds.has('o1')).toBe(false);
    expect(out.current?.leavingPendingIds.has('o1')).toBe(false);
  });

  // Not itself a regression test for the mountedRef reset bug (nothing
  // here distinguishes "correctly guarded" from "would have thrown
  // anyway") — kept only as a smoke test that unmounting mid-flight is
  // safe to attempt at all.
  it('[smoke] a deferred dismiss whose settlement arrives AFTER the component unmounts does not throw', async () => {
    let resolveDismiss: (() => void) | undefined;
    mocks.dismissInteraction.mockReturnValue(new Promise<void>((r) => { resolveDismiss = r; }));
    const out: { current: ReturnType<typeof useTrackerData> | null } = { current: null };
    const { unmount } = render(createElement(StrictMode, null, createElement(HookHarness, { out })));
    await waitFor(() => expect(out.current?.loading).toBe(false));

    act(() => { out.current?.changeStatus('o1', 'dismissed'); });
    unmount();
    // Resolving after unmount must not throw, warn, or otherwise indicate
    // an attempted state update on a component that's gone.
    await act(async () => { resolveDismiss?.(); });
  });
});
