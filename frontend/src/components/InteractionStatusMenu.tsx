'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown, Check, X } from 'lucide-react';
import type { InteractionType } from '@/lib/supabase';
import { useT } from '@/i18n/client';

export const INTERACTION_OPTIONS: InteractionType[] = [
  'contacted',
  'applied',
  'replied',
  'interviewing',
  'rejected',
  'dismissed',
];

const INTERACTION_PILL_CLASS: Record<InteractionType, string> = {
  contacted: 'bg-sky-50 text-sky-700 border-sky-200',
  applied: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  replied: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  interviewing: 'bg-violet-50 text-violet-700 border-violet-200',
  rejected: 'bg-gray-100 text-gray-500 border-gray-200',
  dismissed: 'bg-gray-100 text-gray-400 border-gray-200',
};

const INTERACTION_DOT_CLASS: Record<InteractionType, string> = {
  contacted: 'bg-sky-500',
  applied: 'bg-indigo-500',
  replied: 'bg-emerald-500',
  interviewing: 'bg-violet-500',
  rejected: 'bg-gray-400',
  dismissed: 'bg-gray-300',
};

export interface InteractionStatusMenuProps {
  opportunityId: string;
  opportunityTitle: string;
  interaction?: InteractionType;
  onTrackInteraction: (opportunityId: string, type: InteractionType) => void;
}

/**
 * R69-C: replaces the inline 5-button interaction row on MatchCard with a
 * single "Mark status ▾" disclosure. The original row stacked 5 status
 * pills (Applied / Got reply / Interviewing / Rejected / Not interested)
 * inline below the Apply + Draft Email buttons; multiplied by 608 cards
 * this dominated the visual weight of the results list with controls most
 * users never touch on a first pass. The menu keeps the same callback
 * contract — onTrackInteraction(opportunityId, type) — and the same
 * untoggle semantic (clicking the active status clears it).
 *
 * Implementation notes:
 * - Trigger label reflects the current status (colored pill) when set, or
 *   the neutral "Mark status" copy when not.
 * - aria-haspopup="menu" + aria-expanded so SRs announce the disclosure.
 * - Menu options are <button role="menuitem"> so keyboard nav follows the
 *   ARIA menu pattern.
 * - Outside-click + Escape close the menu. We attach the listeners only
 *   while open to avoid 608 idle listeners on a populated /results page.
 */
export function InteractionStatusMenu({
  opportunityId,
  opportunityTitle,
  interaction,
  onTrackInteraction,
}: InteractionStatusMenuProps) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  // The menu is rendered through a portal with fixed positioning: MatchCard's
  // root is `overflow-hidden` (rounded corners + urgency border), which would
  // otherwise clip an in-card absolute dropdown — the bug where "Mark status"
  // got cut off and appeared to overlap the expanded reasons in a narrow card.
  const [coords, setCoords] = useState<{ top: number; right: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const place = useCallback(() => {
    const el = triggerRef.current;
    if (!el || typeof window === 'undefined') return;
    const r = el.getBoundingClientRect();
    const EST = 300; // approx menu height; flip above when little room below
    const spaceBelow = window.innerHeight - r.bottom;
    const top = spaceBelow >= EST || r.top < spaceBelow
      ? r.bottom + 4
      : Math.max(8, r.top - EST - 4);
    setCoords({ top, right: Math.max(8, window.innerWidth - r.right) });
  }, []);

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(e: MouseEvent | TouchEvent) {
      const target = e.target as Node | null;
      if (!target) return;
      if (triggerRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    // Re-anchor (don't detach) as the results list scrolls or the window resizes.
    place();
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('touchstart', handlePointerDown);
    document.addEventListener('keydown', handleKey);
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('touchstart', handlePointerDown);
      document.removeEventListener('keydown', handleKey);
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  }, [open, place]);

  const triggerLabel = interaction
    ? t(`detail.tracker.statusLabels.${interaction}`)
    : t('results.statusMenu.trigger');

  const triggerClass = interaction
    ? `${INTERACTION_PILL_CLASS[interaction]} border`
    : 'bg-white border border-gray-200 text-gray-500 hover:border-gray-300';

  return (
    <div className="w-full sm:w-auto sm:ml-auto">
      <button
        ref={triggerRef}
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => {
            if (!v) place();
            return !v;
          });
        }}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('results.statusMenu.ariaTrigger', { title: opportunityTitle })}
        className={`inline-flex items-center gap-1.5 w-full sm:w-auto justify-center sm:justify-start px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${triggerClass}`}
      >
        {interaction && (
          <span
            aria-hidden="true"
            className={`w-1.5 h-1.5 rounded-full ${INTERACTION_DOT_CLASS[interaction]}`}
          />
        )}
        <span>{triggerLabel}</span>
        <ChevronDown
          className={`w-3.5 h-3.5 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
          aria-hidden="true"
        />
      </button>

      {open && coords && typeof document !== 'undefined' && createPortal(
        <div
          ref={menuRef}
          role="menu"
          aria-label={t('results.statusMenu.ariaMenu', { title: opportunityTitle })}
          style={{ position: 'fixed', top: coords.top, right: coords.right, zIndex: 50 }}
          className="w-56 max-h-[70vh] overflow-auto bg-white rounded-xl shadow-[0_8px_28px_rgba(0,0,0,0.12)] border border-gray-100 py-1.5"
        >
          {INTERACTION_OPTIONS.map((type) => {
            const isActive = interaction === type;
            return (
              <button
                key={type}
                type="button"
                // menuitemradio (not menuitem) so aria-checked is
                // semantically valid: the 5 statuses are mutually
                // exclusive — picking one deselects the others.
                role="menuitemradio"
                aria-checked={isActive}
                onClick={(e) => {
                  e.stopPropagation();
                  onTrackInteraction(opportunityId, type);
                  setOpen(false);
                }}
                className={`flex items-center w-full gap-2 px-3 py-2 text-[13px] text-left transition-colors duration-150 ${
                  isActive
                    ? 'bg-indigo-50/50 text-gray-900 font-medium'
                    : 'text-gray-700 hover:bg-gray-50'
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`w-1.5 h-1.5 rounded-full shrink-0 ${INTERACTION_DOT_CLASS[type]}`}
                />
                <span className="flex-1">{t(`detail.tracker.statusLabels.${type}`)}</span>
                {isActive && <Check className="w-3.5 h-3.5 text-indigo-600 shrink-0" aria-hidden="true" />}
              </button>
            );
          })}
          {interaction && (
            <>
              <div className="my-1 border-t border-gray-100" aria-hidden="true" />
              <button
                type="button"
                role="menuitem"
                onClick={(e) => {
                  e.stopPropagation();
                  // Re-clicking the active status untoggles it (matches the
                  // existing useResults / supabase handler contract — see
                  // page.tsx:172-184 handleTrackInteraction).
                  onTrackInteraction(opportunityId, interaction);
                  setOpen(false);
                }}
                className="flex items-center w-full gap-2 px-3 py-2 text-[13px] text-gray-500 hover:bg-gray-50 transition-colors duration-150"
              >
                <X className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                <span>{t('results.statusMenu.clear')}</span>
              </button>
            </>
          )}
        </div>,
        document.body,
      )}
    </div>
  );
}
