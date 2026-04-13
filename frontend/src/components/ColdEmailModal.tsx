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
import { getEmailVariants } from '@/lib/api';
import type { ProfileData, EmailVariant } from '@/lib/types';

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

const QUICK_ACTIONS = [
  { label: 'More formal', prompt: 'formal' },
  { label: 'Shorter', prompt: 'shorter' },
  { label: 'More enthusiastic', prompt: 'enthusiastic' },
  { label: 'Add coursework', prompt: 'coursework' },
] as const;

function applyQuickEdit(body: string, action: string, profile: ProfileData): { body: string; reply: string } {
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
      return { body: updated, reply: 'Made the tone more formal and professional.' };
    }
    case 'shorter': {
      const lines = body.split('\n').filter((l) => l.trim());
      const filtered = lines.filter(
        (l) =>
          !l.includes('I am a fast learner') &&
          !l.includes('I am confident I can') &&
          !l.includes('always eager'),
      );
      return { body: filtered.join('\n'), reply: 'Trimmed filler sentences to make it more concise.' };
    }
    case 'enthusiastic': {
      const updated = body
        .replace(/I am very interested in/g, 'I am truly excited about')
        .replace(/I really enjoyed learning/g, 'I was fascinated by')
        .replace(/I would love the chance/g, 'I would be thrilled at the opportunity')
        .replace(/I would greatly appreciate the chance/g, 'I would be thrilled at the opportunity');
      return { body: updated, reply: 'Added more enthusiasm and energy to the tone.' };
    }
    case 'coursework': {
      const courses = profile.coursework ?? [];
      if (courses.length === 0) {
        return { body, reply: 'No coursework found in your profile. Add courses on the main page first.' };
      }
      const courseStr = courses.slice(0, 4).join(', ');
      const insertion = `\n\nI have completed relevant coursework including ${courseStr}.`;
      const closingIdx = body.lastIndexOf('\n\nBest');
      const respectIdx = body.lastIndexOf('\n\nRespectfully');
      const insertAt = Math.max(closingIdx, respectIdx);
      if (insertAt > 0) {
        return {
          body: body.slice(0, insertAt) + insertion + body.slice(insertAt),
          reply: `Added coursework: ${courseStr}`,
        };
      }
      return { body: body + insertion, reply: `Added coursework: ${courseStr}` };
    }
    default:
      return { body, reply: 'No changes applied.' };
  }
}

export default function ColdEmailModal({
  isOpen,
  onClose,
  profile,
  opportunityId,
  opportunityTitle,
}: ColdEmailModalProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [variants, setVariants] = useState<EmailVariant[]>([]);
  const [activeVariant, setActiveVariant] = useState(0);

  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [recipient, setRecipient] = useState('');
  const [copied, setCopied] = useState(false);

  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const chatEndRef = useRef<HTMLDivElement>(null);

  const fetchVariants = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getEmailVariants(profile, opportunityId);
      setVariants(data.variants);
      if (data.variants.length > 0) {
        const first = data.variants[0];
        setSubject(first.subject);
        setBody(first.body);
        setRecipient(first.recipient_email);
        setActiveVariant(0);
      }
      setChatMessages([
        { role: 'assistant', content: `Generated ${data.variants.length} variants. Pick one as your base, then use quick actions or type a request to refine it.` },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate email');
    } finally {
      setLoading(false);
    }
  }, [profile, opportunityId]);

  useEffect(() => {
    if (isOpen) fetchVariants();
    return () => {
      setVariants([]);
      setSubject('');
      setBody('');
      setCopied(false);
      setError(null);
      setChatMessages([]);
      setChatInput('');
    };
  }, [isOpen, fetchVariants]);

  useEffect(() => {
    if (isOpen) document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, [isOpen]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  function selectVariant(idx: number) {
    const v = variants[idx];
    if (!v) return;
    setActiveVariant(idx);
    setSubject(v.subject);
    setBody(v.body);
    setRecipient(v.recipient_email);
    setChatMessages((prev) => [
      ...prev,
      { role: 'assistant', content: `Switched to "${v.label}" variant.` },
    ]);
  }

  function handleQuickAction(prompt: string) {
    const action = QUICK_ACTIONS.find((a) => a.prompt === prompt);
    if (!action) return;
    setChatMessages((prev) => [...prev, { role: 'user', content: action.label }]);
    const { body: newBody, reply } = applyQuickEdit(body, prompt, profile);
    setBody(newBody);
    setChatMessages((prev) => [...prev, { role: 'assistant', content: reply }]);
  }

  function handleChatSubmit() {
    const msg = chatInput.trim();
    if (!msg) return;
    setChatInput('');
    setChatMessages((prev) => [...prev, { role: 'user', content: msg }]);

    const lower = msg.toLowerCase();
    if (lower.includes('formal') || lower.includes('professional')) {
      const { body: b, reply } = applyQuickEdit(body, 'formal', profile);
      setBody(b);
      setChatMessages((prev) => [...prev, { role: 'assistant', content: reply }]);
    } else if (lower.includes('short') || lower.includes('concise') || lower.includes('brief')) {
      const { body: b, reply } = applyQuickEdit(body, 'shorter', profile);
      setBody(b);
      setChatMessages((prev) => [...prev, { role: 'assistant', content: reply }]);
    } else if (lower.includes('enthus') || lower.includes('excit') || lower.includes('energy')) {
      const { body: b, reply } = applyQuickEdit(body, 'enthusiastic', profile);
      setBody(b);
      setChatMessages((prev) => [...prev, { role: 'assistant', content: reply }]);
    } else if (lower.includes('course') || lower.includes('class')) {
      const { body: b, reply } = applyQuickEdit(body, 'coursework', profile);
      setBody(b);
      setChatMessages((prev) => [...prev, { role: 'assistant', content: reply }]);
    } else {
      setChatMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: 'Try the quick actions below, or ask to make it "more formal", "shorter", "more enthusiastic", or "add coursework". Full AI editing coming soon!',
        },
      ]);
    }
  }

  async function handleCopy() {
    await navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function getMailtoLink(): string {
    const to = recipient || '';
    return `https://outlook.office365.com/mail/deeplink/compose?to=${encodeURIComponent(to)}&subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  }

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm" onClick={onClose} />

      <div className="relative w-full max-w-5xl mx-2 sm:mx-4 bg-white rounded-2xl shadow-2xl max-h-[90vh] flex flex-col overflow-hidden animate-in">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-blue-50 flex items-center justify-center">
              <Mail className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-gray-900">Email Editor</h2>
              <p className="text-sm text-gray-500 truncate max-w-md">{opportunityTitle}</p>
            </div>
          </div>
          <button type="button" onClick={onClose} className="p-2 rounded-lg hover:bg-gray-100 transition-colors" aria-label="Close">
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>

        {/* Loading / Error */}
        {loading && (
          <div className="flex flex-col items-center justify-center py-20 gap-4">
            <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
            <p className="text-sm text-gray-500">Generating email variants...</p>
          </div>
        )}
        {error && (
          <div className="flex flex-col items-center justify-center py-20 gap-4">
            <AlertCircle className="w-8 h-8 text-red-500" />
            <p className="text-sm text-red-600">{error}</p>
            <button type="button" onClick={fetchVariants} className="text-sm text-blue-600 underline hover:text-blue-700">Try again</button>
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
                </div>

                <div className="flex-1 overflow-y-auto px-5 pb-4 space-y-4">
                  <div>
                    <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                      To
                      {!recipient && (
                        <span className="ml-2 text-amber-500 normal-case tracking-normal font-normal">
                          — find the PI&apos;s email on their lab page or department directory
                        </span>
                      )}
                    </label>
                    <input
                      type="email"
                      value={recipient}
                      onChange={(e) => setRecipient(e.target.value)}
                      placeholder="e.g. professor@illinois.edu — check the posting or lab website"
                      className={`w-full px-3.5 py-2.5 border rounded-xl text-sm text-gray-900 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none transition-all ${!recipient ? 'border-amber-300 bg-amber-50/30' : 'border-gray-200'}`}
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Subject</label>
                    <input
                      type="text"
                      value={subject}
                      onChange={(e) => setSubject(e.target.value)}
                      className="w-full px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm font-medium text-gray-900 focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none transition-all"
                    />
                  </div>
                  <div className="flex-1 flex flex-col">
                    <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Body</label>
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
                  <span className="text-sm font-semibold text-gray-700">Refine</span>
                </div>

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
                    {QUICK_ACTIONS.map((action) => (
                      <button
                        key={action.prompt}
                        type="button"
                        onClick={() => handleQuickAction(action.prompt)}
                        className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-white border border-gray-200 text-gray-600 hover:bg-gray-100 transition-colors"
                      >
                        {action.label}
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
                      placeholder="Type a request..."
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
                  <><CheckCircle className="w-4 h-4 text-emerald-500" />Copied!</>
                ) : (
                  <><Copy className="w-4 h-4" />Copy</>
                )}
              </button>
              <button
                type="button"
                onClick={() => { window.location.href = getMailtoLink(); }}
                className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-semibold text-white bg-gradient-to-r from-blue-600 to-blue-500 rounded-xl hover:from-blue-700 hover:to-blue-600 shadow-sm hover:shadow transition-all"
              >
                <ExternalLink className="w-4 h-4" />
                Open in Email
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
