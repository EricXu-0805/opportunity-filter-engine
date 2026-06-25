'use client';

import { useCallback, useState } from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import {
  ArrowRight,
  Check,
  ClipboardCopy,
  Loader2,
  RotateCw,
  Sparkles,
  AlertCircle,
  Bookmark,
} from 'lucide-react';
import {
  importByUrl,
  importByText,
  type ImportedOpportunity,
} from '@/lib/api';
import {
  addCustomImport,
  findExistingImport,
  useCustomImports,
  type CustomImport,
} from '@/lib/custom-imports';
import { useT } from '@/i18n/client';

const MarkdownPreview = dynamic(() => import('@/components/MarkdownPreview'), {
  ssr: false,
  loading: () => null,
});

type Mode = 'url' | 'text';

const TEXT_MIN_CHARS = 50;

type FetchState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'success'; opportunity: ImportedOpportunity; llmEnriched: boolean; mode: Mode }
  | { kind: 'error'; message: string };

export default function ImportPage() {
  const { t } = useT();
  const [mode, setMode] = useState<Mode>('url');
  const [url, setUrl] = useState('');
  const [text, setText] = useState('');
  const [state, setState] = useState<FetchState>({ kind: 'idle' });
  const [copied, setCopied] = useState(false);
  const customImports = useCustomImports();
  const savedEntry: CustomImport | null = state.kind === 'success'
    ? findExistingImport(state.opportunity, customImports)
    : null;

  const handleSave = useCallback(() => {
    if (state.kind !== 'success') return;
    addCustomImport(state.opportunity);
  }, [state]);

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setCopied(false);

    if (mode === 'url') {
      const trimmed = url.trim();
      if (!trimmed) {
        setState({ kind: 'error', message: t('import.errorEmpty') });
        return;
      }
      setState({ kind: 'loading' });
      try {
        const result = await importByUrl(trimmed);
        if (!result.ok || !result.opportunity) {
          const msg = result.error?.toLowerCase().includes('unsafe')
            ? t('import.errorUnsafe')
            : t('import.errorFetch');
          setState({ kind: 'error', message: msg });
          return;
        }
        setState({
          kind: 'success',
          opportunity: result.opportunity,
          llmEnriched: result.llm_enriched,
          mode: 'url',
        });
      } catch {
        setState({ kind: 'error', message: t('import.errorFetch') });
      }
      return;
    }

    const trimmedText = text.trim();
    if (!trimmedText) {
      setState({ kind: 'error', message: t('import.errorEmptyText') });
      return;
    }
    if (trimmedText.length < TEXT_MIN_CHARS) {
      setState({ kind: 'error', message: t('import.errorTooShortText') });
      return;
    }
    setState({ kind: 'loading' });
    try {
      const result = await importByText(trimmedText);
      if (!result.ok || !result.opportunity) {
        setState({ kind: 'error', message: t('import.errorExtract') });
        return;
      }
      setState({
        kind: 'success',
        opportunity: result.opportunity,
        llmEnriched: result.llm_enriched,
        mode: 'text',
      });
    } catch {
      setState({ kind: 'error', message: t('import.errorExtract') });
    }
  }, [mode, url, text, t]);

  const handleReset = useCallback(() => {
    if (state.kind === 'success' && state.mode === 'text') {
      setText('');
    } else {
      setUrl('');
    }
    setState({ kind: 'idle' });
    setCopied(false);
  }, [state]);

  const handleModeChange = useCallback((next: Mode) => {
    if (next === mode) return;
    setMode(next);
    setState({ kind: 'idle' });
    setCopied(false);
  }, [mode]);

  const handleCopy = useCallback(async () => {
    if (state.kind !== 'success') return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(state.opportunity, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard unavailable */
    }
  }, [state]);

  const loading = state.kind === 'loading';

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10 sm:py-16">
      <header className="mb-6">
        <h1 className="text-3xl sm:text-4xl font-bold text-gray-900 tracking-tight">
          {t('import.title')}
        </h1>
        <p className="mt-3 text-[15px] text-gray-500 leading-relaxed">
          {t('import.intro')}
        </p>
      </header>

      <div role="tablist" aria-label="Import mode" className="mb-6 flex gap-1 p-1 bg-gray-100 rounded-xl w-fit">
        <ModeTab active={mode === 'url'} onClick={() => handleModeChange('url')} label={t('import.modeUrl')} />
        <ModeTab active={mode === 'text'} onClick={() => handleModeChange('text')} label={t('import.modeText')} />
      </div>

      <form onSubmit={handleSubmit} className="mb-8">
        {mode === 'url' ? (
          <label className="block">
            <span className="text-[13px] font-medium text-gray-700">
              {t('import.urlLabel')}
            </span>
            <div className="mt-2 flex gap-2">
              <input
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder={t('import.urlPlaceholder')}
                disabled={loading}
                className="flex-1 px-4 py-2.5 border border-gray-200 rounded-xl text-[14px] focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none disabled:bg-gray-50"
                autoFocus
              />
              <button
                type="submit"
                disabled={loading}
                className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-indigo-600 text-white text-[13px] font-semibold hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                {loading ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>{t('import.fetchPending')}</span>
                  </>
                ) : (
                  <>
                    <span>{t('import.fetchButton')}</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </>
                )}
              </button>
            </div>
          </label>
        ) : (
          <div>
            <label className="block">
              <span className="text-[13px] font-medium text-gray-700">
                {t('import.textLabel')}
              </span>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={t('import.textPlaceholder')}
                disabled={loading}
                rows={10}
                className="mt-2 block w-full px-4 py-3 border border-gray-200 rounded-xl text-[14px] leading-relaxed focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none disabled:bg-gray-50 resize-y"
                autoFocus
              />
            </label>
            <p className="mt-1.5 text-[12px] text-gray-400">{t('import.textHelp')}</p>
            <button
              type="submit"
              disabled={loading}
              className="mt-3 inline-flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-indigo-600 text-white text-[13px] font-semibold hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              {loading ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>{t('import.extractPending')}</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>{t('import.extractButton')}</span>
                </>
              )}
            </button>
          </div>
        )}
      </form>

      {state.kind === 'error' && (
        <div className="mb-8 flex items-start gap-2.5 p-4 rounded-xl bg-red-50 border border-red-200">
          <AlertCircle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
          <p className="text-[13px] text-red-700">{state.message}</p>
        </div>
      )}

      {state.kind === 'success' && (
        <ResultCard
          opportunity={state.opportunity}
          llmEnriched={state.llmEnriched}
          mode={state.mode}
          onCopy={handleCopy}
          onReset={handleReset}
          onSave={handleSave}
          savedEntry={savedEntry}
          copied={copied}
          t={t}
        />
      )}
    </div>
  );
}

function ModeTab({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`px-3.5 py-1.5 rounded-lg text-[13px] font-medium transition-colors ${
        active
          ? 'bg-white text-gray-900 shadow-sm'
          : 'text-gray-500 hover:text-gray-800'
      }`}
    >
      {label}
    </button>
  );
}

function ResultCard({
  opportunity,
  llmEnriched,
  mode,
  onCopy,
  onReset,
  onSave,
  savedEntry,
  copied,
  t,
}: {
  opportunity: ImportedOpportunity;
  llmEnriched: boolean;
  mode: Mode;
  onCopy: () => void;
  onReset: () => void;
  onSave: () => void;
  savedEntry: CustomImport | null;
  copied: boolean;
  t: (path: string, vars?: Record<string, string | number>) => string;
}) {
  const extra = opportunity.extra_fields ?? {};
  const oppType = typeof extra.opportunity_type === 'string' ? extra.opportunity_type : null;
  const onCampus = typeof extra.on_campus === 'boolean' ? extra.on_campus : null;
  const paid = typeof extra.paid === 'string' ? extra.paid : null;
  const skillsReq = Array.isArray(extra.skills_required) ? (extra.skills_required as string[]) : [];
  const skillsPref = Array.isArray(extra.skills_preferred) ? (extra.skills_preferred as string[]) : [];
  const preferredYear = Array.isArray(extra.preferred_year) ? (extra.preferred_year as string[]) : [];
  const intlFriendly = typeof extra.international_friendly === 'string'
    ? extra.international_friendly
    : null;

  return (
    <article className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] border border-gray-100 p-6 sm:p-8">
      <div className="flex items-start justify-between gap-3 mb-5">
        <h2 className="text-xl font-bold text-gray-900">{opportunity.title}</h2>
        <span
          className={`shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium ${
            llmEnriched
              ? 'bg-indigo-50 text-indigo-700 border border-indigo-200'
              : 'bg-gray-50 text-gray-500 border border-gray-200'
          }`}
        >
          <Sparkles className="w-3 h-3" />
          {llmEnriched ? t('import.llmEnriched') : t('import.fallbackV1')}
        </span>
      </div>

      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4 text-[13px] mb-6">
        <Field label={t('import.fieldOrg')} value={opportunity.organization} t={t} />
        <Field label={t('import.fieldType')} value={oppType} t={t} capitalize />
        <Field label={t('import.fieldLocation')} value={opportunity.location} t={t} />
        <Field
          label={t('import.fieldOnCampus')}
          value={onCampus === null ? null : (onCampus ? 'yes' : 'no')}
          t={t}
          capitalize
        />
        <Field label={t('import.fieldPaid')} value={paid} t={t} capitalize />
        <Field label={t('import.fieldDeadline')} value={opportunity.deadline} t={t} />
        <Field label={t('import.fieldIntl')} value={intlFriendly} t={t} capitalize />
        <Field
          label={t('import.fieldYear')}
          value={preferredYear.length > 0 ? preferredYear.join(', ') : null}
          t={t}
          capitalize
        />
      </dl>

      {opportunity.description_raw && (
        <div className="mb-6">
          <h3 className="text-[12px] uppercase tracking-wide text-gray-400 font-semibold mb-2">
            {t('import.fieldDescription')}
          </h3>
          <MarkdownPreview>{opportunity.description_raw}</MarkdownPreview>
        </div>
      )}

      {skillsReq.length > 0 && (
        <SkillRow label={t('import.fieldSkillsReq')} skills={skillsReq} variant="required" />
      )}
      {skillsPref.length > 0 && (
        <SkillRow label={t('import.fieldSkillsPref')} skills={skillsPref} variant="preferred" />
      )}

      <p className="text-[12px] text-gray-400 leading-relaxed border-t border-gray-100 pt-4 mt-6">
        {t('import.persistNote')}
      </p>

      <div className="flex flex-wrap gap-2 mt-5">
        {savedEntry ? (
          <span className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-700 text-[13px] font-semibold">
            <Check className="w-3.5 h-3.5" />
            {t('import.saved')}
          </span>
        ) : (
          <button
            type="button"
            onClick={onSave}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-indigo-600 text-white text-[13px] font-semibold hover:bg-indigo-700 transition-colors"
          >
            <Bookmark className="w-3.5 h-3.5" />
            {t('import.saveToList')}
          </button>
        )}
        {savedEntry && (
          <Link
            href="/favorites"
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl border border-gray-200 text-gray-600 text-[13px] font-medium hover:bg-gray-50 transition-colors"
          >
            {t('import.viewInFavorites')}
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        )}
        <button
          type="button"
          onClick={onCopy}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gray-900 text-white text-[13px] font-semibold hover:bg-gray-800 transition-colors"
        >
          <ClipboardCopy className="w-3.5 h-3.5" />
          {copied ? t('import.copied') : t('import.copyJson')}
        </button>
        <button
          type="button"
          onClick={onReset}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl border border-gray-200 text-gray-600 text-[13px] font-medium hover:bg-gray-50 transition-colors"
        >
          <RotateCw className="w-3.5 h-3.5" />
          {mode === 'text' ? t('import.tryAnotherText') : t('import.tryAnother')}
        </button>
      </div>
    </article>
  );
}

function Field({
  label,
  value,
  t,
  capitalize,
}: {
  label: string;
  value: string | null | undefined;
  t: (path: string, vars?: Record<string, string | number>) => string;
  capitalize?: boolean;
}) {
  const display = value && value.trim() ? value : t('import.notProvided');
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wide text-gray-400 font-semibold mb-0.5">
        {label}
      </dt>
      <dd className={`text-gray-800 ${capitalize ? 'capitalize' : ''}`}>{display}</dd>
    </div>
  );
}

function SkillRow({
  label,
  skills,
  variant,
}: {
  label: string;
  skills: string[];
  variant: 'required' | 'preferred';
}) {
  const chipClass = variant === 'required'
    ? 'bg-indigo-50 text-indigo-700 border-indigo-100'
    : 'bg-gray-50 text-gray-600 border-gray-200';
  return (
    <div className="mb-4">
      <h3 className="text-[11px] uppercase tracking-wide text-gray-400 font-semibold mb-2">
        {label}
      </h3>
      <div className="flex flex-wrap gap-1.5">
        {skills.map((skill) => (
          <span
            key={skill}
            className={`inline-flex px-2.5 py-1 rounded-full border text-[12px] font-medium ${chipClass}`}
          >
            {skill}
          </span>
        ))}
      </div>
    </div>
  );
}
