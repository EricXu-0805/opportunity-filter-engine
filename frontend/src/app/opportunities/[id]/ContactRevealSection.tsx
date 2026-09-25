'use client';

import { useEffect, useState, useSyncExternalStore } from 'react';
import { Lock, Mail } from 'lucide-react';
import { ApiError, getOpportunityById } from '@/lib/api';
import { useAuthModal } from '@/lib/auth-modal-context';
import { getAuthState, onAuthChange, type AuthState } from '@/lib/supabase';
import { captureOwnerToken, isTokenOwnerStillCurrent, onLocalOwnerStateChange } from '@/lib/identity-owner';
import type { Opportunity } from '@/lib/types';
import { Section } from './DetailSections';
import type { TFunc } from './types';

export const CONTACT_AUTH_TIMEOUT_MS = 15_000;
const buttonClass = 'mt-2 inline-flex min-h-10 items-center rounded-xl bg-indigo-600 px-3.5 py-2 text-[13px] font-semibold text-white hover:bg-indigo-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600';

function ownerSnapshot() {
  const { uid, epoch, generation } = captureOwnerToken();
  return JSON.stringify([uid, epoch, generation]);
}
function subscribeOwner(changed: () => void) {
  const stop = onLocalOwnerStateChange(changed);
  window.addEventListener('storage', changed);
  return () => { stop(); window.removeEventListener('storage', changed); };
}
function blocksContact(opp: Pick<Opportunity, 'source_type' | 'faculty_availability_status' | 'target_truth'>) {
  return (opp.source_type === 'faculty_research' && opp.faculty_availability_status === 'not_accepting_undergraduates')
    || opp.target_truth?.actionable === false;
}

/** Contact responses belong to one target and one sign-in period. */
export function ContactRevealSection({ opp, t }: { opp: Opportunity; t: TFunc }) {
  const owner = useSyncExternalStore(subscribeOwner, ownerSnapshot, () => 'server');
  if (blocksContact(opp) || !opp.contact_email_status) return null;
  if (opp.contact_email_status === 'unavailable') return <Unavailable t={t} />;
  // A cached "revealed" prop has no identity binding. Recheck it rather than
  // exposing a previous session's address before auth has resolved.
  return <ContactAuth key={JSON.stringify([owner, opp.id, opp.contact_email_status, opp.writing_target_version])} opp={opp} t={t} />;
}

type AuthResult = { state: AuthState } | { error: true };
function ContactAuth({ opp, t }: { opp: Opportunity; t: TFunc }) {
  const [auth, setAuth] = useState<AuthResult | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    let revision = 0;
    const owner = captureOwnerToken();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const accept = (result: AuthResult) => {
      if (!active || !isTokenOwnerStillCurrent(owner)) return;
      clearTimeout(timer);
      setAuth(result);
    };
    const initial = revision;
    timer = setTimeout(() => {
      if (revision !== initial) return;
      revision += 1; // A timed-out snapshot cannot overwrite a later retry.
      accept({ error: true });
    }, CONTACT_AUTH_TIMEOUT_MS);
    const stop = onAuthChange(state => { revision += 1; accept({ state }); });
    void getAuthState({ throwOnError: true }).then(
      state => { if (revision === initial) accept({ state }); },
      () => { if (revision === initial) accept({ error: true }); },
    );
    return () => { active = false; clearTimeout(timer); stop(); };
  }, [attempt]);

  if (!auth) return <Loading t={t} />;
  if ('error' in auth) return <LoadError t={t} authError onRetry={() => { setAuth(null); setAttempt(value => value + 1); }} />;
  if (!auth.state.session || auth.state.isAnonymous) return <SignIn t={t} />;
  if (!auth.state.user?.id) return <LoadError t={t} authError onRetry={() => { setAuth(null); setAttempt(value => value + 1); }} />;
  // A token refresh for this same account leaves the current GET alone. The
  // API already does its one auth refresh; remounting here would loop it.
  return <ContactRead key={auth.state.user.id} opp={opp} t={t} />;
}

type RevealResult =
  | { state: 'loading' | 'error' | 'sign_in_required' | 'unavailable' | 'blocked' }
  | { state: 'revealed'; email: string };
function ContactRead({ opp, t }: { opp: Opportunity; t: TFunc }) {
  const [result, setResult] = useState<RevealResult>({ state: 'loading' });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const owner = captureOwnerToken();
    const current = () => !controller.signal.aborted && isTokenOwnerStillCurrent(owner);
    void getOpportunityById(opp.id, { signal: controller.signal }).then(body => {
      if (!current()) return;
      if (!body || body.id !== opp.id) throw new Error('Contact target changed');
      if (blocksContact(body as unknown as Opportunity)) {
        setResult({ state: 'blocked' });
      } else if (body.contact_email_status === 'revealed') {
        const email = body.contact_email;
        if (typeof email !== 'string' || !email.trim() || /[\s\r\n]/.test(email) || !email.includes('@')) {
          throw new Error('Invalid contact response');
        }
        setResult({ state: 'revealed', email });
      } else if (body.contact_email_status === 'unavailable' || body.contact_email_status === 'sign_in_required') {
        setResult({ state: body.contact_email_status });
      } else {
        throw new Error('Invalid contact status');
      }
    }).catch(error => {
      if (!current()) return;
      setResult({ state: error instanceof ApiError && error.status === 401 ? 'sign_in_required' : 'error' });
    });
    return () => controller.abort();
  }, [opp.id, attempt]);

  if (result.state === 'blocked') return null;
  if (result.state === 'loading') return <Loading t={t} />;
  if (result.state === 'error') return <LoadError t={t} onRetry={() => { setResult({ state: 'loading' }); setAttempt(value => value + 1); }} />;
  if (result.state === 'unavailable') return <Unavailable t={t} />;
  if (result.state === 'sign_in_required') return <SignIn t={t} sessionRequired onRetry={() => { setResult({ state: 'loading' }); setAttempt(value => value + 1); }} />;
  if (result.state !== 'revealed') return null;
  return (
    <Section title={t('detail.sections.contact')}>
      <div className="flex items-start gap-3">
        <span className="mt-0.5 shrink-0 text-gray-400" aria-hidden="true"><Mail /></span>
        <div className="min-w-0">
          <dt className="mb-0.5 text-[11px] uppercase tracking-wider text-gray-400">{t('detail.fields.contactEmail')}</dt>
          <dd className="break-words text-[14px]">
            <a href={`mailto:${encodeURIComponent(result.email)}`} className="text-indigo-600 hover:text-indigo-700 hover:underline" data-testid="contact-email-link">{result.email}</a>
          </dd>
          <p className="mt-1 text-[11px] text-gray-400">{t('detail.contactVerifyHint')}</p>
        </div>
      </div>
    </Section>
  );
}
function Loading({ t }: { t: TFunc }) {
  return <Section title={t('detail.sections.contact')}><p role="status" data-testid="contact-reveal-loading" className="text-[14px] text-gray-600">{t('detail.contactLoading')}</p></Section>;
}
function Unavailable({ t }: { t: TFunc }) {
  return <Section title={t('detail.sections.contact')}><p role="status" data-testid="contact-unavailable" className="text-[14px] text-gray-600">{t('detail.contactUnavailable')}</p></Section>;
}
function LoadError({ t, onRetry, authError = false }: { t: TFunc; onRetry: () => void; authError?: boolean }) {
  return <Section title={t('detail.sections.contact')}>
    <p role="alert" data-testid="contact-reveal-error" className="text-[14px] text-gray-700">{t(authError ? 'detail.contactAuthError' : 'detail.contactLoadError')}</p>
    <button type="button" className={buttonClass} onClick={onRetry}>{t('detail.contactRetry')}</button>
  </Section>;
}
function SignIn({ t, sessionRequired = false, onRetry }: { t: TFunc; sessionRequired?: boolean; onRetry?: () => void }) {
  const { openModal } = useAuthModal();
  return <Section title={t('detail.sections.contact')}>
    <div className="flex items-start gap-3" data-testid="contact-sign-in">
      <span className="mt-0.5 shrink-0 text-gray-400" aria-hidden="true"><Lock /></span>
      <div className="min-w-0">
        <p className="text-[14px] text-gray-700">{t(sessionRequired ? 'detail.contactSessionRequired' : 'detail.contactSignInPrompt')}</p>
        <button type="button" onClick={() => openModal({ reason: 'contact-reveal', ...(sessionRequired ? { phase: 'signin' as const } : {}) })} className={buttonClass}>{t('detail.contactSignInCta')}</button>
        {onRetry && <button type="button" onClick={onRetry} className="ml-2 mt-2 inline-flex min-h-10 items-center rounded-xl border border-gray-300 px-3.5 py-2 text-[13px] font-semibold text-gray-700 hover:bg-gray-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600" data-testid="contact-check-again">{t('detail.contactCheckAgain')}</button>}
      </div>
    </div>
  </Section>;
}
