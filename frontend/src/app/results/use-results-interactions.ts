'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getAuthState,
  getFavorites,
  getInteractions,
  onAuthChange,
  removeInteraction,
  toggleFavorite,
  trackInteraction,
  type InteractionType,
} from '@/lib/supabase';
import { captureOwnerToken } from '@/lib/identity-owner';

// The exact operation a favorite/status write attempted — captured as DATA
// at the moment of the ORIGINAL user action (or a prior retry), never
// re-derived from current UI state. A retry replays exactly this, so it can
// never silently diverge from what the user actually asked for even if
// something else touched the same id in between the failure and the retry
// (see retryFavSave/retryTrackSave below). Mirrors the same "retry-as-data,
// not-recomputed-closure" pattern already established for Tracker's
// performStatusOp/retryStatusItem (use-tracker-data.ts).
type FavIntent = { kind: 'add' } | { kind: 'remove' };
type StatusIntent = { kind: 'set'; type: InteractionType } | { kind: 'remove'; type: InteractionType };

export interface UseResultsInteractionsResult {
  favs: Set<string>;
  interactions: Map<string, InteractionType>;
  /** True once getFavorites() has primed the shared owner primitive for the
   *  CURRENT identity generation — see identity-owner.ts. A click before
   *  this is true would capture the unprimed {uid:null, epoch:0} sentinel,
   *  which is never a wildcard. */
  ownerReady: boolean;
  /** Bumps ONLY on a REAL uid transition (the very first identity
   *  resolution counts; a same-uid re-observation — e.g. TOKEN_REFRESHED —
   *  is a no-op). Never derived from ownerReady (which can flip false->true
   *  more than once WITHIN one identity, e.g. a load failure + retry) or
   *  from any opportunity id. Callers that need to force-remount/destroy
   *  identity-scoped local UI state (e.g. a card's own Tailor draft) on a
   *  real identity change — but preserve it across a benign same-uid
   *  rerender — must key on this, not on ownerReady. */
  identityGeneration: number;
  /** The exact CURRENT resolved uid, or null while unresolved (before the
   *  very first identity observation, or the transient window between a
   *  sign-out and its replacement anon session). NOT a boolean — callers
   *  that persist private, per-owner content (e.g. a Tailor draft) key
   *  their storage by this exact value, never by ownerReady or an
   *  opportunity id alone. A null value means there is no safe scope to
   *  persist under; such content must stay ephemeral (in-memory only). */
  ownerScopeKey: string | null;
  /** True until the bulk favorites read for the CURRENT generation has
   *  settled (success or failure). */
  favoritesLoading: boolean;
  /** True when the bulk favorites read failed — ownerReady stays false (and
   *  every owner write stays disabled) until a retry for this SAME
   *  generation succeeds; see retryFavoritesLoad. */
  favoritesLoadError: boolean;
  retryFavoritesLoad: () => void;
  /** True until the bulk interaction read for the CURRENT generation has
   *  settled. A read failure must never be treated as "no interactions" —
   *  a track/dismiss write built on that false-empty map could upsert over
   *  a real status the read simply failed to surface. */
  interactionsLoading: boolean;
  interactionsError: boolean;
  /** Opportunity ids whose LATEST favorite/status write attempt failed —
   *  per-id, never a single global slot: a second id's start/success/
   *  failure must never clear or overwrite a DIFFERENT id's still-visible
   *  error. Render each at its own card, not one page-level ambiguous
   *  retry. */
  favSaveErrors: Set<string>;
  trackSaveErrors: Set<string>;
  /** Opportunity ids with a favorite write currently in flight — the ONLY
   *  thing that actually prevents a same-tick double-click race (checked
   *  synchronously via a ref before the ref-mirroring state below even
   *  re-renders); exposed as state so callers can disable the control. */
  pendingFavIds: Set<string>;
  pendingTrackIds: Set<string>;
  handleToggleFav: (opportunityId: string) => Promise<void>;
  handleTrackInteraction: (opportunityId: string, type: InteractionType) => Promise<void>;
  /** Replays the EXACT captured intent behind that id's failed write — an
   *  add stays an add, a remove stays a remove, a SET(type) stays that same
   *  SET, a REMOVE calls removeInteraction again and never trackInteraction
   *  — never recomputed from whatever the UI happens to show now. */
  retryFavSave: (opportunityId: string) => void;
  retryTrackSave: (opportunityId: string) => void;
  retryInteractionsLoad: () => void;
}

/**
 * Owns the results page's favorite/interaction bulk state, bound to the
 * live identity via the same owner-token/generation contract already
 * established in use-opportunity-detail.ts and use-favorites-data.ts,
 * generalized here to a LIST of opportunities rather than one target:
 *
 *   - identityGenerationRef bumps on every REAL uid change observed via
 *     onAuthChange (never on a same-uid re-observation like
 *     TOKEN_REFRESHED) and resets favs/interactions/ownerReady/pending
 *     state, then re-hydrates for the new identity. A hydration or write
 *     completion whose captured generation no longer matches is dropped —
 *     it belongs to an identity this view has already moved on from. This
 *     is what makes a U1 read that resolves AFTER a live U1->U2 switch
 *     safe: it can never overwrite U2's freshly-reset state.
 *   - pendingFavIds/pendingTrackIds (backed by a REF checked synchronously,
 *     before any await) are a per-opportunity in-flight guard: a second
 *     click on the SAME id while its own write is still resolving is a
 *     fail-closed no-op, not a second overlapping mutation. This is what
 *     actually prevents a same-tick double-click race — not just careful
 *     ref timing.
 *   - favsRef/interactionsRef mirror the corresponding state SYNCHRONOUSLY
 *     at every mutation site (never via a separate useEffect, which lags by
 *     a render+effect cycle) so two reads issued in the same tick always
 *     see the same, current value.
 *   - favSaveErrors/trackSaveErrors are PER-OPPORTUNITY (Set<string>, backed
 *     by a ref-held retry-intent Map keyed the same way) — a failure on id A
 *     must remain visible and independently retryable no matter what
 *     succeeds or fails for a DIFFERENT id B afterward. The retry intent is
 *     captured as data at the moment of the attempt (add/remove for
 *     favorites, SET(type)/REMOVE for status) and replayed verbatim by
 *     retryFavSave/retryTrackSave — never recomputed from favsRef/
 *     interactionsRef at retry time, which could have drifted if some other
 *     action touched the same id between the failure and the retry.
 */
export function useResultsInteractions(onIdentityChange?: () => void): UseResultsInteractionsResult {
  const [favs, setFavs] = useState<Set<string>>(new Set());
  const favsRef = useRef(favs);
  const [interactions, setInteractions] = useState<Map<string, InteractionType>>(new Map());
  const interactionsRef = useRef(interactions);
  const [ownerReady, setOwnerReady] = useState(false);
  const [identityGeneration, setIdentityGeneration] = useState(0);
  const [ownerScopeKey, setOwnerScopeKey] = useState<string | null>(null);
  const [favoritesLoading, setFavoritesLoading] = useState(true);
  const [favoritesLoadError, setFavoritesLoadError] = useState(false);
  const [interactionsLoading, setInteractionsLoading] = useState(true);
  const [interactionsError, setInteractionsError] = useState(false);
  const favSaveErrorsRef = useRef<Set<string>>(new Set());
  const [favSaveErrors, setFavSaveErrors] = useState<Set<string>>(new Set());
  const favRetryIntentRef = useRef<Map<string, FavIntent>>(new Map());
  const trackSaveErrorsRef = useRef<Set<string>>(new Set());
  const [trackSaveErrors, setTrackSaveErrors] = useState<Set<string>>(new Set());
  const trackRetryIntentRef = useRef<Map<string, StatusIntent>>(new Map());
  const pendingFavIdsRef = useRef<Set<string>>(new Set());
  const [pendingFavIds, setPendingFavIds] = useState<Set<string>>(new Set());
  const pendingTrackIdsRef = useRef<Set<string>>(new Set());
  const [pendingTrackIds, setPendingTrackIds] = useState<Set<string>>(new Set());

  const identityGenerationRef = useRef(0);
  // Always the latest onIdentityChange, refreshed every render via a
  // no-deps effect (never assigned during render itself — see
  // use-favorites-data.ts for the same pattern) so the mount-once effect
  // below never closes over a stale callback without needing to re-run.
  const onIdentityChangeRef = useRef(onIdentityChange);
  useEffect(() => {
    onIdentityChangeRef.current = onIdentityChange;
  });

  const addPendingFav = useCallback((id: string) => {
    const next = new Set(pendingFavIdsRef.current).add(id);
    pendingFavIdsRef.current = next;
    setPendingFavIds(next);
  }, []);
  const removePendingFav = useCallback((id: string) => {
    if (!pendingFavIdsRef.current.has(id)) return;
    const next = new Set(pendingFavIdsRef.current);
    next.delete(id);
    pendingFavIdsRef.current = next;
    setPendingFavIds(next);
  }, []);
  const addPendingTrack = useCallback((id: string) => {
    const next = new Set(pendingTrackIdsRef.current).add(id);
    pendingTrackIdsRef.current = next;
    setPendingTrackIds(next);
  }, []);
  const removePendingTrack = useCallback((id: string) => {
    if (!pendingTrackIdsRef.current.has(id)) return;
    const next = new Set(pendingTrackIdsRef.current);
    next.delete(id);
    pendingTrackIdsRef.current = next;
    setPendingTrackIds(next);
  }, []);

  const setFavFailed = useCallback((id: string, intent: FavIntent) => {
    favRetryIntentRef.current.set(id, intent);
    const next = new Set(favSaveErrorsRef.current).add(id);
    favSaveErrorsRef.current = next;
    setFavSaveErrors(next);
  }, []);
  const clearFavFailed = useCallback((id: string) => {
    if (!favSaveErrorsRef.current.has(id)) return;
    favRetryIntentRef.current.delete(id);
    const next = new Set(favSaveErrorsRef.current);
    next.delete(id);
    favSaveErrorsRef.current = next;
    setFavSaveErrors(next);
  }, []);
  const setTrackFailed = useCallback((id: string, intent: StatusIntent) => {
    trackRetryIntentRef.current.set(id, intent);
    const next = new Set(trackSaveErrorsRef.current).add(id);
    trackSaveErrorsRef.current = next;
    setTrackSaveErrors(next);
  }, []);
  const clearTrackFailed = useCallback((id: string) => {
    if (!trackSaveErrorsRef.current.has(id)) return;
    trackRetryIntentRef.current.delete(id);
    const next = new Set(trackSaveErrorsRef.current);
    next.delete(id);
    trackSaveErrorsRef.current = next;
    setTrackSaveErrors(next);
  }, []);

  // Per-channel latest-attempt epoch, independent of identityGenerationRef:
  // a manual retry re-loads under the SAME identity generation, so an
  // older, slower in-flight request racing a newer retry would otherwise
  // share the same generation number and be indistinguishable from it —
  // the identity-generation check alone cannot tell "abandoned identity"
  // apart from "superseded same-identity attempt". Bumped on every
  // load*() call regardless of cause (initial hydrate or retry), so only
  // the MOST RECENT attempt for the current identity may ever apply its
  // result to loading/error/data/ownerReady — deterministic by INVOCATION
  // order, not by which network call happens to resolve first. Mirrors
  // use-tracker-data.ts's loadAttemptRef.
  const favoritesAttemptRef = useRef(0);
  const interactionsAttemptRef = useRef(0);

  const loadFavorites = useCallback((generation: number) => {
    const attempt = ++favoritesAttemptRef.current;
    const stale = () => identityGenerationRef.current !== generation || favoritesAttemptRef.current !== attempt;
    setFavoritesLoading(true);
    setFavoritesLoadError(false);
    getFavorites()
      .then((d) => {
        if (stale()) return; // a newer identity OR a newer same-identity retry has superseded this attempt
        favsRef.current = d;
        setFavs(d);
        setOwnerReady(true);
        setFavoritesLoading(false);
      })
      .catch(() => {
        // getFavorites() itself never rejects in practice (it degrades to
        // the local fallback internally) — this branch exists defensively
        // for an unexpected rejection, which gives no guarantee
        // ensureAnonSession ever primed the shared owner primitive.
        // ownerReady stays false — every owner write stays disabled — until
        // a retry for this SAME generation succeeds; see
        // retryFavoritesLoad. Never touch state for a superseded attempt:
        // an abandoned identity's late rejection must not paint the new
        // identity's screen, and an OLDER same-identity retry's late
        // rejection must not overwrite a NEWER retry's already-applied
        // success (or vice versa).
        if (stale()) return;
        setFavoritesLoading(false);
        setFavoritesLoadError(true);
      });
  }, []);

  const retryFavoritesLoad = useCallback(() => {
    loadFavorites(identityGenerationRef.current);
  }, [loadFavorites]);

  const loadInteractions = useCallback((generation: number) => {
    const attempt = ++interactionsAttemptRef.current;
    const stale = () => identityGenerationRef.current !== generation || interactionsAttemptRef.current !== attempt;
    setInteractionsLoading(true);
    setInteractionsError(false);
    getInteractions()
      .then((d) => {
        if (stale()) return;
        interactionsRef.current = d;
        setInteractions(d);
        setInteractionsLoading(false);
      })
      .catch(() => {
        if (stale()) return;
        setInteractionsLoading(false);
        setInteractionsError(true);
      });
  }, []);

  const retryInteractionsLoad = useCallback(() => {
    loadInteractions(identityGenerationRef.current);
  }, [loadInteractions]);

  useEffect(() => {
    let cancelled = false;
    // A live onAuthChange event is always authoritative over the initial
    // getAuthState() snapshot — see use-opportunity-detail.ts for why.
    let liveEventSeen = false;
    let lastIdentity: string | null | undefined;
    // The first identity resolution is a normal hydration, not a "switch" —
    // onIdentityChange (used by the caller to e.g. close a write-capable
    // modal) must fire only for a REAL subsequent transition.
    let isFirstIdentity = true;

    function resetForIdentity(identity: string | null) {
      const generation = ++identityGenerationRef.current;
      const wasFirst = isFirstIdentity;
      isFirstIdentity = false;
      setIdentityGeneration(generation);
      setOwnerScopeKey(identity);
      setOwnerReady(false);
      favsRef.current = new Set();
      setFavs(favsRef.current);
      interactionsRef.current = new Map();
      setInteractions(interactionsRef.current);
      setFavoritesLoading(true);
      setFavoritesLoadError(false);
      setInteractionsLoading(true);
      setInteractionsError(false);
      favSaveErrorsRef.current = new Set();
      setFavSaveErrors(favSaveErrorsRef.current);
      favRetryIntentRef.current = new Map();
      trackSaveErrorsRef.current = new Set();
      setTrackSaveErrors(trackSaveErrorsRef.current);
      trackRetryIntentRef.current = new Map();
      pendingFavIdsRef.current = new Set();
      setPendingFavIds(pendingFavIdsRef.current);
      pendingTrackIdsRef.current = new Set();
      setPendingTrackIds(pendingTrackIdsRef.current);
      if (!wasFirst) onIdentityChangeRef.current?.();
      loadFavorites(generation);
      loadInteractions(generation);
    }

    function applyIdentity(identity: string | null) {
      if (identity === lastIdentity) return; // not a real transition (e.g. TOKEN_REFRESHED re-reporting the same uid)
      lastIdentity = identity;
      resetForIdentity(identity);
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
  }, [loadFavorites, loadInteractions]);

  // The actual mutate+persist+rollback logic, taking an EXPLICIT intent
  // rather than re-deriving add-vs-remove from current state — a retry must
  // replay the exact operation the user originally invoked, not whatever
  // favsRef happens to show by the time the retry runs (which could have
  // drifted if some other click touched this same id in between).
  const performFavOp = useCallback(async (oppId: string, intent: FavIntent) => {
    if (!ownerReady || pendingFavIdsRef.current.has(oppId)) return;
    const generation = identityGenerationRef.current;
    const token = captureOwnerToken();
    const wasFaved = intent.kind === 'remove';
    const applyFaved = (s: Set<string>, faved: boolean) => {
      const next = new Set(s);
      if (faved) next.add(oppId); else next.delete(oppId);
      return next;
    };
    favsRef.current = applyFaved(favsRef.current, !wasFaved);
    setFavs(favsRef.current);
    clearFavFailed(oppId);
    addPendingFav(oppId);
    try {
      // toggleFavorite is allowed to resolve after a remote failure — it
      // falls back to a local-only write and still returns normally (the
      // supported degrade, surfaced via StorageStatusBanner). Only an
      // actual thrown exception rolls back here.
      await toggleFavorite(oppId, wasFaved, token);
    } catch {
      // Silent-drop only when the generation has genuinely moved on (a real
      // identity switch reset this state already, including this same
      // oppId's optimistic flip) — otherwise this is a real failure for the
      // context still on screen and must roll back visibly. A DIFFERENT
      // id's own error/pending is untouched — this only ever writes oppId's
      // own entry in the per-id map.
      if (identityGenerationRef.current === generation) {
        favsRef.current = applyFaved(favsRef.current, wasFaved); // restore the pre-attempt state
        setFavs(favsRef.current);
        setFavFailed(oppId, intent);
      }
    } finally {
      // Only clear PENDING for the generation this write was invoked under.
      // If identity has since switched (a real U1->U2 transition) and the
      // new identity has ALREADY started its own write for this same
      // oppId, this stale U1 completion — success OR failure — must not
      // clear U2's legitimate in-flight flag; resetForIdentity already gave
      // this generation a fresh (empty) pending set, and U2's own
      // addPendingFav owns whatever is in it now.
      if (identityGenerationRef.current === generation) removePendingFav(oppId);
    }
  }, [ownerReady, addPendingFav, removePendingFav, setFavFailed, clearFavFailed]);

  const handleToggleFav = useCallback((oppId: string) => {
    const wasFaved = favsRef.current.has(oppId);
    return performFavOp(oppId, wasFaved ? { kind: 'remove' } : { kind: 'add' });
  }, [performFavOp]);

  const retryFavSave = useCallback((oppId: string) => {
    const intent = favRetryIntentRef.current.get(oppId);
    if (!intent) return;
    void performFavOp(oppId, intent);
  }, [performFavOp]);

  const performTrackOp = useCallback(async (oppId: string, intent: StatusIntent) => {
    if (!ownerReady || interactionsLoading || interactionsError) return;
    if (pendingTrackIdsRef.current.has(oppId)) return;
    const generation = identityGenerationRef.current;
    const token = captureOwnerToken();
    const prevValue = interactionsRef.current.get(oppId);
    const applyValue = (m: Map<string, InteractionType>, val: InteractionType | undefined) => {
      const next = new Map(m);
      if (val === undefined) next.delete(oppId);
      else next.set(oppId, val);
      return next;
    };
    const nextValue = intent.kind === 'remove' ? undefined : intent.type;
    interactionsRef.current = applyValue(interactionsRef.current, nextValue);
    setInteractions(interactionsRef.current);
    clearTrackFailed(oppId);
    addPendingTrack(oppId);
    try {
      if (intent.kind === 'remove') {
        await removeInteraction(oppId, token);
      } else {
        await trackInteraction(oppId, intent.type, token);
      }
    } catch {
      if (identityGenerationRef.current === generation) {
        interactionsRef.current = applyValue(interactionsRef.current, prevValue);
        setInteractions(interactionsRef.current);
        setTrackFailed(oppId, intent);
      }
    } finally {
      // See performFavOp above — same cross-generation contamination guard,
      // so a stale write from an abandoned identity never clears a newer
      // identity's legitimate pending flag for the same oppId.
      if (identityGenerationRef.current === generation) removePendingTrack(oppId);
    }
  }, [ownerReady, interactionsLoading, interactionsError, addPendingTrack, removePendingTrack, setTrackFailed, clearTrackFailed]);

  const handleTrackInteraction = useCallback((oppId: string, type: InteractionType) => {
    const current = interactionsRef.current.get(oppId);
    const isRemoving = current === type;
    return performTrackOp(oppId, isRemoving ? { kind: 'remove', type } : { kind: 'set', type });
  }, [performTrackOp]);

  const retryTrackSave = useCallback((oppId: string) => {
    const intent = trackRetryIntentRef.current.get(oppId);
    if (!intent) return;
    void performTrackOp(oppId, intent);
  }, [performTrackOp]);

  return {
    favs,
    interactions,
    ownerReady,
    identityGeneration,
    ownerScopeKey,
    favoritesLoading,
    favoritesLoadError,
    retryFavoritesLoad,
    interactionsLoading,
    interactionsError,
    favSaveErrors,
    trackSaveErrors,
    pendingFavIds,
    pendingTrackIds,
    handleToggleFav,
    handleTrackInteraction,
    retryFavSave,
    retryTrackSave,
    retryInteractionsLoad,
  };
}
