'use client';

import { useCallback, useReducer, useRef, useState } from 'react';
import { captureOwnerToken } from '@/lib/identity-owner';
import {
  commitProfileAction,
  readProfileView,
  RESULTS_WRITER,
  type ProfileViewSnapshot,
} from '@/lib/profile-sync';
import { migrateProfile, type LegacyProfileShape } from './types';
import type { ProfileData } from '@/lib/types';

/** The document this page renders and the snapshot a write from it carries,
 *  accepted together in one step. Kept as one value on purpose: a separately
 *  refreshed ref beside a separately derived profile is two states that
 *  drift, and the drift is invisible — the toggle would then send a flip the
 *  person made against values they were never shown. */
export interface AcceptedProfileView {
  profile: ProfileData | null;
  view: ProfileViewSnapshot | null;
}

const EMPTY: AcceptedProfileView = { profile: null, view: null };

export function useAcceptedProfileView(): {
  accepted: AcceptedProfileView;
  /** Re-read storage and publish both halves together. */
  accept: () => void;
  /** Publish nothing, synchronously. Call this IN the identity transition,
   *  not from an effect keyed on the generation: an effect runs after paint
   *  and leaves the previous account's document on screen — and its view
   *  actionable — for a full render. */
  clear: () => void;
} {
  const [accepted, dispatch] = useReducer(
    (_prev: AcceptedProfileView, next: AcceptedProfileView) => next,
    EMPTY,
  );
  const accept = useCallback(() => {
    // ONE read; both halves come out of it.
    const view = readProfileView(captureOwnerToken());
    dispatch({
      profile: view
        ? migrateProfile(view.renderedProfile as unknown as LegacyProfileShape)
        : null,
      view,
    });
  }, []);
  const clear = useCallback(() => dispatch(EMPTY), []);
  return { accepted, accept, clear };
}

/** A flip that did not take effect, kept WITH the view it was made against.
 *  Storing only the boolean would let Retry re-run one identity's click
 *  against whatever view has been accepted since — including another's. */
interface FailedFlip {
  view: ProfileViewSnapshot;
  next: boolean;
}

export function useCrossSchoolToggle(
  view: ProfileViewSnapshot | null,
  /** Runs only when the change actually took effect. */
  onApplied: () => void,
): {
  busy: boolean;
  failed: boolean;
  toggle: (next: boolean) => void;
  retry: () => void;
  clear: () => void;
} {
  const [failure, setFailure] = useState<FailedFlip | null>(null);
  const [busy, setBusy] = useState(false);
  // Every attempt gets an id, and only the CURRENT one may touch state.
  //
  // A plain in-flight boolean is not enough. When the identity switches
  // mid-flight, the old attempt is still running: without an id it would come
  // back and set a failure the new owner never caused, call onApplied and
  // throw away their match set, and release the busy guard the new owner's
  // own attempt is holding — while the boolean, still true, locked the new
  // owner out until the old request finished. Bumping the sequence abandons
  // the old attempt outright and frees the control immediately.
  const opSeqRef = useRef(0);
  const activeOpRef = useRef<number | null>(null);

  const apply = useCallback(async (against: ProfileViewSnapshot | null, next: boolean) => {
    // No accepted view means this page cannot say what the change was made
    // against. Fail closed rather than borrow the current revision.
    // A second click while one is in flight is the same click twice.
    if (!against || activeOpRef.current !== null) return;
    opSeqRef.current += 1;
    const op = opSeqRef.current;
    activeOpRef.current = op;
    setBusy(true);
    setFailure(null);
    try {
      // ONE key. This page holds a snapshot that may be older than the profile
      // the user edited on another device — under the old blind full-row
      // write, flipping this toggle re-uploaded that whole stale snapshot and
      // undid, among other things, a résumé they had removed.
      //
      // AWAITED, and the match set is dropped only once the change actually
      // took effect. Durability is NOT success: a durably recorded operation
      // still comes back conflict / abandoned / device-failed, and re-ranking
      // under a setting the row does not have is exactly the lie this page
      // told by clearing first and hoping.
      const outcome = await commitProfileAction({
        keys: ['include_cross_school'],
        view: against,
        desiredAfter: {
          ...against.renderedProfile,
          include_cross_school: next,
        } as ProfileData,
        writer: RESULTS_WRITER,
      }).catch(() => null);
      if (activeOpRef.current !== op) return; // abandoned; someone else owns the UI
      const status = outcome?.durable ? outcome.result?.status : undefined;
      const landed = status === 'saved' || status === 'already-saved'
        || status === 'local-only' || status === 'staged-local';
      if (!landed) {
        setFailure({ view: against, next });
        return;
      }
      onApplied();
    } finally {
      // Only this attempt's own guard. An abandoned attempt releasing the
      // flag would unlock a control the CURRENT attempt is still using.
      if (activeOpRef.current === op) {
        activeOpRef.current = null;
        setBusy(false);
      }
    }
  }, [onApplied]);

  const toggle = useCallback((next: boolean) => { void apply(view, next); }, [apply, view]);
  const retry = useCallback(() => {
    // The ORIGINAL view, never whatever is current: a retry is the same click
    // again. If its owner has moved on the coordinator refuses it outright
    // instead of re-aiming it at the new one.
    if (failure) void apply(failure.view, failure.next);
  }, [apply, failure]);
  const clear = useCallback(() => {
    opSeqRef.current += 1;   // every outstanding attempt is now abandoned
    activeOpRef.current = null; // and the control is free for the new owner
    setFailure(null);
    setBusy(false);
  }, []);

  return { busy, failed: failure !== null, toggle, retry, clear };
}
