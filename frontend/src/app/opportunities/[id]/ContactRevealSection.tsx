'use client';

import { useEffect, useRef, useState } from 'react';
import { Lock, Mail } from 'lucide-react';
import { getOpportunityById } from '@/lib/api';
import { useAuthModal } from '@/lib/auth-modal-context';
import { getAuthState, onAuthChange, type AuthState } from '@/lib/supabase';
import type { ContactEmailStatus, Opportunity } from '@/lib/types';
import { Section } from './DetailSections';
import type { TFunc } from './types';

/**
 * W10b auth-gated contact reveal. The page is server-rendered from an
 * anonymous fetch, so the detail payload arrives with the contact hidden and
 * a status flag; a signed-in visitor upgrades client-side by re-fetching the
 * detail with their token (the api layer refreshes a stale session once and
 * retries — a still-stale session lands back here as the sign-in affordance,
 * never an error). 'unavailable' renders nothing: no verified address exists,
 * and the cold-email modal owns that honest state.
 */
export function ContactRevealSection({ opp, t }: { opp: Opportunity; t: TFunc }) {
  const { openModal } = useAuthModal();
  const [status, setStatus] = useState<ContactEmailStatus | null>(
    opp.contact_email_status ?? null,
  );
  const [email, setEmail] = useState(opp.contact_email ?? '');
  const [authState, setAuthState] = useState<AuthState | null>(null);
  const revealInFlight = useRef(false);

  useEffect(() => {
    let cancelled = false;
    getAuthState().then((s) => { if (!cancelled) setAuthState(s); });
    const unsubscribe = onAuthChange((s) => { if (!cancelled) setAuthState(s); });
    return () => { cancelled = true; unsubscribe(); };
  }, []);

  const signedIn = authState !== null && !!authState.session && !authState.isAnonymous;

  useEffect(() => {
    if (status !== 'sign_in_required' || !signedIn || revealInFlight.current) return;
    revealInFlight.current = true;
    let cancelled = false;
    void (async () => {
      try {
        const body = await getOpportunityById(opp.id);
        if (cancelled) return;
        if (
          body.contact_email_status === 'revealed'
          && typeof body.contact_email === 'string'
        ) {
          setEmail(body.contact_email);
          setStatus('revealed');
        }
      } catch {
        /* keep the affordance — the draft flow still works */
      } finally {
        revealInFlight.current = false;
      }
    })();
    return () => { cancelled = true; };
  }, [status, signedIn, opp.id]);

  if (status === 'revealed' && email) {
    return (
      <Section title={t('detail.sections.contact')}>
        <div className="flex items-start gap-3">
          <span className="shrink-0 mt-0.5 text-gray-400" aria-hidden="true">
            <Mail />
          </span>
          <div className="min-w-0">
            <dt className="text-[11px] text-gray-400 uppercase tracking-wider mb-0.5">
              {t('detail.fields.contactEmail')}
            </dt>
            <dd className="text-[14px] break-words">
              <a
                href={`mailto:${encodeURIComponent(email)}`}
                className="text-indigo-600 hover:text-indigo-700 hover:underline"
                data-testid="contact-email-link"
              >
                {email}
              </a>
            </dd>
            <p className="mt-1 text-[11px] text-gray-400">
              {t('detail.contactVerifyHint')}
            </p>
          </div>
        </div>
      </Section>
    );
  }

  if (status === 'sign_in_required') {
    return (
      <Section title={t('detail.sections.contact')}>
        <div className="flex items-start gap-3" data-testid="contact-sign-in">
          <span className="shrink-0 mt-0.5 text-gray-400" aria-hidden="true">
            <Lock />
          </span>
          <div className="min-w-0">
            <p className="text-[14px] text-gray-700">
              {t('detail.contactSignInPrompt')}
            </p>
            <button
              type="button"
              onClick={() => openModal({ reason: 'contact-reveal' })}
              className="mt-2 inline-flex items-center px-3.5 py-2 rounded-xl bg-indigo-600 text-white text-[13px] font-semibold hover:bg-indigo-700 transition-colors"
            >
              {t('detail.contactSignInCta')}
            </button>
          </div>
        </div>
      </Section>
    );
  }

  return null;
}
