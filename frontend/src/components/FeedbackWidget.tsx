'use client';

import { useCallback, useEffect, useState } from 'react';
import { MessageSquarePlus, X } from 'lucide-react';
import { useT } from '@/i18n/client';
import { submitFeedback } from '@/lib/supabase';
import { track } from '@/lib/analytics';

type Status = 'idle' | 'sending' | 'done' | 'error';

// Always-available floating feedback affordance (bottom-LEFT, below modals at
// z-50 — bottom-right belongs to the mobile Ask-AI FAB on opportunity pages,
// which this button used to cover). Writes one row to Supabase via
// submitFeedback() under per-user RLS; failures surface inline and never
// throw. Email is optional (for a reply).
export default function FeedbackWidget() {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState('');
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<Status>('idle');

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const send = async () => {
    const text = message.trim();
    if (!text || status === 'sending') return;
    setStatus('sending');
    const ok = await submitFeedback(text, email.trim() || null, {
      path: typeof window !== 'undefined' ? window.location.pathname : '',
    });
    if (ok) {
      track('feedback_submitted');
      setStatus('done');
      setMessage('');
      setEmail('');
    } else {
      setStatus('error');
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => { setStatus('idle'); setOpen(true); }}
        aria-label={t('feedback.open')}
        data-testid="feedback-open"
        className="fixed bottom-4 left-2 sm:left-3 z-40 inline-flex items-center gap-2 rounded-full bg-gray-900 text-white text-[13px] font-medium pl-3 pr-4 py-2.5 shadow-lg hover:bg-gray-800 transition-colors"
      >
        <MessageSquarePlus className="w-4 h-4" aria-hidden="true" />
        <span className="hidden sm:inline">{t('feedback.button')}</span>
      </button>
    );
  }

  return (
    <div
      role="dialog"
      aria-label={t('feedback.title')}
      data-testid="feedback-panel"
      className="fixed bottom-4 left-2 sm:left-3 z-40 w-[calc(100vw-1rem)] max-w-sm rounded-2xl bg-white shadow-2xl border border-black/[0.06] overflow-hidden"
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-black/[0.06]">
        <p className="text-[14px] font-semibold text-gray-900">{t('feedback.title')}</p>
        <button
          type="button"
          onClick={close}
          aria-label={t('feedback.close')}
          className="p-1 -mr-1 text-gray-400 hover:text-gray-700 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {status === 'done' ? (
        <div className="px-4 py-6 text-center" data-testid="feedback-thanks">
          <p className="text-[14px] text-gray-700">{t('feedback.thanks')}</p>
          <button
            type="button"
            onClick={close}
            className="mt-4 text-[13px] font-medium text-indigo-600 hover:text-indigo-700"
          >
            {t('feedback.close')}
          </button>
        </div>
      ) : (
        <div className="p-4 space-y-3">
          <p className="text-[12px] text-gray-500">{t('feedback.subtitle')}</p>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder={t('feedback.placeholder')}
            rows={4}
            aria-label={t('feedback.title')}
            className="w-full rounded-xl border border-gray-200 px-3 py-2 text-[14px] text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
          />
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder={t('feedback.emailPlaceholder')}
            className="w-full rounded-xl border border-gray-200 px-3 py-2 text-[13px] text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
          {status === 'error' && (
            <p className="text-[12px] text-red-600" role="alert">{t('feedback.error')}</p>
          )}
          <button
            type="button"
            onClick={send}
            disabled={!message.trim() || status === 'sending'}
            data-testid="feedback-send"
            className="w-full rounded-xl bg-gray-900 text-white text-[14px] font-medium py-2.5 hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {status === 'sending' ? t('feedback.sending') : t('feedback.send')}
          </button>
        </div>
      )}
    </div>
  );
}
