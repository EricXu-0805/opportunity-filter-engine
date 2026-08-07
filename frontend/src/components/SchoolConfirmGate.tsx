'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import UniversitySwitcherModal from '@/components/UniversitySwitcherModal';
import { useT } from '@/i18n/client';
import { track } from '@/lib/analytics';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange } from '@/lib/identity-owner';
import { readProfileView, type ProfileViewSnapshot } from '@/lib/profile-sync';
import { isSchoolConfirmed, persistHomeSchool } from '@/lib/school-confirmation';
import { HOME_SCHOOL_EVENT, STORAGE_KEYS } from '@/lib/storage-keys';

// Session-scoped soft-gate dismissal: closing the prompt parks it until the
// next browser session instead of nagging every navigation. Deliberately NOT
// the confirmation itself — matching keeps running on the unconfirmed school
// meanwhile (honest, not hostage-taking).
const SESSION_DEFER_KEY = 'ofe_school_confirm_deferred';

/**
 * W10b one-time school re-confirmation. Existing users (tour already seen)
 * whose profile school carries no confirmation receipt see the school picker
 * ONCE, pre-selected on their current campus: one click confirms (or changes)
 * and writes the receipt, and every other school-choosing flow (onboarding
 * finish, profile switcher) writes the same receipt — so nobody is asked
 * twice. New users never see this: their tour's school gate confirms.
 */
interface PendingConfirmation {
  slug: string;
  // The row this modal's `slug` was read out of, the revision that row is,
  // and the owner it was read for — ONE capture from ONE read, made at the
  // moment evaluate() decided to show this campus.
  //
  // The token half is why a click can never be laundered: it can land after
  // a live identity switch has ALREADY advanced the shared owner
  // (advanceOwnerEpoch runs synchronously) but BEFORE React commits the
  // re-render that would close this modal. Capturing a token at click time
  // would hand a stale U1-derived campus a FRESH, currently-valid U2 token
  // and every downstream preflight would wave it through.
  //
  // The revision half is why it cannot silently overwrite: the pair is
  // whatever was on screen, so another tab's newer row is a conflict rather
  // than a base this modal gets to claim it was choosing against.
  view: ProfileViewSnapshot;
}

export default function SchoolConfirmGate() {
  const { t } = useT();
  const [pending, setPending] = useState<PendingConfirmation | null>(null);
  const [confirming, setConfirming] = useState(false);
  const confirmInFlightRef = useRef(false);
  // The reason the last confirm did not land. Rendered rather than swallowed:
  // a gate that closes on failure is how a user ends up matched against a
  // campus they never confirmed.
  const [error, setError] = useState<string | null>(null);

  const evaluate = useCallback((): PendingConfirmation | null => {
    try {
      // The first-visit tour still owns brand-new users (it ends on its own
      // school gate, which records the confirmation).
      if (localStorage.getItem(STORAGE_KEYS.ONBOARDING_SEEN) !== '1') return null;
      if (sessionStorage.getItem(SESSION_DEFER_KEY) === '1') return null;
      // ONE read decides BOTH what this gate displays and what it will later
      // confirm against. Reading the campus here and the revision at click
      // time would let the two disagree — the person answering about the row
      // they can see, the write claiming a row they never saw.
      //
      // It is also ownership-gated all the way down (readUserScopedRaw):
      // while local ownership is BLOCKED (mid account-switch, identity not
      // yet confirmed) this reads as "no profile yet" rather than surfacing
      // the previous identity's still-sitting-in-storage home_school, which
      // would pre-select the gate on a campus that isn't this owner's.
      const view = readProfileView(captureOwnerToken());
      if (!view) return null; // no profile yet, or ownership not yet confirmed
      const stored = view.renderedProfile.home_school;
      // Pre-school-gate profiles have no home_school; they have been matched
      // as UIUC all along (the api-layer default), so that is what the user
      // is asked to confirm or correct.
      const slug = typeof stored === 'string' && stored ? stored : 'uiuc';
      if (isSchoolConfirmed(slug)) return null;
      return { slug, view };
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    /* eslint-disable-next-line react-hooks/set-state-in-effect --
       gate decision reads localStorage (window-only), so it must run after
       mount to avoid an SSR/hydration mismatch (same as OnboardingIntro) */
    setPending(evaluate());
    const reevaluate = () => setPending(evaluate());
    // HOME_SCHOOL_EVENT: the tour just confirmed, or the school changed live.
    // 'storage': an account switch cleared SCHOOL_CONFIRMED (identity-owner
    // dispatches a synthetic StorageEvent per cleared key) or another tab
    // confirmed — both must re-run the decision.
    window.addEventListener(HOME_SCHOOL_EVENT, reevaluate);
    window.addEventListener('storage', reevaluate);
    // A pending modal is captured under WHOEVER was current when it opened.
    // The instant identity moves on (advanceOwnerEpoch marks the realm
    // 'blocked' synchronously, before any React re-render), evaluate()'s
    // readUserScopedRaw read starts returning null and this drops
    // `pending` to null — a stale U1-derived campus must never keep
    // showing (or be confirmable) once U2 is the current owner. This is
    // belt-and-suspenders alongside the ORIGIN token below: it closes the
    // modal in the common case, but the token is what still fails closed
    // even in the race window before this listener's setState commits.
    const unsubscribeOwner = onLocalOwnerStateChange(reevaluate);
    return () => {
      window.removeEventListener(HOME_SCHOOL_EVENT, reevaluate);
      window.removeEventListener('storage', reevaluate);
      unsubscribeOwner();
    };
  }, [evaluate]);

  if (!pending) return null;

  const confirm = async (slug: string) => {
    // The ref, not the state: two clicks in the same tick both read the old
    // `confirming` and both run.
    if (confirmInFlightRef.current) return;
    confirmInFlightRef.current = true;
    // The ORIGIN snapshot from when this modal decided what to show — never
    // re-read here. A click landing after a live identity switch (but before
    // React unmounts this stale modal) must fail the preflight against the
    // OLD owner, not succeed against whichever owner happens to be current at
    // click time; and the base it claims is the row it displayed, not the one
    // another tab has written since.
    setConfirming(true);
    // ONE ordered helper: it persists home_school through the profile
    // coordinator (a single-key CAS patch), and only if that actually landed
    // does it write the confirmation receipt and broadcast. Everything below
    // is gated on its result — the pre-CAS code called a now-async function
    // synchronously, so `persisted` was a Promise (always truthy) and a
    // cloud conflict still wrote a receipt, fired the analytics event and
    // closed the gate on a campus that was never saved.
    try {
      const result = await persistHomeSchool(slug, pending.view, { confirm: true });
      if (!result.ok) {
        // Keep the modal open — its Confirm button is the retry.
        setError(result.reason);
        return;
      }
      track('school_confirmed', { school: slug, changed: slug !== pending.slug });
      setPending(null);
    } finally {
      confirmInFlightRef.current = false;
      setConfirming(false);
    }
  };

  return (
    <UniversitySwitcherModal
      initialSelectedSlug={pending.slug}
      title={t('schoolConfirm.title')}
      note={t('schoolConfirm.note')}
      confirmLabel={t(confirming ? 'common.saving' : 'schoolConfirm.confirm')}
      errorMessage={error ? t('schoolConfirm.failed') : null}
      busy={confirming}
      onCancel={() => {
        // SESSION_DEFER_KEY is session-wide, not per-identity — writing it
        // for a STALE cancel (U1's modal, dismissed after U2 already took
        // over but before React unmounted it) would suppress U2's own
        // confirm gate for the rest of the session, even though U2 never
        // dismissed anything. Only the current owner's cancel may defer;
        // a stale one just closes the leftover modal.
        if (isOwnerTokenValid(pending.view.token, pending.view.token.uid)) {
          try { sessionStorage.setItem(SESSION_DEFER_KEY, '1'); } catch { /* ignore */ }
        }
        setPending(null);
      }}
      onConfirm={(slug) => { void confirm(slug); }}
    />
  );
}
