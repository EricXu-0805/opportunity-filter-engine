'use client';

import { useEffect, useState } from 'react';
import type { MatchResult } from '@/lib/types';

export interface UseResultsKeyboardNavParams {
  paginated: MatchResult[];
  emailModalOpen: boolean;
  onCloseEmailModal: () => void;
  onToggleFavorite: (opportunityId: string) => void;
  onOpenHelp: () => void;
}

export interface UseResultsKeyboardNavResult {
  focusedIdx: number;
  setFocusedIdx: React.Dispatch<React.SetStateAction<number>>;
}

// Vim-style nav: j/k or ArrowDown/ArrowUp moves the focus ring across
// the paginated set, Enter opens the focused card's apply URL in a new
// tab, s toggles favorite on the focused card, / focuses search input,
// ?+Shift opens the help dialog, Escape closes the email modal.
// Caller resets focusedIdx to -1 when filters change (the new list is
// shorter and the old index would point off the end).
export function useResultsKeyboardNav({
  paginated,
  emailModalOpen,
  onCloseEmailModal,
  onToggleFavorite,
  onOpenHelp,
}: UseResultsKeyboardNavParams): UseResultsKeyboardNavResult {
  const [focusedIdx, setFocusedIdx] = useState(-1);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && emailModalOpen) {
        onCloseEmailModal();
        return;
      }
      const target = e.target as HTMLElement;
      const isTyping = target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA' || target?.isContentEditable;
      if (isTyping) return;

      if (e.key === '/') {
        e.preventDefault();
        document.getElementById('results-search-input')?.focus();
        return;
      }

      // Help must work independently of the list: with the branch below the
      // empty-list return, `?` was dead on an empty results list, and flaky
      // right after load — between paint and the passive-effect re-subscribe
      // a stale listener still closes over paginated=[] and swallows the key.
      if (e.key === '?' && e.shiftKey) {
        e.preventDefault();
        onOpenHelp();
        return;
      }

      if (paginated.length === 0) return;

      if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault();
        setFocusedIdx(i => {
          const next = Math.min(paginated.length - 1, i < 0 ? 0 : i + 1);
          document.getElementById(`match-card-${paginated[next]?.opportunity.id}`)
            ?.scrollIntoView({ block: 'center', behavior: 'smooth' });
          return next;
        });
      } else if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault();
        setFocusedIdx(i => {
          const next = Math.max(0, i <= 0 ? 0 : i - 1);
          document.getElementById(`match-card-${paginated[next]?.opportunity.id}`)
            ?.scrollIntoView({ block: 'center', behavior: 'smooth' });
          return next;
        });
      } else if (e.key === 's' && focusedIdx >= 0) {
        e.preventDefault();
        const match = paginated[focusedIdx];
        if (match) onToggleFavorite(match.opportunity.id);
      } else if (e.key === 'Enter' && focusedIdx >= 0) {
        e.preventDefault();
        const match = paginated[focusedIdx];
        // Enter opens the in-app detail page, for every record and every
        // posture. It used to jump straight out to an external destination,
        // which made a keyboard press an unlabelled Apply — the one action
        // that must come from a control the user can read first.
        if (match) {
          window.location.assign(`/opportunities/${encodeURIComponent(match.opportunity.id)}`);
        }
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [emailModalOpen, paginated, focusedIdx, onCloseEmailModal, onToggleFavorite, onOpenHelp]);

  return { focusedIdx, setFocusedIdx };
}
