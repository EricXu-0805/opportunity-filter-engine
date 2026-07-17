'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  X,
  Copy,
  ExternalLink,
  Loader2,
  CheckCircle,
  AlertCircle,
  BellRing,
  Mail,
  Send,
  Sparkles,
} from 'lucide-react';
import { generateColdEmail, getEmailVariants, refineEmail, extractResumeBullets } from '@/lib/api';
import {
  getInteractionDetail,
  trackInteraction,
  updateInteractionDetails,
} from '@/lib/supabase';
import type { ProfileData, EmailVariant, LabType, EmailStyle, ColdEmailFallbackReason } from '@/lib/types';
import { useT } from '@/i18n/client';
import LabTypeBadge from './LabTypeBadge';
import EmailTipsPanel from './EmailTipsPanel';

const AI_VARIANT_ID = 'ai';
const STYLE_KEYS: readonly EmailStyle[] = ['professional', 'warm', 'friendly', 'lively'];

interface ColdEmailModalProps {
  isOpen: boolean;
  onClose: () => void;
  profile: ProfileData;
  opportunityId: string;
  opportunityTitle: string;
  /** Slug of the opportunity's host school — lets the no-email explainer link
   *  the student to their campus' official self-lookup directory. */
  opportunitySchool?: string | null;
}

/*
 * Schools whose faculty emails we cannot (or may not) harvest, but whose
 * OFFICIAL directory lets the student look one up themselves — with their own
 * campus login where required. Individual lookup is exactly the use these
 * directories permit (UW's directory ToS restricts bulk/commercial use, which
 * is why we don't harvest it — but the student searching one professor is the
 * intended use).
 */
const SELF_LOOKUP_DIRECTORIES: Record<string, { name: string; url: string }> = {
  uw: { name: 'UW Directory', url: 'https://directory.uw.edu/' },
  umich: { name: 'MCommunity', url: 'https://mcommunity.umich.edu/' },
  princeton: { name: 'Princeton Directory', url: 'https://directory.princeton.edu/' },
  stanford: { name: 'Stanford Directory', url: 'https://stanfordwho.stanford.edu/' },
};

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
      // FE-4: insert before the sign-off. The template closes with "Best
      // regards"/"Respectfully", but an AI draft can drift to "Sincerely",
      // "Warm regards", etc. — matching only Best/Respectfully appended the line
      // BELOW the signature in that case. Match a broad set of closings and use
      // the last one.
      const closingRe = /\n\n(?:Best regards|Best|Sincerely|Respectfully|Warm(?:est)? regards|Warmly|Kind regards|Regards|Thank you|Thanks|Cheers)\b/gi;
      let insertAt = -1;
      for (const m of body.matchAll(closingRe)) {
        if (m.index !== undefined) insertAt = m.index;
      }
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
  opportunitySchool,
}: ColdEmailModalProps) {
  const { t } = useT();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [variants, setVariants] = useState<EmailVariant[]>([]);
  const [aiVariant, setAiVariant] = useState<EmailVariant | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [activeVariant, setActiveVariant] = useState(0);
  const [labType, setLabType] = useState<LabType | null>(null);
  // Voice overlay for the AI draft. `selectedStyle` seeds from the lab-type
  // recommendation once variants load; the picker re-generates on change.
  const [selectedStyle, setSelectedStyle] = useState<EmailStyle>('professional');
  const [recommendedStyle, setRecommendedStyle] = useState<EmailStyle | null>(null);

  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [recipient, setRecipient] = useState('');
  const [copied, setCopied] = useState(false);
  // After the user copies/opens the email we treat the lab as contacted: record
  // last_contacted_at (and create an 'applied' interaction if none exists yet, so
  // it shows up in the tracker) and offer a one-tap follow-up reminder.
  const [contacted, setContacted] = useState(false);
  const [followUpDate, setFollowUpDate] = useState<string | null>(null);

  const allVariants: EmailVariant[] = aiVariant ? [...variants, aiVariant] : variants;

  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const chatEndRef = useRef<HTMLDivElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  // Cache the resume experience bullets extracted from the profile's resume
  // text so every AI (re)generation reuses one extraction. null = not yet
  // attempted; [] = attempted, none found (or no resume).
  const resumeBulletsRef = useRef<string[] | null>(null);
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
      const rec = data.recommended_style ?? null;
      setRecommendedStyle(rec);
      if (rec) setSelectedStyle(rec);
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
      setSelectedStyle('professional');
      setRecommendedStyle(null);
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

  // Generate (or re-generate) the AI draft in a given voice. Used by both the
  // ✨ AI pill (current/recommended tone) and the tone picker (switches voice).
  const generateAi = useCallback(async (style: EmailStyle) => {
    if (aiLoading) return;
    const aiIdx = variants.length;
    setAiLoading(true);
    setSelectedStyle(style);
    setChatMessages((prev) => [
      ...prev,
      { role: 'assistant', content: t('coldEmail.tone.generating', { style: t(`coldEmail.tone.${style}`) }) },
    ]);

    try {
      // Extract the student's real resume bullets once, so the AI draft can
      // cite their actual experience (the backend grounds them). Best-effort:
      // a failure just falls back to skills/coursework-only grounding.
      if (resumeBulletsRef.current === null) {
        try {
          resumeBulletsRef.current = profile.resume_text
            ? (await extractResumeBullets(profile.resume_text)).bullets ?? []
            : [];
        } catch {
          resumeBulletsRef.current = [];
        }
      }
      const bullets = resumeBulletsRef.current;
      const resp = await generateColdEmail(profile, opportunityId, {
        engine: 'ai',
        style,
        ...(bullets && bullets.length > 0 ? { resumeBullets: bullets } : {}),
      });
      const v: EmailVariant = {
        id: AI_VARIANT_ID,
        label: t('coldEmail.aiVariantLabel'),
        subject: resp.subject,
        body: resp.body,
        recipient_email: resp.recipient_email,
        mailto_link: resp.mailto_link,
        lab_type: resp.lab_type ?? labType ?? null,
        method: resp.method,
        fallback_reason: resp.fallback_reason,
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
  }, [aiLoading, variants.length, profile, opportunityId, labType, t]);

  function handleAiPillClick() {
    if (aiLoading) return;
    if (aiVariant) {
      selectVariant(variants.length);
      return;
    }
    generateAi(selectedStyle);
  }

  function handleToneClick(style: EmailStyle) {
    if (aiLoading) return;
    generateAi(style);
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
      const result = await refineEmail(body, msg, profile, opportunityId);
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

  // Record the contact without clobbering an existing status: create an
  // 'applied' row only if none exists, then stamp last_contacted_at (+ remind_at
  // when a follow-up was chosen). Best-effort — never blocks the email action.
  const recordContact = useCallback(async (remindAt?: string) => {
    try {
      const detail = await getInteractionDetail(opportunityId);
      if (!detail) await trackInteraction(opportunityId, 'applied');
      await updateInteractionDetails(opportunityId, {
        last_contacted_at: new Date().toISOString(),
        ...(remindAt ? { remind_at: remindAt } : {}),
      });
    } catch { /* best-effort */ }
  }, [opportunityId]);

  const markContacted = useCallback(() => {
    setContacted(true);
    recordContact();
  }, [recordContact]);

  const setFollowUp = useCallback((days: number) => {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() + days);
    const date = d.toISOString().slice(0, 10);
    setFollowUpDate(date);
    recordContact(date);
  }, [recordContact]);

  async function handleCopy() {
    await navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    markContacted();
  }

  function getMailtoLink(provider: 'default' | 'gmail' | 'outlook' = 'default'): string {
    const to = encodeURIComponent(recipient || '');
    const subj = encodeURIComponent(subject);
    const b = encodeURIComponent(body);
    if (provider === 'gmail') return `https://mail.google.com/mail/?view=cm&to=${to}&su=${subj}&body=${b}`;
    if (provider === 'outlook') return `https://outlook.office365.com/mail/deeplink/compose?to=${to}&subject=${subj}&body=${b}`;
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
            <div className="w-9 h-9 rounded-xl bg-indigo-50 flex items-center justify-center" aria-hidden="true">
              <Mail className="w-5 h-5 text-indigo-600" />
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
            className="p-2 rounded-lg hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 transition-colors"
            aria-label={t('coldEmail.closeAria')}
          >
            <X className="w-5 h-5 text-gray-400" aria-hidden="true" />
          </button>
        </div>

        {/* Loading / Error */}
        {loading && (
          <div className="flex flex-col items-center justify-center py-20 gap-4">
            <Loader2 className="w-8 h-8 text-indigo-500 animate-spin" />
            <p className="text-sm text-gray-500">{t('coldEmail.generating')}</p>
          </div>
        )}
        {error && (
          <div className="flex flex-col items-center justify-center py-20 gap-4">
            <AlertCircle className="w-8 h-8 text-red-500" />
            <p className="text-sm text-red-600">{error}</p>
            <button type="button" onClick={fetchVariants} className="text-sm text-indigo-600 underline hover:text-indigo-700">{t('coldEmail.tryAgain')}</button>
          </div>
        )}

        {/* Two-panel layout */}
        {!loading && !error && (
          <>
            <div className="flex-1 flex flex-col lg:flex-row min-h-0">
              <div className="flex-1 flex flex-col lg:border-r border-gray-100 min-w-0">
                {/* Variant tabs */}
                <div className="flex items-center gap-1 px-5 pt-4 pb-2 shrink-0">
                  {variants.map((v, i) => (
                    <button
                      key={v.id}
                      type="button"
                      onClick={() => selectVariant(i)}
                      className={`px-3 py-1.5 rounded-full text-[12px] font-medium transition-all duration-200 ${
                        activeVariant === i
                          ? 'bg-indigo-600 text-white'
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

                {/* Tone picker — drives the AI draft's voice. The recommended
                    tone is derived from the detected lab type (no scraping). */}
                <div className="flex items-center gap-1.5 px-5 pb-2 shrink-0 flex-wrap">
                  <span className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mr-0.5">
                    {t('coldEmail.tone.label')}
                  </span>
                  {STYLE_KEYS.map((s) => {
                    const isActive = activeVariant === variants.length && aiVariant != null && selectedStyle === s;
                    const isRecommended = recommendedStyle === s;
                    return (
                      <button
                        key={s}
                        type="button"
                        onClick={() => handleToneClick(s)}
                        disabled={aiLoading}
                        className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium transition-all duration-200 disabled:opacity-60 disabled:cursor-wait ${
                          isActive
                            ? 'bg-indigo-600 text-white shadow-sm'
                            : 'bg-indigo-50/70 text-indigo-600 hover:bg-indigo-100'
                        }`}
                      >
                        {t(`coldEmail.tone.${s}`)}
                        {isRecommended && (
                          <span
                            className={`text-[9px] font-semibold uppercase tracking-wide px-1 py-px rounded ${
                              isActive ? 'bg-white/25 text-white' : 'bg-indigo-100 text-indigo-500'
                            }`}
                          >
                            {t('coldEmail.tone.recommended')}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>

                <div className="flex-1 overflow-y-auto px-5 pb-4 space-y-4">
                  <div>
                    <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                      {t('coldEmail.to')}
                    </label>
                    <input
                      type="email"
                      value={recipient}
                      onChange={(e) => setRecipient(e.target.value)}
                      placeholder={t('coldEmail.toPlaceholder')}
                      className={`w-full px-3.5 py-2.5 border rounded-xl text-sm text-gray-900 placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none transition-all ${!recipient ? 'border-amber-300 bg-amber-50/30' : 'border-gray-200'}`}
                    />
                    {!recipient ? (
                      <div className="mt-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2">
                        <p className="text-[12px] font-medium text-amber-800">
                          {t('coldEmail.emailUnavailableTitle')}
                        </p>
                        <p className="mt-0.5 text-[12px] leading-snug text-amber-700">
                          {t('coldEmail.emailUnavailableBody')}
                        </p>
                        {opportunitySchool && SELF_LOOKUP_DIRECTORIES[opportunitySchool] && (
                          <a
                            href={SELF_LOOKUP_DIRECTORIES[opportunitySchool].url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="mt-1 inline-block text-[12px] font-medium text-amber-800 underline underline-offset-2 hover:text-amber-900"
                          >
                            {t('coldEmail.emailLookupDirectory', {
                              directory: SELF_LOOKUP_DIRECTORIES[opportunitySchool].name,
                            })}
                          </a>
                        )}
                      </div>
                    ) : (
                      <p className="mt-1.5 text-[11px] text-gray-400">
                        {t('coldEmail.verifyBeforeSend')}
                      </p>
                    )}
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">{t('coldEmail.subject')}</label>
                    <input
                      type="text"
                      value={subject}
                      onChange={(e) => setSubject(e.target.value)}
                      className="w-full px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm font-medium text-gray-900 focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none transition-all"
                    />
                  </div>
                  <div className="flex-1 flex flex-col">
                    <div className="flex items-center gap-2 mb-1.5">
                      <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('coldEmail.body')}</label>
                      {/* FE-5: durable provenance — the active variant is the AI
                          pill but the backend served the template; say so here so
                          the signal survives chat-scroll and reopen. */}
                      {activeVariant === variants.length && aiVariant && aiVariant.method !== 'ai' && (
                        <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-amber-50 text-amber-700">
                          {t('coldEmail.templateFallbackBadge')}
                        </span>
                      )}
                    </div>
                    <textarea
                      value={body}
                      onChange={(e) => setBody(e.target.value)}
                      rows={12}
                      className="w-full flex-1 px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-700 leading-relaxed focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none transition-all resize-y"
                    />
                  </div>
                </div>
              </div>

              <div className="w-full lg:w-80 flex flex-col bg-gray-50/60 min-w-0 border-t lg:border-t-0 border-gray-100">
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
                            ? 'bg-indigo-600 text-white rounded-br-sm'
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
                      className="flex-1 px-3 py-2 border border-gray-200 rounded-xl text-sm bg-white placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500/20 outline-none transition-all"
                    />
                    <button
                      type="submit"
                      disabled={!chatInput.trim()}
                      className="p-2 rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
                    >
                      <Send className="w-4 h-4" />
                    </button>
                  </form>
                </div>
              </div>
            </div>

            {/* Follow-up reminder strip — appears once the email is copied/opened */}
            {contacted && (
              <div className="flex flex-wrap items-center gap-2 px-6 py-2.5 border-t border-gray-100 bg-amber-50/60 shrink-0 text-sm">
                {followUpDate ? (
                  <span className="inline-flex items-center gap-1.5 font-medium text-amber-700">
                    <BellRing className="w-4 h-4" />
                    {t('coldEmail.reminderSet', { date: followUpDate })}
                  </span>
                ) : (
                  <>
                    <span className="inline-flex items-center gap-1.5 text-gray-600">
                      <BellRing className="w-4 h-4 text-amber-500" />
                      {t('coldEmail.remindPrompt')}
                    </span>
                    {([['coldEmail.remind3', 3], ['coldEmail.remind7', 7], ['coldEmail.remind14', 14]] as const).map(
                      ([key, days]) => (
                        <button
                          key={days}
                          type="button"
                          onClick={() => setFollowUp(days)}
                          className="px-2.5 py-1 rounded-lg border border-amber-200 bg-white text-[12px] font-medium text-amber-700 hover:bg-amber-100 transition-colors"
                        >
                          {t(key)}
                        </button>
                      ),
                    )}
                  </>
                )}
              </div>
            )}

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
              {/* FE-2: the deep-link send buttons open a real compose window, so
                  disable them when no recipient is resolved — otherwise the user
                  is dropped into a draft addressed to nobody with no warning. The
                  amber "To" hint above guides them to add an address; the Copy
                  button stays enabled since pasting elsewhere is still useful. */}
              <div
                className="flex items-stretch rounded-xl overflow-hidden shadow-sm"
                title={!recipient.trim() ? t('coldEmail.toHint') : undefined}
              >
                <button
                  type="button"
                  disabled={!recipient.trim()}
                  onClick={() => { window.open(getMailtoLink('default'), '_blank'); markContacted(); }}
                  className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-semibold text-white bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-700 hover:to-indigo-600 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ExternalLink className="w-4 h-4" />
                  {t('coldEmail.openInEmail')}
                </button>
                <div className="w-px bg-indigo-400" />
                <button
                  type="button"
                  disabled={!recipient.trim()}
                  onClick={() => { window.open(getMailtoLink('gmail'), '_blank'); markContacted(); }}
                  className="inline-flex items-center justify-center px-3 py-2.5 text-[11px] font-semibold text-indigo-100 bg-indigo-600 hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  title={t('coldEmail.openGmailTitle')}
                >
                  {t('coldEmail.gmail')}
                </button>
                <button
                  type="button"
                  disabled={!recipient.trim()}
                  onClick={() => { window.open(getMailtoLink('outlook'), '_blank'); markContacted(); }}
                  className="inline-flex items-center justify-center px-3 py-2.5 text-[11px] font-semibold text-indigo-100 bg-indigo-600 hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
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
