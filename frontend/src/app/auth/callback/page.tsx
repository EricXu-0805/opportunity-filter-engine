'use client';

/*
 * Magic-link landing page.
 *
 * Handles BOTH shapes Supabase can send:
 *   1. PKCE:      `/auth/callback?code=<pkce-code>`
 *      → exchangeCodeForSession(code)
 *   2. verifyOtp: `/auth/callback?token_hash=<hash>&type=<email|magiclink|email_change>`
 *      The Supabase DEFAULT email template uses this shape.
 *      → verifyOtp({ token_hash, type })
 *
 * R66 redesign goals (per Oracle's diagnosis):
 *   - 900ms dwell was sub-perception → bumped to 2500ms.
 *   - Auto-redirect with a visible countdown so it feels intentional,
 *     not a flash.
 *   - "Welcome eric@illinois.edu" line — names the actual outcome.
 *   - Real data inventory line ("we kept your N favorites, profile,
 *     M tracked applications") — this is the moment of recognition.
 *   - Always-clickable "Go home" so the user controls the redirect.
 *
 * Why client-side: app uses localStorage session store (not @supabase/ssr
 * cookies); PKCE code_verifier is in the same localStorage, so the
 * exchange must happen here, not in a route handler.
 */

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useState } from 'react';
import { CheckCircle, Sparkles } from 'lucide-react';
import type { EmailOtpType } from '@supabase/supabase-js';
import {
  getAuthState,
  getDataInventory,
  supabase,
  type DataInventory,
} from '@/lib/supabase';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { useT } from '@/i18n/client';

type Status = 'pending' | 'success' | 'error';

const DWELL_MS = 2500;
const TICK_MS = 100;

function CallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const { t } = useT();
  const [status, setStatus] = useState<Status>('pending');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [signedInEmail, setSignedInEmail] = useState<string | null>(null);
  const [inventory, setInventory] = useState<DataInventory | null>(null);
  const [remainingMs, setRemainingMs] = useState<number>(DWELL_MS);

  // ============ exchange + load inventory ============
  useEffect(() => {
    let cancelled = false;

    (async () => {
      // Surface OAuth-style errors before attempting the exchange.
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

      // R68: idempotency guard. PKCE code_verifier is single-use — the
      // successful first exchange consumes and clears it from
      // localStorage. If the user hits back/forward, reloads the page,
      // re-clicks the email link, or otherwise re-lands on /auth/callback
      // with the same `code=` after a successful exchange, the second
      // exchange call fails with "PKCE code verifier not found in
      // storage" even though the session is already established. The
      // user (correctly) sees the error page but ALSO sees themselves as
      // signed in everywhere else in the app — confusing and
      // contradictory. Detect "already signed in" before exchanging and
      // skip straight to the success path.
      //
      // We only short-circuit on PERMANENT sessions, not anonymous ones,
      // so a guest who happens to have an anon session still goes
      // through the conversion path. (signInOrLinkEmail already prevents
      // a permanent-user re-request from ever sending a magic link, so
      // a permanent session at callback time means: this user already
      // completed THIS link's conversion in an earlier tick.)
      const preflight = await getAuthState();
      if (preflight.user && !preflight.isAnonymous) {
        const inv = await getDataInventory().catch(() => null);
        if (cancelled) return;
        setSignedInEmail(preflight.email);
        setInventory(inv);
        setStatus('success');
        try {
          sessionStorage.removeItem(STORAGE_KEYS.JUST_SIGNED_OUT);
          sessionStorage.removeItem(STORAGE_KEYS.GUEST_BANNER_DISMISSED);
        } catch { /* private mode */ }
        return;
      }

      // PKCE wins if both shapes are present; otherwise we use verifyOtp
      // for Supabase's default email template format.
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
        exchangeError = { message: t('auth.callback.errMissingType') };
      }
      if (cancelled) return;
      if (exchangeError) {
        // R68 second-chance: a "code verifier not found" error after we
        // already passed the preflight check above is rare but possible
        // — e.g., if a parallel onAuthStateChange tick wrote the session
        // between preflight and exchange. Re-check session state; if
        // we're now signed in, treat the exchange's stale-verifier
        // error as a no-op and show success.
        const postCheck = await getAuthState();
        if (!cancelled && postCheck.user && !postCheck.isAnonymous) {
          const inv = await getDataInventory().catch(() => null);
          if (cancelled) return;
          setSignedInEmail(postCheck.email);
          setInventory(inv);
          setStatus('success');
          try {
            sessionStorage.removeItem(STORAGE_KEYS.JUST_SIGNED_OUT);
            sessionStorage.removeItem(STORAGE_KEYS.GUEST_BANNER_DISMISSED);
          } catch { /* private mode */ }
          return;
        }
        setStatus('error');
        setErrorMsg(exchangeError.message);
        return;
      }

      // Load inventory + email AFTER exchange so RLS lets us read the
      // user's rows. If inventory fails, we still show success — the
      // inventory is the cherry on top, not the load-bearing wall.
      const [state, inv] = await Promise.all([
        getAuthState(),
        getDataInventory().catch(() => null),
      ]);
      if (cancelled) return;
      setSignedInEmail(state.email);
      setInventory(inv);
      setStatus('success');
      // Clear any "just signed out" flag — they came back, no banner
      // needed.
      try {
        sessionStorage.removeItem(STORAGE_KEYS.JUST_SIGNED_OUT);
        sessionStorage.removeItem(STORAGE_KEYS.GUEST_BANNER_DISMISSED);
      } catch { /* private mode */ }
    })();

    return () => { cancelled = true; };
  }, [params, t]);

  // ============ countdown + auto-redirect on success ============
  useEffect(() => {
    if (status !== 'success') return;
    // No explicit reset here — useState's lazy initial DWELL_MS is
    // already correct, and `status` only transitions pending→success
    // once per page load (no re-entry), so we don't need to reset.
    const start = performance.now();
    const interval = window.setInterval(() => {
      const elapsed = performance.now() - start;
      const left = Math.max(0, DWELL_MS - elapsed);
      setRemainingMs(left);
      if (left <= 0) {
        window.clearInterval(interval);
        router.replace('/');
      }
    }, TICK_MS);
    return () => window.clearInterval(interval);
  }, [status, router]);

  const secondsLeft = Math.ceil(remainingMs / 1000);
  const inventoryLine = buildInventoryLine(inventory, t);

  return (
    <div className="max-w-md mx-auto px-4 py-16">
      {status === 'pending' && (
        <div className="text-center">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-blue-50 mb-4">
            <Sparkles className="w-7 h-7 text-blue-600 animate-pulse" aria-hidden="true" />
          </div>
          <h1 className="text-[18px] font-semibold text-gray-900">
            {t('auth.callback.verifying')}
          </h1>
          <p className="mt-2 text-sm text-gray-500">
            {t('auth.callback.verifyingHint')}
          </p>
        </div>
      )}

      {status === 'success' && (
        <div className="text-center">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-emerald-50 mb-4">
            <CheckCircle className="w-7 h-7 text-emerald-600" aria-hidden="true" />
          </div>
          <h1 className="text-[20px] font-semibold text-gray-900">
            {t('auth.callback.successTitle')}
          </h1>
          {signedInEmail && (
            <p className="mt-1 text-sm text-gray-600">
              {t('auth.callback.signedInAs', { email: signedInEmail })}
            </p>
          )}
          {inventoryLine && (
            <p className="mt-4 text-sm text-gray-700 leading-relaxed">
              {inventoryLine}
            </p>
          )}
          <p className="mt-5 text-xs text-gray-400" aria-live="polite">
            {t('auth.callback.autoRedirect', { seconds: secondsLeft })}
          </p>
          <div className="mt-3 flex items-center justify-center gap-3">
            <Link
              href="/"
              replace
              className="px-4 py-2 rounded-full bg-gray-900 text-white text-sm font-medium hover:bg-black transition-colors"
            >
              {t('auth.callback.goHomeNow')}
            </Link>
          </div>
        </div>
      )}

      {status === 'error' && (
        <div className="text-center">
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
        </div>
      )}
    </div>
  );
}

/**
 * Builds a "we kept your N favorites, profile, and M tracked applications"
 * string from whatever fields are non-zero. Returns null if there's
 * nothing to brag about (zero of everything) — in that case the success
 * screen still shows the welcome, just without the inventory line. We
 * intentionally do NOT show "0 favorites" — naming the empty state
 * undermines the moment.
 */
function buildInventoryLine(
  inv: DataInventory | null,
  t: (key: string, vars?: Record<string, string | number>) => string,
): string | null {
  if (!inv) return null;
  const parts: string[] = [];
  if (inv.favorites > 0) parts.push(t('auth.callback.invFavorites', { count: inv.favorites }));
  if (inv.hasProfile) parts.push(t('auth.callback.invProfile'));
  if (inv.interactions > 0) parts.push(t('auth.callback.invInteractions', { count: inv.interactions }));
  if (inv.savedSearches > 0) parts.push(t('auth.callback.invSavedSearches', { count: inv.savedSearches }));
  if (parts.length === 0) return null;
  return t('auth.callback.inventoryPrefix') + ' ' + joinHuman(parts, t);
}

/** "a, b, and c" / "a 和 b" — defers list joining to i18n where the
 *  conjunction word differs (English "and" / Chinese "和"). */
function joinHuman(parts: string[], t: (key: string) => string): string {
  if (parts.length === 0) return '';
  if (parts.length === 1) return parts[0];
  if (parts.length === 2) return `${parts[0]} ${t('common.and')} ${parts[1]}`;
  return `${parts.slice(0, -1).join(', ')}, ${t('common.and')} ${parts[parts.length - 1]}`;
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={null}>
      <CallbackInner />
    </Suspense>
  );
}
