'use client';

import { useCallback, useEffect, useId, useRef, useState } from 'react';
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
  /** True while this opportunity's status is unwritable — a write already
   *  in flight for it, or the bulk interaction read isn't ready yet. */
  disabled?: boolean;
}

/**
 * R69-C: replaces the inline 5-button interaction row on MatchCard with a
 * single "Mark status ▾" disclosure. The original row stacked 5 status
 * pills (Applied / Got reply / Interviewing / Rejected / Not interested)
 * inline below the Apply + Draft Email buttons; multiplied by 608 cards
 * this dominated the visual weight of the results list with controls most
 * users never touch on a first pass. The menu keeps the same callback
 * contract — onTrackInteraction(opportunityId, type). Removing the active
 * status entirely (which deletes its notes/reminder too, permanently) is
 * ONLY reachable via the explicit, confirmed "Remove from Tracker" footer —
 * re-clicking the already-active status option is a no-op, not an untoggle.
 *
 * This is an anchored, NON-modal disclosure dialog (role="dialog", no
 * aria-modal, no page lock) — NOT an ARIA menu. An earlier version used
 * role="menu" + menuitemradio, which requires the full roving-tabindex +
 * arrow/Home/End keyboard model to be a valid implementation of that
 * pattern — and once the destructive-remove confirm step added plain
 * <button>s directly inside role="menu", that combination became invalid
 * ARIA regardless (menu children must be menuitem/menuitemradio/
 * menuitemcheckbox). A disclosure dialog needs none of that: plain buttons,
 * a simple Tab/Shift+Tab cycle, and explicit focus management on
 * open/close/state-transitions (below) is a complete, correct
 * implementation with much less surface area.
 *
 * The trigger deliberately NEVER uses the native `disabled` attribute (only
 * `aria-disabled` + a guard at the top of its own click handler). An
 * earlier version keyed a wrapper on `disabled` to force React to unmount
 * and remount the whole component across that edge — but a status-select/
 * Confirm click can itself cause the PARENT to flip `disabled=true` in the
 * SAME batch that closes the popup, tearing the old instance down before
 * any of its own effects (which would otherwise restore focus) ever ran.
 * Whatever "restore focus to the fresh trigger later" mechanism was built
 * to paper over that then had a SECOND problem: it fires unconditionally
 * once re-enabled, even if the user had, during the pending window,
 * deliberately moved focus somewhere else — stealing it back. Keeping the
 * SAME trigger element mounted and focusable throughout removes the need
 * for either mechanism: nothing ever unmounts due to `disabled` changing,
 * so there is nothing to restore, and therefore nothing to accidentally
 * steal back.
 */
export function InteractionStatusMenu({
  opportunityId,
  opportunityTitle,
  interaction,
  onTrackInteraction,
  disabled = false,
}: InteractionStatusMenuProps) {
  const { t } = useT();
  // A stable, collision-free id for the confirm body's aria-describedby
  // link — opportunityId is NOT safe to build a DOM id from directly (not
  // guaranteed unique per rendered instance if the same opportunity is
  // ever shown twice on a page, and may contain characters that aren't
  // valid in a bare id attribute).
  const confirmDescId = useId();
  const [open, setOpen] = useState(false);
  // Removing an interaction entirely (status + notes + reminder, permanent)
  // is destructive and — unlike picking a different status — irreversible.
  // Clicking the footer enters this confirm sub-state INSIDE the same open
  // dialog (rather than closing it or popping a native window.confirm) so
  // Cancel is a true no-op: zero callback, zero write, the dialog stays
  // open and usable, and the user can go straight on to pick a status.
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  // The dialog is rendered through a portal with fixed positioning: MatchCard's
  // root is `overflow-hidden` (rounded corners + urgency border), which would
  // otherwise clip an in-card absolute dropdown — the bug where "Mark status"
  // got cut off and appeared to overlap the expanded reasons in a narrow card.
  const [coords, setCoords] = useState<{ top: number; right: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const optionRefs = useRef<Partial<Record<InteractionType, HTMLButtonElement | null>>>({});
  const removeFooterRef = useRef<HTMLButtonElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);

  // A single, general "what to focus after the next render" slot — every
  // action site below sets this (or leaves it null to intentionally NOT
  // move focus, e.g. an outside click must never steal focus from
  // whatever the user just clicked).
  const pendingFocusRef = useRef<(() => HTMLElement | null) | null>(null);
  useEffect(() => {
    if (!pendingFocusRef.current) return;
    const getEl = pendingFocusRef.current;
    pendingFocusRef.current = null;
    getEl()?.focus();
  });

  const closeMenu = useCallback(() => {
    setOpen(false);
    setConfirmingRemove(false);
  }, []);

  // Bumped (during render, see below) whenever disabled-becoming-true
  // force-closes an open dialog, so the effect just below it can move
  // focus back to the trigger. A separate tick rather than reusing
  // pendingFocusRef here: writing to a ref during render is itself
  // disallowed in this codebase (react-hooks/refs) — state is the only
  // render-safe way to signal "do this focus move" out to an effect.
  const [focusTriggerTick, setFocusTriggerTick] = useState(0);
  useEffect(() => {
    if (focusTriggerTick > 0) triggerRef.current?.focus();
  }, [focusTriggerTick]);

  // If a write starts (disabled flips true) WHILE the dialog is open —
  // whether because the user's OWN action here caused it, or some other
  // surface acting on the same opportunity — close it and queue focus back
  // to the trigger. This is React's documented "adjusting state when a
  // prop changes" pattern (setState called DURING render, gated on a
  // previous-value comparison held in state) rather than a `useEffect`
  // calling setState in its body — the latter is a lint-forbidden
  // cascading-render anti-pattern in this codebase (see the git history:
  // an earlier version used a disabled-keyed wrapper remount specifically
  // to route around it, which is what caused the whole focus-race bug
  // this component's doc comment above describes). This is now completely
  // safe to run unconditionally: the trigger is the SAME element the whole
  // time (never unmounted), so it can never fire "late" against a trigger
  // the user has already moved away from — it only ever runs at the exact
  // render where `disabled` first flips true, a single deterministic edge,
  // not "whenever re-enabled."
  const [prevDisabled, setPrevDisabled] = useState(disabled);
  if (disabled !== prevDisabled) {
    setPrevDisabled(disabled);
    if (disabled && open) {
      setOpen(false);
      setConfirmingRemove(false);
      setFocusTriggerTick((n) => n + 1);
    }
  }

  const place = useCallback(() => {
    const el = triggerRef.current;
    if (!el || typeof window === 'undefined') return;
    const r = el.getBoundingClientRect();
    const EST = 300; // approx dialog height; flip above when little room below
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
      // Outside click: close, but never steal focus from whatever the user
      // just clicked — pendingFocusRef stays null (closeMenu never touches it).
      closeMenu();
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key !== 'Escape') return;
      closeMenu();
      triggerRef.current?.focus();
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
  }, [open, place, closeMenu]);

  // Manual Tab/Shift+Tab cycle: the dialog is portaled to the end of
  // document.body, so the browser's natural tab order would otherwise
  // carry focus OUT of it (forward: off the end of the page; backward:
  // into whatever else happens to be portaled later in body). Cycling is
  // scoped to whichever buttons are CURRENTLY rendered inside menuRef, so
  // it adapts automatically between the status-list view and the 2-button
  // confirm view without any special-casing.
  function handleDialogKeyDown(e: React.KeyboardEvent) {
    if (e.key !== 'Tab') return;
    const container = menuRef.current;
    if (!container) return;
    const focusables = Array.from(container.querySelectorAll<HTMLButtonElement>('button'));
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey) {
      if (document.activeElement === first) {
        e.preventDefault();
        last.focus();
      }
    } else if (document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  const statusLabel = interaction ? t(`detail.tracker.statusLabels.${interaction}`) : null;
  const triggerLabel = statusLabel ?? t('results.statusMenu.trigger');

  const triggerClass = interaction
    ? `${INTERACTION_PILL_CLASS[interaction]} border`
    : 'bg-white border border-gray-200 text-gray-500 hover:border-gray-300';

  const baseTriggerAria = t('results.statusMenu.ariaTrigger', { title: opportunityTitle });
  // The visible pill already shows the current status to sighted users;
  // aria-label OVERRIDES a button's text content for its accessible name,
  // so without appending it here a screen reader would announce only "Set
  // application status for {title}" and never the actual status.
  const triggerAriaLabel = statusLabel ? `${baseTriggerAria}: ${statusLabel}` : baseTriggerAria;

  // The confirm sub-state is a DIFFERENT dialog in effect — it must not
  // still identify itself as "Application status options for {title}"
  // once it's actually asking the user to confirm a permanent deletion.
  // aria-describedby (confirmDescId, from useId() above) wires up the
  // visible warning body as the dialog's accessible description so a
  // screen reader user landing on Cancel/Remove hears both what this
  // dialog IS and what it is about to do.
  const dialogAriaLabel = confirmingRemove
    ? `${t('results.statusMenu.remove')}: ${opportunityTitle}`
    : t('results.statusMenu.ariaDialog', { title: opportunityTitle });

  return (
    <div className="w-full sm:w-auto sm:ml-auto">
      <button
        ref={triggerRef}
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          // Replaces the native `disabled` attribute's own click-blocking
          // — see the component doc comment for why this stays a real,
          // focusable button instead.
          if (disabled) return;
          setConfirmingRemove(false);
          setOpen((v) => {
            const next = !v;
            if (next) {
              place();
              pendingFocusRef.current = () =>
                (interaction ? optionRefs.current[interaction] : optionRefs.current[INTERACTION_OPTIONS[0]]) ?? null;
            }
            return next;
          });
        }}
        aria-disabled={disabled || undefined}
        aria-busy={disabled}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={triggerAriaLabel}
        className={`inline-flex items-center gap-1.5 w-full sm:w-auto justify-center sm:justify-start px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${disabled ? 'opacity-50 cursor-wait' : ''} ${triggerClass}`}
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

      {open && !disabled && coords && typeof document !== 'undefined' && createPortal(
        <div
          ref={menuRef}
          role="dialog"
          aria-label={dialogAriaLabel}
          aria-describedby={confirmingRemove ? confirmDescId : undefined}
          onKeyDown={handleDialogKeyDown}
          style={{ position: 'fixed', top: coords.top, right: coords.right, zIndex: 50 }}
          className="w-56 max-h-[70vh] overflow-auto bg-white rounded-xl shadow-[0_8px_28px_rgba(0,0,0,0.12)] border border-gray-100 py-1.5"
        >
          {confirmingRemove && interaction ? (
            <div className="p-3">
              <p id={confirmDescId} className="mb-3 text-[12px] leading-relaxed text-gray-600">
                {t('results.statusMenu.removeConfirmBody')}
              </p>
              <div className="flex items-center justify-end gap-2">
                <button
                  ref={cancelRef}
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setConfirmingRemove(false); // zero callback, zero write — dialog stays open
                    pendingFocusRef.current = () => removeFooterRef.current;
                  }}
                  className="rounded-lg px-3 py-1.5 text-[12px] font-medium text-gray-600 hover:bg-gray-100"
                >
                  {t('common.cancel')}
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    // Same same-type callback the underlying REMOVE
                    // contract already expects (see use-tracker-data.ts /
                    // use-results-interactions.ts) — only the UI trigger
                    // changed, not the write path.
                    onTrackInteraction(opportunityId, interaction);
                    pendingFocusRef.current = () => triggerRef.current;
                    closeMenu();
                  }}
                  className="rounded-lg bg-red-600 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-red-700"
                >
                  {t('results.statusMenu.removeConfirmYes')}
                </button>
              </div>
            </div>
          ) : (
            <>
              {INTERACTION_OPTIONS.map((type) => {
                const isActive = interaction === type;
                return (
                  <button
                    key={type}
                    ref={(el) => { optionRefs.current[type] = el; }}
                    type="button"
                    aria-pressed={isActive}
                    aria-disabled={isActive || undefined}
                    onClick={(e) => {
                      e.stopPropagation();
                      // Re-clicking the ALREADY-active status used to
                      // silently untoggle/delete it. Destructive removal is
                      // now ONLY reachable via the explicit, confirmed
                      // footer below — picking the current status again is
                      // simply a no-op.
                      if (isActive) return;
                      onTrackInteraction(opportunityId, type);
                      pendingFocusRef.current = () => triggerRef.current;
                      closeMenu();
                    }}
                    className={`flex items-center w-full gap-2 px-3 py-2 text-[13px] text-left transition-colors duration-150 ${
                      isActive
                        ? 'bg-indigo-50/50 text-gray-900 font-medium cursor-default'
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
                    ref={removeFooterRef}
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setConfirmingRemove(true);
                      pendingFocusRef.current = () => cancelRef.current;
                    }}
                    className="flex items-center w-full gap-2 px-3 py-2 text-[13px] text-gray-500 hover:bg-gray-50 transition-colors duration-150"
                  >
                    <X className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                    <span>{t('results.statusMenu.remove')}</span>
                  </button>
                </>
              )}
            </>
          )}
        </div>,
        document.body,
      )}
    </div>
  );
}
