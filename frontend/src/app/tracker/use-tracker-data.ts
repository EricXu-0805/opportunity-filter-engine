'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { getOpportunitiesByIds } from '@/lib/api';
import {
  getInteractionsFull,
  removeInteraction,
  trackInteraction,
  updateInteractionDetails,
  type InteractionRecord,
  type InteractionType,
} from '@/lib/supabase';
import { useAuthUid } from '@/lib/use-auth-uid';
import type { Opp } from '@/app/favorites/types';

export interface TrackedItem {
  opp: Opp;
  record: InteractionRecord;
}

export interface UseTrackerDataResult {
  items: TrackedItem[];
  loading: boolean;
  /** W14: true when the board failed to load — the page renders an error +
   *  retry, distinct from genuinely empty columns. */
  loadError: boolean;
  retry: () => void;
  changeStatus: (id: string, type: InteractionType) => void;
  saveNotes: (id: string, notes: string) => void;
  setReminder: (id: string, date: string | null) => void;
}

// Hydrates the tracker once at mount: pull every tracked interaction (status +
// notes + reminders) from Supabase, resolve the opportunity_ids to full
// payloads via getOpportunitiesByIds, and join. Mutations are optimistic with a
// background Supabase write — the same pattern /results uses for status, so the
// two views stay consistent.
//
// W14: a failed load sets `loadError` (no more false-empty board), failed
// writes revert their optimistic update, and the load re-runs on a cross-tab
// identity switch (authEpoch).
export function useTrackerData(): UseTrackerDataResult {
  const [items, setItems] = useState<TrackedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const { epoch: authEpoch } = useAuthUid();

  // Mirror items into a ref so the mutation callbacks can read the current
  // board without depending on `items` (which would recreate them per render)
  // and without doing side effects inside a state updater.
  const itemsRef = useRef(items);
  useEffect(() => { itemsRef.current = items; }, [items]);

  useEffect(() => {
    let cancelled = false;
    /* eslint-disable react-hooks/set-state-in-effect --
       Reset before fetching: a no-op on mount, the isolation clear on an
       identity switch, and the error-state clear on retry. */
    setItems([]);
    setLoading(true);
    setLoadError(false);
    /* eslint-enable react-hooks/set-state-in-effect */
    async function load() {
      try {
        const full = await getInteractionsFull();
        if (cancelled) return;
        const ids = Array.from(full.keys());
        if (ids.length === 0) {
          setLoading(false);
          return;
        }
        const opps = (await getOpportunitiesByIds(ids)) as unknown as Opp[];
        if (cancelled) return;
        const byId = new Map(opps.map((o) => [o.id, o]));
        const merged: TrackedItem[] = [];
        for (const [id, record] of full) {
          const opp = byId.get(id);
          if (opp) merged.push({ opp, record });
        }
        setItems(merged);
      } catch {
        // W14 truthful zero states: network/RLS failure is an ERROR state,
        // never an empty board that claims the user tracked nothing.
        if (!cancelled) setLoadError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [authEpoch, attempt]);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);

  const changeStatus = useCallback((id: string, type: InteractionType) => {
    const cur = itemsRef.current.find((it) => it.opp.id === id);
    if (cur && cur.record.type === type) {
      // Re-selecting the active status clears it (same untoggle semantics as
      // the per-card menu on /results).
      setItems((prev) => prev.filter((it) => it.opp.id !== id));
      removeInteraction(id).catch(() => {});
      return;
    }
    const prevType = cur?.record.type;
    setItems((prev) => prev.map((it) =>
      it.opp.id === id ? { ...it, record: { ...it.record, type } } : it,
    ));
    trackInteraction(id, type).catch(() => {
      // W14: the write failed — revert the optimistic column move instead of
      // displaying a status that was never persisted.
      if (prevType === undefined) return;
      setItems((prev) => prev.map((it) =>
        it.opp.id === id ? { ...it, record: { ...it.record, type: prevType } } : it,
      ));
    });
  }, []);

  const saveNotes = useCallback((id: string, notes: string) => {
    const prevNotes = itemsRef.current.find((it) => it.opp.id === id)?.record.notes;
    setItems((prev) =>
      prev.map((it) =>
        it.opp.id === id ? { ...it, record: { ...it.record, notes } } : it,
      ),
    );
    void updateInteractionDetails(id, { notes: notes.trim() || null }).then((ok) => {
      // W14: revert the optimistic note on a failed write.
      if (!ok) {
        setItems((prev) => prev.map((it) =>
          it.opp.id === id ? { ...it, record: { ...it.record, notes: prevNotes } } : it,
        ));
      }
    });
  }, []);

  const setReminder = useCallback((id: string, date: string | null) => {
    const prevRemindAt = itemsRef.current.find((it) => it.opp.id === id)?.record.remind_at;
    setItems((prev) =>
      prev.map((it) =>
        it.opp.id === id ? { ...it, record: { ...it.record, remind_at: date ?? undefined } } : it,
      ),
    );
    void updateInteractionDetails(id, { remind_at: date }).then((ok) => {
      // W14: revert the optimistic reminder on a failed write.
      if (!ok) {
        setItems((prev) => prev.map((it) =>
          it.opp.id === id ? { ...it, record: { ...it.record, remind_at: prevRemindAt } } : it,
        ));
      }
    });
  }, []);

  return { items, loading, loadError, retry, changeStatus, saveNotes, setReminder };
}

/** ISO date (YYYY-MM-DD) `daysAhead` from today, for quick reminder presets. */
export function dateInDays(daysAhead: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + daysAhead);
  return d.toISOString().slice(0, 10);
}

/** A reminder is "due" when its date is today or earlier. */
export function isReminderDue(date?: string): boolean {
  return !!date && date <= new Date().toISOString().slice(0, 10);
}

// The pipeline columns, in order. "dismissed" is intentionally excluded — it is
// the hide-from-results status, not a stage in the application funnel.
export const TRACKER_COLUMNS: InteractionType[] = [
  'contacted',
  'applied',
  'replied',
  'interviewing',
  'rejected',
];
