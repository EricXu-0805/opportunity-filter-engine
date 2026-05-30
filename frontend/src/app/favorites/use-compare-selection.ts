'use client';

import { useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import { MAX_COMPARE, MIN_COMPARE, type Opp } from './types';

export interface UseCompareSelectionResult {
  selectionMode: boolean;
  selected: Set<string>;
  enterSelection: () => void;
  cancelSelection: () => void;
  toggleSelect: (opp: Opp) => void;
  confirmCompare: () => void;
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

  const confirmCompare = useCallback(() => {
    if (selected.size < MIN_COMPARE) return;
    const ids = Array.from(selected).map(encodeURIComponent).join(',');
    router.push(`/compare?ids=${ids}`);
  }, [selected, router]);

  return {
    selectionMode,
    selected,
    enterSelection,
    cancelSelection,
    toggleSelect,
    confirmCompare,
  };
}
