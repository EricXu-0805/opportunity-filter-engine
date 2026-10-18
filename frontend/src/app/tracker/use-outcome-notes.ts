'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { appendOutcomeNote, getOutcomeNotes, type InteractionType } from '@/lib/supabase';
import {
  outcomeNoteBodyProblem,
  OutcomeNoteError,
  type OutcomeNote,
  type OutcomeNoteOutcome,
} from '@/lib/outcome-notes';
import { captureOwnerToken } from '@/lib/identity-owner';

export interface OutcomeDraft {
  body: string;
  outcome: OutcomeNoteOutcome | null;
  /** Kept from the first save attempt until the text or outcome changes, so a
   *  retry after an unknown result replays that note instead of adding one. */
  noteId?: string;
}

export type OutcomeNoteProblem = 'empty' | 'too_long' | 'not_one_line' | 'busy' | 'conflict'
  | 'target_unavailable' | 'failed';

export interface UseOutcomeNotesResult {
  /** Notes per target, newest first. Undefined until the first read succeeds. */
  notes: Map<string, OutcomeNote[]> | undefined;
  loadError: boolean;
  retryLoad: () => void;
  drafts: Map<string, OutcomeDraft>;
  setDraft: (id: string, draft: Pick<OutcomeDraft, 'body' | 'outcome'>) => void;
  pendingIds: Set<string>;
  problems: Map<string, OutcomeNoteProblem>;
  submit: (id: string) => void;
}

const EMPTY_DRAFT: OutcomeDraft = { body: '', outcome: null };

/**
 * Outcome notes on the tracker board (checklist M49). Drafts live here, not in
 * the card, because a status change moves a card to another column and React
 * remounts it there (see useTrackerData's noteDrafts). A failed save keeps
 * the draft and its note id; only a confirmed save clears it.
 */
export function useOutcomeNotes({ identityGeneration, ready, runStatusWrite }: {
  identityGeneration: number;
  /** The board itself has loaded for this identity. */
  ready: boolean;
  runStatusWrite: (id: string, leaving: boolean, write: () => Promise<InteractionType | null>) => Promise<boolean>;
}): UseOutcomeNotesResult {
  const [notes, setNotesState] = useState<Map<string, OutcomeNote[]> | undefined>(undefined);
  const notesRef = useRef(notes);
  const setNotes = useCallback((next: Map<string, OutcomeNote[]> | undefined) => {
    notesRef.current = next;
    setNotesState(next);
  }, []);
  const [loadError, setLoadError] = useState(false);
  const [drafts, setDrafts] = useState<Map<string, OutcomeDraft>>(new Map());
  const draftsRef = useRef(drafts);
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set());
  const pendingRef = useRef(pendingIds);
  const [problems, setProblems] = useState<Map<string, OutcomeNoteProblem>>(new Map());
  const generationRef = useRef(identityGeneration);
  const loadAttemptRef = useRef(0);
  const [loadRequest, setLoadRequest] = useState(0);

  const setProblem = useCallback((id: string, problem: OutcomeNoteProblem | null) => {
    setProblems((prev) => {
      const next = new Map(prev);
      if (problem) next.set(id, problem); else next.delete(id);
      return next;
    });
  }, []);
  const setPending = useCallback((id: string, on: boolean) => {
    const next = new Set(pendingRef.current);
    if (on) next.add(id); else next.delete(id);
    pendingRef.current = next;
    setPendingIds(next);
  }, []);
  const putDraft = useCallback((id: string, draft: OutcomeDraft | null) => {
    const next = new Map(draftsRef.current);
    if (draft) next.set(id, draft); else next.delete(id);
    draftsRef.current = next;
    setDrafts(next);
  }, []);

  // A new identity starts with nothing: no notes, drafts or results of the
  // previous one. identityGeneration only moves on a real account change.
  useEffect(() => {
    generationRef.current = identityGeneration;
    loadAttemptRef.current++;
    /* eslint-disable react-hooks/set-state-in-effect --
       dropping the previous account's notes and drafts at the change itself;
       deferring it would render them for one frame under the new account. */
    setNotes(undefined);
    setLoadError(false);
    draftsRef.current = new Map();
    setDrafts(draftsRef.current);
    pendingRef.current = new Set();
    setPendingIds(pendingRef.current);
    setProblems(new Map());
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [identityGeneration, setNotes]);

  useEffect(() => {
    if (!ready) return;
    const attempt = ++loadAttemptRef.current;
    const generation = identityGeneration;
    const stale = () => generationRef.current !== generation || loadAttemptRef.current !== attempt;
    const token = captureOwnerToken();
    (async () => {
      try {
        const loaded = await getOutcomeNotes(token);
        if (stale()) return;
        setNotes(loaded);
        setLoadError(false);
      } catch {
        if (stale()) return;
        setLoadError(true);
      }
    })();
  }, [identityGeneration, ready, loadRequest, setNotes]);

  const retryLoad = useCallback(() => {
    setLoadError(false);
    setLoadRequest((n) => n + 1);
  }, []);

  const setDraft = useCallback((id: string, draft: Pick<OutcomeDraft, 'body' | 'outcome'>) => {
    if (pendingRef.current.has(id)) return;
    const prev = draftsRef.current.get(id);
    const same = prev && prev.body === draft.body && prev.outcome === draft.outcome;
    putDraft(id, { ...draft, noteId: same ? prev.noteId : undefined });
    setProblem(id, null);
  }, [putDraft, setProblem]);

  const submit = useCallback((id: string) => {
    if (pendingRef.current.has(id)) return;
    const draft = draftsRef.current.get(id) ?? EMPTY_DRAFT;
    // The student's words as typed, apart from spaces at either end.
    const body = draft.body.trim();
    const problem = outcomeNoteBodyProblem(body);
    if (problem) { setProblem(id, problem); return; }
    const noteId = draft.noteId ?? crypto.randomUUID();
    const sent: OutcomeDraft = { body: draft.body, outcome: draft.outcome, noteId };
    putDraft(id, sent);
    const generation = generationRef.current;
    const token = captureOwnerToken();
    setProblem(id, null);
    setPending(id, true);
    (async () => {
      let saved: OutcomeNote | null = null;
      const write = async () => {
        const result = await appendOutcomeNote(id, { noteId, body, outcome: draft.outcome }, token);
        saved = result.note;
        return draft.outcome ? result.status : null;
      };
      try {
        const ran = draft.outcome
          ? await runStatusWrite(id, draft.outcome === 'dismissed', write)
          : (await write(), true);
        if (generationRef.current !== generation) return;
        if (!ran) { setProblem(id, 'busy'); return; }
        const note = saved as OutcomeNote | null;
        // Before a first successful read there is no list to add to: read
        // again rather than show this one note as the target's whole list.
        if (note && notesRef.current) {
          const list = (notesRef.current.get(id) ?? []).filter((n) => n.id !== note.id);
          notesRef.current = new Map(notesRef.current).set(id, [note, ...list]);
          setNotes(notesRef.current);
        } else if (note) {
          setLoadRequest((n) => n + 1);
        }
        // Clear only the draft that was sent; an edit made meanwhile is refused
        // by setDraft, so this is the same text.
        putDraft(id, null);
      } catch (error) {
        if (generationRef.current !== generation) return;
        const kind = error instanceof OutcomeNoteError ? error.kind : null;
        setProblem(id, kind === 'conflict' ? 'conflict' : kind === 'target_unavailable' ? 'target_unavailable' : 'failed');
      } finally {
        if (generationRef.current === generation) setPending(id, false);
      }
    })();
  }, [putDraft, runStatusWrite, setNotes, setPending, setProblem]);

  return { notes, loadError, retryLoad, drafts, setDraft, pendingIds, problems, submit };
}
