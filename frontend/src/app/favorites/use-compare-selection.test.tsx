/* @vitest-environment jsdom */
// The selection set is assembled over time and acted on later, so the moment
// of navigation is the only place the world can be re-checked. Everything here
// is about that gap: a row ticked while live, closed by the next refresh, and
// still in the set when the student presses Compare.
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

import { useCompareSelection } from './use-compare-selection';
import type { Opp } from './types';

const ACTIONABLE_TRUTH = {
  listing_state: 'open',
  reference_only: false,
  actionable: true,
  accepting_state: 'accepting',
  reason_code: null,
  verified_at: null,
  expires_at: null,
} as const;

// A confirmed listing: reviewed source type, the wire kind the server sends
// with it, and the canonical live truth. An unreviewed source type is no
// longer actionable, so a fixture without one would be untickable and every
// selection assertion below would pass for the wrong reason.
function live(id: string): Opp {
  return {
    id,
    title: id,
    source_type: 'campus_program',
    record_kind: 'listing',
    target_truth: { ...ACTIONABLE_TRUTH },
  } as unknown as Opp;
}

function closed(id: string): Opp {
  return {
    id,
    title: id,
    source_type: 'campus_program',
    record_kind: 'listing',
    target_truth: {
      ...ACTIONABLE_TRUTH,
      actionable: false,
      listing_state: 'closed',
      accepting_state: 'not_accepting',
      reason_code: 'listing_closed',
      reference_only: true,
    },
  } as unknown as Opp;
}

beforeEach(() => push.mockReset());

function selectBoth(rows: Opp[]) {
  const { result } = renderHook(() => useCompareSelection());
  act(() => result.current.enterSelection());
  act(() => rows.forEach((row) => result.current.toggleSelect(row)));
  return result;
}

describe('confirmCompare re-checks the world it is about to act on', () => {
  it('navigates with both ids when they are still comparable', () => {
    const rows = [live('a'), live('b')];
    const result = selectBoth(rows);

    act(() => result.current.confirmCompare(rows));

    expect(push).toHaveBeenCalledWith('/compare?ids=a,b');
  });

  it('refuses when a selected row closed after it was ticked', () => {
    const rows = [live('a'), live('b')];
    const result = selectBoth(rows);

    // The same ids, re-resolved against a refreshed list where one has closed.
    act(() => result.current.confirmCompare([rows[0], closed('b')]));

    expect(push).not.toHaveBeenCalled();
  });

  it('fails closed when the caller passes no records at all', () => {
    // The signature is required, but a JS caller — or a refactor that drops
    // the argument — can still reach this. The old code treated "no records"
    // as "skip the check" and navigated on the raw selection, which is the
    // stale set this re-check exists to catch. Nothing to verify against now
    // means nothing to compare.
    const rows = [live('a'), live('b')];
    const result = selectBoth(rows);

    act(() => {
      (result.current.confirmCompare as (records?: Opp[]) => void)(undefined);
    });

    expect(push).not.toHaveBeenCalled();
  });

  it('is a type error to call without records', () => {
    const result = selectBoth([live('a'), live('b')]);
    // @ts-expect-error — the records argument is required, and tsc is the
    // first line of defence against the fail-open above ever returning.
    // If this stops erroring, the signature went back to optional.
    () => result.current.confirmCompare();
  });

  it('reconciles a set that went stale, so the row stays untickable but removable', () => {
    const rows = [live('a'), live('b')];
    const result = selectBoth(rows);
    expect(result.current.selected.size).toBe(2);

    act(() => result.current.reconcileSelection([rows[0], closed('b')]));

    // Dropped, not merely ignored: toggleSelect refuses a dead row, so a
    // selection left in place would be one the user cannot untick.
    expect(Array.from(result.current.selected)).toEqual(['a']);
  });
});
