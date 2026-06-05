'use client';

import { useCallback, useEffect, useState } from 'react';

import { getOpportunitiesByIds } from '@/lib/api';
import {
  getInteractionsFull,
  removeInteraction,
  trackInteraction,
  updateInteractionDetails,
  type InteractionRecord,
  type InteractionType,
} from '@/lib/supabase';
import type { Opp } from '@/app/favorites/types';

export interface TrackedItem {
  opp: Opp;
  record: InteractionRecord;
}

export interface UseTrackerDataResult {
  items: TrackedItem[];
  loading: boolean;
  changeStatus: (id: string, type: InteractionType) => void;
  saveNotes: (id: string, notes: string) => void;
  setReminder: (id: string, date: string | null) => void;
}

// Hydrates the tracker once at mount: pull every tracked interaction (status +
// notes + reminders) from Supabase, resolve the opportunity_ids to full
// payloads via getOpportunitiesByIds, and join. Mutations are optimistic with a
// background Supabase write — the same pattern /results uses for status, so the
// two views stay consistent.
export function useTrackerData(): UseTrackerDataResult {
  const [items, setItems] = useState<TrackedItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
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
        // network/RLS failure → leave items empty; the empty state renders.
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  const changeStatus = useCallback((id: string, type: InteractionType) => {
    setItems((prev) => {
      const cur = prev.find((it) => it.opp.id === id);
      if (cur && cur.record.type === type) {
        // Re-selecting the active status clears it (same untoggle semantics as
        // the per-card menu on /results).
        removeInteraction(id).catch(() => {});
        return prev.filter((it) => it.opp.id !== id);
      }
      trackInteraction(id, type).catch(() => {});
      return prev.map((it) =>
        it.opp.id === id ? { ...it, record: { ...it.record, type } } : it,
      );
    });
  }, []);

  const saveNotes = useCallback((id: string, notes: string) => {
    setItems((prev) =>
      prev.map((it) =>
        it.opp.id === id ? { ...it, record: { ...it.record, notes } } : it,
      ),
    );
    updateInteractionDetails(id, { notes: notes.trim() || null }).catch(() => {});
  }, []);

  const setReminder = useCallback((id: string, date: string | null) => {
    setItems((prev) =>
      prev.map((it) =>
        it.opp.id === id ? { ...it, record: { ...it.record, remind_at: date ?? undefined } } : it,
      ),
    );
    updateInteractionDetails(id, { remind_at: date }).catch(() => {});
  }, []);

  return { items, loading, changeStatus, saveNotes, setReminder };
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
  'applied',
  'replied',
  'interviewing',
  'rejected',
];
