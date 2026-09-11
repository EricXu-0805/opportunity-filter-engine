'use client';

import { useEffect, useState, useRef } from 'react';
import { CheckCircle, Send } from 'lucide-react';
import {
  getAuthState,
  loadConciergeRequests,
  requestConciergeApply,
  type AuthState,
} from '@/lib/supabase';
import { track } from '@/lib/analytics';
import { Section } from './DetailSections';
import type { TFunc } from './types';
import { captureOwnerToken, getLocalOwnerState, isTokenOwnerStillCurrent, OwnerMismatchError, onLocalOwnerStateChange } from '@/lib/identity-owner';

/**
 * "Have JoinALab do this one for me" — the concierge request, bound to the
 * professor it is about.
 *
 * The generic intent capture on /account asks whether someone would like help
 * in the abstract, which nobody can act on: the work is per-professor. This
 * asks in front of the target, records which target, and says plainly that a
 * person will do it by hand and that nothing is charged. That last part is not
 * modesty — there is no commercial contract yet (migration 026), so any
 * language implying a purchase would be a claim the product cannot honour.
 */
export function ConciergeRequestSection({
  opportunityId,
  t,
}: {
  opportunityId: string;
  t: TFunc;
}) {
  const [auth, setAuth] = useState<AuthState | null>(null);
  // null = not yet known. Rendering the ask before the answer arrives invites
  // a student to request something they already requested.
  const [requested, setRequested] = useState<boolean | null>(null);
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [failed, setFailed] = useState(false);
  const [ownerGeneration, setOwnerGeneration] = useState(0);
  // The email and "already requested" state below are read for whoever is
  // signed in at mount; an identity change must re-read them, or the next
  // account submits with the previous account's address prefilled. The
  // listener fires on every readiness transition — including the same uid
  // going pending→ready during the load itself — so bump only when the owner
  // actually changed, or the reload feeds its own trigger and `requested`
  // never settles.
  const lastOwnerRef = useRef<string | null | undefined>(undefined);
  useEffect(() => onLocalOwnerStateChange(() => {
    // A pure snapshot: captureOwnerToken() is not free of side effects, and a
    // listener that provokes the very transition it listens for never settles.
    const uid = getLocalOwnerState().uid;
    if (uid === null || uid === lastOwnerRef.current) return;
    const first = lastOwnerRef.current === undefined;
    lastOwnerRef.current = uid;
    if (!first) setOwnerGeneration((g) => g + 1);
  }), []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const state = await getAuthState();
      if (cancelled) return;
      setAuth(state);
      if (state.email) setEmail(state.email);
      const mine = await loadConciergeRequests();
      if (cancelled) return;
      // A failed read stays null: "we could not find out" is not "you have not
      // asked", and only the second one may draw a fresh button.
      setRequested(mine === null ? null : mine.has(opportunityId));
    })();
    return () => { cancelled = true; };
  }, [opportunityId, ownerGeneration]);

  if (requested === null) return null;

  if (requested) {
    return (
      <Section title={t('detail.concierge.title')}>
        <p
          className="flex items-start gap-2 text-[14px] text-emerald-700"
          data-testid="concierge-requested"
        >
          <CheckCircle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
          {t('detail.concierge.done')}
        </p>
      </Section>
    );
  }

  const needsEmail = !auth?.email;

  return (
    <Section title={t('detail.concierge.title')}>
      <p className="text-[14px] text-gray-700">{t('detail.concierge.body')}</p>
      <form
        className="mt-3 flex flex-wrap items-center gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          if (submitting) return;
          const token = captureOwnerToken();
          setSubmitting(true);
          setFailed(false);
          void track('concierge_request_submitted', { opportunity_id: opportunityId });
          let ok: boolean;
          try {
            ok = await requestConciergeApply(
              opportunityId,
              email.trim() || auth?.email || null,
              {},
              token,
            );
          } catch (err) {
            // The account changed under us: the request was refused, and this
            // screen now belongs to someone else. Paint nothing.
            if (err instanceof OwnerMismatchError) return;
            throw err;
          }
          if (!isTokenOwnerStillCurrent(token)) return;
          setSubmitting(false);
          // Only a confirmed write flips the state. An optimistic "requested"
          // over a failed insert is the one outcome worse than the button:
          // the student stops asking and nobody ever sees the request.
          if (ok) setRequested(true);
          else setFailed(true);
        }}
      >
        {needsEmail && (
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder={t('detail.concierge.emailPlaceholder')}
            aria-label={t('detail.concierge.emailPlaceholder')}
            className="w-56 px-3 py-2 rounded-xl border border-gray-200 text-[13px] focus:outline-none focus:ring-2 focus:ring-indigo-200"
          />
        )}
        <button
          type="submit"
          disabled={submitting}
          data-testid="concierge-request-submit"
          className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl bg-indigo-600 text-white text-[13px] font-semibold hover:bg-indigo-700 disabled:opacity-60 transition-colors"
        >
          <Send className="w-3.5 h-3.5" aria-hidden="true" />
          {t('detail.concierge.cta')}
        </button>
      </form>
      {failed && (
        <p className="mt-2 text-[12px] text-red-700" role="alert">
          {t('detail.concierge.failed')}
        </p>
      )}
      <p className="mt-2 text-[11px] text-gray-400">{t('detail.concierge.note')}</p>
    </Section>
  );
}
