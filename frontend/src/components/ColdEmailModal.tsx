'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  X,
  Copy,
  ExternalLink,
  Loader2,
  CheckCircle,
  AlertCircle,
  Mail,
  Send,
  Sparkles,
} from 'lucide-react';
import { generateColdEmail, getEmailVariants, refineEmail } from '@/lib/api';
import type { ProfileData, EmailVariant, LabType, ColdEmailFallbackReason } from '@/lib/types';
import { useT } from '@/i18n/client';
import LabTypeBadge from './LabTypeBadge';
import EmailTipsPanel from './EmailTipsPanel';

const AI_VARIANT_ID = 'ai';

interface ColdEmailModalProps {
  isOpen: boolean;
  onClose: () => void;
  profile: ProfileData;
  opportunityId: string;
  opportunityTitle: string;
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

const QUICK_ACTION_KEYS = ['formal', 'shorter', 'enthusiastic', 'coursework'] as const;
type QuickActionKey = typeof QUICK_ACTION_KEYS[number];

type Replier = (path: string, vars?: Record<string, string | number>) => string;

// R72-A: pick the right fallback hint. 'fabrication' (the AI invented an
// unverifiable detail and was rejected) gets a distinct message — the old
// "no provider configured" line would be misleading since AI *is* wired.
function aiFallbackMessage(
  reason: ColdEmailFallbackReason | null | undefined,
  t: Replier,
): string {
  if (reason === 'fabrication') return t('coldEmail.aiFallbackFabrication');
  if (reason === 'not_configured') return t('coldEmail.aiFallback');
  return t('coldEmail.aiFallbackGeneric');
}

function applyQuickEdit(
  body: string,
  action: QuickActionKey,
  profile: ProfileData,
  t: Replier,
): { body: string; reply: string } {
  switch (action) {
    case 'formal': {
      let updated = body
        .replace(/I would love/g, 'I would greatly appreciate')
        .replace(/I am a fast learner/g, 'I am committed to continuous professional development')
        .replace(/Would you be open to/g, 'Would it be possible to arrange')
        .replace(/a short meeting/g, 'a brief meeting at your convenience')
        .replace(/a brief conversation/g, 'a brief meeting at your convenience')
        .replace(/Best regards/g, 'Respectfully')
        .replace(/Best,/g, 'Respectfully,');
      if (updated === body) updated = body.replace(/I really enjoyed/g, 'I was greatly impressed by');
      return { body: updated, reply: t('coldEmail.replies.formal') };
    }
    case 'shorter': {
      const lines = body.split('\n').filter((l) => l.trim());
      const filtered = lines.filter(
        (l) =>
          !l.includes('I am a fast learner') &&
          !l.includes('I am confident I can') &&
          !l.includes('always eager'),
      );
      return { body: filtered.join('\n'), reply: t('coldEmail.replies.shorter') };
    }
    case 'enthusiastic': {
      const updated = body
        .replace(/I am very interested in/g, 'I am truly excited about')
        .replace(/I really enjoyed learning/g, 'I was fascinated by')
        .replace(/I would love the chance/g, 'I would be thrilled at the opportunity')
        .replace(/I would greatly appreciate the chance/g, 'I would be thrilled at the opportunity');
      return { body: updated, reply: t('coldEmail.replies.enthusiastic') };
    }
    case 'coursework': {
      const courses = profile.coursework ?? [];
      if (courses.length === 0) {
        return { body, reply: t('coldEmail.replies.courseworkNone') };
      }
      const courseStr = courses.slice(0, 4).join(', ');
      const insertion = `\n\nI have completed relevant coursework including ${courseStr}.`;
      const closingIdx = body.lastIndexOf('\n\nBest');
      const respectIdx = body.lastIndexOf('\n\nRespectfully');
      const insertAt = Math.max(closingIdx, respectIdx);
      const reply = t('coldEmail.replies.courseworkAdded', { list: courseStr });
      if (insertAt > 0) {
        return {
          body: body.slice(0, insertAt) + insertion + body.slice(insertAt),
          reply,
        };
      }
      return { body: body + insertion, reply };
    }
    default:
      return { body, reply: t('coldEmail.replies.noChanges') };
  }
}

export default function ColdEmailModal({
  isOpen,
  onClose,
  profile,
  opportunityId,
  opportunityTitle,
}: ColdEmailModalProps) {
  const { t } = useT();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [variants, setVariants] = useState<EmailVariant[]>([]);
  const [aiVariant, setAiVariant] = useState<EmailVariant | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [activeVariant, setActiveVariant] = useState(0);
  const [labType, setLabType] = useState<LabType | null>(null);

  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [recipient, setRecipient] = useState('');
  const [copied, setCopied] = useState(false);

  const allVariants: EmailVariant[] = aiVariant ? [...variants, aiVariant] : variants;

  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const chatEndRef = useRef<HTMLDivElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  const fetchVariants = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getEmailVariants(profile, opportunityId);
      setVariants(data.variants);
      const inferredLabType =
        data.lab_type
        ?? (data.variants.find((v) => v.lab_type)?.lab_type ?? null);
      setLabType(inferredLabType);
      if (data.variants.length > 0) {
        const first = data.variants[0];
        setSubject(first.subject);
        setBody(first.body);
        setRecipient(first.recipient_email);
        setActiveVariant(0);
      }
      setChatMessages([
        { role: 'assistant', content: t('coldEmail.generated', { count: data.variants.length }) },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('coldEmail.failedGenerate'));
    } finally {
      setLoading(false);
    }
  }, [profile, opportunityId, t]);

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect --
       Modal-lifecycle effect. Open path calls fetchVariants() whose
       sync prefix flips setLoading(true) before any await. Cleanup
       path resets every internal state slice so the next open()
       starts from a known-empty surface — splitting this into two
       effects would race the next open's fetchVariants() with stale
       residue from the previous session. */
    if (isOpen) fetchVariants();
    return () => {
      setVariants([]);
      setAiVariant(null);
      setAiLoading(false);
      setLabType(null);
      setSubject('');
      setBody('');
      setCopied(false);
      setError(null);
      setChatMessages([]);
      setChatInput('');
    };
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [isOpen, fetchVariants]);

  useEffect(() => {
    if (!isOpen) return;
    previouslyFocusedRef.current = document.activeElement as HTMLElement;

    const modal = modalRef.current;
    if (modal) {
      const focusable = modal.querySelector<HTMLElement>(
        'button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])',
      );
      focusable?.focus();
    }

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== 'Tab' || !modalRef.current) return;
      const focusables = modalRef.current.querySelectorAll<HTMLElement>(
        'button, [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = prevOverflow;
      previouslyFocusedRef.current?.focus();
    };
  }, [isOpen, onClose]);

  useEffect(() => {
    if (isOpen) document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, [isOpen]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  function selectVariant(idx: number) {
    const v = allVariants[idx];
    if (!v) return;
    setActiveVariant(idx);
    setSubject(v.subject);
    setBody(v.body);
    setRecipient(v.recipient_email);
    setChatMessages((prev) => [
      ...prev,
      { role: 'assistant', content: t('coldEmail.switched', { label: v.label }) },
    ]);
  }

  async function handleAiPillClick() {
    if (aiLoading) return;
    const aiIdx = variants.length;

    if (aiVariant) {
      selectVariant(aiIdx);
      return;
    }

    setAiLoading(true);
    setChatMessages((prev) => [
      ...prev,
      { role: 'assistant', content: t('coldEmail.aiGenerating') },
    ]);

    try {
      const resp = await generateColdEmail(profile, opportunityId, { engine: 'ai' });
      const v: EmailVariant = {
        id: AI_VARIANT_ID,
        label: t('coldEmail.aiVariantLabel'),
        subject: resp.subject,
        body: resp.body,
        recipient_email: resp.recipient_email,
        mailto_link: resp.mailto_link,
        lab_type: resp.lab_type ?? labType ?? null,
      };
      setAiVariant(v);
      setActiveVariant(aiIdx);
      setSubject(v.subject);
      setBody(v.body);
      setRecipient(v.recipient_email);
      if (resp.lab_type && resp.lab_type !== labType) setLabType(resp.lab_type);
      setChatMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: resp.method === 'ai' ? t('coldEmail.aiGenerated') : aiFallbackMessage(resp.fallback_reason, t),
        },
      ]);
    } catch {
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: t('coldEmail.aiFailed') },
      ]);
    } finally {
      setAiLoading(false);
    }
  }

  function handleQuickAction(key: QuickActionKey) {
    const label = t(`coldEmail.quickActions.${key}`);
    setChatMessages((prev) => [...prev, { role: 'user', content: label }]);
    const { body: newBody, reply } = applyQuickEdit(body, key, profile, t);
    setBody(newBody);
    setChatMessages((prev) => [...prev, { role: 'assistant', content: reply }]);
  }

  async function handleChatSubmit() {
    const msg = chatInput.trim();
    if (!msg) return;
    setChatInput('');
    setChatMessages((prev) => [...prev, { role: 'user', content: msg }]);
    setChatMessages((prev) => [...prev, { role: 'assistant', content: t('coldEmail.editing') }]);

    try {
      const result = await refineEmail(body, msg);
      setBody(result.body);
      setChatMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: 'assistant',
          content:
            result.method === 'llm'
              ? t('coldEmail.doneLlm')
              : result.fallback_reason === 'fabrication'
                ? t('coldEmail.refineFabrication')
                : t('coldEmail.doneFallback'),
        };
        return updated;
      });
    } catch {
      setChatMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: 'assistant',
          content: t('coldEmail.editFailed'),
        };
        return updated;
      });
    }
  }

  async function handleCopy() {
    await navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function getMailtoLink(provider: 'default' | 'gmail' | 'outlook' = 'default'): string {
    const to = recipient || '';
    const subj = encodeURIComponent(subject);
    const b = encodeURIComponent(body);
    if (provider === 'gmail') return `https://mail.google.com/mail/?view=cm&to=${to}&su=${subj}&body=${b}`;
    if (provider === 'outlook') return `https://outlook.office365.com/mail/deeplink/compose?to=${encodeURIComponent(to)}&subject=${subj}&body=${b}`;
    return `mailto:${to}?subject=${subj}&body=${b}`;
  }

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex sm:items-center sm:justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="email-modal-title"
    >
      <div className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm" onClick={onClose} aria-hidden="true" />

      <div
        ref={modalRef}
        className="relative w-full sm:max-w-5xl sm:mx-4 bg-white sm:rounded-2xl shadow-2xl h-full sm:h-auto sm:max-h-[90vh] flex flex-col overflow-hidden animate-in"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 sm:px-6 py-3 sm:py-4 border-b border-gray-100 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-blue-50 flex items-center justify-center" aria-hidden="true">
              <Mail className="w-5 h-5 text-blue-600" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2 id="email-modal-title" className="text-lg font-bold text-gray-900">{t('coldEmail.title')}</h2>
                <LabTypeBadge labType={labType} />
              </div>
              <p className="text-sm text-gray-500 truncate max-w-md">{opportunityTitle}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 transition-colors"
            aria-label={t('coldEmail.closeAria')}
          >
            <X className="w-5 h-5 text-gray-400" aria-hidden="true" />
          </button>
        </div>

        {/* Loading / Error */}
        {loading && (
          <div className="flex flex-col items-center justify-center py-20 gap-4">
            <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
            <p className="text-sm text-gray-500">{t('coldEmail.generating')}</p>
          </div>
        )}
        {error && (
          <div className="flex flex-col items-center justify-center py-20 gap-4">
            <AlertCircle className="w-8 h-8 text-red-500" />
            <p className="text-sm text-red-600">{error}</p>
            <button type="button" onClick={fetchVariants} className="text-sm text-blue-600 underline hover:text-blue-700">{t('coldEmail.tryAgain')}</button>
          </div>
        )}

        {/* Two-panel layout */}
        {!loading && !error && (
          <>
            <div className="flex-1 flex flex-col md:flex-row min-h-0">
              <div className="flex-1 flex flex-col md:border-r border-gray-100 min-w-0">
                {/* Variant tabs */}
                <div className="flex items-center gap-1 px-5 pt-4 pb-2 shrink-0">
                  {variants.map((v, i) => (
                    <button
                      key={v.id}
                      type="button"
                      onClick={() => selectVariant(i)}
                      className={`px-3 py-1.5 rounded-full text-[12px] font-medium transition-all duration-200 ${
                        activeVariant === i
                          ? 'bg-blue-600 text-white'
                          : 'bg-black/[0.04] text-gray-500 hover:bg-black/[0.08]'
                      }`}
                    >
                      {v.label}
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={handleAiPillClick}
                    disabled={aiLoading}
                    title={t('coldEmail.aiVariantTitle')}
                    className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-[12px] font-medium transition-all duration-200 disabled:opacity-60 disabled:cursor-wait ${
                      activeVariant === variants.length && aiVariant
                        ? 'bg-gradient-to-r from-indigo-600 to-fuchsia-500 text-white shadow-sm'
                        : 'bg-indigo-50 text-indigo-600 hover:bg-indigo-100'
                    }`}
                  >
                    {aiLoading ? (
                      <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />
                    ) : null}
                    {t('coldEmail.aiVariantLabel')}
                  </button>
                </div>

                <div className="flex-1 overflow-y-auto px-5 pb-4 space-y-4">
                  <div>
                    <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                      {t('coldEmail.to')}
                      {!recipient && (
                        <span className="ml-2 text-amber-500 normal-case tracking-normal font-normal">
                          {t('coldEmail.toHint')}
                        </span>
                      )}
                    </label>
                    <input
                      type="email"
                      value={recipient}
                      onChange={(e) => setRecipient(e.target.value)}
                      placeholder={t('coldEmail.toPlaceholder')}
                      className={`w-full px-3.5 py-2.5 border rounded-xl text-sm text-gray-900 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none transition-all ${!recipient ? 'border-amber-300 bg-amber-50/30' : 'border-gray-200'}`}
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">{t('coldEmail.subject')}</label>
                    <input
                      type="text"
                      value={subject}
                      onChange={(e) => setSubject(e.target.value)}
                      className="w-full px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm font-medium text-gray-900 focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none transition-all"
                    />
                  </div>
                  <div className="flex-1 flex flex-col">
                    <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">{t('coldEmail.body')}</label>
                    <textarea
                      value={body}
                      onChange={(e) => setBody(e.target.value)}
                      rows={12}
                      className="w-full flex-1 px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-700 leading-relaxed focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none transition-all resize-y"
                    />
                  </div>
                </div>
              </div>

              <div className="w-full md:w-72 lg:w-80 flex flex-col bg-gray-50/60 min-w-0 border-t md:border-t-0 border-gray-100">
                <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 shrink-0">
                  <Sparkles className="w-4 h-4 text-indigo-500" />
                  <span className="text-sm font-semibold text-gray-700">{t('coldEmail.refine')}</span>
                </div>

                {labType && (
                  <div className="px-4 pt-3 shrink-0">
                    <EmailTipsPanel labType={labType} />
                  </div>
                )}

                {/* Chat messages */}
                <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
                  {chatMessages.map((msg, i) => (
                    <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div
                        className={`max-w-[90%] px-3 py-2 rounded-xl text-[13px] leading-relaxed ${
                          msg.role === 'user'
                            ? 'bg-blue-600 text-white rounded-br-sm'
                            : 'bg-white text-gray-700 border border-gray-200 rounded-bl-sm shadow-sm'
                        }`}
                      >
                        {msg.content}
                      </div>
                    </div>
                  ))}
                  <div ref={chatEndRef} />
                </div>

                {/* Quick actions */}
                <div className="px-4 pb-2 shrink-0">
                  <div className="flex flex-wrap gap-1.5">
                    {QUICK_ACTION_KEYS.map((key) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => handleQuickAction(key)}
                        className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-white border border-gray-200 text-gray-600 hover:bg-gray-100 transition-colors"
                      >
                        {t(`coldEmail.quickActions.${key}`)}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Chat input */}
                <div className="px-4 pb-4 pt-2 shrink-0">
                  <form
                    onSubmit={(e) => { e.preventDefault(); handleChatSubmit(); }}
                    className="flex items-center gap-2"
                  >
                    <input
                      type="text"
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      placeholder={t('coldEmail.refinePlaceholder')}
                      className="flex-1 px-3 py-2 border border-gray-200 rounded-xl text-sm bg-white placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all"
                    />
                    <button
                      type="submit"
                      disabled={!chatInput.trim()}
                      className="p-2 rounded-xl bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
                    >
                      <Send className="w-4 h-4" />
                    </button>
                  </form>
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-3 px-6 py-3 border-t border-gray-100 bg-gray-50/50 shrink-0">
              <button
                type="button"
                onClick={handleCopy}
                className="inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors"
              >
                {copied ? (
                  <><CheckCircle className="w-4 h-4 text-emerald-500" />{t('coldEmail.copied')}</>
                ) : (
                  <><Copy className="w-4 h-4" />{t('coldEmail.copy')}</>
                )}
              </button>
              <div className="flex items-stretch rounded-xl overflow-hidden shadow-sm">
                <button
                  type="button"
                  onClick={() => { window.open(getMailtoLink('default'), '_blank'); }}
                  className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-semibold text-white bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600 transition-all"
                >
                  <ExternalLink className="w-4 h-4" />
                  {t('coldEmail.openInEmail')}
                </button>
                <div className="w-px bg-blue-400" />
                <button
                  type="button"
                  onClick={() => { window.open(getMailtoLink('gmail'), '_blank'); }}
                  className="inline-flex items-center justify-center px-3 py-2.5 text-[11px] font-semibold text-blue-100 bg-blue-600 hover:bg-blue-700 transition-colors"
                  title={t('coldEmail.openGmailTitle')}
                >
                  {t('coldEmail.gmail')}
                </button>
                <button
                  type="button"
                  onClick={() => { window.open(getMailtoLink('outlook'), '_blank'); }}
                  className="inline-flex items-center justify-center px-3 py-2.5 text-[11px] font-semibold text-blue-100 bg-blue-600 hover:bg-blue-700 transition-colors"
                  title={t('coldEmail.openOutlookTitle')}
                >
                  {t('coldEmail.outlook')}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
