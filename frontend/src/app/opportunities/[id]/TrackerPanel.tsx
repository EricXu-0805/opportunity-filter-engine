'use client';

import dynamic from 'next/dynamic';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { BellRing, StickyNote } from 'lucide-react';
import type { InteractionRecord } from '@/lib/supabase';
import type { SaveDetailsResult } from './use-opportunity-detail';
import type { TFunc } from './types';

const MarkdownPreview = dynamic(() => import('@/components/MarkdownPreview'), { ssr: false });
const AttachmentsPanel = dynamic(() => import('@/components/AttachmentsPanel'), { ssr: false });
const StatusTimeline = dynamic(() => import('@/components/StatusTimeline'), { ssr: false });

type NotesPatch = { notes?: string | null; remind_at?: string | null };

// The SAME transforms applied on the wire — dirty comparisons and patch
// construction must use these consistently on BOTH the draft and the
// baseline. Comparing a raw draft ("  hi  ") against an already-normalized
// baseline ("hi") would make the field look permanently dirty even right
// after its own save committed, dragging it along on every later save of
// an unrelated field (breaking the sparse-patch contract).
function normalizeNotes(v: string): string | null {
  return v.trim() ? v.trim().slice(0, 2000) : null;
}
function normalizeRemindAt(v: string): string | null {
  return v || null;
}

export function TrackerPanel({
  detail,
  onSave,
  opportunityId,
  hasInteraction,
  /** False while the owner/interaction-read state this panel writes
   *  against is not yet trustworthy (owner not primed, read loading/
   *  failed, no status yet, or a status write in flight) — see
   *  OpportunityDetail.tsx's computation. Disables every edit control:
   *  typing while a slow read is still in flight risks auto-saving a
   *  draft against a target that hasn't actually confirmed its current
   *  state yet, and a save attempted while not ready would resolve
   *  'abandoned' with no UI path back to retry it. Defaults to true so
   *  existing callers/tests that don't pass it are unaffected. */
  writeReady = true,
  /** Whether the reminders cron would actually send for this row — the
   *  target still actionable AND the status one it selects. Deliberately
   *  SEPARATE from writeReady: folding it in there would disable notes and
   *  the whole panel for a closed listing, which is the student's own record
   *  and must stay editable. What it gates is only scheduling: for anything
   *  else, the date input would accept a value, persist it, and then nothing
   *  would ever fire.
   *
   *  REQUIRED, with no default. A default of `true` means a caller that
   *  forgets it silently re-opens the exact control this exists to close;
   *  every call site has to make the decision explicitly. */
  reminderEligible,
  t,
}: {
  detail: InteractionRecord | null;
  onSave: (patch: NotesPatch) => Promise<SaveDetailsResult>;
  opportunityId: string;
  hasInteraction: boolean;
  writeReady?: boolean;
  reminderEligible: boolean;
  t: TFunc;
}) {
  const [open, setOpen] = useState(!!(detail?.notes || detail?.remind_at));
  const [notes, setNotes] = useState(detail?.notes ?? '');
  const [remindAt, setRemindAt] = useState(detail?.remind_at ?? '');
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [notesMode, setNotesMode] = useState<'edit' | 'preview'>('edit');

  // Each field's own last-CONFIRMED-from-parent baseline — separate from
  // the `notes`/`remindAt` DRAFT state above. A parent detail rewrite (an
  // earlier save's own round-trip landing, possibly after the user has
  // since started a newer, still-uncommitted edit) may only update a field
  // that is NOT currently dirty relative to its baseline; it must never
  // stomp a dirty draft — that is the "N1 completion overwrites N2" bug.
  const notesBaselineRef = useRef(detail?.notes ?? '');
  const remindAtBaselineRef = useRef(detail?.remind_at ?? '');
  // Bumped SYNCHRONOUSLY on every keystroke (onChange), NOT when a
  // debounced attemptSave eventually starts — a save started for N1 must
  // be recognized as stale the INSTANT the user begins typing N2, even
  // though N2's own debounce hasn't fired yet 600ms later. Bumping this
  // only at attemptSave-start would leave a window where N1's completion
  // (while N2 is drafted but not yet attempted) could still flash
  // Saved/Error over the user's fresher, uncommitted edit.
  const draftRevisionRef = useRef(0);
  // The EXACT sparse patch that last failed — Retry replays this verbatim,
  // never a fresh dirty-diff recomputed at retry time (which could differ
  // if some other field changed in between). Cleared the INSTANT a new
  // edit happens (see the onChange handlers) so a stale Retry can never
  // write back a patch the user has already changed their mind about.
  const lastFailedPatchRef = useRef<NotesPatch | null>(null);

  useEffect(() => {
    // The functional updater reads the CURRENT draft at flush time (never
    // a closure over the outer `notes` variable), so the dirty comparison
    // is always against the freshest value with no stale-closure risk —
    // and the effect's own deps genuinely need only detail?.notes.
    const oldBaseline = notesBaselineRef.current;
    const nextBaseline = detail?.notes ?? '';
    notesBaselineRef.current = nextBaseline;
    setNotes((cur) => (cur === oldBaseline ? nextBaseline : cur));
  }, [detail?.notes]);

  useEffect(() => {
    // See the notes effect above; independent per field.
    const oldBaseline = remindAtBaselineRef.current;
    const nextBaseline = detail?.remind_at ?? '';
    remindAtBaselineRef.current = nextBaseline;
    setRemindAt((cur) => (cur === oldBaseline ? nextBaseline : cur));
  }, [detail?.remind_at]);

  // A new edit ALWAYS invalidates a stale failure/retry immediately — the
  // user should never be able to click a Retry button that would write
  // back a patch for a draft they've since changed. Bumping the revision
  // here (not at attemptSave-start) is also what makes an in-flight save
  // correctly recognize itself as superseded the instant the next edit
  // happens, not 600ms later when that edit's own debounce fires.
  function handleNotesChange(value: string) {
    // The `disabled` attribute on the textarea is a UI-layer defense
    // (blocks real browser typing) but not a logic-layer guarantee — this
    // check is what actually makes it impossible to register an edit while
    // not writeReady, regardless of how the change event was dispatched.
    if (!writeReady) return;
    draftRevisionRef.current += 1;
    if (saveStatus === 'error') { setSaveStatus('idle'); lastFailedPatchRef.current = null; }
    setNotes(value);
  }
  // Read at execution time, not captured. A date can be picked while the row
  // is still eligible and then land after the student marks it rejected — the
  // 600ms debounce is long enough for exactly that — and a failed non-null
  // save can be retried after eligibility is gone. Both must refuse.
  //
  // useLayoutEffect, not useEffect: a passive effect runs after paint, so a
  // Retry clicked in the window between the new prop committing and the
  // effect flushing would read the OLD answer and replay a write the page has
  // already decided against. Layout effects run before the browser can
  // deliver that click.
  const reminderEligibleRef = useRef(reminderEligible);
  useLayoutEffect(() => {
    reminderEligibleRef.current = reminderEligible;
    if (reminderEligible) return;
    // Withdraw anything that could still write a date, in the same commit the
    // answer changes — not on the next debounce tick. A Retry offering to
    // replay a date-only patch that can no longer be accepted is a control
    // whose only possible outcome is to fail again; a mixed patch keeps its
    // notes half and stays retryable.
    setRemindAt(remindAtBaselineRef.current);
    const failed = lastFailedPatchRef.current;
    if (failed && failed.remind_at != null) {
      const { remind_at: _dropped, ...rest } = failed;
      if (Object.keys(rest).length === 0) {
        lastFailedPatchRef.current = null;
        setSaveStatus('idle');
      } else {
        lastFailedPatchRef.current = rest;
      }
    }
  }, [reminderEligible]);

  function handleRemindAtChange(value: string) {
    if (!writeReady) return;
    // Clearing is always allowed: dropping a date the student set is never
    // the thing this gate exists to prevent. Setting one is.
    if (value && !reminderEligibleRef.current) return;
    draftRevisionRef.current += 1;
    if (saveStatus === 'error') { setSaveStatus('idle'); lastFailedPatchRef.current = null; }
    setRemindAt(value);
  }

  // Shared by the debounced auto-save effect and the manual Retry button.
  // Without an explicit `patchOverride`, computes a SPARSE patch from
  // whichever field(s) currently differ from their own baseline (compared
  // using the SAME normalize* transforms as the wire patch — see their doc
  // comment for why raw comparison would falsely stay dirty forever) — a
  // notes-only edit must never carry remind_at (and vice versa), so a
  // concurrent edit to the other field via some other path is never
  // silently reverted to whatever this component happened to be showing
  // for it. `patchOverride` is used by Retry to replay the EXACT patch
  // that failed, not a recomputation.
  //
  // onSave (the hook's saveDetails) resolves to a discriminated result —
  // 'committed' only after real persistence; 'abandoned' covers every
  // precondition/generation-moved-on case — and only 'committed' is
  // treated as "Saved". A genuine failure for the current context throws.
  async function attemptSave(patchOverride?: NotesPatch) {
    if (!writeReady) { setSaveStatus('idle'); return; } // never actually attempt while not ready
    const patch: NotesPatch = patchOverride ?? {};
    if (!patchOverride) {
      const notesDirty = normalizeNotes(notes) !== normalizeNotes(notesBaselineRef.current);
      const remindAtDirty = normalizeRemindAt(remindAt) !== normalizeRemindAt(remindAtBaselineRef.current);
      if (notesDirty) patch.notes = normalizeNotes(notes);
      if (remindAtDirty) patch.remind_at = normalizeRemindAt(remindAt);
      if (!notesDirty && !remindAtDirty) {
        setSaveStatus('idle'); // nothing to save — clear a stale 'saving' left over from before the draft matched baseline again
        return;
      }
    }
    // ONE gate, on the fully-constructed patch, whichever path built it.
    // Checking the override alone left the debounced path open: a date picked
    // while the row was eligible is assembled here 600ms later, by which time
    // the student may have marked it rejected. A DOM-level hide never sees
    // that timer, and Retry replays a patch built under the old answer.
    //
    // Only a non-null remind_at is refused. A notes-only patch is unaffected,
    // and clearing an existing reminder (null) is always allowed — dropping a
    // date the student set is never what this prevents.
    if (patch.remind_at != null && !reminderEligibleRef.current) {
      delete patch.remind_at;
      // The draft goes back to what is actually persisted. Leaving the picked
      // date on screen while refusing to write it is the worst outcome of the
      // three: the student sees their date, sees "Saved", and has neither.
      setRemindAt(remindAtBaselineRef.current);
      lastFailedPatchRef.current = null;
    }
    // Emptiness is decided on the patch, not on the dirty flags that built
    // it. Reading the flags meant a refused reminder still counted as a
    // change, so onSave({}) went out and reported Saved for nothing.
    if (Object.keys(patch).length === 0) {
      setSaveStatus('idle');
      return;
    }
    const myRevision = draftRevisionRef.current;
    setSaveStatus('saving');
    try {
      const result = await onSave(patch);
      if (myRevision !== draftRevisionRef.current) return; // a newer edit has since happened
      if (result.status === 'committed') {
        lastFailedPatchRef.current = null;
        setSaveStatus('saved');
        setTimeout(() => { if (myRevision === draftRevisionRef.current) setSaveStatus('idle'); }, 1500);
      } else {
        // 'abandoned' — precondition/generation moved on, not the user's
        // fault; the identity-generation-keyed remount (see
        // OpportunityDetail.tsx) already handles a real account switch by
        // unmounting this component entirely, so quietly returning to idle
        // is correct here rather than flashing an error.
        setSaveStatus('idle');
      }
    } catch {
      if (myRevision !== draftRevisionRef.current) return;
      lastFailedPatchRef.current = patch;
      setSaveStatus('error');
    }
  }

  useEffect(() => {
    // Notes/reminders persist on the interactions row, so saving with no
    // status would have to invent one ('applied' = a send event the user
    // never reported). No status yet → no auto-save; the statusFirst hint
    // below asks the user to pick one instead. Not writeReady means the
    // same thing for a different reason (untrustworthy read, or a status
    // write in flight) — see the prop doc comment. Neither branch may
    // leave a stale 'saving' indicator behind: nothing is actually
    // happening once we bail out here.
    if (!hasInteraction || !writeReady) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- clears a stale indicator left over from before hasInteraction/writeReady flipped false; no timer is scheduled in this branch
      setSaveStatus('idle');
      return;
    }
    if (
      normalizeNotes(notes) === normalizeNotes(detail?.notes ?? '') &&
      normalizeRemindAt(remindAt) === normalizeRemindAt(detail?.remind_at ?? '')
    ) {
      // Clears a stale 'saving' left over from before the user reverted
      // their draft back to baseline within the 600ms window.
      setSaveStatus('idle');
      return;
    }
    setSaveStatus('saving');
    const timer = setTimeout(() => { void attemptSave(); }, 600);
    return () => clearTimeout(timer);
    // reminderEligible is a dep so losing eligibility tears down a debounce
    // that was scheduled while the row still had it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notes, remindAt, hasInteraction, writeReady, reminderEligible]);

  const hasContent = !!(notes || remindAt);

  return (
    <div className="border-t border-gray-100 px-5 sm:px-8 py-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 text-[12px] text-gray-500 hover:text-gray-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded"
        aria-expanded={open}
      >
        <StickyNote className="w-3.5 h-3.5" aria-hidden="true" />
        <span className="font-medium">
          {hasContent ? t('detail.tracker.openButton') : t('detail.tracker.addButton')}
        </span>
        {hasContent && !open && (
          <span className="ml-auto text-[11px] text-gray-400">
            {notes && <span>{notes.length > 40 ? notes.slice(0, 40) + '…' : notes}</span>}
            {remindAt && (
              // Collapsed, the amber bell and a date read as "this is
              // scheduled" — and the warning only existed once expanded, which
              // is the state a student scanning the page never enters. The
              // date stays (it is theirs); the colour drops to neutral and the
              // sentence comes with it.
              <span
                className={`ml-2 inline-flex items-center gap-1 ${
                  reminderEligible ? 'text-amber-600' : 'text-gray-400'
                }`}
              >
                <BellRing className="w-3 h-3" aria-hidden="true" />
                {remindAt}
                {!reminderEligible && (
                  <span className="ml-1">{t('tracker.reminderWontSend')}</span>
                )}
              </span>
            )}
          </span>
        )}
        <span className="ml-auto text-[11px] text-gray-400" aria-live="polite">
          {saveStatus === 'saving' && t('common.saving')}
          {saveStatus === 'saved' && t('common.saved')}
        </span>
      </button>
      {open && (
        <div className="mt-3 space-y-3 animate-in">
          {!hasInteraction && (
            <p className="text-[11px] text-amber-600 bg-amber-50 border border-amber-100 rounded-lg px-2.5 py-1.5">
              {t('detail.tracker.statusFirst')}
            </p>
          )}
          {saveStatus === 'error' && (
            <p role="alert" className="flex items-center gap-2 text-[11px] text-red-700 bg-red-50 border border-red-100 rounded-lg px-2.5 py-1.5">
              {t('detail.tracker.saveError')}
              <button
                type="button"
                onClick={() => { void attemptSave(lastFailedPatchRef.current ?? undefined); }}
                disabled={!writeReady}
                className="font-semibold text-indigo-600 hover:text-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded disabled:opacity-50 disabled:cursor-wait"
              >
                {t('common.retry')}
              </button>
            </p>
          )}
          {detail?.type && detail?.updated_at && (
            <StatusTimeline
              opportunityId={opportunityId}
              fallbackType={detail.type}
              fallbackUpdatedAt={detail.updated_at}
            />
          )}
          <div>
            <div role="tablist" aria-label={t('detail.tracker.notesTabsAria')} className="flex items-center gap-1 mb-1.5">
              <button
                type="button"
                role="tab"
                aria-selected={notesMode === 'edit'}
                onClick={() => setNotesMode('edit')}
                className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${
                  notesMode === 'edit'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                }`}
              >
                {t('detail.tracker.editTab')}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={notesMode === 'preview'}
                onClick={() => setNotesMode('preview')}
                className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${
                  notesMode === 'preview'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                }`}
              >
                {t('detail.tracker.previewTab')}
              </button>
            </div>
            {notesMode === 'edit' ? (
              <label className="block">
                <span className="sr-only">{t('detail.sections.description')}</span>
                <textarea
                  value={notes}
                  onChange={(e) => handleNotesChange(e.target.value)}
                  disabled={!writeReady}
                  maxLength={2000}
                  rows={3}
                  placeholder={t('detail.tracker.notesPlaceholder')}
                  className="w-full px-3 py-2 text-[13px] bg-white border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500/40 focus:border-indigo-400 resize-y disabled:opacity-60 disabled:cursor-wait"
                />
                <div className="flex justify-between mt-1 text-[10px] text-gray-400">
                  <span className="italic">{t('detail.tracker.markdownHint')}</span>
                  <span>{notes.length} / 2000</span>
                </div>
              </label>
            ) : (
              <div
                role="tabpanel"
                className="min-h-[5rem] px-3 py-2 text-[13px] bg-white border border-gray-200 rounded-lg prose prose-sm prose-gray max-w-none prose-headings:mt-2 prose-headings:mb-1 prose-p:my-1.5 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0 prose-pre:my-2 prose-pre:p-2 prose-pre:text-[12px]"
              >
                {notes.trim() ? (
                  <MarkdownPreview>{notes}</MarkdownPreview>
                ) : (
                  <p className="text-gray-400 italic text-[12px]">{t('detail.tracker.previewEmpty')}</p>
                )}
              </div>
            )}
          </div>
          <label className="flex items-center gap-2 text-[12px] text-gray-600">
            <BellRing className="w-3.5 h-3.5 text-amber-500" aria-hidden="true" />
            <span className="font-medium">{t('detail.tracker.remindLabel')}</span>
            {/* Absent, not disabled, when nothing would be delivered: a
                disabled date input still says "you may schedule one here,
                later". An existing date stays readable, and its Clear stays
                live — the student set that reminder, and dropping it is
                always allowed. */}
            {reminderEligible ? (
              <input
                type="date"
                value={remindAt}
                onChange={(e) => handleRemindAtChange(e.target.value)}
                disabled={!writeReady}
                className="px-2 py-1 text-[12px] bg-white border border-gray-200 rounded focus:outline-none focus:ring-2 focus:ring-indigo-500/40 disabled:opacity-60 disabled:cursor-wait"
              />
            ) : remindAt ? (
              <span className="px-2 py-1 text-[12px] text-gray-500">{remindAt}</span>
            ) : null}
            {remindAt && (
              <button
                type="button"
                onClick={() => handleRemindAtChange('')}
                disabled={!writeReady}
                className="text-[11px] text-gray-400 hover:text-red-500 transition-colors disabled:opacity-50 disabled:cursor-wait"
              >
                {t('common.clear')}
              </button>
            )}
            {!reminderEligible && (
              <span className="text-[11px] text-gray-400">
                {t(remindAt
                  ? 'tracker.reminderWontSend'
                  : 'tracker.reminderUnavailable')}
              </span>
            )}
          </label>
          {hasInteraction && (
            <div className="pt-2 border-t border-gray-50">
              <AttachmentsPanel opportunityId={opportunityId} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
