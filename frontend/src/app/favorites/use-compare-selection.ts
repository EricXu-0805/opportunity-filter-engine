'use client';

import { useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import { targetPosture } from '@/lib/target-truth';
import { MAX_COMPARE, MIN_COMPARE, type Opp } from './types';

export interface UseCompareSelectionResult {
  selectionMode: boolean;
  selected: Set<string>;
  enterSelection: () => void;
  cancelSelection: () => void;
  toggleSelect: (opp: Opp) => void;
  /** Drop selections that stopped being comparable (see the implementation). */
  reconcileSelection: (opportunities: Opp[]) => void;
  confirmCompare: (opportunities: Opp[]) => void;
}

// Compare-selection state machine for /favorites. Custom imports
// (opp._customId set) are never selectable because /compare can't
// resolve them against the server-side opportunity table — toggleSelect
// rejects them at the boundary so the disabled state on the button is
// the only signal.
export function useCompareSelection(): UseCompareSelectionResult {
  const router = useRouter();
  const [selectionMode, setSelectionMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const enterSelection = useCallback(() => {
    setSelectionMode(true);
    setSelected(new Set());
  }, []);

  const cancelSelection = useCallback(() => {
    setSelectionMode(false);
    setSelected(new Set());
  }, []);

  const toggleSelect = useCallback((opp: Opp) => {
    if (opp._customId) return;
    // Rejected at the state boundary, not just hidden on the card: a
    // comparison built around a closed listing advises on a choice the student
    // no longer has, and /compare would spend a per-card explain call to say so.
    if (targetPosture(opp) !== 'actionable') return;
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(opp.id)) {
        next.delete(opp.id);
      } else if (next.size < MAX_COMPARE) {
        next.add(opp.id);
      }
      return next;
    });
  }, []);

  /**
   * Drop selections that stopped being comparable.
   *
   * toggleSelect refuses a non-actionable target, but a row can be selected
   * while live and turn closed on the next refresh. `toggleSelect` returning
   * early then makes it *unremovable*: the user cannot untick what the guard
   * will not let them touch. Reconciling here keeps the set honest and keeps
   * the count that gates Compare honest with it.
   */
  const reconcileSelection = useCallback((opportunities: Opp[]) => {
    const comparable = new Set(
      opportunities
        .filter((o) => !o._customId && targetPosture(o) === 'actionable')
        .map((o) => o.id),
    );
    setSelected((prev) => {
      const next = new Set(Array.from(prev).filter((id) => comparable.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, []);

  const confirmCompare = useCallback((opportunities: Opp[]) => {
    // Required, not optional. The old signature fell back to the raw selection
    // when the caller passed nothing — so a call site that simply forgot the
    // argument navigated on a set assembled before the last refresh, which is
    // exactly the stale state this re-check exists to catch. Fail closed
    // instead: no records to check against means nothing to compare.
    if (!Array.isArray(opportunities)) return;
    // Re-checked at the moment of navigation, not only when each row was
    // ticked: the set may have been assembled before a refresh closed one.
    const ids = Array.from(selected).filter((id) => {
      const record = opportunities.find((o) => o.id === id);
      return !!record && !record._customId && targetPosture(record) === 'actionable';
    });
    if (ids.length < MIN_COMPARE) return;
    router.push(`/compare?ids=${ids.map(encodeURIComponent).join(',')}`);
  }, [selected, router]);

  return {
    selectionMode,
    selected,
    enterSelection,
    cancelSelection,
    toggleSelect,
    reconcileSelection,
    confirmCompare,
  };
}
