'use client';

import {
  OUTCOME_NOTE_MAX_LENGTH,
  OUTCOME_NOTE_OUTCOMES,
  type OutcomeNote,
  type OutcomeNoteOutcome,
} from '@/lib/outcome-notes';
import { contactTimestamp } from '@/lib/contact-ledger';
import type { TFunc } from '@/app/favorites/types';

import type { OutcomeDraft, OutcomeNoteProblem } from './use-outcome-notes';

/** The student's local calendar date of the save, as YYYY-MM-DD. */
function savedOn(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Newest first, in the read's order: the database's save time to the
 *  microsecond, then the note id, both descending. */
function newestFirst(notes: OutcomeNote[]): OutcomeNote[] {
  const at = (note: OutcomeNote) => contactTimestamp(note.recordedAt) ?? BigInt(0);
  return [...notes].sort((a, b) => {
    const x = at(a), y = at(b);
    if (x !== y) return x < y ? 1 : -1;
    return a.id < b.id ? 1 : a.id > b.id ? -1 : 0;
  });
}

/**
 * The append-only outcome notes of one tracked target (checklist M49): the
 * saved notes, newest first, and one field to add another. There is no edit
 * or delete control, and the server refuses both; a correction is a new note.
 */
export function OutcomeNotes({
  opportunityId,
  notes,
  loadError,
  onRetryLoad,
  draft,
  onDraftChange,
  onSubmit,
  pending,
  problem,
  disabled = false,
  t,
}: {
  opportunityId: string;
  /** Undefined while the first read is outstanding or after it failed. */
  notes: OutcomeNote[] | undefined;
  loadError: boolean;
  onRetryLoad: () => void;
  draft: OutcomeDraft;
  onDraftChange: (id: string, draft: Pick<OutcomeDraft, 'body' | 'outcome'>) => void;
  onSubmit: (id: string) => void;
  pending: boolean;
  problem?: OutcomeNoteProblem;
  disabled?: boolean;
  t: TFunc;
}) {
  const inputId = `outcome-note-${opportunityId}`;
  const count = Array.from(draft.body.trim()).length;
  const locked = pending || disabled;
  return (
    <section className="mt-3 border-t border-gray-100 pt-3" aria-label={t('tracker.outcomeNotes.title')}>
      <h3 className="text-[11px] font-semibold text-gray-700">{t('tracker.outcomeNotes.title')}</h3>
      {notes ? (
        notes.length === 0 ? (
          <p className="mt-1 text-[11px] text-gray-500">{t('tracker.outcomeNotes.empty')}</p>
        ) : (
          <ol className="mt-1 space-y-1.5" aria-label={t('tracker.outcomeNotes.title')}>
            {newestFirst(notes).map((note) => (
              <li key={note.id} className="text-xs text-gray-700">
                <p className="text-[11px] text-gray-500">
                  <time dateTime={note.recordedAt}>
                    {t('tracker.outcomeNotes.notedOn', { date: savedOn(note.recordedAt) })}
                  </time>
                  {note.outcome && (
                    <> · {t('tracker.outcomeNotes.statusSet', { status: t(`detail.tracker.statusLabels.${note.outcome}`) })}</>
                  )}
                </p>
                <p className="whitespace-pre-wrap break-words">{note.body}</p>
              </li>
            ))}
          </ol>
        )
      ) : loadError ? (
        <p role="alert" className="mt-1 flex items-center gap-1.5 text-[11px] text-red-700">
          {t('tracker.outcomeNotes.loadError')}
          <button type="button" onClick={onRetryLoad} className="font-semibold text-indigo-600 hover:text-indigo-700">
            {t('common.retry')}
          </button>
        </p>
      ) : (
        <p className="mt-1 text-[11px] text-gray-500">{t('tracker.outcomeNotes.loading')}</p>
      )}

      <label htmlFor={inputId} className="mt-2 block text-[11px] font-medium text-gray-700">
        {t('tracker.outcomeNotes.addLabel')}
      </label>
      <p className="text-[11px] text-gray-500">{t('tracker.outcomeNotes.hint')}</p>
      <input
        id={inputId}
        type="text"
        value={draft.body}
        onChange={(e) => onDraftChange(opportunityId, { body: e.target.value, outcome: draft.outcome })}
        onKeyDown={(e) => {
          // Enter that ends an input method's composition (pinyin, kana)
          // picks the characters; saving then would keep a half-typed note
          // that can never be edited or deleted.
          if (e.key !== 'Enter' || locked || e.nativeEvent.isComposing || e.keyCode === 229) return;
          e.preventDefault();
          onSubmit(opportunityId);
        }}
        placeholder={t('tracker.outcomeNotes.placeholder')}
        readOnly={locked}
        aria-invalid={problem === 'empty' || problem === 'too_long' || problem === 'not_one_line'}
        className="mt-1 w-full rounded-xl border border-gray-200 px-3 py-2 text-xs text-gray-700 placeholder:text-gray-400 focus:border-indigo-300 focus:ring-2 focus:ring-indigo-500/20 outline-none read-only:opacity-60"
      />
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1 text-[11px] text-gray-600">
          {t('tracker.outcomeNotes.outcomeLabel')}
          <select
            value={draft.outcome ?? ''}
            onChange={(e) => onDraftChange(opportunityId, {
              body: draft.body,
              outcome: (e.target.value || null) as OutcomeNoteOutcome | null,
            })}
            disabled={locked}
            className="rounded-md border border-gray-200 px-1 py-0.5 text-[11px] text-gray-700 disabled:opacity-50"
          >
            <option value="">{t('tracker.outcomeNotes.outcomeNone')}</option>
            {OUTCOME_NOTE_OUTCOMES.map((outcome) => (
              <option key={outcome} value={outcome}>{t(`detail.tracker.statusLabels.${outcome}`)}</option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => onSubmit(opportunityId)}
          disabled={locked}
          className="rounded-md border border-indigo-200 px-2 py-0.5 text-[11px] font-semibold text-indigo-700 hover:bg-indigo-50 disabled:opacity-50 disabled:cursor-wait"
        >
          {pending ? t('tracker.outcomeNotes.saving') : t('tracker.outcomeNotes.save')}
        </button>
        <span className={`text-[11px] ${count > OUTCOME_NOTE_MAX_LENGTH ? 'text-red-700' : 'text-gray-500'}`}>
          {t('tracker.outcomeNotes.count', { count, max: OUTCOME_NOTE_MAX_LENGTH })}
        </span>
        {draft.outcome === 'dismissed' && (
          <span className="basis-full text-[11px] text-gray-500">{t('tracker.outcomeNotes.dismissedHint')}</span>
        )}
      </div>
      {problem && (
        <p role="alert" className="mt-1 text-[11px] text-red-700">
          {t(`tracker.outcomeNotes.errors.${problem}`, { max: OUTCOME_NOTE_MAX_LENGTH })}
        </p>
      )}
    </section>
  );
}
