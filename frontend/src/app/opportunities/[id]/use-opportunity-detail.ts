'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  getFavorites,
  toggleFavorite,
  trackInteraction,
  removeInteraction,
  getInteractionDetail,
  updateInteractionDetails,
  getAuthState,
  onAuthChange,
} from '@/lib/supabase';
import type { InteractionType, InteractionRecord } from '@/lib/supabase';
import { captureOwnerToken } from '@/lib/identity-owner';
import { track } from '@/lib/analytics';
import { suggestReminderForStatusChange, type ReminderSuggestion } from '@/lib/status-suggestions';
import { canDeliverReminder } from '@/lib/reminders';
import type { Opportunity } from '@/lib/types';

type StatusOp = { kind: 'set'; type: InteractionType } | { kind: 'remove' };

/** saveDetails' outcome: a caller (TrackerPanel) must never show "Saved"
 *  just because the promise resolved — 'abandoned' covers every case where
 *  nothing was actually persisted for the CURRENT context (no interaction
 *  yet, owner/read not ready, or the identity/target generation moved on
 *  before or after the write) and must be treated as a quiet no-op, never
 *  a success. A genuine failure for the current, still-applicable context
 *  throws instead. */
export type SaveDetailsResult = { status: 'committed' } | { status: 'abandoned' };

export interface UseOpportunityDetailResult {
  /** Bumps on every REAL identity transition (never a same-uid
   *  re-observation) for this mounted target. The page keys TrackerPanel by
   *  `${identityGeneration}:${opp.id}` — relying on interactionDetail
   *  merely passing through null between identities is not a robust
   *  guarantee that React unmounts a card sharing the same opportunity id
   *  across two accounts; the generation-qualified key forces a fresh
   *  instance explicitly, by construction. */
  identityGeneration: number;
  /** The exact CURRENT resolved uid, or null while unresolved (before the
   *  first identity observation, or the transient window between a
   *  sign-out and its replacement anon session). Callers that persist
   *  private, per-owner content (e.g. TailorModal's draft) key their
   *  storage by this exact value, never by ownerReady or the opportunity
   *  id alone — see ownerScopeKey in use-results-interactions.ts for the
   *  same contract. */
  ownerScopeKey: string | null;
  isFavorited: boolean;
  favoriteLoading: boolean;
  favoriteError: boolean;
  retryFavoriteHydration: () => void;
  favoriteSaving: boolean;
  favoriteSaveError: boolean;
  /** True once an owner identity has been resolved at least once for this
   *  target — private actions (star, status, notes/reminder save, Cold
   *  Email confirm) must stay disabled until this is true: capturing an
   *  owner token before any identity is known is never a safe first click,
   *  it's indistinguishable from a late arrival racing an intervening
   *  switch. See identity-owner.ts's isOwnerTokenValid contract. */
  ownerReady: boolean;
  interactionDetail: InteractionRecord | null;
  /** Records what the cold-email dialog just confirmed, so this page stops
   *  telling the student they have not tracked anything. */
  noteContactConfirmed: (record: InteractionRecord | null) => void;
  interaction: InteractionType | undefined;
  /** True until the interaction read for the CURRENT generation has
   *  settled (success or failure). A read failure must never be
   *  represented as "no interaction" — trackInteraction's upsert would
   *  then overwrite a real replied/interviewing/... row the UI simply
   *  failed to load. Status/notes actions stay disabled while this (or
   *  interactionError) is true. */
  interactionLoading: boolean;
  /** True when the interaction read failed — interactionDetail is NOT
   *  trustworthy while this is true (it still holds the hydration reset
   *  value, not a confirmed "no interaction"). Visible + retryable via
   *  retryInteractionHydration(), never silently treated as no-status. */
  interactionError: boolean;
  retryInteractionHydration: () => void;
  /** True while a status add/change/remove write is in flight — the pill
   *  UI must not show the new status as active until this settles
   *  successfully (pessimistic: no fake "persisted" state). */
  statusSaving: boolean;
  /** True after a status write fails — interactionDetail still reflects
   *  the last known-persisted value; retryTrack() replays the failed
   *  attempt. */
  statusError: boolean;
  retryTrack: () => void;
  emailModalOpen: boolean;
  setEmailModalOpen: (v: boolean) => void;
  shareCopied: boolean;
  chatDrawerOpen: boolean;
  setChatDrawerOpen: (v: boolean) => void;
  tailorOpen: boolean;
  setTailorOpen: (v: boolean) => void;
  renovationOpen: boolean;
  setRenovationOpen: (v: boolean) => void;
  suggestion: ReminderSuggestion | null;
  /** True while handleUseSuggestion's own save is in flight. */
  suggestionSaving: boolean;
  /** True after handleUseSuggestion's save genuinely fails — the
   *  suggestion stays visible (never cleared) so the user can retry the
   *  SAME action; see handleUseSuggestion. */
  suggestionError: boolean;
  handleStar: () => Promise<void>;
  handleTrack: (type: InteractionType) => Promise<void>;
  /** Resolves to a discriminated result — 'committed' only after the write
   *  actually persisted for the CURRENT context; 'abandoned' covers every
   *  precondition-not-met or generation-moved-on case (never shown as
   *  "Saved"). Rejects on a genuine failure for the current, still-
   *  applicable context so TrackerPanel can show an honest error + retry. */
  saveDetails: (patch: { notes?: string | null; remind_at?: string | null }) => Promise<SaveDetailsResult>;
  handleUseSuggestion: () => Promise<void>;
  handleDismissSuggestion: () => void;
  handleShare: () => Promise<void>;
}

/**
 * Target-local state (favorite, interaction, modals) is meant to be reset by
 * the CALLER remounting this hook's owner with `key={opp.id}` on an
 * opportunity switch — that gives a fresh initial-state render for free,
 * with no stale flash. This hook still reacts if `opp.id` changes on a live
 * instance (defense in depth for a caller that doesn't remount), but the
 * reset for that path — like every other reset here — is driven from an
 * async callback (auth event / fetch continuation), never synchronously
 * inside an effect body, so a real account switch mid-view is handled the
 * same way whether or not a remount already happened.
 *
 * Every private write (favorite toggle, status track/remove, notes/
 * reminder save) captures an OwnerToken via captureOwnerToken() at
 * invocation — before any optimistic UI update or await — and passes it to
 * the corresponding supabase.ts helper, which re-validates it against the
 * live identity before touching anything. ownerReady only flips true once
 * getFavorites' own ensureAnonSession() call has actually primed the
 * shared owner primitive (identity-owner.ts) — never synchronously at
 * hydration start — so a click can never capture the unprimed
 * {uid:null, epoch:0} sentinel, which is never a wildcard and would
 * spuriously fail the browser's very first legitimate write.
 *
 * An OwnerMismatchError (or any other failure) caught here is dropped
 * silently ONLY when the generation ref has ALSO since changed — that is
 * the actual, sole signal that a real hydrate() already reset this view
 * for a new target/identity and this result no longer applies to it. If
 * the generation is unchanged, the write genuinely failed for the context
 * the user is still looking at, and it is treated exactly like any other
 * failure: rollback / visible error / retry — an OwnerMismatchError is not
 * given special silent treatment on its own.
 */
// The truth fields are optional so the many callers/tests that pass only
// { id, title } keep compiling — but they are declared, because this hook now
// decides whether to OFFER a reminder, and that decision needs the same
// envelope every other surface reads. Absent fields resolve to a posture of
// `unknown`, which is the fail-closed answer: no suggestion.
type DetailTarget = {
  id: string;
  title: string;
  source_type?: string;
  record_kind?: string;
  target_truth?: Opportunity['target_truth'];
};

export function useOpportunityDetail(opp: DetailTarget): UseOpportunityDetailResult {
  const [isFavorited, setIsFavorited] = useState(false);
  const [favoriteLoading, setFavoriteLoading] = useState(true);
  const [favoriteError, setFavoriteError] = useState(false);
  const [favoriteSaving, setFavoriteSaving] = useState(false);
  const [favoriteSaveError, setFavoriteSaveError] = useState(false);
  const [ownerReady, setOwnerReady] = useState(false);
  const [interactionDetail, setInteractionDetail] = useState<InteractionRecord | null>(null);
  const [interactionLoading, setInteractionLoading] = useState(true);
  const [interactionError, setInteractionError] = useState(false);
  const [statusSaving, setStatusSaving] = useState(false);
  const [statusError, setStatusError] = useState(false);
  const [emailModalOpen, setEmailModalOpen] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);
  const [chatDrawerOpen, setChatDrawerOpen] = useState(false);
  const [tailorOpen, setTailorOpen] = useState(false);
  const [renovationOpen, setRenovationOpen] = useState(false);
  const [suggestion, setSuggestion] = useState<ReminderSuggestion | null>(null);
  const [suggestionSaving, setSuggestionSaving] = useState(false);
  const [suggestionError, setSuggestionError] = useState(false);
  // Reactive mirror of generationRef.current, exposed so the CALLER can key
  // TrackerPanel by it (`${identityGeneration}:${opp.id}`) — relying on
  // interactionDetail merely passing through null between identities is not
  // a robust guarantee that React unmounts a card sharing the same
  // opportunity id across two different accounts; the generation-qualified
  // key forces a fresh instance explicitly, by construction (same fix as
  // tracker/page.tsx's TrackerCard keying).
  const [identityGeneration, setIdentityGeneration] = useState(0);
  const [ownerScopeKey, setOwnerScopeKey] = useState<string | null>(null);
  // Target generation: bumped whenever a full (favorite + interaction + UI)
  // hydration pass starts, and on unmount. Guards handleShare and the
  // modal/UI-only resets.
  const generationRef = useRef(0);
  // Favorite generation: bumped by every hydration pass AND by an explicit
  // favorite-only retry. Guards the favorites fetch and handleStar — kept
  // separate from generationRef so a favorite retry can never touch
  // Tracker/modal state, and so a stale save can't roll back a fresher one.
  const favoriteGenerationRef = useRef(0);
  // Interaction generation: bumped by every hydration pass AND by an
  // explicit interaction-only retry. Guards the interaction fetch,
  // handleTrack, and saveDetails — kept separate so a status/notes write
  // can never be attributed to an abandoned interaction-read context, and
  // so an interaction-only retry can never touch favorite/modal state.
  const interactionGenerationRef = useRef(0);
  // The type a failed status write attempted — replayed by retryTrack().
  // The exact op a failed status write attempted, as DATA (never a
  // closure) — stored so retryTrack() replays the SAME set-vs-remove
  // decision, rather than re-deriving it from `interaction` at retry time,
  // which would invert its meaning if the status had since changed for any
  // other reason (see the identical fix in tracker/use-tracker-data.ts).
  const lastFailedTrackRef = useRef<StatusOp | null>(null);

  const interaction = interactionDetail?.type;

  // A suggestion already on screen when the target stops being deliverable —
  // a listing closing under an open detail page, or the student marking the
  // row rejected — has to go immediately, not wait to be refused on click.
  // The banner IS the claim: it says "set a reminder for this date", and
  // leaving it up while the handler quietly declines is the same false
  // capability the gates elsewhere remove. One-way on purpose: it clears, and
  // a target becoming deliverable again never resurrects it, because the
  // status transition that produced it is long past.
  // The latest target, readable after an await. `performStatusChange` fires a
  // network call and only then decides whether to produce a suggestion — by
  // which time a same-id rerender may have replaced the record with a closed
  // one. The captured `opp` in that closure is the old truth, and the boolean
  // effect below will not re-run for it, so the suggestion would appear with
  // nothing left to withdraw it.
  const latestOppRef = useRef(opp);
  useLayoutEffect(() => { latestOppRef.current = opp; }, [opp]);

  const reminderDeliverable = canDeliverReminder(opp, interaction);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- withdrawing a claim the page is currently making; it must land in the same commit the posture changes, not on the next interaction
    if (!reminderDeliverable) setSuggestion(null);
  }, [reminderDeliverable]);

  // Analytics fires once per distinct opportunity — independent of the
  // hydration/auth lifecycle below so an account switch mid-view doesn't
  // double-count the same "opened" event.
  useEffect(() => {
    track('match_opened', { opportunity_id: opp.id });
  }, [opp.id]);

  const fetchFavorites = useCallback((favoriteGeneration: number) => {
    getFavorites().then((set) => {
      if (favoriteGenerationRef.current !== favoriteGeneration) return; // stale — a newer favorite context is active
      setIsFavorited(set.has(opp.id));
      setFavoriteLoading(false);
      // getFavorites() unconditionally calls ensureAnonSession() as its own
      // first step, so by the time this resolves the shared owner
      // primitive has definitely been primed (or reconfirmed) — only NOW
      // is it safe to let a click capture a token that isn't the unprimed
      // {uid:null, epoch:0} sentinel, which is never a wildcard and would
      // spuriously reject the browser's very first legitimate write.
      setOwnerReady(true);
    }).catch(() => {
      if (favoriteGenerationRef.current !== favoriteGeneration) return;
      setFavoriteLoading(false);
      setFavoriteError(true);
      // Deliberately NOT setting ownerReady here: getFavorites() itself
      // never rejects (it degrades to the local fallback internally) —
      // this branch only exists defensively for an unexpected rejection,
      // which gives no guarantee ensureAnonSession ever ran to completion
      // and actually primed the shared primitive. Leave ownerReady false;
      // the existing Retry path (retryFavoriteHydration -> fetchFavorites)
      // is what gets another chance to prime it.
    });
  }, [opp.id]);

  // The cold-email dialog writes the contact row itself and re-checks the
  // token owner after its await, so this only has to stop the page
  // contradicting it: fetchInteraction runs on mount and on a real identity
  // change, and closing a modal is neither. Without it the panel says "Pick a
  // status above first" and disables the notes box for a contact just
  // recorded. No await here, so there is no generation window to guard: the
  // dialog's own post-await owner check is what decides whether this fires.
  const noteContactConfirmed = useCallback((record: InteractionRecord | null) => {
    if (!record) return;
    setInteractionDetail((d) => ({ ...(d ?? {}), ...record }));
  }, []);

  // A read failure here must NEVER be represented as "no interaction" —
  // interactionDetail stays at whatever hydrate()'s reset left it, and
  // interactionError is the explicit, separate signal that it is not
  // trustworthy. Without this, a failed read that silently resolved to
  // "no status" would let handleTrack's upsert overwrite a real
  // replied/interviewing/... row the UI simply failed to load.
  const fetchInteraction = useCallback((interactionGeneration: number) => {
    getInteractionDetail(opp.id).then((d) => {
      if (interactionGenerationRef.current !== interactionGeneration) return;
      setInteractionDetail(d); // explicit, including null — a genuine, confirmed absence
      setInteractionLoading(false);
    }).catch(() => {
      if (interactionGenerationRef.current !== interactionGeneration) return;
      setInteractionLoading(false);
      setInteractionError(true);
    });
  }, [opp.id]);

  // Full hydration pass for a (possibly new) target/account. Only ever
  // invoked from an async callback below (an auth event, or a fetch
  // continuation) — never synchronously from an effect body — so the resets
  // here are the React-endorsed "subscribe to an external system, setState
  // in its callback" pattern, not a same-tick effect-body write.
  const hydrate = useCallback((identity: string | null) => {
    const generation = ++generationRef.current;
    setIdentityGeneration(generation);
    setOwnerScopeKey(identity);
    const favoriteGeneration = ++favoriteGenerationRef.current;
    const interactionGeneration = ++interactionGenerationRef.current;

    setIsFavorited(false);
    setInteractionDetail(null);
    setInteractionLoading(true);
    setInteractionError(false);
    setStatusSaving(false);
    setStatusError(false);
    lastFailedTrackRef.current = null;
    setSuggestion(null);
    setSuggestionSaving(false);
    setSuggestionError(false);
    setFavoriteSaveError(false);
    setFavoriteSaving(false);
    setFavoriteLoading(true);
    setFavoriteError(false);
    setEmailModalOpen(false);
    setChatDrawerOpen(false);
    setShareCopied(false);
    setTailorOpen(false);
    setRenovationOpen(false);
    // Reset to false on EVERY hydration pass, not just the first: on a
    // U1->U2 switch the old true value would otherwise survive until the
    // new getFavorites() call settles, leaving a still-clickable handler
    // able to capture/write against the outgoing identity during the
    // transition window (same class of bug fixed in the favorites hook —
    // see use-favorites-data.ts). fetchFavorites flips it back to true only
    // once ITS OWN getFavorites() call for this generation (which always
    // primes the shared primitive via ensureAnonSession) has settled.
    setOwnerReady(false);

    fetchFavorites(favoriteGeneration);
    fetchInteraction(interactionGeneration);
  }, [fetchFavorites, fetchInteraction]);

  useEffect(() => {
    let cancelled = false;
    // A live onAuthChange event is always authoritative over this initial
    // snapshot — if the network-fetched getAuthState() resolves AFTER a
    // real event has already fired (e.g. it was slow, or a sign-in raced
    // it), applying it would overwrite the newer, correct identity with a
    // stale one.
    let liveEventSeen = false;
    // onAuthChange also fires for non-identity events (INITIAL_SESSION,
    // TOKEN_REFRESHED, ...), and the initial snapshot can resolve with the
    // same identity a live INITIAL_SESSION event already reported. Only an
    // actual identity change should hydrate — undefined is a real sentinel
    // here since the resolved identity is always `string | null`.
    let lastIdentity: string | null | undefined;
    function applyIdentity(identity: string | null) {
      if (identity === lastIdentity) return;
      lastIdentity = identity;
      hydrate(identity);
    }
    getAuthState().then((state) => {
      if (cancelled || liveEventSeen) return;
      applyIdentity(state.user?.id ?? null);
    }).catch(() => {
      if (cancelled || liveEventSeen) return;
      applyIdentity(null);
    });
    const unsubscribe = onAuthChange((state) => {
      // A queued callback can still fire once after cleanup requests
      // unsubscribe but before it takes effect — check cancelled first.
      if (cancelled) return;
      liveEventSeen = true;
      applyIdentity(state.user?.id ?? null);
    });
    return () => {
      cancelled = true;
      unsubscribe();
      // Unmount, or a newer target is about to hydrate its own generation —
      // either way, any work still in flight here must be treated as stale.
      // Intentionally reads/writes the refs' LIVE values, not a snapshot.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      generationRef.current++;
      // eslint-disable-next-line react-hooks/exhaustive-deps
      favoriteGenerationRef.current++;
      // eslint-disable-next-line react-hooks/exhaustive-deps
      interactionGenerationRef.current++;
    };
  }, [hydrate]);

  const retryFavoriteHydration = useCallback(() => {
    // Favorite-only: does not touch interactionDetail, suggestion, or any
    // modal/temp state — a user mid-edit on the Tracker panel must not lose
    // unsaved input just because they retried a failed favorite load.
    //
    // Fail-closed no-op while a save is genuinely in flight (or a previous
    // retry already is): bumping favoriteGeneration here would orphan that
    // save's own catch/finally (stale-generation-guarded), leaving
    // favoriteSaving stuck true forever with nothing left to clear it.
    // Racing a fresh read against an in-flight write is not a case worth
    // supporting — let the save settle on its own first.
    if (favoriteSaving || favoriteLoading) return;
    const favoriteGeneration = ++favoriteGenerationRef.current;
    setFavoriteLoading(true);
    setFavoriteError(false);
    fetchFavorites(favoriteGeneration);
  }, [fetchFavorites, favoriteSaving, favoriteLoading]);

  const retryInteractionHydration = useCallback(() => {
    // Interaction-only: mirrors retryFavoriteHydration — never touches
    // favorite/modal state, and is a fail-closed no-op while a status
    // write is genuinely in flight (bumping interactionGeneration then
    // would orphan that write's own generation-guarded catch/finally,
    // leaving statusSaving stuck true forever).
    if (statusSaving || interactionLoading) return;
    const interactionGeneration = ++interactionGenerationRef.current;
    setInteractionLoading(true);
    setInteractionError(false);
    fetchInteraction(interactionGeneration);
  }, [fetchInteraction, statusSaving, interactionLoading]);

  const handleStar = useCallback(async () => {
    // No overlapping saves, no toggling before the true state is known, and
    // — critically — no toggling off a hydration failure: favoriteError
    // means isFavorited is a fabricated default, not a fact, and the only
    // recovery path is the visible Retry, not a save built on that guess.
    if (!ownerReady || favoriteLoading || favoriteSaving || favoriteError) return;
    const favoriteGeneration = favoriteGenerationRef.current;
    const token = captureOwnerToken();
    const wasFav = isFavorited;
    setIsFavorited(!wasFav);
    setFavoriteSaving(true);
    setFavoriteSaveError(false);
    try {
      // toggleFavorite is allowed to resolve after a remote failure — it
      // falls back to a local-only write and still returns normally. That
      // is the supported degrade path (surfaced via StorageStatusBanner),
      // not an error; only an actual thrown exception rolls back here.
      await toggleFavorite(opp.id, wasFav, token);
    } catch {
      // A hydration/retry that started after this save began means this
      // save belongs to an abandoned favorite context — its rollback must
      // never land on whatever the fresher context's state is now. If the
      // generation is UNCHANGED, this is a genuine failure for the context
      // the user is still looking at (including an OwnerMismatchError that
      // fired despite ownerReady — never given silent special treatment on
      // its own) and must roll back visibly.
      if (favoriteGenerationRef.current !== favoriteGeneration) return;
      setIsFavorited(wasFav);
      setFavoriteSaveError(true);
    } finally {
      if (favoriteGenerationRef.current === favoriteGeneration) setFavoriteSaving(false);
    }
  }, [opp.id, isFavorited, ownerReady, favoriteLoading, favoriteSaving, favoriteError]);

  // The actual mutate+persist+rollback logic, taking an EXPLICIT op rather
  // than re-deriving set-vs-remove from current state — retryTrack must
  // replay the exact operation the user originally invoked. Re-deriving
  // from `interaction` at retry time would invert its meaning if the
  // status had since changed for any other reason (mirrors the identical
  // fix in tracker/use-tracker-data.ts's performStatusOp).
  const performStatusChange = useCallback(async (op: StatusOp) => {
    // interactionLoading/interactionError gate this: a still-loading or
    // failed-to-load interaction read means we do NOT actually know
    // whether a real status already exists — proceeding could upsert
    // 'applied' over a genuine replied/interviewing/... row the UI simply
    // failed to fetch. Wait for a confirmed read (including a confirmed
    // null) before any status write is possible. suggestionSaving is also
    // gated here — mutual exclusion with handleUseSuggestion (see there) —
    // so a status change can never race a suggestion-accept save for the
    // same interaction row.
    if (!ownerReady || interactionLoading || interactionError || statusSaving || suggestionSaving) return;
    const interactionGeneration = interactionGenerationRef.current;
    const token = captureOwnerToken();
    const prev = interaction;
    setStatusSaving(true);
    setStatusError(false);
    // A new status action supersedes any stale suggestion-save failure from
    // a previous status change — that suggestion may itself be about to be
    // replaced or cleared below, and its retry banner must not linger.
    setSuggestionError(false);
    try {
      if (op.kind === 'remove') {
        await removeInteraction(opp.id, token);
        if (interactionGenerationRef.current !== interactionGeneration) return;
        setInteractionDetail(null);
        setSuggestion(null);
      } else {
        await trackInteraction(opp.id, op.type, token);
        if (interactionGenerationRef.current !== interactionGeneration) return;
        // Only now — after persistence succeeds — does the UI present this
        // as the current status. No optimistic pre-write flip: a failed
        // write must never have been shown as active even briefly.
        setInteractionDetail((d) => ({
          ...(d ?? {}),
          type: op.type,
          last_contacted_at: new Date().toISOString(),
        }));
        // Always an explicit assignment, never a conditional no-op: a
        // status change that produces NO suggestion (suggestReminderForStatusChange
        // returns null for this transition) must CLEAR any suggestion left
        // over from an earlier status change — leaving it untouched would
        // show a suggestion banner for a transition that is no longer current.
        // Gated at generation, not just at display. This suggestion is a
        // one-click "Use this date" that writes a reminder directly — the
        // fastest path in the product to a reminder that will never be
        // delivered, because a replied/interviewing status on a closed
        // listing is exactly the transition it fires on. Offering it and
        // hiding the panel underneath would still leave the banner.
        // `latestOppRef`, not the captured `opp`: this runs after an await,
        // and the record may have been replaced under the same id while the
        // write was in flight. The status change itself still lands — that is
        // the student's own action — but a suggestion built on a truth that
        // is no longer current is a recommendation for a target that has
        // already gone.
        const next = interactionDetail?.remind_at
          || !canDeliverReminder(latestOppRef.current, op.type)
          ? null
          : suggestReminderForStatusChange(prev ?? null, op.type);
        setSuggestion(next ?? null);
      }
      lastFailedTrackRef.current = null;
    } catch {
      // See handleStar above: unchanged generation means a genuine
      // failure for the current context, shown regardless of error type.
      if (interactionGenerationRef.current !== interactionGeneration) return;
      lastFailedTrackRef.current = op; // exact same op, as data — never re-derived
      setStatusError(true);
    } finally {
      if (interactionGenerationRef.current === interactionGeneration) setStatusSaving(false);
    }
    // `opp` in full, not just its id: the suggestion gate reads its truth
    // envelope, so a stale record here would decide against a stale posture.
  }, [opp, interaction, interactionDetail, ownerReady, interactionLoading, interactionError, statusSaving, suggestionSaving]);

  const handleTrack = useCallback((type: InteractionType) => {
    // Re-selecting the active status clears it (untoggle semantics) —
    // decided ONCE here, at the moment of the user's actual click, then
    // fixed for the lifetime of this attempt (including any retry of it).
    return performStatusChange(interaction === type ? { kind: 'remove' } : { kind: 'set', type });
  }, [interaction, performStatusChange]);

  const retryTrack = useCallback(() => {
    if (lastFailedTrackRef.current) void performStatusChange(lastFailedTrackRef.current);
  }, [performStatusChange]);

  const saveDetails = useCallback(
    async (patch: { notes?: string | null; remind_at?: string | null }): Promise<SaveDetailsResult> => {
      // Notes/reminders attach to an existing status the user chose. Never
      // fabricate an 'applied' here — that would record an outreach event
      // (a "send") the user did not report. The TrackerPanel disables
      // auto-save and shows a pick-a-status hint until one exists.
      // interactionLoading/interactionError block this exactly like
      // performStatusChange — see there for why a not-yet-confirmed read
      // must never be written over.
      if (!interaction || !ownerReady || interactionLoading || interactionError) return { status: 'abandoned' };
      // The last gate before anything is persisted, checked at execution
      // time. TrackerPanel hides its date input and the suggestion banner
      // checks too, but this is the one function every reminder write on this
      // page passes through — a retained handler, a future caller, or a race
      // between the panel's debounce and a status change all arrive here.
      // Sanitized, not abandoned. A single patch can carry notes AND a date —
      // the panel's debounce assembles exactly that — and abandoning the whole
      // write would throw away notes the student typed because of a rule about
      // reminders. Only the non-null date is stripped; clearing (null) and
      // notes always travel. An emptied patch is a no-op, reported as
      // abandoned so no caller shows "Saved".
      let effective = patch;
      if (patch.remind_at != null && !canDeliverReminder(opp, interaction)) {
        const { remind_at: _dropped, ...rest } = patch;
        effective = rest;
        if (Object.keys(effective).length === 0) return { status: 'abandoned' };
      }
      const interactionGeneration = interactionGenerationRef.current;
      const token = captureOwnerToken();
      try {
        await updateInteractionDetails(opp.id, effective, token);
      } catch (err) {
        // Unchanged generation means a genuine failure for the current
        // context — rethrown regardless of error type (including an
        // OwnerMismatchError firing despite ownerReady) so TrackerPanel can
        // show an honest error + retry, never "Saved". A generation change
        // means this attempt was abandoned, not failed — the caller must
        // not surface an error for a context it has already moved past.
        if (interactionGenerationRef.current !== interactionGeneration) return { status: 'abandoned' };
        throw err;
      }
      if (interactionGenerationRef.current !== interactionGeneration) return { status: 'abandoned' };
      // Only now, after persistence succeeds, does the presented record
      // reflect the new notes/reminder — the caller's draft (local input
      // state) is separate and survives regardless of this outcome.
      setInteractionDetail((prev) => {
        const base: InteractionRecord = prev ?? { type: interaction };
        // From `effective`, not `patch`: a stripped date was never written,
        // so presenting it here would show the student a reminder that does
        // not exist on the server.
        return {
          ...base,
          notes: effective.notes === null ? undefined : effective.notes ?? base.notes,
          remind_at: effective.remind_at === null
            ? undefined
            : effective.remind_at ?? base.remind_at,
        };
      });
      return { status: 'committed' };
    },
    // `opp` in full, not `opp.id`. This callback now reads the truth envelope
    // to decide whether a reminder may be written, and a same-id record whose
    // truth changed (a listing closing under an open detail page) would
    // otherwise be judged against the posture captured at mount.
    [opp, interaction, ownerReady, interactionLoading, interactionError],
  );

  const handleUseSuggestion = useCallback(async () => {
    // Mutual exclusion with performStatusChange (see there): a status
    // change already in flight could itself be about to replace or clear
    // this exact suggestion, so accepting it concurrently is never safe.
    if (!suggestion || suggestionSaving || statusSaving) return;
    // Re-checked at the write, not only where the banner is produced. The
    // status can change under a visible suggestion (a second status write
    // lands, or the student marks it rejected), and this is the one place a
    // non-null reminder actually reaches the database from this page.
    if (!canDeliverReminder(opp, interaction)) {
      setSuggestion(null);
      return;
    }
    const date = suggestion.date;
    // Captured so a stale U1 completion landing after a U2 switch can never
    // touch U2's own, separately-started suggestionSaving/suggestionError —
    // this component instance is reused across an identity switch (it is
    // NOT remounted by opp.id alone), so without this guard a slow U1
    // attempt's finally{} would clobber a genuinely in-flight U2 attempt.
    const interactionGeneration = interactionGenerationRef.current;
    setSuggestionSaving(true);
    setSuggestionError(false);
    try {
      const result = await saveDetails({ remind_at: date });
      if (interactionGenerationRef.current !== interactionGeneration) return;
      // Only clear the suggestion once the write has actually committed —
      // an 'abandoned' result (precondition/generation moved on) means
      // nothing was persisted, so the suggestion must stay actionable
      // rather than silently vanish as if it had been applied.
      if (result.status === 'committed') setSuggestion(null);
    } catch {
      // A genuine failure for the current context — keep the suggestion
      // visible with a retry, never silently drop it (that would look like
      // the reminder was set when it was not).
      if (interactionGenerationRef.current !== interactionGeneration) return;
      setSuggestionError(true);
    } finally {
      if (interactionGenerationRef.current === interactionGeneration) setSuggestionSaving(false);
    }
    // Same reason as performStatusChange: the write-time re-check reads both.
  }, [suggestion, suggestionSaving, statusSaving, saveDetails, opp, interaction]);

  const handleDismissSuggestion = useCallback(() => {
    setSuggestion(null);
    setSuggestionError(false);
  }, []);

  const handleShare = useCallback(async () => {
    const generation = generationRef.current;
    const url = typeof window !== 'undefined' ? window.location.href : '';
    try {
      if (navigator.share) {
        await navigator.share({ title: opp.title, url });
      } else {
        await navigator.clipboard.writeText(url);
        if (generationRef.current !== generation) return; // target changed mid-copy — don't flash "Copied" on the new target's header
        setShareCopied(true);
        setTimeout(() => {
          if (generationRef.current === generation) setShareCopied(false);
        }, 2000);
      }
    } catch {
      /* user canceled */
    }
  }, [opp.title]);

  return {
    identityGeneration,
    ownerScopeKey,
    isFavorited,
    favoriteLoading,
    favoriteError,
    retryFavoriteHydration,
    favoriteSaving,
    favoriteSaveError,
    ownerReady,
    interactionDetail,
    interaction,
    noteContactConfirmed,
    interactionLoading,
    interactionError,
    retryInteractionHydration,
    statusSaving,
    statusError,
    retryTrack,
    emailModalOpen,
    setEmailModalOpen,
    shareCopied,
    chatDrawerOpen,
    setChatDrawerOpen,
    tailorOpen,
    setTailorOpen,
    renovationOpen,
    setRenovationOpen,
    // Gated at the boundary, synchronously. The state clear below is a
    // passive effect, so on its own it leaves one painted frame in which a
    // "Use this date" button is on screen for a target that just closed —
    // exactly the window a fast click lives in. Masking it here means the
    // banner is gone in the same render the posture changes; the state clear
    // still runs, so a target becoming deliverable again never resurrects a
    // suggestion whose triggering transition is long past.
    suggestion: reminderDeliverable ? suggestion : null,
    suggestionSaving,
    suggestionError,
    handleStar,
    handleTrack,
    saveDetails,
    handleUseSuggestion,
    handleDismissSuggestion,
    handleShare,
  };
}
