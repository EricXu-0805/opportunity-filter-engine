// Shared by the tracker and supabase.ts, outside it so tests that mock the
// Supabase client still render the note form.
// supabase/migrations/20261018052512_outcome_notes.sql: one line of 1-300
// characters per note, appended by append_outcome_note and never edited.
export const OUTCOME_NOTE_MAX_LENGTH = 300;
export const OUTCOME_NOTE_OUTCOMES = ['replied', 'interviewing', 'rejected', 'dismissed'] as const;
export type OutcomeNoteOutcome = typeof OUTCOME_NOTE_OUTCOMES[number];
export interface OutcomeNote {
  id: string;
  opportunityId: string;
  body: string;
  outcome: OutcomeNoteOutcome | null;
  /** When the database saved the note, not when the outcome happened. */
  recordedAt: string;
}
export type OutcomeNoteErrorKind = 'invalid_input' | 'conflict' | 'target_unavailable' | 'unavailable';
export class OutcomeNoteError extends Error {
  constructor(readonly kind: OutcomeNoteErrorKind) {
    super(`outcome note ${kind}`);
    this.name = 'OutcomeNoteError';
  }
}
/** Same rule as the SQL CHECK: code points, not UTF-16 units, and no control
 *  or line-separator characters. */
export function outcomeNoteBodyProblem(body: string): 'empty' | 'too_long' | 'not_one_line' | null {
  if (!body.trim()) return 'empty';
  if (Array.from(body).length > OUTCOME_NOTE_MAX_LENGTH) return 'too_long';
  // SQL [[:cntrl:]] under UTF-8 also matches C1 and U+2028/2029; with the
  // u flag the surrogate range matches only a lone half PostgreSQL refuses.
  if (/[\u0000-\u001f\u007f-\u009f\u2028\u2029]/.test(body) || /[\ud800-\udfff]/u.test(body)) return 'not_one_line';
  return null;
}
