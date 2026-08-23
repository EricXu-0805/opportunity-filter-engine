'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { getShortlistOpportunities } from '@/lib/api';
import {
  dismissInteraction,
  getAuthState,
  getInteractionsFull,
  onAuthChange,
  removeInteraction,
  trackInteraction,
  updateInteractionDetails,
  type InteractionRecord,
  type InteractionType,
} from '@/lib/supabase';
import { captureOwnerToken } from '@/lib/identity-owner';
import { canDeliverReminder } from '@/lib/reminders';
import type { Opp } from '@/app/favorites/types';

export interface TrackedItem {
  opp: Opp;
  record: InteractionRecord;
}

// An interaction row whose opportunity_id no longer resolves via
// getShortlistOpportunities (deleted/archived/deactivated from the catalog,
// but the interaction row itself still exists). Silently dropping these
// during the merge would make the tracker look emptier than it truly is —
// including, in the worst case, a fully populated tracker rendering as
// "nothing tracked" if every tracked opportunity happened to go
// unavailable at once. Kept as an explicit placeholder record instead, so
// the user can see it (and clear it) rather than have it vanish unexplained.
// Never built for a 'dismissed' interaction, though — TRACKER_COLUMNS
// already excludes 'dismissed' from every pipeline view, and an unavailable
// opportunity must not resurrect it as something to look at.
export interface UnavailableTrackedItem {
  id: string;
  record: InteractionRecord;
}

export interface UseTrackerDataResult {
  items: TrackedItem[];
  /** Interaction rows whose opportunity could not be resolved this load —
   *  see UnavailableTrackedItem. Never silently dropped from the count:
   *  the page's empty-state check must also account for this array, or a
   *  fully (or partially) unavailable tracker would render as though
   *  nothing were tracked at all. */
  unavailableItems: UnavailableTrackedItem[];
  /** Clears (removes the interaction row for) an unavailable placeholder —
   *  the only action available for one, since there is no real opportunity
   *  left to track a status/notes/reminder against. Pessimistic, and
   *  shares the exclusive channel's pending/error/retry — see
   *  performStatusOp. */
  clearUnavailable: (id: string) => void;
  /** Bumps on every REAL identity transition (never a same-uid
   *  re-observation). The page keys each TrackerCard by
   *  `${identityGeneration}:${opp.id}` — relying on `items` merely PASSING
   *  through an empty array between identities is not a robust guarantee
   *  that React actually unmounts a card sharing the same opportunity id
   *  across two different accounts; the generation-qualified key forces a
   *  fresh instance (and therefore a fresh, empty local notes draft)
   *  explicitly, by construction. */
  identityGeneration: number;
  loading: boolean;
  /** True when the bulk interaction read failed — items is NOT a confirmed
   *  "nothing tracked" in this state, just unknown. Never silently rendered
   *  as the empty-tracker state; see retry(). */
  error: boolean;
  retry: () => void;
  /** Opportunity ids with a status/remove or reminder write currently in
   *  flight — status and reminder share ONE exclusive slot per id (only one
   *  of the two may be outstanding at a time; a second attempt is a
   *  fail-closed no-op), so this set doubles as their shared busy/disabled
   *  signal. A notes save NEVER appears here and never blocks or is
   *  blocked by this channel — see notesPendingIds/saveNotes. */
  statusPendingIds: Set<string>;
  /** Subset of statusPendingIds specifically for a REMOVE or dismiss-SET —
   *  ops that make the card LEAVE the board once confirmed, as opposed to
   *  an ordinary SET (which only moves it between columns and stays). The
   *  caller must disable the notes textarea for exactly this subset: a new
   *  edit started while the card is about to disappear has nowhere safe to
   *  land (see use-tracker-data.ts's performStatusOp for the full
   *  reasoning) — an ordinary SET's pending window must NOT gate it. */
  leavingPendingIds: Set<string>;
  /** Opportunity ids whose last status/remove-or-reminder attempt failed. */
  statusErrors: Set<string>;
  retryStatusItem: (id: string) => void;
  /** Opportunity ids with a notes save currently in flight — informational
   *  only (e.g. a small "Saving…" indicator); never gates the textarea, or
   *  a second edit before the first save round-trips could never be typed. */
  notesPendingIds: Set<string>;
  /** Opportunity ids whose LATEST notes save attempt failed. An earlier
   *  save's failure is never reported here once a newer one has been
   *  issued for the same id — see saveNotes. */
  notesErrors: Set<string>;
  retryNotesItem: (id: string) => void;
  /** The live, uncommitted per-id textarea draft — owned HERE rather than
   *  by the card component, so it survives a status-triggered move between
   *  pipeline columns (a remount at the DOM level; see the module doc
   *  comment). Falls back to the persisted `record.notes` for an id with no
   *  entry yet (nothing typed since load). */
  noteDrafts: Map<string, string>;
  /** The textarea's onChange handler — updates the live draft and, since an
   *  edit means the user has moved past any prior failed attempt,
   *  immediately invalidates a stale notes error/Retry (does not wait for
   *  blur). */
  setNoteDraft: (id: string, value: string) => void;
  changeStatus: (id: string, type: InteractionType) => void;
  saveNotes: (id: string, notes: string) => void;
  setReminder: (id: string, date: string | null) => void;
}

// Trim-based equivalence, matching what actually gets persisted
// (updateInteractionDetails sends notes.trim() || null) — comparing raw
// strings would treat "hi" and "hi " (or "" vs undefined) as different
// baselines when the server considers them identical.
function normalizeNotes(v: string | null | undefined): string | null {
  const t = (v ?? '').trim();
  return t ? t : null;
}

type StatusOp =
  | { kind: 'set'; type: InteractionType }
  | { kind: 'remove'; expectedType: InteractionType };

// The exclusive channel's last-failed attempt, stored as DATA (never a
// closure) so retryStatusItem — declared after performStatusOp/setReminder,
// which it dispatches to — never needs either of them to reference
// themselves recursively from inside their own useCallback body.
type ExclusiveIntent = StatusOp | { kind: 'reminder'; date: string | null };

// Hydrates the tracker on mount AND on every real identity change: pull every
// tracked interaction (status + notes + reminders) from Supabase, resolve the
// opportunity_ids to full payloads via getShortlistOpportunities, and join.
// Mutations capture an owner token at the moment of the user action (before
// any await) and never silently swallow a write error — the same owner-
// token/honest-error contract established for /results
// (use-results-interactions.ts) and the opportunity detail page
// (use-opportunity-detail.ts). A genuine failure on the exclusive (status/
// reminder) channel rolls its field back to the last known-persisted value;
// the notes channel deliberately does NOT roll back its visible draft on
// failure — see saveNotes below for why.
//
// Two INDEPENDENT per-id channels, deliberately never blocking each other:
//   - "exclusive" (status set/remove + reminder): mutually block each other
//     — only one of the two may be in flight per id at a time — because
//     both are discrete, single-shot button clicks, and a lost click would
//     be a silent, confusing UI failure.
//   - "notes": a save is invoked on every textarea blur, so blocking a
//     second save while an earlier one is still in flight would risk
//     dropping an edit. Every invocation is allowed through — all still
//     land on the remote row in invocation order via the shared write
//     queue (identity-owner.ts's enqueuePrivateWrite, keyed by
//     owner+opportunityId) — but only the LATEST invocation for an id may
//     ever update the visible draft/error state (a monotonic per-id
//     intent counter), so an earlier save's late completion can never
//     clobber a newer one.
// The two channels never gate each other: a status click issued while a
// notes save is in flight for the same id proceeds immediately (its remote
// call simply enqueues behind the notes save); a notes edit while a status
// change is in flight is equally unaffected.
export function useTrackerData(): UseTrackerDataResult {
  const [items, setItems] = useState<TrackedItem[]>([]);
  const itemsRef = useRef(items);
  const [unavailableItems, setUnavailableItems] = useState<UnavailableTrackedItem[]>([]);
  const unavailableItemsRef = useRef(unavailableItems);
  const [identityGeneration, setIdentityGeneration] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  // --- exclusive channel (status set/remove + reminder) ---
  const statusPendingRef = useRef<Set<string>>(new Set());
  const [statusPendingIds, setStatusPendingIds] = useState<Set<string>>(new Set());
  const statusErrorsRef = useRef<Set<string>>(new Set());
  const [statusErrors, setStatusErrors] = useState<Set<string>>(new Set());
  const statusRetryIntentRef = useRef<Map<string, ExclusiveIntent>>(new Map());
  // Subset of statusPendingIds specifically for a REMOVE or dismiss-SET —
  // ops that make the card LEAVE the board once confirmed, as opposed to an
  // ordinary SET (which only moves it between columns and stays). Only this
  // subset disables the notes textarea (see TrackerCard's `leavingPending`
  // prop): if the card is about to disappear/have its row deleted, a NEW
  // edit typed during that window has nowhere safe to land — it would
  // either be silently discarded by the post-success cleanup, or (if
  // blurred) queue a write that fails once the row is already gone (both
  // writes for the same opportunity id share ONE serialized queue — see
  // identity-owner.ts's enqueuePrivateWrite). An ordinary SET's pending
  // window must NOT gate the textarea this way — the card is staying.
  const leavingPendingRef = useRef<Set<string>>(new Set());
  const [leavingPendingIds, setLeavingPendingIds] = useState<Set<string>>(new Set());

  // --- notes channel ---
  const noteBusyCountRef = useRef<Map<string, number>>(new Map());
  const [notesPendingIds, setNotesPendingIds] = useState<Set<string>>(new Set());
  const noteIntentRef = useRef<Map<string, number>>(new Map());
  const noteErrorsRef = useRef<Set<string>>(new Set());
  const [notesErrors, setNotesErrors] = useState<Set<string>>(new Set());
  // The raw failed draft (data, not a closure) — retryNotesItem replays it
  // through the already-declared saveNotes, so saveNotes never needs to
  // reference itself recursively from inside its own useCallback body.
  const noteRetryDraftRef = useRef<Map<string, string>>(new Map());
  // Last CONFIRMED-persisted notes value per id (raw, un-trimmed — matching
  // how record.notes/the draft are compared everywhere else). Used ONLY to
  // skip a genuinely redundant network write when the user edits back to
  // exactly this value — see saveNotes. Never used to roll back the visible
  // draft (a failure keeps showing exactly what the user last typed).
  const notesBaselineRef = useRef<Map<string, string | null>>(new Map());
  // The live per-id textarea draft — lives HERE, not as TrackerCard's own
  // local state. An optimistic status SET moves a card between pipeline
  // columns, which page.tsx renders as DIFFERENT parent <section> elements.
  // React does not "move" a component across different parents even with a
  // matching key — it unmounts the old fiber and mounts a fresh one. A
  // draft held in component-local state would be silently destroyed by
  // that remount before the user ever blurred, with zero onSaveNotes call
  // — real, observed data loss. Holding it here instead means the remount
  // is invisible: the fresh instance is handed the SAME draft back as a
  // prop. Reset only on a real identity switch (resetForIdentity) — never
  // on a background reload/retry, which must not discard unsaved typing.
  const noteDraftsRef = useRef<Map<string, string>>(new Map());
  const [noteDrafts, setNoteDraftsState] = useState<Map<string, string>>(new Map());

  const identityGenerationRef = useRef(0);
  // UI-level defense only — set false once, in the unmount cleanup below.
  // This does NOT solve cross-surface write interleaving (a component
  // unmounting doesn't change what another surface enqueues against the
  // SAME opportunity id); that correctness property comes from
  // dismissInteraction's single atomic enqueue in supabase.ts. This just
  // avoids touching state after the component backing it is gone — e.g. a
  // dismiss still in flight when the user navigates away from /tracker
  // entirely — which React otherwise silently no-ops but is still worth
  // not attempting.
  const mountedRef = useRef(true);
  useEffect(() => {
    // StrictMode (dev) double-invokes effects: setup -> cleanup -> setup.
    // A bare `() => { mountedRef.current = false }` cleanup with no
    // corresponding reset on the SECOND setup would leave this stuck
    // false forever after the first mount/unmount/remount cycle, silently
    // blocking every real state update for the rest of the component's
    // life. The setup must explicitly reset it back to true.
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // exclusive-channel helpers
  const addStatusPending = useCallback((id: string) => {
    const next = new Set(statusPendingRef.current).add(id);
    statusPendingRef.current = next;
    setStatusPendingIds(next);
  }, []);
  const removeStatusPending = useCallback((id: string) => {
    if (!statusPendingRef.current.has(id)) return;
    const next = new Set(statusPendingRef.current);
    next.delete(id);
    statusPendingRef.current = next;
    setStatusPendingIds(next);
  }, []);
  const addLeavingPending = useCallback((id: string) => {
    const next = new Set(leavingPendingRef.current).add(id);
    leavingPendingRef.current = next;
    setLeavingPendingIds(next);
  }, []);
  const removeLeavingPending = useCallback((id: string) => {
    if (!leavingPendingRef.current.has(id)) return;
    const next = new Set(leavingPendingRef.current);
    next.delete(id);
    leavingPendingRef.current = next;
    setLeavingPendingIds(next);
  }, []);
  const setStatusFailed = useCallback((id: string, intent?: ExclusiveIntent) => {
    // clearUnavailable has no ExclusiveIntent to store — retryStatusItem
    // special-cases an unavailable id BEFORE ever consulting
    // statusRetryIntentRef (see there), so there is nothing to replay via
    // this map for that case.
    if (intent) statusRetryIntentRef.current.set(id, intent);
    const next = new Set(statusErrorsRef.current).add(id);
    statusErrorsRef.current = next;
    setStatusErrors(next);
  }, []);
  const clearStatusFailed = useCallback((id: string) => {
    if (!statusErrorsRef.current.has(id)) return;
    statusRetryIntentRef.current.delete(id);
    const next = new Set(statusErrorsRef.current);
    next.delete(id);
    statusErrorsRef.current = next;
    setStatusErrors(next);
  }, []);

  // notes-channel helpers
  const incNoteBusy = useCallback((id: string) => {
    const n = (noteBusyCountRef.current.get(id) ?? 0) + 1;
    noteBusyCountRef.current.set(id, n);
    if (n === 1) setNotesPendingIds(new Set(noteBusyCountRef.current.keys()));
  }, []);
  const decNoteBusy = useCallback((id: string) => {
    const n = (noteBusyCountRef.current.get(id) ?? 0) - 1;
    if (n <= 0) {
      noteBusyCountRef.current.delete(id);
      setNotesPendingIds(new Set(noteBusyCountRef.current.keys()));
    } else {
      noteBusyCountRef.current.set(id, n);
    }
  }, []);
  const setNoteFailed = useCallback((id: string, draft: string) => {
    noteRetryDraftRef.current.set(id, draft);
    const next = new Set(noteErrorsRef.current).add(id);
    noteErrorsRef.current = next;
    setNotesErrors(next);
  }, []);
  const clearNoteFailed = useCallback((id: string) => {
    if (!noteErrorsRef.current.has(id)) return;
    noteRetryDraftRef.current.delete(id);
    const next = new Set(noteErrorsRef.current);
    next.delete(id);
    noteErrorsRef.current = next;
    setNotesErrors(next);
  }, []);
  // The textarea's onChange handler (live typing, before any blur/commit).
  // An edit invalidates a stale failure/Retry THE INSTANT it happens — never
  // waits for the next blur. Bumping the shared per-id intent counter here
  // also means an OLDER in-flight save's late failure (still resolving from
  // before this edit) is recognized as superseded once it settles, so it
  // can never resurrect an error/Retry describing text the user has since
  // changed — see saveNotes' catch branch, which checks this same counter.
  const setNoteDraft = useCallback((id: string, value: string) => {
    // Fail-closed against leavingPending here too, not just via the
    // textarea's `disabled` attribute — a stale event handler reference or
    // a caller that bypasses the DOM (as RTL's fireEvent does) must not be
    // able to start a new edit that has nowhere safe to land.
    if (leavingPendingRef.current.has(id)) return;
    const next = new Map(noteDraftsRef.current);
    next.set(id, value);
    noteDraftsRef.current = next;
    setNoteDraftsState(next);
    noteIntentRef.current.set(id, (noteIntentRef.current.get(id) ?? 0) + 1);
    clearNoteFailed(id);
  }, [clearNoteFailed]);
  // Defensive hygiene when a card leaves the tracker entirely (removed, or
  // dismissed and thereby hidden): an id can in principle be tracked again
  // later, and a stale leftover draft from a PRIOR tracking session must
  // never resurface as though it were typed in the new one.
  const clearNoteDraft = useCallback((id: string) => {
    if (!noteDraftsRef.current.has(id)) return;
    const next = new Map(noteDraftsRef.current);
    next.delete(id);
    noteDraftsRef.current = next;
    setNoteDraftsState(next);
  }, []);
  // Called once a REMOVE or dismiss-SET is CONFIRMED — the interaction row
  // is gone, so every piece of this id's notes-channel state (not just the
  // draft) is moot: an error/retry describes a row that no longer exists,
  // a baseline has nothing left to compare against, and any leftover busy
  // count would be a stale artifact (the write that set it necessarily
  // already resolved — see the leavingPending gating below for why a NEW
  // one can never start during this window). Leaving any of this behind
  // would be a silent per-id leak, not a visible bug, but a leak all the
  // same.
  const clearAllNotesStateFor = useCallback((id: string) => {
    clearNoteDraft(id);
    clearNoteFailed(id);
    if (noteBusyCountRef.current.has(id)) {
      noteBusyCountRef.current.delete(id);
      setNotesPendingIds(new Set(noteBusyCountRef.current.keys()));
    }
    noteIntentRef.current.delete(id);
    notesBaselineRef.current.delete(id);
  }, [clearNoteDraft, clearNoteFailed]);

  // Independent of identityGenerationRef: a manual retry() re-loads under
  // the SAME identity generation, so an old, slow load racing a fresh retry
  // would otherwise share the same generation number and be indistinguishable
  // from it. loadAttemptRef is bumped on every load() call regardless of
  // cause, so only the MOST RECENT attempt — old or new identity — may ever
  // apply its result.
  const loadAttemptRef = useRef(0);

  const load = useCallback((generation: number) => {
    const attempt = ++loadAttemptRef.current;
    const stale = () => identityGenerationRef.current !== generation || loadAttemptRef.current !== attempt;
    setLoading(true);
    setError(false);
    (async () => {
      try {
        const full = await getInteractionsFull();
        if (stale()) return;
        const ids = Array.from(full.keys());
        if (ids.length === 0) {
          itemsRef.current = [];
          setItems([]);
          unavailableItemsRef.current = [];
          setUnavailableItems([]);
          notesBaselineRef.current = new Map();
          setLoading(false);
          return;
        }
        // getShortlistOpportunities (not getOpportunitiesByIds) fails
        // CLOSED on any batch-accounting mismatch — a stale/duplicate/
        // malformed response throws instead of silently trusting a
        // partial result, and its own unavailableIds accounting is what
        // this hook relies on below rather than re-deriving a "missing"
        // set by hand.
        const { opportunities, unavailableIds } = await getShortlistOpportunities(ids);
        if (stale()) return;
        const opps = opportunities as unknown as Opp[];
        const byId = new Map(opps.map((o) => [o.id, o]));
        const unavailableIdSet = new Set(unavailableIds);
        const merged: TrackedItem[] = [];
        const unavailable: UnavailableTrackedItem[] = [];
        for (const [id, record] of full) {
          const opp = byId.get(id);
          if (opp) merged.push({ opp, record });
          // A dismissed interaction stays invisible even when its
          // opportunity is unavailable — surfacing it as a placeholder
          // would reintroduce something Tracker already hides everywhere
          // else (see TRACKER_COLUMNS below).
          else if (unavailableIdSet.has(id) && record.type !== 'dismissed') unavailable.push({ id, record });
          // else: neither resolved nor reported unavailable — a same-tick
          // race the contract itself already fails closed for; nothing to
          // do here since getShortlistOpportunities would have thrown.
        }
        itemsRef.current = merged;
        setItems(merged);
        unavailableItemsRef.current = unavailable;
        setUnavailableItems(unavailable);
        notesBaselineRef.current = new Map(merged.map((it) => [it.opp.id, normalizeNotes(it.record.notes)]));
        setLoading(false);
      } catch {
        if (stale()) return;
        setLoading(false);
        setError(true);
      }
    })();
  }, []);

  const retry = useCallback(() => {
    load(identityGenerationRef.current);
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    let liveEventSeen = false;
    let lastIdentity: string | null | undefined;

    function resetForIdentity() {
      const generation = ++identityGenerationRef.current;
      setIdentityGeneration(generation);
      itemsRef.current = [];
      setItems([]);
      unavailableItemsRef.current = [];
      setUnavailableItems([]);
      statusPendingRef.current = new Set();
      setStatusPendingIds(statusPendingRef.current);
      leavingPendingRef.current = new Set();
      setLeavingPendingIds(leavingPendingRef.current);
      statusErrorsRef.current = new Set();
      setStatusErrors(statusErrorsRef.current);
      statusRetryIntentRef.current = new Map();
      noteBusyCountRef.current = new Map();
      setNotesPendingIds(new Set());
      noteIntentRef.current = new Map();
      noteErrorsRef.current = new Set();
      setNotesErrors(noteErrorsRef.current);
      noteRetryDraftRef.current = new Map();
      noteDraftsRef.current = new Map();
      setNoteDraftsState(noteDraftsRef.current);
      notesBaselineRef.current = new Map();
      load(generation);
    }

    function applyIdentity(identity: string | null) {
      if (identity === lastIdentity) return; // not a real transition (e.g. TOKEN_REFRESHED re-reporting the same uid)
      lastIdentity = identity;
      resetForIdentity();
    }

    getAuthState().then((state) => {
      if (cancelled || liveEventSeen) return;
      applyIdentity(state.user?.id ?? null);
    }).catch(() => {
      if (cancelled || liveEventSeen) return;
      applyIdentity(null);
    });
    const unsubscribe = onAuthChange((state) => {
      if (cancelled) return;
      liveEventSeen = true;
      applyIdentity(state.user?.id ?? null);
    });
    return () => {
      cancelled = true;
      unsubscribe();
      identityGenerationRef.current += 1; // orphan any work still in flight
    };
  }, [load]);

  // The actual mutate+persist+rollback logic, taking an EXPLICIT op rather
  // than re-deriving set-vs-remove from current state — a retry must replay
  // the exact operation the user originally invoked. Re-deriving from
  // itemsRef.current at retry time would invert its meaning if the item's
  // status had since changed for any other reason (e.g. a direct click on a
  // different status before the user hit Retry on the stale failure).
  const performStatusOp = useCallback((id: string, op: StatusOp) => {
    if (statusPendingRef.current.has(id)) return;
    const generation = identityGenerationRef.current;
    const token = captureOwnerToken();
    const curIndex = itemsRef.current.findIndex((it) => it.opp.id === id);
    if (curIndex === -1) return;
    const prevItem = itemsRef.current[curIndex];
    // SET to 'dismissed' is pessimistic, exactly like REMOVE — 'dismissed'
    // is excluded from every pipeline column (TRACKER_COLUMNS), so applying
    // it optimistically would make the card vanish from the board before
    // the server ever confirmed the write, a fake-success bug. A failure
    // then leaves a card that was never actually changed — no rollback
    // needed, same as REMOVE.
    const isDismiss = op.kind === 'set' && op.type === 'dismissed';
    if (op.kind === 'set' && !isDismiss) {
      // Ordinary SET is optimistic — the card stays visible, just shows a
      // different status; a failure rolls back the `type` field in place.
      itemsRef.current = itemsRef.current.map((it) =>
        it.opp.id === id ? { ...it, record: { ...it.record, type: op.type } } : it,
      );
      setItems(itemsRef.current);
    }
    const isLeaving = op.kind === 'remove' || isDismiss;
    clearStatusFailed(id);
    addStatusPending(id);
    // Disables the notes textarea for exactly this window (see TrackerCard's
    // `leavingPending` prop) — the card is about to disappear/have its row
    // deleted, so a NEW edit started now has nowhere safe to land: it would
    // either be silently discarded by the post-success cleanup below, or
    // (if blurred) queue a write that fails once the row is already gone,
    // since every write for this opportunity id shares ONE serialized
    // queue (enqueuePrivateWrite). An ordinary SET never sets this — the
    // card is staying, and the textarea must remain editable throughout.
    if (isLeaving) addLeavingPending(id);
    (async () => {
      try {
        if (op.kind === 'remove') {
          await removeInteraction(id, token);
          if (identityGenerationRef.current !== generation || !mountedRef.current) return;
          itemsRef.current = itemsRef.current.filter((it) => it.opp.id !== id);
          setItems(itemsRef.current);
          // The row is gone — ANY notes-channel state for this id (not
          // just the draft) now describes something that no longer
          // exists: an error/retry with nothing left to retry against, a
          // baseline with nothing left to compare to. A dirty/failed
          // draft that existed BEFORE this op was invoked is discarded
          // here too, same as any other in-progress edit in a record the
          // user just chose to delete — the leavingPending gate above is
          // what guarantees nothing NEW could have raced in behind it.
          clearAllNotesStateFor(id);
        } else if (isDismiss) {
          // Dismissing does NOT delete the interaction row — it only hides
          // it from every Tracker column (TRACKER_COLUMNS excludes
          // 'dismissed'). The notes column on that row is still real,
          // persisted data, so an unsaved/dirty draft must NOT be silently
          // discarded the way a genuine REMOVE discards one.
          //
          // This MUST be ONE atomic call (dismissInteraction), not two
          // separately-awaited helpers (a notes flush then trackInteraction)
          // — chaining them left a real window: the second call is not even
          // INVOKED until the first one's promise resolves, so a DIFFERENT
          // surface acting on the SAME opportunity (e.g. the user hits Back
          // to /results mid-flush and clicks a different status there) could
          // enqueue its own write and land BETWEEN the two, only to be
          // overridden once the stale dismiss's second call finally got its
          // turn — and since that second call used to be trackInteraction
          // (an UPSERT), a REMOVE landing in that same window would have
          // been silently resurrected. dismissInteraction reserves its ONE
          // queue slot the instant it's invoked and uses UPDATE (never
          // upsert), so it structurally cannot resurrect a deleted row —
          // see supabase.ts for the full reasoning.
          const draft = noteDraftsRef.current.get(id) ?? prevItem.record.notes ?? '';
          // A flush is required not only when the draft differs from the
          // confirmed baseline, but ALSO whenever an EARLIER notes write
          // is still in flight (busyCount > 0) for this id — even if the
          // CURRENT draft happens to already equal the baseline. That
          // earlier write was dispatched with whatever content was current
          // THEN, which may differ from now; it shares the same per-id
          // queue, so it will land BEFORE this call regardless — and if we
          // omitted notes here, its stale content would become the final
          // persisted value with nothing left to correct it. Including the
          // CURRENT draft in this SAME atomic call always corrects for
          // this, landing right after that earlier write.
          const needsFlush = (noteBusyCountRef.current.get(id) ?? 0) > 0
            || normalizeNotes(notesBaselineRef.current.get(id)) !== normalizeNotes(draft);
          await dismissInteraction(id, needsFlush ? (draft.trim() || null) : undefined, token);
          if (identityGenerationRef.current !== generation || !mountedRef.current) return;
          if (needsFlush) {
            notesBaselineRef.current.set(id, normalizeNotes(draft));
            clearNoteFailed(id);
          }
          // Only now — confirmed — does the card actually leave the board.
          itemsRef.current = itemsRef.current.map((it) =>
            it.opp.id === id
              ? { ...it, record: { ...it.record, type: op.type, ...(needsFlush ? { notes: draft } : {}) } }
              : it,
          );
          setItems(itemsRef.current);
          // The row still exists — unlike REMOVE, notes-channel state is
          // NOT wiped (there is a real persisted value to keep tracking).
        } else {
          await trackInteraction(id, op.type, token);
        }
      } catch {
        if (identityGenerationRef.current === generation && mountedRef.current) {
          // Ordinary SET's rollback restores ONLY this id's `type` against
          // the CURRENT items — writes for other opportunities are
          // deliberately concurrent (not serialized against each other),
          // so a failure on THIS id must never erase a successful/
          // optimistic change already applied to a DIFFERENT one. REMOVE
          // and dismiss-SET need no rollback at all: nothing was changed yet
          // — and since the card never left, its notes-channel state (the
          // whole point of leavingPending) is left completely untouched.
          if (op.kind === 'set' && !isDismiss) {
            // Spreads the CURRENT record (not prevItem's) so a concurrent
            // notes save for this SAME id — never blocked against status,
            // see saveNotes — keeps its own newer value; only `type` reverts.
            itemsRef.current = itemsRef.current.map((it) =>
              it.opp.id === id ? { ...it, record: { ...it.record, type: prevItem.record.type } } : it,
            );
            setItems(itemsRef.current);
          }
          setStatusFailed(id, op); // exact same op, as data — never re-derived
        }
      } finally {
        if (identityGenerationRef.current === generation && mountedRef.current) {
          removeStatusPending(id);
          if (isLeaving) removeLeavingPending(id);
        }
      }
    })();
  }, [addStatusPending, removeStatusPending, addLeavingPending, removeLeavingPending, setStatusFailed, clearStatusFailed, clearAllNotesStateFor, clearNoteFailed]);

  const changeStatus = useCallback((id: string, type: InteractionType) => {
    const cur = itemsRef.current.find((it) => it.opp.id === id);
    if (!cur) return;
    // Re-selecting the active status clears it (untoggle semantics, same as
    // the per-card menu on /results) — decided ONCE here, at the moment of
    // the user's actual click, then fixed for the lifetime of this attempt
    // (including any retry of it).
    const op: StatusOp = cur.record.type === type
      ? { kind: 'remove', expectedType: type }
      : { kind: 'set', type };
    performStatusOp(id, op);
  }, [performStatusOp]);

  // The only action available on an unavailable placeholder: remove its
  // interaction row. Pessimistic (stays visible/pending until the remote
  // delete confirms — same reasoning as performStatusOp's REMOVE) and
  // shares the exclusive channel's pending/error state for a consistent
  // busy/disabled signal, but operates on unavailableItemsRef, not
  // itemsRef — there is no real opportunity to look up an index into.
  const clearUnavailable = useCallback((id: string) => {
    if (statusPendingRef.current.has(id)) return;
    const generation = identityGenerationRef.current;
    const token = captureOwnerToken();
    if (!unavailableItemsRef.current.some((u) => u.id === id)) return;
    clearStatusFailed(id);
    addStatusPending(id);
    (async () => {
      try {
        await removeInteraction(id, token);
        if (identityGenerationRef.current !== generation) return;
        unavailableItemsRef.current = unavailableItemsRef.current.filter((u) => u.id !== id);
        setUnavailableItems(unavailableItemsRef.current);
        clearAllNotesStateFor(id);
      } catch {
        if (identityGenerationRef.current === generation) setStatusFailed(id);
      } finally {
        if (identityGenerationRef.current === generation) removeStatusPending(id);
      }
    })();
  }, [addStatusPending, removeStatusPending, setStatusFailed, clearStatusFailed, clearAllNotesStateFor]);

  // Never gated by statusPendingRef, and never touches the exclusive
  // channel's pending/error state — see the module doc comment above for
  // why notes is a fully independent channel. A second (or third) call for
  // the SAME id is never blocked; every call proceeds and lands on the
  // remote row in invocation order via the shared write queue. Only the
  // invocation still holding the CURRENT per-id intent number when it
  // settles may touch the visible draft/error state.
  const saveNotes = useCallback((id: string, notes: string) => {
    // Fail-closed against leavingPending, not just via TrackerCard's
    // `disabled` attribute — see setNoteDraft's identical guard above for
    // why. A commit that raced in during this window would either be lost
    // to the post-confirmation cleanup or fail once the row is gone.
    if (leavingPendingRef.current.has(id)) return;
    const generation = identityGenerationRef.current;
    const intent = (noteIntentRef.current.get(id) ?? 0) + 1;
    noteIntentRef.current.set(id, intent);
    const cur = itemsRef.current.find((it) => it.opp.id === id);
    if (!cur) return;
    itemsRef.current = itemsRef.current.map((it) =>
      it.opp.id === id ? { ...it, record: { ...it.record, notes } } : it,
    );
    setItems(itemsRef.current);
    if (noteIntentRef.current.get(id) === intent) clearNoteFailed(id);

    // Nothing to persist when this exactly matches the last CONFIRMED value
    // AND nothing else is still in flight for this id. The in-flight guard
    // is load-bearing, not defensive: if a prior write for this id were
    // still pending, skipping here on baseline alone and later having that
    // prior write SUCCEED would silently move server truth away from what
    // the user just typed, with no write left queued to correct it back —
    // undetectable data loss. Only genuinely idle-and-unchanged skips.
    if (
      (noteBusyCountRef.current.get(id) ?? 0) === 0 &&
      normalizeNotes(notesBaselineRef.current.get(id)) === normalizeNotes(notes)
    ) {
      return;
    }

    const token = captureOwnerToken();
    incNoteBusy(id);
    (async () => {
      try {
        await updateInteractionDetails(id, { notes: notes.trim() || null }, token);
        // A successful write advances the CONFIRMED baseline regardless of
        // whether it's still the latest intent — a LATER edit that reverts
        // back to this value must be recognized as redundant too.
        if (identityGenerationRef.current === generation) {
          notesBaselineRef.current.set(id, normalizeNotes(notes));
        }
      } catch {
        // Silent-drop when EITHER identity has switched OR a newer notes
        // intent for this id has since been issued — in both cases this
        // failure belongs to an attempt the user has already moved past,
        // and must not roll back a newer draft or show an error for it.
        // "Only the latest intent may settle visible UI."
        if (identityGenerationRef.current === generation && noteIntentRef.current.get(id) === intent) {
          // Deliberately does NOT roll back the VISIBLE draft to the
          // baseline. A status change moves this card to a different
          // pipeline column, unmounting/remounting TrackerCard — a fresh
          // instance would then initialize its local textarea buffer from
          // whatever `items[id].record.notes` shows. Rolling back here
          // would silently swap the user's actual last-attempted text for
          // stale, already-confirmed content, while the error banner (and
          // a Retry that replays THIS exact failed draft, invisibly held
          // in noteRetryDraftRef) still references the ORIGINAL text — a
          // confusing display/retry mismatch. The failed text stays exactly
          // as shown; notesBaselineRef only ever gates whether a write is
          // attempted, never what is displayed.
          setNoteFailed(id, notes); // the raw draft, as data — never re-derived
        }
      } finally {
        if (identityGenerationRef.current === generation) decNoteBusy(id);
      }
    })();
  }, [incNoteBusy, decNoteBusy, setNoteFailed, clearNoteFailed]);

  const setReminder = useCallback((id: string, date: string | null) => {
    if (statusPendingRef.current.has(id)) return;
    const generation = identityGenerationRef.current;
    const token = captureOwnerToken();
    // An unavailable placeholder is a real interaction row the student owns —
    // it just has no resolvable opportunity this load. Clearing a reminder on
    // one has to work: the reminder is theirs, the corpus outage is ours, and
    // the cron will not send for an unresolved target anyway. Only the array
    // it lives in differs, so both branches share this single write path.
    const cur = itemsRef.current.find((it) => it.opp.id === id);
    const placeholder = cur
      ? undefined
      : unavailableItemsRef.current.find((u) => u.id === id);
    if (!cur && !placeholder) return;
    // Clearing is always allowed; scheduling is not. The UI already hides the
    // presets, but a hidden control is not a guarantee — this is the single
    // write path, and it is where the rule has to hold. A placeholder can
    // never be scheduled (the cron fails closed on an unresolved target), and
    // a resolved row only when the cron would actually send for it.
    if (date !== null) {
      if (placeholder) return;
      if (!canDeliverReminder(cur!.opp, cur!.record.type)) return;
    }
    const prevRemindAt = (cur ?? placeholder)!.record.remind_at;
    const applyRemindAt = (value: string | undefined) => {
      if (cur) {
        itemsRef.current = itemsRef.current.map((it) =>
          it.opp.id === id ? { ...it, record: { ...it.record, remind_at: value } } : it,
        );
        setItems(itemsRef.current);
        return;
      }
      unavailableItemsRef.current = unavailableItemsRef.current.map((u) =>
        u.id === id ? { ...u, record: { ...u.record, remind_at: value } } : u,
      );
      setUnavailableItems(unavailableItemsRef.current);
    };
    applyRemindAt(date ?? undefined);
    clearStatusFailed(id);
    addStatusPending(id);
    (async () => {
      try {
        await updateInteractionDetails(id, { remind_at: date }, token);
      } catch {
        if (identityGenerationRef.current === generation) {
          // Restore ONLY this id's remind_at against the CURRENT array —
          // writes for other opportunities (and even a concurrent notes
          // save for this SAME id, which is never blocked against the
          // exclusive channel) are never serialized against this one and
          // must not be clobbered by a whole-array snapshot rollback.
          applyRemindAt(prevRemindAt);
          setStatusFailed(id, { kind: 'reminder', date }); // as data — never re-derived
        }
      } finally {
        if (identityGenerationRef.current === generation) removeStatusPending(id);
      }
    })();
  }, [addStatusPending, removeStatusPending, setStatusFailed, clearStatusFailed]);

  const retryStatusItem = useCallback((id: string) => {
    const intent = statusRetryIntentRef.current.get(id);
    // A placeholder used to have exactly one possible action, so this branch
    // could dispatch clearUnavailable without consulting the intent. It now
    // has two: clearing its reminder can fail as well, and replaying THAT
    // failure as clearUnavailable would delete the whole interaction — the
    // student's status and notes with it — when all they asked for was to
    // drop a date. The stored intent decides.
    if (unavailableItemsRef.current.some((u) => u.id === id)) {
      if (intent?.kind === 'reminder') {
        setReminder(id, intent.date);
        return;
      }
      clearUnavailable(id);
      return;
    }
    if (!intent) return;
    if (intent.kind === 'reminder') {
      setReminder(id, intent.date);
    } else {
      performStatusOp(id, intent);
    }
  }, [performStatusOp, setReminder, clearUnavailable]);
  const retryNotesItem = useCallback((id: string) => {
    // Explicit guard (saveNotes below already fails closed on this too) —
    // a notes retry while a REMOVE/dismiss is in flight for this id would
    // either land after the row is gone or race the dismiss's own
    // final-draft flush. The error/Retry stays visible; the action itself
    // waits for the leave to fail (re-enabling it) or succeed (moot).
    if (leavingPendingRef.current.has(id)) return;
    const draft = noteRetryDraftRef.current.get(id);
    if (draft === undefined) return;
    saveNotes(id, draft);
  }, [saveNotes]);

  return {
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
  };
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
// the hide-from-results status, not a stage in the funnel.
//
// 'contacted' is the first stage and was missing entirely: the cold-email
// confirm-sent flow and the follow-up chips both write it, and the reminders
// cron sends for it — so a student who emailed a professor had a tracked row,
// a deliverable reminder, and no card anywhere on this board. Reaching out is
// where the funnel starts; it is not a footnote to applying.
export const TRACKER_COLUMNS: InteractionType[] = [
  'contacted',
  'applied',
  'replied',
  'interviewing',
  'rejected',
];
