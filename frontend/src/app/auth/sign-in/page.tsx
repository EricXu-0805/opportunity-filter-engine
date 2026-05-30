'use client';

/*
 * Magic-link sign-in page.
 *
 * Sole UI surface for kicking off Flow A. The actual API branching
 * (updateUser vs signInWithOtp) lives in `signInOrLinkEmail` — this
 * page just collects the email + renders outcome state.
 *
 * The page is *idempotent* and *aware* of the current session:
 *   - If a permanent user is already signed in, we show a "you're
 *     signed in as X" panel with a sign-out button instead of a form.
 *   - If anonymous, we show the in-place-conversion copy ("we'll move
 *     your saved data with you").
 *   - If no session at all (rare; happens after sign-out before the
 *     anon re-issue completes), we show the plain sign-in copy.
 */

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import {
  getAuthState,
  onAuthChange,
  signInOrLinkEmail,
  signOutOfAccount,
  type AuthState,
  type SignInOutcome,
} from '@/lib/supabase';
import { useT } from '@/i18n/client';

type Phase = 'idle' | 'sending' | 'sent' | 'error';

export default function SignInPage() {
  const router = useRouter();
  const { t } = useT();
  const [state, setState] = useState<AuthState | null>(null);
  const [email, setEmail] = useState('');
  const [phase, setPhase] = useState<Phase>('idle');
  const [outcome, setOutcome] = useState<SignInOutcome | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAuthState().then(s => { if (!cancelled) setState(s); });
    const unsub = onAuthChange(s => setState(s));
    return () => { cancelled = true; unsub(); };
  }, []);

  const onSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (phase === 'sending') return;
    setPhase('sending');
    setOutcome(null);
    const redirectTo = `${window.location.origin}/auth/callback`;
    const result = await signInOrLinkEmail(email, redirectTo);
    setOutcome(result);
    setPhase(result.ok ? 'sent' : 'error');
  }, [email, phase]);

  const onSignOut = useCallback(async () => {
    await signOutOfAccount();
    router.push('/');
  }, [router]);

  const isPermanentUser = Boolean(state?.user && !state.isAnonymous);

  return (
    <div className="max-w-md mx-auto px-4 py-12">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">
          {isPermanentUser ? t('auth.signIn.signedInTitle') : t('auth.signIn.title')}
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          {isPermanentUser
            ? t('auth.signIn.signedInSubtitle')
            : state?.isAnonymous
              ? t('auth.signIn.subtitleAnon')
              : t('auth.signIn.subtitle')}
        </p>
      </header>

      {isPermanentUser ? (
        <div className="rounded-2xl border border-black/[0.06] bg-white/60 p-5">
          <p className="text-sm text-gray-700">
            {t('auth.signIn.signedInAs', { email: state?.email || '' })}
          </p>
          <button
            type="button"
            onClick={onSignOut}
            className="mt-4 inline-flex items-center justify-center px-4 py-2 rounded-full bg-gray-900 text-white text-sm font-medium hover:bg-black transition-colors"
          >
            {t('auth.signIn.signOut')}
          </button>
          <p className="mt-3 text-xs text-gray-400">
            {t('auth.signIn.signOutHint')}
          </p>
        </div>
      ) : phase === 'sent' && outcome?.ok ? (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
          <h2 className="text-sm font-semibold text-emerald-900">
            {t('auth.signIn.sentTitle')}
          </h2>
          <p className="mt-1 text-sm text-emerald-800">{outcome.message}</p>
          <p className="mt-3 text-xs text-emerald-700">
            {t('auth.signIn.sameBrowserHint')}
          </p>
        </div>
      ) : (
        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="auth-email"
              className="block text-xs font-medium text-gray-600 mb-1"
            >
              {t('auth.signIn.emailLabel')}
            </label>
            <input
              id="auth-email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@illinois.edu"
              className="w-full px-3 py-2 rounded-lg border border-black/[0.08] focus:outline-none focus:ring-2 focus:ring-blue-500 text-[15px]"
            />
          </div>

          {phase === 'error' && outcome && !outcome.ok && (
            <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
              {outcome.message}
            </div>
          )}

          <button
            type="submit"
            disabled={phase === 'sending'}
            className="w-full py-2 rounded-full bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {phase === 'sending' ? t('auth.signIn.sending') : t('auth.signIn.submit')}
          </button>

          <p className="text-xs text-gray-400 text-center">
            {state?.isAnonymous
              ? t('auth.signIn.privacyAnon')
              : t('auth.signIn.privacy')}
          </p>
        </form>
      )}

      <div className="mt-8 text-center">
        <Link href="/" className="text-xs text-gray-400 hover:text-gray-600">
          {t('auth.signIn.backHome')}
        </Link>
      </div>
    </div>
  );
}
