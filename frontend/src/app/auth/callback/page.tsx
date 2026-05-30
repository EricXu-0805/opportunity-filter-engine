'use client';

/*
 * Magic-link landing page.
 *
 * Handles BOTH shapes Supabase can send:
 *   1. PKCE:      `/auth/callback?code=<pkce-code>`
 *      Requires the email template to use `{{ .SiteURL }}/auth/callback?code={{ .TokenHash }}`.
 *      → exchangeCodeForSession(code)
 *   2. verifyOtp: `/auth/callback?token_hash=<hash>&type=<email|magiclink|email_change>`
 *      The Supabase DEFAULT email template uses this shape. Works without
 *      any template customization.
 *      → verifyOtp({ token_hash, type })
 *
 * We support both so this PR ships green regardless of whether the
 * Supabase Dashboard email templates have been customized for PKCE.
 *
 * Why client-side (not a server Route Handler):
 *   - We DON'T use @supabase/ssr; the app stores its session in
 *     localStorage (`storageKey: 'ofe_auth'` in lib/supabase.ts), not
 *     in cookies. A server Route Handler would have no access to the
 *     PKCE code_verifier, so the exchange would 400.
 *
 * Known limitation surfaced in copy:
 *   - The PKCE code_verifier lives in the originating browser's local-
 *     Storage. Clicking the link in a *different* browser/profile will
 *     fail for the `?code=` path. The `?token_hash=` path does NOT
 *     have this limitation. We tell the user to open the link on the
 *     same device either way (simpler copy).
 */

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useState } from 'react';
import type { EmailOtpType } from '@supabase/supabase-js';
import { supabase } from '@/lib/supabase';
import { useT } from '@/i18n/client';

type Status = 'pending' | 'success' | 'error';

function CallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const { t } = useT();
  const [status, setStatus] = useState<Status>('pending');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      // Supabase reports OAuth-style errors as either `?error=...` query
      // params (PKCE flow) or `#error=...` hash fragments (implicit). We
      // only use PKCE, but cover both to keep the failure path readable.
      const queryError = params.get('error_description') || params.get('error');
      const hashError = typeof window !== 'undefined' && window.location.hash.includes('error')
        ? decodeURIComponent(window.location.hash.replace(/^#/, ''))
        : null;
      if (queryError || hashError) {
        if (!cancelled) {
          setStatus('error');
          setErrorMsg(queryError || hashError);
        }
        return;
      }

      // Branch by which param Supabase sent. PKCE wins if both are
      // present (custom template upgrade in progress); otherwise we
      // fall back to verifyOtp for the default template shape.
      const code = params.get('code');
      const tokenHash = params.get('token_hash');
      const otpType = params.get('type') as EmailOtpType | null;

      if (!code && !tokenHash) {
        if (!cancelled) {
          setStatus('error');
          setErrorMsg(t('auth.callback.errMissingCode'));
        }
        return;
      }

      let exchangeError: { message: string } | null = null;
      if (code) {
        const { error } = await supabase.auth.exchangeCodeForSession(code);
        exchangeError = error ?? null;
      } else if (tokenHash && otpType) {
        const { error } = await supabase.auth.verifyOtp({
          token_hash: tokenHash,
          type: otpType,
        });
        exchangeError = error ?? null;
      } else {
        // token_hash present but no type — malformed link
        exchangeError = { message: t('auth.callback.errMissingType') };
      }
      if (cancelled) return;
      if (exchangeError) {
        setStatus('error');
        setErrorMsg(exchangeError.message);
        return;
      }
      setStatus('success');
      // Tiny delay so the success message is visible, then route home.
      setTimeout(() => {
        if (!cancelled) router.replace('/');
      }, 900);
    })();

    return () => { cancelled = true; };
  }, [params, router, t]);

  return (
    <div className="max-w-md mx-auto px-4 py-16 text-center">
      {status === 'pending' && (
        <>
          <h1 className="text-lg font-semibold text-gray-900">
            {t('auth.callback.verifying')}
          </h1>
          <p className="mt-2 text-sm text-gray-500">
            {t('auth.callback.verifyingHint')}
          </p>
        </>
      )}
      {status === 'success' && (
        <>
          <h1 className="text-lg font-semibold text-gray-900">
            {t('auth.callback.success')}
          </h1>
          <p className="mt-2 text-sm text-gray-500">
            {t('auth.callback.successHint')}
          </p>
        </>
      )}
      {status === 'error' && (
        <>
          <h1 className="text-lg font-semibold text-gray-900">
            {t('auth.callback.errTitle')}
          </h1>
          <p className="mt-2 text-sm text-gray-600">
            {errorMsg || t('auth.callback.errGeneric')}
          </p>
          <p className="mt-3 text-xs text-gray-400">
            {t('auth.callback.sameBrowserHint')}
          </p>
          <div className="mt-6 flex items-center justify-center gap-3">
            <Link
              href="/auth/sign-in"
              className="px-4 py-2 rounded-full bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 transition-colors"
            >
              {t('auth.callback.tryAgain')}
            </Link>
            <Link
              href="/"
              className="px-4 py-2 rounded-full text-gray-600 text-sm font-medium hover:bg-black/[0.04] transition-colors"
            >
              {t('auth.callback.goHome')}
            </Link>
          </div>
        </>
      )}
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={null}>
      <CallbackInner />
    </Suspense>
  );
}
