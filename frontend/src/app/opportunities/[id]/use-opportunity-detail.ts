'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
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
import { track } from '@/lib/analytics';
import { suggestReminderForStatusChange, type ReminderSuggestion } from '@/lib/status-suggestions';

export interface UseOpportunityDetailResult {
  isFavorited: boolean;
  favoriteLoading: boolean;
  favoriteError: boolean;
  retryFavoriteHydration: () => void;
  favoriteSaving: boolean;
  favoriteSaveError: boolean;
  interactionDetail: InteractionRecord | null;
  interaction: InteractionType | undefined;
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
  handleStar: () => Promise<void>;
  handleTrack: (type: InteractionType) => Promise<void>;
  saveDetails: (patch: { notes?: string | null; remind_at?: string | null }) => Promise<void>;
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
 */
export function useOpportunityDetail(opp: { id: string; title: string }): UseOpportunityDetailResult {
  const [isFavorited, setIsFavorited] = useState(false);
  const [favoriteLoading, setFavoriteLoading] = useState(true);
  const [favoriteError, setFavoriteError] = useState(false);
  const [favoriteSaving, setFavoriteSaving] = useState(false);
  const [favoriteSaveError, setFavoriteSaveError] = useState(false);
  const [interactionDetail, setInteractionDetail] = useState<InteractionRecord | null>(null);
  const [emailModalOpen, setEmailModalOpen] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);
  const [chatDrawerOpen, setChatDrawerOpen] = useState(false);
  const [tailorOpen, setTailorOpen] = useState(false);
  const [renovationOpen, setRenovationOpen] = useState(false);
  const [suggestion, setSuggestion] = useState<ReminderSuggestion | null>(null);
  // Target generation: bumped whenever a full (favorite + interaction + UI)
  // hydration pass starts, and on unmount. Guards handleTrack/handleShare
  // and the interaction fetch.
  const generationRef = useRef(0);
  // Favorite generation: bumped by every hydration pass AND by an explicit
  // favorite-only retry. Guards the favorites fetch and handleStar — kept
  // separate from generationRef so a favorite retry can never touch
  // Tracker/modal state, and so a stale save can't roll back a fresher one.
  const favoriteGenerationRef = useRef(0);

  const interaction = interactionDetail?.type;

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
    }).catch(() => {
      if (favoriteGenerationRef.current !== favoriteGeneration) return;
      setFavoriteLoading(false);
      setFavoriteError(true);
    });
  }, [opp.id]);

  // Full hydration pass for a (possibly new) target/account. Only ever
  // invoked from an async callback below (an auth event, or a fetch
  // continuation) — never synchronously from an effect body — so the resets
  // here are the React-endorsed "subscribe to an external system, setState
  // in its callback" pattern, not a same-tick effect-body write.
  const hydrate = useCallback(() => {
    const generation = ++generationRef.current;
    const favoriteGeneration = ++favoriteGenerationRef.current;

    setIsFavorited(false);
    setInteractionDetail(null);
    setSuggestion(null);
    setFavoriteSaveError(false);
    setFavoriteSaving(false);
    setFavoriteLoading(true);
    setFavoriteError(false);
    setEmailModalOpen(false);
    setChatDrawerOpen(false);
    setShareCopied(false);
    setTailorOpen(false);
    setRenovationOpen(false);

    fetchFavorites(favoriteGeneration);

    getInteractionDetail(opp.id).then((d) => {
      if (generationRef.current !== generation) return;
      setInteractionDetail(d); // explicit, including null — never leans on the reset above to represent "no interaction"
    }).catch(() => {});
  }, [opp.id, fetchFavorites]);

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
      hydrate();
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

  const handleStar = useCallback(async () => {
    // No overlapping saves, no toggling before the true state is known, and
    // — critically — no toggling off a hydration failure: favoriteError
    // means isFavorited is a fabricated default, not a fact, and the only
    // recovery path is the visible Retry, not a save built on that guess.
    if (favoriteLoading || favoriteSaving || favoriteError) return;
    const favoriteGeneration = favoriteGenerationRef.current;
    const wasFav = isFavorited;
    setIsFavorited(!wasFav);
    setFavoriteSaving(true);
    setFavoriteSaveError(false);
    try {
      // toggleFavorite is allowed to resolve after a remote failure — it
      // falls back to a local-only write and still returns normally. That
      // is the supported degrade path (surfaced via StorageStatusBanner),
      // not an error; only an actual thrown exception rolls back here.
      await toggleFavorite(opp.id, wasFav);
    } catch {
      // A hydration/retry that started after this save began means this
      // save belongs to an abandoned favorite context — its rollback must
      // never land on whatever the fresher context's state is now.
      if (favoriteGenerationRef.current !== favoriteGeneration) return;
      setIsFavorited(wasFav);
      setFavoriteSaveError(true);
    } finally {
      if (favoriteGenerationRef.current === favoriteGeneration) setFavoriteSaving(false);
    }
  }, [opp.id, isFavorited, favoriteLoading, favoriteSaving, favoriteError]);

  const handleTrack = useCallback(async (type: InteractionType) => {
    const generation = generationRef.current;
    const prev = interaction;
    if (prev === type) {
      setInteractionDetail(null);
      setSuggestion(null);
      await removeInteraction(opp.id).catch(() => {});
      return;
    }
    setInteractionDetail((d) => ({
      ...(d ?? {}),
      type,
      last_contacted_at: new Date().toISOString(),
    }));
    await trackInteraction(opp.id, type).catch(() => {});

    if (generationRef.current !== generation) return; // target/account changed mid-flight — don't drop a suggestion onto the new target
    if (!interactionDetail?.remind_at) {
      const next = suggestReminderForStatusChange(prev ?? null, type);
      if (next) setSuggestion(next);
    }
  }, [opp.id, interaction, interactionDetail?.remind_at]);

  const saveDetails = useCallback(
    async (patch: { notes?: string | null; remind_at?: string | null }) => {
      // Notes/reminders attach to an existing status the user chose. Never
      // fabricate an 'applied' here — that would record an outreach event
      // (a "send") the user did not report. The TrackerPanel disables
      // auto-save and shows a pick-a-status hint until one exists.
      if (!interaction) return;
      setInteractionDetail((prev) => {
        const base: InteractionRecord = prev ?? { type: interaction };
        return {
          ...base,
          notes: patch.notes === null ? undefined : patch.notes ?? base.notes,
          remind_at: patch.remind_at === null ? undefined : patch.remind_at ?? base.remind_at,
        };
      });
      await updateInteractionDetails(opp.id, patch).catch(() => {});
    },
    [opp.id, interaction],
  );

  const handleUseSuggestion = useCallback(async () => {
    if (!suggestion) return;
    const date = suggestion.date;
    setSuggestion(null);
    await saveDetails({ remind_at: date });
  }, [suggestion, saveDetails]);

  const handleDismissSuggestion = useCallback(() => setSuggestion(null), []);

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
    isFavorited,
    favoriteLoading,
    favoriteError,
    retryFavoriteHydration,
    favoriteSaving,
    favoriteSaveError,
    interactionDetail,
    interaction,
    emailModalOpen,
    setEmailModalOpen,
    shareCopied,
    chatDrawerOpen,
    setChatDrawerOpen,
    tailorOpen,
    setTailorOpen,
    renovationOpen,
    setRenovationOpen,
    suggestion,
    handleStar,
    handleTrack,
    saveDetails,
    handleUseSuggestion,
    handleDismissSuggestion,
    handleShare,
  };
}
