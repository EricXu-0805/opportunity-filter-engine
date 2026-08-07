'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Copy, MessageSquarePlus, X } from 'lucide-react';
import { useT } from '@/i18n/client';
import { submitFeedback } from '@/lib/supabase';
import type { FeedbackCategory, FeedbackResult } from '@/lib/supabase';
import { track } from '@/lib/analytics';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { readLocalStorageJSON, writeLocalStorageJSON } from '@/lib/use-local-storage-json';
import { captureOwnerToken } from '@/lib/identity-owner';

type Status = 'idle' | 'sending' | 'done' | 'error';
type ErrorKind = 'generic' | 'no-session' | 'timeout';

// Categories offered in the select. '' is NOT a sixth category — it means the
// user didn't classify their report, and it is sent as NULL (026 allows it).
// Defaulting to 'other' would put words in their mouth and make "actively
// chose Other" indistinguishable from "ignored the dropdown" during triage.
const CATEGORIES: readonly FeedbackCategory[] = ['bug', 'idea', 'data_issue', 'account', 'other'];
const CATEGORY_LABEL_KEY: Record<FeedbackCategory, string> = {
  bug: 'feedback.categoryBug',
  idea: 'feedback.categoryIdea',
  data_issue: 'feedback.categoryDataIssue',
  account: 'feedback.categoryAccount',
  other: 'feedback.categoryOther',
};

const MESSAGE_MAX = 4000;
const SUBJECT_MAX = 120;
// A send that hasn't resolved in 15s is hung (asleep tab, dead socket, a
// Supabase call that will never settle). Without this the button stays
// disabled forever and the user's only escape is a reload.
const SEND_TIMEOUT_MS = 15_000;
// Same shape as supabase.ts's sign-in check: reject obvious junk, never try
// to out-clever RFC 5322.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface FeedbackDraft {
  message: string;
  email: string;
  category: FeedbackCategory | '';
  subject: string;
  /** Idempotency token; see mintClientToken. */
  clientToken: string;
}

const EMPTY_DRAFT: FeedbackDraft = { message: '', email: '', category: '', subject: '', clientToken: '' };

/**
 * One token per COMPOSED MESSAGE, minted when the user starts typing and
 * reused byte-for-byte on every retry of that message, so a retry after an
 * ambiguous failure (row committed, response lost) collides with the existing
 * ticket instead of opening a second one. Regenerated only after a confirmed
 * send — a failure must never rotate it, or the retry loses its dedupe.
 */
function mintClientToken(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID();
    }
  } catch { /* fall through */ }
  return `fb-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function readDraft(): FeedbackDraft {
  const raw = readLocalStorageJSON<Partial<FeedbackDraft>>(STORAGE_KEYS.FEEDBACK_DRAFT);
  if (!raw || typeof raw !== 'object') return EMPTY_DRAFT;
  const category = str(raw.category);
  return {
    message: str(raw.message).slice(0, MESSAGE_MAX),
    email: str(raw.email),
    category: (CATEGORIES as readonly string[]).includes(category) ? (category as FeedbackCategory) : '',
    subject: str(raw.subject).slice(0, SUBJECT_MAX),
    clientToken: str(raw.clientToken),
  };
}

function hasContent(draft: FeedbackDraft): boolean {
  return Boolean(draft.message.trim() || draft.email.trim() || draft.subject.trim());
}

// What the send race resolves to. 'timeout' is contributed only by the local
// timer leg — submitFeedback never returns it — so the two legs stay
// distinguishable while sharing the `ok` discriminant.
type SendOutcome = FeedbackResult | { ok: false; reason: 'timeout' };

// Always-available floating feedback affordance (bottom-LEFT, below modals at
// z-50 — bottom-right belongs to the mobile Ask-AI FAB on opportunity pages,
// which this button used to cover). Writes one TICKET row to Supabase via
// submitFeedback() under per-user RLS; failures surface inline and never
// throw. Email is optional (for a reply).
//
// W15: the in-progress draft is mirrored to localStorage so a reload or a
// failed send can't destroy what the user typed, and each composed message
// carries an idempotency token so retrying an ambiguous failure reuses the
// ticket instead of filing a duplicate. Success is still shown ONLY after a
// confirmed insert, and now quotes the ticket UUID the server returned.
export default function FeedbackWidget() {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<FeedbackDraft>(readDraft);
  const [status, setStatus] = useState<Status>('idle');
  const [errorKind, setErrorKind] = useState<ErrorKind>('generic');
  const [ticket, setTicket] = useState<{ id: string | null; duplicate: boolean } | null>(null);
  const [emailError, setEmailError] = useState(false);
  const [copied, setCopied] = useState(false);

  const persistedRef = useRef(false);

  const close = useCallback(() => setOpen(false), []);

  const patch = useCallback((next: Partial<FeedbackDraft>) => {
    setDraft((cur) => ({ ...cur, ...next }));
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  // Mirror the draft (message + email + category + subject + its token) so a
  // reload, an accidental close, or a failed send doesn't lose it. ONE draft,
  // no history: feedback routinely contains personal detail, so the local
  // copy exists only until the send is confirmed — the success path below
  // resets the draft, which removes the key here.
  useEffect(() => {
    const populated = hasContent(draft);
    // Nothing typed and nothing stored: don't touch storage at all (a user
    // who never opens the widget should leave no trace).
    if (!populated && !persistedRef.current) return;
    persistedRef.current = populated;
    // FEEDBACK_DRAFT is user-scoped (W15), so the write carries the owner
    // capability. Captured at the write itself: this mirror fires on the
    // typist's own keystroke, so action time IS write time — there is no
    // earlier moment the intent could have been captured at.
    writeLocalStorageJSON(STORAGE_KEYS.FEEDBACK_DRAFT, populated ? draft : null, captureOwnerToken());
  }, [draft]);

  const send = useCallback(async () => {
    const message = draft.message.trim();
    if (!message || status === 'sending') return;

    const email = draft.email.trim();
    if (email && !EMAIL_RE.test(email)) {
      // Storing a typo'd reply address looks like a channel we have and
      // don't — block the send and say so, rather than filing it silently.
      setEmailError(true);
      return;
    }
    setEmailError(false);

    // Composing normally mints the token; cover the paths that skip onChange
    // (a restored pre-W15 draft, an autofilled textarea).
    const clientToken = draft.clientToken || mintClientToken();
    if (clientToken !== draft.clientToken) patch({ clientToken });

    setStatus('sending');
    let timer: ReturnType<typeof setTimeout> | undefined;
    // The losing leg keeps running: if a "timed out" insert does land later,
    // the retry's identical token collides with it and resolves to the same
    // ticket, so the escape hatch can't manufacture a duplicate.
    const result: SendOutcome = await Promise.race<SendOutcome>([
      submitFeedback({
        message,
        email: email || null,
        category: draft.category || null,
        subject: draft.subject.trim() || null,
        clientToken,
        props: { path: typeof window !== 'undefined' ? window.location.pathname : '' },
      }),
      new Promise<SendOutcome>((resolve) => {
        timer = setTimeout(() => resolve({ ok: false, reason: 'timeout' }), SEND_TIMEOUT_MS);
      }),
    ]);
    if (timer !== undefined) clearTimeout(timer);

    if (!result.ok) {
      setErrorKind(
        result.reason === 'timeout'
          ? 'timeout'
          : result.reason === 'no-session' ? 'no-session' : 'generic',
      );
      // The draft is deliberately left untouched — every failure path keeps
      // what the user wrote (and its token) so the retry is a single tap.
      setStatus('error');
      return;
    }
    // 'duplicate' means the ticket was already created by an earlier attempt —
    // counting it again would inflate the funnel with a retry.
    if (result.reason === 'created') track('feedback_submitted');
    setTicket({ id: result.id, duplicate: result.reason === 'duplicate' });
    setStatus('done');
    // Confirmed insert — and only now — the local copy goes away and the next
    // message gets a fresh token.
    setDraft(EMPTY_DRAFT);
  }, [draft, patch, status]);

  const copyReference = useCallback(async () => {
    if (!ticket?.id) return;
    try {
      await navigator.clipboard.writeText(ticket.id);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard.writeText rejects in insecure contexts — the reference is
      // on screen and selectable, so this is a shortcut, not the only path.
    }
  }, [ticket]);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => {
          setStatus('idle');
          setTicket(null);
          setCopied(false);
          setEmailError(false);
          setOpen(true);
        }}
        aria-label={t('feedback.open')}
        data-testid="feedback-open"
        className="fixed bottom-4 left-2 sm:left-3 z-40 inline-flex items-center gap-2 rounded-full bg-gray-900 text-white text-[13px] font-medium pl-3 pr-4 py-2.5 shadow-lg hover:bg-gray-800 transition-colors"
      >
        <MessageSquarePlus className="w-4 h-4" aria-hidden="true" />
        <span className="hidden sm:inline">{t('feedback.button')}</span>
      </button>
    );
  }

  const errorKey = errorKind === 'no-session'
    ? 'feedback.errorOffline'
    : errorKind === 'timeout'
      ? 'feedback.errorTimeout'
      : 'feedback.error';

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
          {ticket?.duplicate && (
            <p className="mt-2 text-[12px] text-gray-500" data-testid="feedback-duplicate-note">
              {t('feedback.duplicateNote')}
            </p>
          )}
          {ticket?.id && (
            <div className="mt-4 rounded-xl bg-gray-50 border border-black/[0.06] px-3 py-2.5 text-left">
              <p className="text-[11px] uppercase tracking-wide text-gray-400">{t('feedback.reference')}</p>
              <div className="mt-1 flex items-center gap-2">
                <code
                  className="font-mono text-[13px] text-gray-900"
                  data-testid="feedback-reference"
                >
                  {ticket.id.slice(0, 8)}
                </code>
                <button
                  type="button"
                  onClick={copyReference}
                  aria-label={t('feedback.copyReference')}
                  data-testid="feedback-copy-reference"
                  className="inline-flex items-center gap-1 text-[12px] text-indigo-600 hover:text-indigo-700"
                >
                  {copied
                    ? <Check className="w-3.5 h-3.5" aria-hidden="true" />
                    : <Copy className="w-3.5 h-3.5" aria-hidden="true" />}
                  {copied ? t('feedback.copied') : t('feedback.copyReference')}
                </button>
              </div>
              <p className="mt-1.5 text-[11px] text-gray-500">{t('feedback.referenceHint')}</p>
            </div>
          )}
          <button
            type="button"
            onClick={close}
            className="mt-4 text-[13px] font-medium text-indigo-600 hover:text-indigo-700"
          >
            {t('feedback.close')}
          </button>
        </div>
      ) : (
        <form
          className="p-4 space-y-3"
          noValidate
          onSubmit={(e) => { e.preventDefault(); void send(); }}
        >
          <p className="text-[12px] text-gray-500">{t('feedback.subtitle')}</p>

          <label className="block">
            <span className="sr-only">{t('feedback.categoryLabel')}</span>
            <select
              value={draft.category}
              onChange={(e) => patch({ category: e.target.value as FeedbackCategory | '' })}
              aria-label={t('feedback.categoryLabel')}
              data-testid="feedback-category"
              className="w-full rounded-xl border border-gray-200 px-3 py-2 text-[13px] text-gray-900 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">{t('feedback.categoryUnset')}</option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{t(CATEGORY_LABEL_KEY[c])}</option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="sr-only">{t('feedback.subjectLabel')}</span>
            <input
              type="text"
              value={draft.subject}
              onChange={(e) => patch({ subject: e.target.value })}
              maxLength={SUBJECT_MAX}
              placeholder={t('feedback.subjectPlaceholder')}
              data-testid="feedback-subject"
              className="w-full rounded-xl border border-gray-200 px-3 py-2 text-[13px] text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </label>

          <label className="block">
            <span className="sr-only">{t('feedback.messageLabel')}</span>
            <textarea
              value={draft.message}
              onChange={(e) => {
                const message = e.target.value;
                // Start the idempotency token the moment composing starts,
                // and never rotate it mid-message.
                setDraft((cur) => ({
                  ...cur,
                  message,
                  clientToken: cur.clientToken || mintClientToken(),
                }));
              }}
              placeholder={t('feedback.placeholder')}
              rows={4}
              maxLength={MESSAGE_MAX}
              aria-label={t('feedback.messageLabel')}
              className="w-full rounded-xl border border-gray-200 px-3 py-2 text-[14px] text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
            />
            <span
              className="mt-1 block text-right text-[10px] text-gray-400"
              data-testid="feedback-counter"
            >
              {t('feedback.counter', { count: draft.message.length, max: MESSAGE_MAX })}
            </span>
          </label>

          <label className="block">
            <span className="sr-only">{t('feedback.emailLabel')}</span>
            <input
              type="email"
              value={draft.email}
              onChange={(e) => { patch({ email: e.target.value }); setEmailError(false); }}
              placeholder={t('feedback.emailPlaceholder')}
              aria-invalid={emailError}
              aria-describedby={emailError ? 'feedback-email-error' : undefined}
              data-testid="feedback-email"
              className={`w-full rounded-xl border px-3 py-2 text-[13px] text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 ${
                emailError
                  ? 'border-red-300 focus:ring-red-400'
                  : 'border-gray-200 focus:ring-indigo-500'
              }`}
            />
          </label>
          {emailError && (
            <p
              id="feedback-email-error"
              className="text-[12px] text-red-600"
              role="alert"
              data-testid="feedback-email-error"
            >
              {t('feedback.emailInvalid')}
            </p>
          )}

          {status === 'error' && (
            <p className="text-[12px] text-red-600" role="alert" data-testid="feedback-error">
              {t(errorKey)}
            </p>
          )}

          <button
            type="submit"
            disabled={!draft.message.trim() || status === 'sending'}
            data-testid="feedback-send"
            className="w-full rounded-xl bg-gray-900 text-white text-[14px] font-medium py-2.5 hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {status === 'sending' ? t('feedback.sending') : t('feedback.send')}
          </button>
          <p className="text-[11px] text-gray-400 text-center">{t('feedback.draftSaved')}</p>
        </form>
      )}
    </div>
  );
}
