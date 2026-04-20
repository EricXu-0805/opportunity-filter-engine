'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Mail, CheckCircle, AlertCircle, Loader2, X } from 'lucide-react';
import { useT } from '@/i18n/client';

type SendResult = { ok: boolean; count?: number };

interface EmailMeButtonProps {
  label: string;
  title?: string;
  onSend: (email: string) => Promise<SendResult>;
  disabled?: boolean;
  className?: string;
}

const LS_KEY = 'ofe_email_hint';

export default function EmailMeButton({
  label,
  title,
  onSend,
  disabled,
  className,
}: EmailMeButtonProps) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  const [message, setMessage] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      try {
        const cached = localStorage.getItem(LS_KEY);
        if (cached) setEmail(cached);
      } catch { /* noop */ }
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', onEsc);
    return () => window.removeEventListener('keydown', onEsc);
  }, [open]);

  const submit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = email.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) {
      setState('error');
      setMessage(t('email.invalidEmail'));
      return;
    }
    setState('sending');
    setMessage(null);
    try {
      await onSend(trimmed);
      try { localStorage.setItem(LS_KEY, trimmed); } catch { /* quota */ }
      setState('sent');
      setMessage(t('email.sentMessage'));
      setTimeout(() => { setOpen(false); setState('idle'); setMessage(null); }, 2500);
    } catch (err) {
      setState('error');
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes('503')) setMessage(t('email.notConfigured'));
      else if (msg.includes('429')) setMessage(t('email.rateLimit'));
      else setMessage(t('email.sendFailed'));
    }
  }, [email, onSend, t]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={disabled}
        title={title}
        className={className ?? 'inline-flex items-center gap-2 px-3 py-2 text-[12px] font-medium text-gray-600 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors disabled:opacity-50'}
      >
        <Mail className="w-3.5 h-3.5" />
        {label}
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
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
              <div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center">
                <Mail className="w-5 h-5 text-blue-600" />
              </div>
              <div>
                <h2 className="text-[16px] font-semibold text-gray-900">{t('email.title')}</h2>
                <p className="text-[12px] text-gray-500">{t('email.subtitle')}</p>
              </div>
            </div>

            <form onSubmit={submit} className="space-y-3">
              <label className="block">
                <span className="text-[12px] font-medium text-gray-700">{t('email.emailLabel')}</span>
                <input
                  ref={inputRef}
                  type="email"
                  required
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  disabled={state === 'sending' || state === 'sent'}
                  className="mt-1.5 w-full px-3.5 py-2.5 border border-gray-200 rounded-xl text-[14px] focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none disabled:bg-gray-50"
                />
              </label>

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
                  type="submit"
                  disabled={state === 'sending' || state === 'sent' || !email.trim()}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-[13px] font-semibold text-white bg-blue-600 rounded-xl hover:bg-blue-700 disabled:opacity-50"
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
