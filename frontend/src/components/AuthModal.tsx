'use client';

/*
 * AuthModal — the single auth surface for R66 onwards.
 *
 * Four phases, one modal:
 *   - 'signin'           — guest form: collect email → trigger magic link
 *   - 'sent'             — post-submit confirmation: "check your inbox"
 *   - 'account'          — signed-in panel: email + sign-out button
 *   - 'signout-confirm'  — "are you sure?" before destroying the session
 *
 * Phase selection rules (matters for tests):
 *   - Provider's `phase` is 'auto' (the default for the header CTA and
 *     most anchors): we pick `signin` for guests and `account` for
 *     permanent users. This is the "no surprises" path.
 *   - Provider can FORCE a specific phase (e.g. anchors that always
 *     want the signin form even if the user happens to be signed in;
 *     deep-link `/auth/sign-in` route that wants the form). Sent +
 *     signout-confirm are reached transitionally from inside the modal,
 *     never as initial phases.
 *
 * Why we keep "Sign in" copy in only ONE place (the footer of the
 * signin form, "Already have an account? Sign in"): per R66 plan, the
 * verb is "Save my work". Everywhere else uses save/sync language.
 * Centralising the modal makes that vocabulary discipline enforceable.
 *
 * Visual language mirrors EmailMeButton + KeyboardHelpDialog exactly:
 *   fixed inset-0 z-50 flex items-center justify-center p-4
 *   absolute inset-0 bg-gray-900/60 backdrop-blur-sm
 *   relative w-full max-w-md bg-white rounded-2xl shadow-2xl
 * That's the project's modal vocabulary; we MUST match or it'll feel
 * "disjointed" (the original complaint).
 */

import {
  CheckCircle,
  GraduationCap,
  Inbox,
  Mail,
  MonitorSmartphone,
  ShieldCheck,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getAuthState,
  onAuthChange,
  signInExistingEmail,
  signInOrLinkEmail,
  signInWithOAuthProvider,
  signOutOfAccount,
  type AuthState,
  type OAuthProvider,
  type SignInOutcome,
} from '@/lib/supabase';
import { detectSchoolFromEmail } from '@/lib/schools';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { useAuthModal, type AuthModalPhase } from '@/lib/auth-modal-context';
import { useT } from '@/i18n/client';

/**
 * Live env read. We're behind 'use client' so `process.env` reflects
 * what Next.js inlines at build time. Default to 'dev-echo' because
 * (a) the SMTP currently uses Resend's test sender that can only send
 * to the project owner, and (b) we want the warning to appear unless
 * Eric explicitly flips this to 'live' after buying a domain. Treating
 * 'dev-echo' as default = "loud about limitations" instead of silently
 * misleading testers.
 */
function getEmailMode(): 'live' | 'dev-echo' {
  const v = process.env.NEXT_PUBLIC_AUTH_EMAIL_MODE;
  return v === 'live' ? 'live' : 'dev-echo';
}

/**
 * Comma-separated OAuth provider allowlist (e.g. "google,azure").
 * Absent/empty → no provider buttons render and the modal behaves
 * exactly as before. The flag exists so the OAuth code path can ship
 * (and stay tested) before Eric configures Google + Entra in Supabase;
 * like getEmailMode, the env read is inlined by Next.js at build time.
 */
function getEnabledProviders(): OAuthProvider[] {
  const raw = process.env.NEXT_PUBLIC_AUTH_PROVIDERS ?? '';
  return raw
    .split(',')
    .map(s => s.trim().toLowerCase())
    .filter((s): s is OAuthProvider => s === 'google' || s === 'azure');
}

const VALUE_PROPS = [
  { key: 'auth.modal.prop1', icon: MonitorSmartphone },
  { key: 'auth.modal.prop2', icon: ShieldCheck },
  { key: 'auth.modal.prop3', icon: Inbox },
] as const;

function GoogleLogo() {
  return (
    <svg viewBox="0 0 24 24" className="w-[18px] h-[18px] shrink-0" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47a5.57 5.57 0 0 1-2.4 3.58v3h3.86c2.26-2.09 3.56-5.17 3.56-8.82z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.86-3c-1.08.72-2.45 1.16-4.07 1.16-3.13 0-5.78-2.11-6.73-4.96H1.29v3.09A11.99 11.99 0 0 0 12 24z"
      />
      <path
        fill="#FBBC05"
        d="M5.27 14.29A7.13 7.13 0 0 1 4.89 12c0-.8.14-1.57.38-2.29V6.62H1.29a11.97 11.97 0 0 0 0 10.76l3.98-3.09z"
      />
      <path
        fill="#EA4335"
        d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42A11.97 11.97 0 0 0 1.29 6.62l3.98 3.09C6.22 6.86 8.87 4.75 12 4.75z"
      />
    </svg>
  );
}

function MicrosoftLogo() {
  return (
    <svg viewBox="0 0 21 21" className="w-[18px] h-[18px] shrink-0" aria-hidden="true">
      <rect x="1" y="1" width="9" height="9" fill="#F25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
      <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
      <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
    </svg>
  );
}

const PROVIDER_BTN_CLASS =
  'w-full flex items-center justify-center gap-2.5 py-2.5 px-3 rounded-xl border border-gray-200 bg-white text-[14px] font-medium text-gray-700 leading-snug hover:bg-gray-50 disabled:opacity-60 transition-colors';

export default function AuthModal() {
  const { open, phase, closeModal, setPhase } = useAuthModal();
  const { t, locale } = useT();

  // Live auth state. We refresh on open and subscribe to onAuthChange
  // while open so that if the user clicks the email link in another
  // tab, the modal pops over to the 'account' phase automatically.
  const [authState, setAuthState] = useState<AuthState | null>(null);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    getAuthState().then(s => { if (!cancelled) setAuthState(s); });
    const unsub = onAuthChange(s => { if (!cancelled) setAuthState(s); });
    return () => { cancelled = true; unsub(); };
  }, [open]);

  // Resolve `auto` to the right phase based on auth state.
  const resolved: AuthModalPhase = (() => {
    if (phase !== 'auto') return phase;
    if (!authState) return 'signin';
    return authState.user && !authState.isAnonymous ? 'account' : 'signin';
  })();

  // Form state. Lives in modal-scoped state so it's preserved across
  // phase transitions inside the modal (e.g. "Wrong email? Edit" in
  // 'sent' brings us back to 'signin' with the same email pre-filled).
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [outcome, setOutcome] = useState<SignInOutcome | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Reset transient state on close. Phase / email persist across same-
  // session reopens by design (user can retry without re-typing). The
  // setState calls here are the canonical "reset derived UI state when
  // an external condition changes" pattern — calling them in render
  // would loop, and calling them in the close handler would miss
  // out-of-band close events (ESC, backdrop click).
  useEffect(() => {
    if (!open) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- legitimate reset on close
      setSubmitting(false);
      setOutcome(null);
    } else if (resolved === 'signin') {
      // Defer to next tick so the autofocus actually happens after the
      // backdrop fades in — focusing during the same frame causes jsdom
      // tests to fire focus before render.
      const id = window.setTimeout(() => inputRef.current?.focus(), 50);
      return () => window.clearTimeout(id);
    }
  }, [open, resolved]);

  // Esc-to-close + body scroll lock while open (adopted from the
  // sign-in-v2 prototype; KeyboardHelpDialog uses the same pattern).
  useEffect(() => {
    if (!open) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeModal();
      }
    }
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, closeModal]);

  const submitSignIn = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setOutcome(null);
    const redirectTo = `${window.location.origin}/auth/callback`;
    const result = await signInOrLinkEmail(email, redirectTo);
    setOutcome(result);
    setSubmitting(false);
    if (result.ok) setPhase('sent');
  }, [email, submitting, setPhase]);

  // R67 problem #2: when signInOrLinkEmail returns `email-taken` (because
  // the user typed an email that's already a permanent account), we surface
  // a button that calls `signInExistingEmail` directly — bypassing the
  // anon-link branch and forcing the magic-link-to-existing-account path.
  // Without this button the user has no way out of the dead end.
  const submitSignInExisting = useCallback(async () => {
    if (submitting) return;
    setSubmitting(true);
    const redirectTo = `${window.location.origin}/auth/callback`;
    const result = await signInExistingEmail(email, redirectTo);
    setOutcome(result);
    setSubmitting(false);
    if (result.ok) setPhase('sent');
  }, [email, submitting, setPhase]);

  // OAuth path. On success Supabase navigates the browser to the
  // provider's consent page, so we deliberately leave `submitting`
  // true (buttons stay disabled instead of flashing back to idle);
  // only a failure returns control to the form.
  const clickProvider = useCallback(async (provider: OAuthProvider) => {
    if (submitting) return;
    setSubmitting(true);
    setOutcome(null);
    const redirectTo = `${window.location.origin}/auth/callback`;
    const result = await signInWithOAuthProvider(provider, redirectTo);
    if (!result.ok) {
      setOutcome(result);
      setSubmitting(false);
    }
  }, [submitting]);

  const confirmSignOut = useCallback(async () => {
    await signOutOfAccount();
    // Tell GuestBanner this was a deliberate sign-out (not first-visit
    // anon) so it shows the post-signout reassurance.
    try {
      sessionStorage.setItem(STORAGE_KEYS.JUST_SIGNED_OUT, '1');
      sessionStorage.removeItem(STORAGE_KEYS.GUEST_BANNER_DISMISSED);
    } catch { /* private mode */ }
    closeModal();
  }, [closeModal]);

  if (!open) return null;

  const isSignedIn = Boolean(authState?.user && !authState.isAnonymous);
  const currentEmail = authState?.email ?? '';
  const providers = getEnabledProviders();
  const detection = detectSchoolFromEmail(email);

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="auth-modal-title"
    >
      <div
        className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm"
        onClick={closeModal}
        aria-hidden="true"
      />
      <div className="relative w-full max-w-md max-h-[calc(100vh-2rem)] overflow-y-auto bg-white rounded-2xl shadow-2xl p-6 animate-in">
        <button
          type="button"
          onClick={closeModal}
          className="absolute top-3 right-3 p-1 rounded-lg hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          aria-label={t('common.close')}
        >
          <X className="w-4 h-4 text-gray-400" />
        </button>

        {/* ============ signin phase ============ */}
        {resolved === 'signin' && (
          <>
            <div className="pr-6">
              <h2
                id="auth-modal-title"
                className="text-2xl font-bold text-gray-900 tracking-tight leading-tight"
              >
                {t('auth.modal.signin.headline')}{' '}
                <span className="bg-gradient-to-r from-blue-600 to-blue-400 bg-clip-text text-transparent">
                  {t('auth.modal.signin.headlineAccent')}
                </span>
              </h2>
              <p className="mt-2 text-[13px] text-gray-500 leading-relaxed">
                {t('auth.modal.signin.subline')}
              </p>
            </div>

            <div className="mt-4 grid grid-cols-3 gap-2 rounded-xl border border-gray-100 bg-gray-50/80 px-3 py-2.5">
              {VALUE_PROPS.map(p => (
                <div key={p.key} className="flex flex-col items-center text-center gap-1">
                  <p.icon className="w-4 h-4 text-blue-600" aria-hidden="true" />
                  <p className="text-[11px] font-medium text-gray-700 leading-tight">
                    {t(p.key)}
                  </p>
                </div>
              ))}
            </div>

            {providers.length > 0 && (
              <>
                <div className="mt-5 space-y-2.5">
                  {providers.includes('google') && (
                    <button
                      type="button"
                      data-testid="auth-provider-google"
                      onClick={() => clickProvider('google')}
                      disabled={submitting}
                      className={PROVIDER_BTN_CLASS}
                    >
                      <GoogleLogo />
                      <span>{t('auth.modal.google')}</span>
                    </button>
                  )}
                  {providers.includes('azure') && (
                    <button
                      type="button"
                      data-testid="auth-provider-azure"
                      onClick={() => clickProvider('azure')}
                      disabled={submitting}
                      className={PROVIDER_BTN_CLASS}
                    >
                      <MicrosoftLogo />
                      <span>{t('auth.modal.microsoft')}</span>
                    </button>
                  )}
                </div>

                <div className="flex items-center gap-3 my-5" aria-hidden="true">
                  <span className="h-px flex-1 bg-gray-200" />
                  <span className="text-[11px] text-gray-400">{t('auth.modal.divider')}</span>
                  <span className="h-px flex-1 bg-gray-200" />
                </div>
              </>
            )}

            <form
              onSubmit={submitSignIn}
              className={providers.length > 0 ? 'space-y-3' : 'mt-5 space-y-3'}
            >
              <label className="block">
                <span className="text-[12px] font-medium text-gray-700">
                  {t('auth.modal.signin.emailLabel')}
                </span>
                <input
                  ref={inputRef}
                  type="email"
                  required
                  autoComplete="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder={t('auth.modal.signin.emailPlaceholder')}
                  disabled={submitting}
                  className="mt-1.5 w-full px-3.5 py-2.5 border border-gray-200 rounded-xl text-[14px] focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none disabled:bg-gray-50"
                />
              </label>

              {/* Live .edu detection chip. Keyed by school slug so
                  switching domains re-runs the fade-slide-in animation. */}
              {detection.kind === 'school' && (
                <div
                  key={detection.school.slug}
                  data-testid="school-chip"
                  className="animate-in flex items-start gap-2.5 rounded-xl border border-gray-100 bg-gray-50/80 px-3 py-2.5"
                >
                  <span
                    className="mt-1.5 w-2.5 h-2.5 rounded-full shrink-0"
                    style={{ backgroundColor: detection.school.color }}
                    aria-hidden="true"
                  />
                  <div className="min-w-0">
                    <p className="flex items-center gap-1.5 text-[13px] font-medium text-gray-800">
                      <span className="truncate">
                        {locale === 'zh' ? detection.school.nameZh : detection.school.name}
                      </span>
                      <CheckCircle
                        className="w-3.5 h-3.5 text-emerald-600 shrink-0"
                        aria-hidden="true"
                      />
                    </p>
                    <p className="text-[11px] text-gray-500 mt-0.5">
                      {t('auth.modal.chip.known', { shortName: detection.school.shortName })}
                    </p>
                  </div>
                </div>
              )}
              {detection.kind === 'edu' && (
                <div
                  data-testid="edu-chip"
                  className="animate-in flex items-start gap-2.5 rounded-xl border border-gray-100 bg-gray-50/80 px-3 py-2.5"
                >
                  <GraduationCap
                    className="w-4 h-4 text-gray-400 shrink-0 mt-0.5"
                    aria-hidden="true"
                  />
                  <div>
                    <p className="text-[13px] font-medium text-gray-700">
                      {t('auth.modal.chip.edu.title')}
                    </p>
                    <p className="text-[11px] text-gray-500 mt-0.5">
                      {t('auth.modal.chip.edu.body')}
                    </p>
                  </div>
                </div>
              )}

              {outcome && !outcome.ok && (
                <div className="text-[12px] text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2 space-y-2">
                  <p>{outcome.message}</p>
                  {outcome.reason === 'email-taken' && (
                    <button
                      type="button"
                      onClick={submitSignInExisting}
                      disabled={submitting}
                      data-testid="auth-modal-signin-existing"
                      className="w-full py-2 rounded-lg bg-white border border-red-300 text-red-800 text-[12px] font-medium hover:bg-red-50 disabled:opacity-60 transition-colors"
                    >
                      {submitting ? t('auth.modal.signin.submitting') : t('auth.modal.signin.signInExistingCta')}
                    </button>
                  )}
                </div>
              )}

              <button
                type="submit"
                disabled={submitting}
                className="w-full py-2.5 rounded-xl bg-blue-600 text-white text-[14px] font-medium hover:bg-blue-700 disabled:opacity-60 transition-colors"
              >
                {submitting ? t('auth.modal.signin.submitting') : t('auth.modal.signin.submit')}
              </button>

              <p className="text-[11px] text-gray-400 text-center leading-relaxed pt-1">
                {t('auth.modal.signin.trust')}
              </p>
            </form>
          </>
        )}

        {/* ============ sent phase ============ */}
        {resolved === 'sent' && outcome?.ok && (
          <>
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center">
                <CheckCircle className="w-5 h-5 text-emerald-600" aria-hidden="true" />
              </div>
              <div>
                <h2 id="auth-modal-title" className="text-[16px] font-semibold text-gray-900">
                  {t('auth.modal.sent.title')}
                </h2>
                <p className="text-[12px] text-gray-500">
                  {t('auth.modal.sent.subtitle', { email: email.trim().toLowerCase() })}
                </p>
              </div>
            </div>

            <div className="bg-gray-50 border border-gray-100 rounded-xl px-4 py-3 mb-3">
              <p className="text-[13px] text-gray-700 leading-relaxed">
                {t('auth.modal.sent.sameBrowserHint')}
              </p>
            </div>

            {getEmailMode() === 'dev-echo' && (
              <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2 mb-3">
                <ShieldCheck className="w-4 h-4 text-amber-700 shrink-0 mt-0.5" aria-hidden="true" />
                <p className="text-[11px] text-amber-900 leading-relaxed">
                  {t('auth.modal.sent.devEchoNotice')}
                </p>
              </div>
            )}

            <div className="flex items-center gap-2 justify-end">
              <button
                type="button"
                onClick={() => setPhase('signin')}
                className="px-3 py-1.5 text-[13px] text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
              >
                {t('auth.modal.sent.wrongEmail')}
              </button>
              <button
                type="button"
                onClick={closeModal}
                className="px-4 py-1.5 text-[13px] font-medium text-white bg-gray-900 hover:bg-black rounded-lg transition-colors"
              >
                {t('auth.modal.sent.done')}
              </button>
            </div>
          </>
        )}

        {/* ============ account phase ============ */}
        {resolved === 'account' && isSignedIn && (
          <>
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center text-blue-700 font-semibold text-[15px] uppercase">
                {firstLetter(currentEmail)}
              </div>
              <div className="min-w-0">
                <h2 id="auth-modal-title" className="text-[16px] font-semibold text-gray-900">
                  {t('auth.modal.account.title')}
                </h2>
                <p className="text-[12px] text-gray-500 truncate">{currentEmail}</p>
              </div>
            </div>

            <p className="text-[13px] text-gray-600 leading-relaxed mb-4">
              {t('auth.modal.account.body')}
            </p>

            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={closeModal}
                className="px-3 py-1.5 text-[13px] text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
              >
                {t('common.close')}
              </button>
              <button
                type="button"
                onClick={() => setPhase('signout-confirm')}
                className="px-4 py-1.5 text-[13px] font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
              >
                {t('auth.modal.account.signOut')}
              </button>
            </div>
          </>
        )}

        {/* ============ signout-confirm phase ============ */}
        {resolved === 'signout-confirm' && (
          <>
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-xl bg-amber-50 flex items-center justify-center">
                <Mail className="w-5 h-5 text-amber-600" aria-hidden="true" />
              </div>
              <div>
                <h2 id="auth-modal-title" className="text-[16px] font-semibold text-gray-900">
                  {t('auth.modal.signOutConfirm.title', { email: currentEmail })}
                </h2>
              </div>
            </div>

            <p className="text-[13px] text-gray-600 leading-relaxed mb-2">
              {t('auth.modal.signOutConfirm.bodySafe')}
            </p>
            <p className="text-[13px] text-gray-600 leading-relaxed mb-4">
              {t('auth.modal.signOutConfirm.bodyGuest')}
            </p>

            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setPhase('account')}
                className="px-4 py-1.5 text-[13px] font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                type="button"
                onClick={confirmSignOut}
                className="px-4 py-1.5 text-[13px] font-medium text-white bg-gray-900 hover:bg-black rounded-lg transition-colors"
              >
                {t('auth.modal.signOutConfirm.confirm')}
              </button>
            </div>
          </>
        )}

        {/* Fallback (no session at all + signed-in account phase
            requested): drop back to signin form so the modal isn't
            empty. Defensive — shouldn't fire in normal use. */}
        {resolved === 'account' && !isSignedIn && (
          <>
            {/* Intentionally re-render the signin form contents inline
                without re-mounting state, by flipping phase. */}
            <button
              type="button"
              onClick={() => setPhase('signin')}
              className="mt-2 underline text-sm text-blue-600"
            >
              {t('auth.modal.signin.title')}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function firstLetter(email: string): string {
  const trimmed = email.trim();
  if (!trimmed) return '?';
  return trimmed[0].toUpperCase();
}
