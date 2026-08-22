'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Mail, CheckCircle, AlertCircle, Loader2, X } from 'lucide-react';
import { ApiError } from '@/lib/api';
import { getAuthState } from '@/lib/supabase';
import { useAuthModal } from '@/lib/auth-modal-context';
import { useT } from '@/i18n/client';

type SendResult = { ok: boolean; count?: number };

interface EmailMeButtonProps {
  label: string;
  title?: string;
  /** Shown in the dialog before sending, when the digest will not carry
   *  everything the caller has (the backend caps a digest at 50 items).
   *  Stated up front rather than after the fact: once the mail is sent there
   *  is nothing in it that reveals what was left out. */
  notice?: string;
  onSend: (email: string) => Promise<SendResult>;
  disabled?: boolean;
  className?: string;
}

/** Who, if anyone, this digest may be sent to.
 *
 *  Resolved from the session rather than typed. The address used to be a free
 *  text field, which is what made both endpoints a way to mail a JoinALab
 *  digest to a stranger; the server now refuses any recipient but the caller's
 *  own confirmed address, and this is the UI telling the same truth. Three
 *  states, because "you cannot send" has two different remedies.
 */
type Recipient =
  | { kind: 'loading' }
  | { kind: 'anonymous' }
  | { kind: 'unconfirmed' }
  | { kind: 'ready'; email: string };

/** GoTrue's own confirmation stamp, including the legacy field older projects
 *  still emit. Same pair the server reads, so the dialog and the endpoint
 *  cannot disagree about whether an address may be written to. */
function isConfirmed(
  user: { email_confirmed_at?: string | null; confirmed_at?: string | null } | null,
): boolean {
  return Boolean(user?.email_confirmed_at || user?.confirmed_at);
}

export default function EmailMeButton({
  label,
  title,
  notice,
  onSend,
  disabled,
  className,
}: EmailMeButtonProps) {
  const { t } = useT();
  const { openModal } = useAuthModal();
  const [open, setOpen] = useState(false);
  const [recipient, setRecipient] = useState<Recipient>({ kind: 'loading' });
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  const [message, setMessage] = useState<string | null>(null);
  const sendRef = useRef<HTMLButtonElement>(null);

  const handleOpen = useCallback(() => {
    setOpen(true);
    setRecipient({ kind: 'loading' });
    void getAuthState().then(({ session, isAnonymous, user, email }) => {
      if (!session || isAnonymous) setRecipient({ kind: 'anonymous' });
      // An address GoTrue holds but the account has not confirmed is exactly
      // the case this gate exists for: someone else's address, entered at
      // sign-up. Confirmation comes from the user record, NOT from `email`
      // being present — `getAuthState().email` is the raw address and stays
      // populated while unconfirmed, because the account menu still has to
      // display it. Reading absence as "unconfirmed" would make this state
      // unreachable and push the discovery to after the send.
      else if (!email || !isConfirmed(user)) setRecipient({ kind: 'unconfirmed' });
      else setRecipient({ kind: 'ready', email: email.trim().toLowerCase() });
    });
    setTimeout(() => sendRef.current?.focus(), 50);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', onEsc);
    return () => window.removeEventListener('keydown', onEsc);
  }, [open]);

  const submit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (recipient.kind !== 'ready') return;
    setState('sending');
    setMessage(null);
    try {
      await onSend(recipient.email);
      setState('sent');
      setMessage(t('email.sentMessage'));
      setTimeout(() => { setOpen(false); setState('idle'); setMessage(null); }, 2500);
    } catch (err) {
      setState('error');
      const msg = err instanceof Error ? err.message : String(err);
      if (err instanceof ApiError && err.status === 503) setMessage(t('email.notConfigured'));
      else if (err instanceof ApiError && err.status === 429) setMessage(t('email.rateLimit'));
      // The session expired between opening the dialog and submitting, or the
      // server disagrees about who this is. Say which, rather than "failed".
      else if (err instanceof ApiError && err.status === 401) setMessage(t('email.signInRequired'));
      // Both of the server's identity refusals are 409, so the CODE is what
      // separates them. Branching on the status alone answered an unconfirmed
      // reader with "nothing was sent to the address you entered" — about a
      // field this dialog no longer has, and with the wrong remedy.
      else if (err instanceof ApiError && err.code === 'EMAIL_NOT_CONFIRMED') setMessage(t('email.confirmRequired'));
      else if (err instanceof ApiError && err.code === 'RECIPIENT_NOT_SELF') setMessage(t('email.notSelf'));
      // Tolerate older/custom callers that still throw a status-bearing string.
      else if (msg.includes('503')) setMessage(t('email.notConfigured'));
      else if (msg.includes('429')) setMessage(t('email.rateLimit'));
      else setMessage(t('email.sendFailed'));
    }
  }, [recipient, onSend, t]);

  return (
    <>
      <button
        type="button"
        onClick={handleOpen}
        disabled={disabled}
        title={title}
        className={className ?? 'inline-flex items-center gap-2 px-3 py-2 text-[12px] font-medium text-gray-600 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors disabled:opacity-50'}
      >
        <Mail className="w-3.5 h-3.5" />
        {label}
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[55] flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
        >
          <div
            className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div className="relative w-full max-w-md bg-white rounded-2xl shadow-2xl p-6 animate-in">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="absolute top-3 right-3 p-1 rounded-lg hover:bg-gray-100"
              aria-label={t('common.close')}
            >
              <X className="w-4 h-4 text-gray-400" />
            </button>

            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-xl bg-indigo-50 flex items-center justify-center">
                <Mail className="w-5 h-5 text-indigo-600" />
              </div>
              <div>
                <h2 className="text-[16px] font-semibold text-gray-900">{t('email.title')}</h2>
                <p className="text-[12px] text-gray-500">{t('email.subtitle')}</p>
              </div>
            </div>

            {notice && (
              <p
                role="status"
                className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-900"
              >
                {notice}
              </p>
            )}

            <form onSubmit={submit} className="space-y-3">
              {recipient.kind === 'ready' && (
                <div className="block">
                  <span className="text-[12px] font-medium text-gray-700">{t('email.emailLabel')}</span>
                  <p className="mt-1.5 w-full px-3.5 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-[14px] text-gray-700 break-all">
                    {recipient.email}
                  </p>
                </div>
              )}
              {recipient.kind === 'anonymous' && (
                <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2.5">
                  <p className="text-[13px] text-indigo-900">{t('email.signInRequired')}</p>
                  <button
                    type="button"
                    onClick={() => { setOpen(false); openModal({ reason: 'email-digest' }); }}
                    className="mt-2 inline-flex px-3 py-1.5 text-[12px] font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700"
                  >
                    {t('email.signInCta')}
                  </button>
                </div>
              )}
              {recipient.kind === 'unconfirmed' && (
                <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-[13px] text-amber-900">
                  {t('email.confirmRequired')}
                </p>
              )}

              {message && state === 'sent' && (
                <div className="flex items-center gap-2 text-[13px] text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2">
                  <CheckCircle className="w-4 h-4 shrink-0" />
                  <span>{message}</span>
                </div>
              )}
              {message && state === 'error' && (
                <div className="flex items-center gap-2 text-[13px] text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{message}</span>
                </div>
              )}

              <div className="flex gap-2 justify-end pt-1">
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="px-4 py-2 text-[13px] font-medium text-gray-600 hover:bg-gray-50 rounded-xl"
                >
                  {t('common.cancel')}
                </button>
                <button
                  ref={sendRef}
                  type="submit"
                  disabled={state === 'sending' || state === 'sent' || recipient.kind !== 'ready'}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-[13px] font-semibold text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 disabled:opacity-50"
                >
                  {state === 'sending' && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  {state === 'sent' ? t('email.sent') : t('email.send')}
                </button>
              </div>

              <p className="text-[10px] text-gray-400 pt-1">
                {t('email.privacyNote')}
              </p>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
