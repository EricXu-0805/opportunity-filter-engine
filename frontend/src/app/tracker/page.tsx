'use client';

import { useEffect, useMemo, useRef } from 'react';
import { ArrowLeft, ClipboardList, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import StorageStatusBanner from '@/components/StorageStatusBanner';
import { useT } from '@/i18n/client';
import type { InteractionType } from '@/lib/supabase';

import { TrackerCard } from './TrackerCard';
import { TRACKER_COLUMNS, useTrackerData } from './use-tracker-data';

const COLUMN_ACCENT: Record<InteractionType, string> = {
  applied: 'text-indigo-700',
  replied: 'text-emerald-700',
  interviewing: 'text-violet-700',
  rejected: 'text-gray-500',
  dismissed: 'text-gray-400',
};

export default function TrackerPage() {
  const router = useRouter();
  const { t } = useT();
  const {
    items,
    unavailableItems,
    clearUnavailable,
    identityGeneration,
    loading,
    error,
    retry,
    statusPendingIds,
    leavingPendingIds,
    statusErrors,
    retryStatusItem,
    notesPendingIds,
    notesErrors,
    retryNotesItem,
    noteDrafts,
    setNoteDraft,
    changeStatus,
    saveNotes,
    setReminder,
  } = useTrackerData();

  const byColumn = useMemo(() => {
    const map = new Map<InteractionType, typeof items>();
    for (const status of TRACKER_COLUMNS) map.set(status, []);
    for (const it of items) {
      const col = map.get(it.record.type);
      if (col) col.push(it);
    }
    return map;
  }, [items]);

  const trackedCount = useMemo(
    () => items.filter((it) => TRACKER_COLUMNS.includes(it.record.type)).length,
    [items],
  );
  // An unavailable placeholder is still something real the user tracked —
  // it must count against the empty-state check, or a partially (or
  // entirely) unavailable tracker would render as "nothing tracked" when
  // there genuinely is something, just not currently viewable.
  const showEmptyState = trackedCount === 0 && unavailableItems.length === 0;

  const boardRef = useRef<HTMLDivElement | null>(null);
  const emptyStateLinkRef = useRef<HTMLAnchorElement | null>(null);
  const prevColumnIdsRef = useRef<Map<InteractionType, string[]>>(new Map());
  // The single card id the user last focused or operated on inside the
  // board, tagged with the identity generation it was recorded under. A
  // redirect below is computed for EXACTLY this card, never "whichever id
  // happens to be first found missing from some column" — a bulk reload or
  // an unrelated card's change must never hijack focus away from wherever
  // the user actually was, and without a recorded intent nothing happens at
  // all (no guessing from raw counts).
  const focusIntentRef = useRef<{ id: string; generation: number } | null>(null);

  const handleBoardFocusCapture = (e: React.FocusEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    const cardEl = target.closest<HTMLElement>('[data-tracker-card-id]');
    const id = cardEl?.getAttribute('data-tracker-card-id');
    if (id) focusIntentRef.current = { id, generation: identityGeneration };
  };

  // An identity switch or a retry/reload boundary makes the PRIOR column
  // snapshot — and whatever card it was tracking — meaningless: comparing a
  // stale generation's layout against a new (possibly smaller, possibly
  // completely different) item set would misread "this account has fewer
  // items" as "the user's card got removed," and redirect focus onto some
  // unrelated card. Reset both the diff baseline and the recorded focus
  // intent at every such boundary; the diff effect below intentionally does
  // nothing when there is no intent to act on.
  useEffect(() => {
    prevColumnIdsRef.current = new Map();
    focusIntentRef.current = null;
  }, [identityGeneration, loading]);

  // A confirmed REMOVE/dismiss — or an ordinary status SET that moves the
  // card to a DIFFERENT column — unmounts the card's whole DOM subtree: a
  // real remount, not a move, since React never carries a fiber across
  // different parents even with a matching key (see TrackerCard.tsx).
  // Browsers move focus to <body> (or `null`) the instant a focused node is
  // removed, synchronously, before any effect (including this one) runs —
  // so there is no "was focus inside the removed card" check left to make
  // after the fact. Instead: only ever act on the SPECIFIC card the user
  // was last focused on/operating (focusIntentRef) — never guess from "the
  // first column that shrank." If that card still exists globally (just
  // under a different column — an ordinary SET), focus its NEW trigger. If
  // it's gone everywhere (a real REMOVE/dismiss), fall back to: the same
  // column's same index, then the previous index; if that column is now
  // itself empty, the nearest actual card elsewhere on the board (forward,
  // then backward — every card in TRACKER_COLUMNS order still has a real,
  // visibly-focusable trigger, unlike a bare tabIndex=-1 header); if the
  // WHOLE board is now empty, the visible empty-state CTA. No timers, no
  // guessing from raw counts — driven entirely by comparing the current
  // column layout against the immediately prior one for this one tracked id.
  useEffect(() => {
    const board = boardRef.current;
    const prevColumnIds = prevColumnIdsRef.current;
    const nextColumnIds = new Map<InteractionType, string[]>();
    for (const status of TRACKER_COLUMNS) {
      nextColumnIds.set(status, (byColumn.get(status) ?? []).map((it) => it.opp.id));
    }
    prevColumnIdsRef.current = nextColumnIds;

    const intent = focusIntentRef.current;
    if (!intent) return; // no specific card was in focus/operated on — nothing to redirect
    if (intent.generation !== identityGeneration) return; // stale across an identity switch
    const trackedId = intent.id;

    const lostToBody = document.activeElement === document.body || document.activeElement == null;
    if (!lostToBody) return; // the user already moved focus somewhere real — never steal it back

    let fromStatus: InteractionType | null = null;
    let fromIndex = -1;
    for (const status of TRACKER_COLUMNS) {
      const idx = (prevColumnIds.get(status) ?? []).indexOf(trackedId);
      if (idx !== -1) { fromStatus = status; fromIndex = idx; break; }
    }
    if (fromStatus == null) return; // wasn't part of the previous snapshot at all

    if ((nextColumnIds.get(fromStatus) ?? []).includes(trackedId)) return; // unchanged — nothing to do

    // A SUCCESSFUL call below synchronously fires a native "focus" event,
    // which bubbles straight into the board's own onFocusCapture — that
    // handler re-records focusIntentRef against the id just focused, before
    // this function call even returns. Callers below MUST NOT clear
    // focusIntentRef after a successful call: doing so would immediately
    // erase the fresh intent that same call just correctly re-armed,
    // leaving nothing tracked for a subsequent KEYBOARD-ONLY action (Enter
    // on the now-focused trigger, no re-click) to redirect against — its
    // own next real change would find focusIntentRef null and silently
    // no-op, losing focus to <body> with no rescue. Only ever clear on
    // outright failure (no candidate, or nothing there to focus).
    const focusCardTrigger = (id: string) => {
      const cardEl = board?.querySelector<HTMLElement>(`[data-tracker-card-id="${id}"]`);
      const btn = cardEl?.querySelector<HTMLElement>('button[aria-haspopup="dialog"]');
      btn?.focus();
      return !!btn;
    };

    // MOVE: an ordinary status SET — the card still exists globally, just
    // relocated to a different column. Never treat this as a removal.
    for (const status of TRACKER_COLUMNS) {
      if (status !== fromStatus && (nextColumnIds.get(status) ?? []).includes(trackedId)) {
        if (!focusCardTrigger(trackedId)) focusIntentRef.current = null; // fail closed only
        return;
      }
    }

    // REMOVE: gone everywhere. Same column, same index -> previous index.
    const sameColumn = nextColumnIds.get(fromStatus) ?? [];
    const sameColumnFallback = sameColumn[fromIndex] ?? sameColumn[fromIndex - 1];
    if (sameColumnFallback && focusCardTrigger(sameColumnFallback)) return;

    // The old column is itself empty now — walk the rest of the board
    // (forward, then backward) for the nearest actual, operable card.
    const fromColIdx = TRACKER_COLUMNS.indexOf(fromStatus);
    for (let i = fromColIdx + 1; i < TRACKER_COLUMNS.length; i++) {
      const ids = nextColumnIds.get(TRACKER_COLUMNS[i]) ?? [];
      if (ids.length > 0 && focusCardTrigger(ids[0])) return;
    }
    for (let i = fromColIdx - 1; i >= 0; i--) {
      const ids = nextColumnIds.get(TRACKER_COLUMNS[i]) ?? [];
      if (ids.length > 0 && focusCardTrigger(ids[ids.length - 1])) return;
    }

    // Every fallback attempt either had no candidate or failed to actually
    // focus one — fail closed. (A successful focus() anywhere above already
    // re-armed focusIntentRef via onFocusCapture and returned before ever
    // reaching here.)
    if (showEmptyState) emptyStateLinkRef.current?.focus();
    focusIntentRef.current = null;
  }, [byColumn, showEmptyState, identityGeneration]);

  if (loading) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
        <p className="text-[13px] text-gray-400">{t('tracker.loading')}</p>
      </div>
    );
  }

  // A read failure is NOT a confirmed "nothing tracked" — rendering the
  // empty state here would silently hide every real tracked item behind a
  // transient network blip. Visible + retryable, never silent.
  if (error) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <p className="text-[13px] text-red-700">{t('tracker.loadError')}</p>
        <button
          type="button"
          onClick={retry}
          className="rounded-xl bg-gray-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-800"
        >
          {t('common.retry')}
        </button>
      </div>
    );
  }

  return (
    <div ref={boardRef} onFocusCapture={handleBoardFocusCapture} className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
      <button
        type="button"
        onClick={() => router.back()}
        className="mb-8 inline-flex items-center gap-2 text-[13px] text-gray-400 transition-colors duration-300 hover:text-gray-600"
      >
        <ArrowLeft className="h-4 w-4" />
        {t('tracker.back')}
      </button>

      <StorageStatusBanner />

      <div className="mb-8 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gray-100">
          <ClipboardList className="h-5 w-5 text-gray-600" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-gray-900">{t('tracker.title')}</h1>
          <p className="text-sm text-gray-400">{t('tracker.subtitle')}</p>
        </div>
      </div>

      {showEmptyState ? (
        <div className="rounded-2xl border border-dashed border-gray-200 px-6 py-16 text-center">
          <p className="text-sm font-medium text-gray-600">{t('tracker.emptyTitle')}</p>
          <p className="mt-1 text-[13px] text-gray-400">{t('tracker.emptyBody')}</p>
          <Link
            ref={emptyStateLinkRef}
            href="/results"
            className="mt-5 inline-flex items-center rounded-xl bg-gray-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-800"
          >
            {t('tracker.emptyCta')}
          </Link>
        </div>
      ) : (
        <>
          {unavailableItems.length > 0 && (
            <section className="mb-6 rounded-2xl border border-dashed border-gray-200 bg-gray-50/60 p-4">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                {t('tracker.unavailable.title')}
              </h2>
              <ul className="space-y-2">
                {unavailableItems.map((u) => (
                  <li
                    key={`${identityGeneration}:${u.id}`}
                    className="flex items-center justify-between gap-3 rounded-xl border border-gray-200 bg-white px-3 py-2"
                  >
                    <div className="min-w-0">
                      <p className="text-[13px] text-gray-500">{t('tracker.unavailable.body')}</p>
                      {statusErrors.has(u.id) && (
                        <p role="alert" className="mt-1 flex items-center gap-1.5 text-[11px] text-red-700">
                          {t('tracker.statusSaveError')}
                          <button
                            type="button"
                            onClick={() => retryStatusItem(u.id)}
                            className="font-semibold text-indigo-600 hover:text-indigo-700"
                          >
                            {t('common.retry')}
                          </button>
                        </p>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => clearUnavailable(u.id)}
                      disabled={statusPendingIds.has(u.id)}
                      className="shrink-0 rounded-lg border border-gray-200 px-2.5 py-1 text-[11px] font-medium text-gray-500 transition-colors hover:border-red-300 hover:text-red-600 disabled:opacity-50 disabled:cursor-wait"
                    >
                      {t('tracker.unavailable.remove')}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {trackedCount > 0 && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4 items-start">
              {TRACKER_COLUMNS.map((status) => {
                const colItems = byColumn.get(status) ?? [];
                return (
                  <section key={status} data-tracker-column={status} className="rounded-2xl bg-gray-50/60 p-3">
                    <h2
                      className={`mb-3 px-1 text-xs font-semibold uppercase tracking-wide ${COLUMN_ACCENT[status]}`}
                    >
                      {t(`tracker.status.${status}`)}
                      <span className="ml-1.5 text-gray-400">{colItems.length}</span>
                    </h2>
                    <div className="space-y-3">
                      {colItems.map((it) => (
                        <TrackerCard
                          key={`${identityGeneration}:${it.opp.id}`}
                          opp={it.opp}
                          status={it.record.type}
                          remindAt={it.record.remind_at}
                          draft={noteDrafts.get(it.opp.id) ?? it.record.notes ?? ''}
                          onDraftChange={setNoteDraft}
                          onChangeStatus={changeStatus}
                          onSaveNotes={saveNotes}
                          onSetReminder={setReminder}
                          statusPending={statusPendingIds.has(it.opp.id)}
                          leavingPending={leavingPendingIds.has(it.opp.id)}
                          statusError={statusErrors.has(it.opp.id)}
                          onRetryStatus={retryStatusItem}
                          notesPending={notesPendingIds.has(it.opp.id)}
                          notesError={notesErrors.has(it.opp.id)}
                          onRetryNotes={retryNotesItem}
                          t={t}
                        />
                      ))}
                      {colItems.length === 0 && (
                        <p className="px-1 py-6 text-center text-xs text-gray-300">{t('tracker.columnEmpty')}</p>
                      )}
                    </div>
                  </section>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
