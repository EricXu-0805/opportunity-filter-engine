'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Send, Sparkles, X, Loader2, AlertCircle, User, Bot, RotateCcw } from 'lucide-react';
import type { Opportunity, ProfileData } from '@/lib/types';
import { chatWithOpportunity, type ChatMessage } from '@/lib/api';
import { useT } from '@/i18n/client';

interface Props {
  opportunity: Opportunity;
  profile: ProfileData | null;
  onClose?: () => void;
}

const SUGGESTED_KEYS = ['fit', 'nextSteps', 'skills', 'email'] as const;

export default function OpportunityChatbot({ opportunity, profile, onClose }: Props) {
  const { t } = useT();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shareProfile, setShareProfile] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const sendMessage = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    setError(null);
    setInput('');
    const newUserMsg: ChatMessage = { role: 'user', content: trimmed };
    const historyForApi = messages.slice();
    setMessages((prev) => [...prev, newUserMsg]);
    setLoading(true);
    try {
      const resp = await chatWithOpportunity(
        opportunity.id,
        trimmed,
        historyForApi,
        shareProfile ? profile : null,
      );
      setMessages((prev) => [...prev, { role: 'assistant', content: resp.reply }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('chatbot.errorGeneric'));
      setMessages((prev) => prev.slice(0, -1));
      setInput(trimmed);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }, [opportunity.id, profile, shareProfile, messages, loading, t]);

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    sendMessage(input);
  }, [input, sendMessage]);

  const handleClear = useCallback(() => {
    setMessages([]);
    setError(null);
    setInput('');
    inputRef.current?.focus();
  }, []);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }, [input, sendMessage]);

  return (
    <div className="flex flex-col h-full bg-white">
      <header className="flex items-center justify-between px-4 py-3 border-b border-gray-100 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-7 h-7 rounded-lg bg-indigo-50 flex items-center justify-center shrink-0">
            <Sparkles className="w-4 h-4 text-indigo-600" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-gray-900 truncate">{t('chatbot.title')}</h3>
            <p className="text-[11px] text-gray-500 truncate">{t('chatbot.subtitle')}</p>
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {messages.length > 0 && (
            <button
              type="button"
              onClick={handleClear}
              className="inline-flex items-center justify-center w-8 h-8 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
              aria-label={t('chatbot.clearAria')}
              title={t('chatbot.clear')}
            >
              <RotateCcw className="w-4 h-4" aria-hidden="true" />
            </button>
          )}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="inline-flex items-center justify-center w-8 h-8 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
              aria-label={t('chatbot.closeAria')}
            >
              <X className="w-4 h-4" aria-hidden="true" />
            </button>
          )}
        </div>
      </header>

      {profile && (
        <div className="px-4 py-2 border-b border-gray-100 shrink-0 flex items-center justify-between gap-2">
          <span className="text-[11px] text-gray-500 leading-snug truncate">
            {shareProfile ? t('chatbot.profileSharedHint') : t('chatbot.profileNotSharedHint')}
          </span>
          <label className="inline-flex items-center gap-1.5 cursor-pointer shrink-0">
            <input
              type="checkbox"
              checked={shareProfile}
              onChange={(e) => setShareProfile(e.target.checked)}
              className="w-3.5 h-3.5 rounded accent-indigo-600"
            />
            <span className="text-[11px] font-medium text-gray-700">{t('chatbot.useProfile')}</span>
          </label>
        </div>
      )}

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3 min-h-0">
        {messages.length === 0 && !loading && (
          <div>
            <div className="flex gap-2 mb-3">
              <div className="w-7 h-7 rounded-full bg-indigo-50 flex items-center justify-center shrink-0">
                <Bot className="w-3.5 h-3.5 text-indigo-600" aria-hidden="true" />
              </div>
              <div className="flex-1 bg-gray-50 rounded-2xl rounded-tl-sm px-3 py-2 text-[13px] text-gray-700 leading-relaxed">
                {t('chatbot.welcome', { title: opportunity.title })}
              </div>
            </div>
            <p className="text-[11px] font-medium text-gray-400 uppercase tracking-wider px-1 mb-2 mt-4">
              {t('chatbot.tryAsking')}
            </p>
            <div className="flex flex-col gap-1.5">
              {SUGGESTED_KEYS.map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => sendMessage(t(`chatbot.suggested.${key}`))}
                  className="text-left px-3 py-2 rounded-xl bg-white border border-gray-200 text-[12.5px] text-gray-700 hover:bg-indigo-50 hover:border-indigo-200 hover:text-indigo-700 transition-colors"
                >
                  {t(`chatbot.suggested.${key}`)}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-2 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
            <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
              msg.role === 'user' ? 'bg-blue-500 text-white' : 'bg-indigo-50 text-indigo-600'
            }`}>
              {msg.role === 'user' ? <User className="w-3.5 h-3.5" /> : <Bot className="w-3.5 h-3.5" />}
            </div>
            <div className={`max-w-[85%] px-3 py-2 rounded-2xl text-[13px] leading-relaxed whitespace-pre-wrap ${
              msg.role === 'user'
                ? 'bg-blue-500 text-white rounded-tr-sm'
                : 'bg-gray-50 text-gray-800 rounded-tl-sm'
            }`}>
              {msg.content}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex gap-2">
            <div className="w-7 h-7 rounded-full bg-indigo-50 flex items-center justify-center shrink-0">
              <Bot className="w-3.5 h-3.5 text-indigo-600" aria-hidden="true" />
            </div>
            <div className="bg-gray-50 rounded-2xl rounded-tl-sm px-3 py-2 text-[13px] text-gray-500 inline-flex items-center gap-2">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              {t('chatbot.thinking')}
            </div>
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-3 py-2 text-[12px] text-red-700 inline-flex items-center gap-2">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            {error}
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="border-t border-gray-100 shrink-0 p-3">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('chatbot.placeholder')}
            rows={1}
            disabled={loading}
            className="flex-1 px-3 py-2 border border-gray-200 rounded-xl text-[13px] resize-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none transition-all disabled:bg-gray-50 disabled:text-gray-400 max-h-32"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="inline-flex items-center justify-center w-9 h-9 rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
            aria-label={t('chatbot.sendAria')}
          >
            <Send className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      </form>
    </div>
  );
}
