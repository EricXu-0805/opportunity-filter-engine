'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
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
  readCustomImportStorageState,
  updateCustomImport,
  useCustomImportStorageState,
  type CustomImportWriteFailureReason,
  type CustomImport,
} from '@/lib/custom-imports';
import { captureOwnerToken, isOwnerTokenValid, isTokenOwnerStillCurrent, onLocalOwnerStateChange, type OwnerToken } from '@/lib/identity-owner';
import { useT } from '@/i18n/client';
import ImportSuggestions from '@/components/ImportSuggestions';
import ImportSourceText from '@/components/ImportSourceText';
import CustomImportStorageNotice from '@/components/CustomImportStorageNotice';
import { customImportFailureKey, canRetryCustomImport } from '@/lib/custom-import-feedback';
import { importFailureKey, importSourceInfo } from '@/lib/import-source';
import { importSuggestions } from '@/lib/import-suggestions';

type Mode = 'url' | 'text';

const TEXT_MIN_CHARS = 50;

type UpdateReason = CustomImportWriteFailureReason | 'unavailable';
type UpdateReview = { expected: CustomImport; candidate: ImportedOpportunity; token: OwnerToken };
const UPDATE_ERROR_KEYS: Record<UpdateReason, string> = {
  owner_changed: 'import.updateOwnerChanged',
  changed: 'import.updateChanged',
  missing: 'import.updateMissing',
  identity_mismatch: 'import.updateIdentityMismatch',
  storage_failed: 'import.updateStorageFailed',
  unavailable: 'import.updateUnavailable',
  storage_damaged: 'import.storageDamaged',
  coordination_unavailable: 'import.storageCoordinationUnavailable',
  lock_timeout: 'import.storageBusy',
};

type FetchState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | {
      kind: 'success';
      opportunity: ImportedOpportunity;
      llmEnriched: boolean;
      mode: Mode;
      // Captured at request-start, when this result was fetched — NOT
      // re-captured at Save-click time. handleSave reuses this so a click
      // landing after a live identity switch (but before the
      // onLocalOwnerStateChange effect below resets this component) fails
      // its own preflight against the OLD owner instead of succeeding
      // under whoever is current at click time.
      token: OwnerToken;
    }
  | { kind: 'error'; message: string };

export default function ImportPage() {
  const { t } = useT();
  const [mode, setMode] = useState<Mode>('url');
  const [url, setUrl] = useState('');
  const [text, setText] = useState('');
  const [state, setState] = useState<FetchState>({ kind: 'idle' });
  const [copied, setCopied] = useState(false);
  const [saveFailed, setSaveFailed] = useState<CustomImportWriteFailureReason | null>(null);
  const [mutationPending, setMutationPending] = useState(false);
  const mutationRef = useRef<symbol | null>(null);
  const [updateReview, setUpdateReview] = useState<UpdateReview | null>(null);
  const [updateError, setUpdateError] = useState<UpdateReason | null>(null);
  const [updated, setUpdated] = useState(false);
  const requestGeneration = useRef(0);
  const customStorage = useCustomImportStorageState();
  const customImports = customStorage.entries;
  const savedEntry: CustomImport | null = state.kind === 'success'
    ? findExistingImport(state.opportunity, customImports)
    : null;

  // An identity change invalidates any in-progress or completed extract
  // for the PREVIOUS owner — reset to idle in the SAME tick the owner
  // moves so a stale result/loading/error never lingers under a new
  // identity, and so its Save button (bound to the OLD origin token) can
  // never be clicked after the switch.
  useEffect(() => onLocalOwnerStateChange(() => {
    requestGeneration.current += 1;
    mutationRef.current = null;
    setMutationPending(false);
    setUpdateReview(null);
    setUpdateError(null);
    setUpdated(false);
    setState({ kind: 'idle' });
    setCopied(false);
    setSaveFailed(null);
  }), []);

  useEffect(() => () => { requestGeneration.current += 1; mutationRef.current = null; }, []);

  const handleSave = useCallback(async () => {
    if (state.kind !== 'success' || mutationRef.current) return;
    const intent = Symbol('save');
    mutationRef.current = intent;
    const generation = requestGeneration.current;
    setMutationPending(true);
    setSaveFailed(null);
    const result = await addCustomImport(state.opportunity, state.token)
      .catch(() => ({ ok: false, reason: 'storage_failed' } as const));
    if (mutationRef.current !== intent || generation !== requestGeneration.current
      || !isTokenOwnerStillCurrent(state.token)) return;
    mutationRef.current = null;
    setMutationPending(false);
    setSaveFailed(result.ok ? null : result.reason);
  }, [state]);

  const handleReviewUpdate = useCallback(() => {
    if (state.kind !== 'success' || mutationRef.current) return;
    // A refresh is a new review, never a silent change to the old confirmation.
    const candidate = updateReview?.candidate ?? state.opportunity;
    const token = updateReview?.token ?? state.token;
    if (!isOwnerTokenValid(token, token.uid)) {
      setUpdateError('owner_changed');
      return;
    }
    const storage = readCustomImportStorageState(token);
    if (storage.status !== 'ready') {
      setUpdateError(storage.status === 'damaged' ? 'storage_damaged' : storage.reason);
      return;
    }
    const current = findExistingImport(candidate, storage.entries);
    if (!current) {
      setUpdateReview(null);
      setUpdateError('unavailable');
      return;
    }
    try {
      setUpdateReview({ expected: structuredClone(current), candidate: structuredClone(candidate), token });
      setUpdateError(null);
      setUpdated(false);
    } catch {
      setUpdateError('storage_failed');
    }
  }, [state, updateReview]);

  const handleConfirmUpdate = useCallback(async () => {
    if (!updateReview || mutationRef.current || (updateError && !canRetryCustomImport(updateError))) return;
    const intent = Symbol('update');
    mutationRef.current = intent;
    const generation = requestGeneration.current;
    setMutationPending(true);
    // This is the exact old entry and candidate shown in the review. The
    // storage operation checks them again; do not swap in the newest entry.
    const result = await updateCustomImport(updateReview.candidate, updateReview.expected, updateReview.token)
      .catch(() => ({ ok: false, reason: 'storage_failed' } as const));
    if (mutationRef.current !== intent || generation !== requestGeneration.current
      || !isTokenOwnerStillCurrent(updateReview.token)) return;
    mutationRef.current = null;
    setMutationPending(false);
    if (!result.ok) {
      setUpdateError(result.reason);
      return;
    }
    setState((current) => current.kind === 'success' && current.token === updateReview.token
      ? { ...current, opportunity: result.entry.opportunity } : current);
    setUpdateReview(null);
    setUpdateError(null);
    setUpdated(true);
  }, [updateReview, updateError]);

  const handleKeepSaved = useCallback(() => {
    if (mutationRef.current) return;
    setUpdateReview(null);
    setUpdateError(null);
  }, []);

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    const generation = ++requestGeneration.current;
    mutationRef.current = null;
    setMutationPending(false);
    setUpdateReview(null);
    setUpdateError(null);
    setUpdated(false);
    setCopied(false);
    setSaveFailed(null);
    // Captured at the moment this extract request begins — stored on the
    // success state itself (see FetchState's own doc comment), never
    // re-captured after the await.
    const requestToken = captureOwnerToken();
    // isOwnerTokenValid, not a plain uid/epoch comparison: a same-uid but
    // still-BLOCKED owner (local ownership not yet confirmed) must also
    // discard the result — rendering a Save button that would just fail
    // its own preflight is worse than discarding and letting the user
    // resubmit once the owner settles.
    const stillCurrent = () => generation === requestGeneration.current && isOwnerTokenValid(requestToken, requestToken.uid);

    if (mode === 'url') {
      const trimmed = url.trim();
      if (!trimmed) {
        setState({ kind: 'error', message: t('import.errorEmpty') });
        return;
      }
      setState({ kind: 'loading' });
      try {
        const result = await importByUrl(trimmed);
        // Identity moved on mid-flight — discard silently. This is not a
        // failure of the CURRENT session, so it must not show an error.
        if (!stillCurrent()) return;
        if (!result.ok || !result.opportunity) {
          const msg = t(importFailureKey('url', result));
          setState({ kind: 'error', message: msg });
          return;
        }
        setState({
          kind: 'success',
          opportunity: result.opportunity,
          llmEnriched: result.llm_enriched,
          mode: 'url',
          token: requestToken,
        });
      } catch {
        // A stale failure must not overwrite the CURRENT owner's UI with
        // an error that belongs to an abandoned request.
        if (!stillCurrent()) return;
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
      if (!stillCurrent()) return;
      if (!result.ok || !result.opportunity) {
        setState({ kind: 'error', message: t(importFailureKey('text', result)) });
        return;
      }
      setState({
        kind: 'success',
        opportunity: result.opportunity,
        llmEnriched: result.llm_enriched,
        mode: 'text',
        token: requestToken,
      });
    } catch {
      if (!stillCurrent()) return;
      setState({ kind: 'error', message: t('import.errorExtract') });
    }
  }, [mode, url, text, t]);

  const handleReset = useCallback(() => {
    requestGeneration.current += 1;
    mutationRef.current = null;
    setMutationPending(false);
    setUpdateReview(null);
    setUpdateError(null);
    setUpdated(false);
    if (state.kind === 'success' && state.mode === 'text') {
      setText('');
    } else {
      setUrl('');
    }
    setState({ kind: 'idle' });
    setCopied(false);
    setSaveFailed(null);
  }, [state]);

  const handleModeChange = useCallback((next: Mode) => {
    if (next === mode) return;
    requestGeneration.current += 1;
    mutationRef.current = null;
    setMutationPending(false);
    setUpdateReview(null);
    setUpdateError(null);
    setUpdated(false);
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

      <CustomImportStorageNotice state={customStorage} />

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

      {state.kind === 'success' && updateError && !updateReview && (
        <p role="alert" className="mb-4 text-sm text-red-700">{t(UPDATE_ERROR_KEYS[updateError])}</p>
      )}

      {state.kind === 'success' && (updateReview ? (
        <ImportUpdateReview review={updateReview} error={updateError} pending={mutationPending} onConfirm={handleConfirmUpdate}
          onKeep={handleKeepSaved} onReread={handleReviewUpdate} t={t} />
      ) : (
        <ResultCard
          opportunity={state.opportunity}
          llmEnriched={state.llmEnriched}
          mode={state.mode}
          onCopy={handleCopy}
          onReset={handleReset}
          onSave={handleSave}
          onReviewUpdate={handleReviewUpdate}
          updated={updated}
          savedEntry={savedEntry}
          saveFailed={saveFailed}
          pending={mutationPending}
          storageReady={customStorage.status === 'ready'}
          copied={copied}
          t={t}
        />
      ))}
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
  onReviewUpdate,
  updated,
  savedEntry,
  saveFailed,
  pending,
  storageReady,
  copied,
  t,
}: {
  opportunity: ImportedOpportunity;
  llmEnriched: boolean;
  mode: Mode;
  onCopy: () => void;
  onReset: () => void;
  onSave: () => void;
  onReviewUpdate: () => void;
  updated: boolean;
  savedEntry: CustomImport | null;
  saveFailed: CustomImportWriteFailureReason | null;
  pending: boolean;
  storageReady: boolean;
  copied: boolean;
  t: (path: string, vars?: Record<string, string | number>) => string;
}) {
  const matchesSaved = savedEntry !== null && sameImportedContent(savedEntry.opportunity, opportunity);

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

      <OpportunityDetails opportunity={opportunity} t={t} />

      <p className="text-[12px] text-gray-400 leading-relaxed border-t border-gray-100 pt-4 mt-6">
        {t('import.persistNote')}
      </p>

      <div className="flex flex-wrap gap-2 mt-5">
        {savedEntry ? (
          <span className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-xl border text-[13px] font-semibold ${matchesSaved ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-gray-50 border-gray-200 text-gray-600'}`}>
            {matchesSaved && <Check className="w-3.5 h-3.5" />}
            {t(matchesSaved ? (updated ? 'import.updated' : 'import.saved') : 'import.savedVersionDiffers')}
          </span>
        ) : (
          <div className="flex flex-col gap-1">
            <button
              type="button"
              onClick={onSave}
              disabled={pending || !storageReady}
              aria-busy={pending}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-indigo-600 text-white text-[13px] font-semibold hover:bg-indigo-700 transition-colors"
            >
              <Bookmark className="w-3.5 h-3.5" />
              {t(pending ? 'import.saving' : 'import.saveToList')}
            </button>
            {saveFailed && (
              <p role="alert" className="text-[12px] text-red-600">{t(saveFailed === 'storage_failed' ? 'import.saveFailed' : customImportFailureKey(saveFailed))}</p>
            )}
          </div>
        )}
        {savedEntry && (
          <button type="button" onClick={onReviewUpdate} disabled={pending || !storageReady}
            className="px-4 py-2 rounded-xl bg-indigo-600 text-white text-[13px] font-semibold hover:bg-indigo-700">
            {t('import.reviewUpdate')}
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

// Equality is deliberately conservative: differing serialization never gets
// a green saved badge. The review/update operation performs its own full check.
function sameImportedContent(a: ImportedOpportunity, b: ImportedOpportunity): boolean {
  try { return JSON.stringify(a) === JSON.stringify(b); } catch { return false; }
}

function OpportunityDetails({ opportunity, t }: {
  opportunity: ImportedOpportunity;
  t: (path: string, vars?: Record<string, string | number>) => string;
}) {
  const extra = opportunity.extra_fields ?? {};
  const oppType = typeof extra.opportunity_type === 'string' ? extra.opportunity_type : null;
  const onCampus = typeof extra.on_campus === 'boolean' ? extra.on_campus : null;
  const paid = typeof extra.paid === 'string' ? extra.paid : null;
  const suggestions = importSuggestions(extra);
  const preferredYear = Array.isArray(extra.preferred_year) ? (extra.preferred_year as string[]) : [];
  const intlFriendly = typeof extra.international_friendly === 'string'
    ? extra.international_friendly
    : null;

  return <>
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
          <ImportSourceText text={opportunity.description_raw} info={importSourceInfo(extra, opportunity.description_raw)} t={t} />
        </div>
      )}

      <ImportSuggestions skills={suggestions.skills} summary={suggestions.summary} t={t} />
  </>;
}

function ImportUpdateReview({ review, error, pending, onConfirm, onKeep, onReread, t }: {
  review: UpdateReview;
  error: UpdateReason | null;
  pending: boolean;
  onConfirm: () => void;
  onKeep: () => void;
  onReread: () => void;
  t: (path: string, vars?: Record<string, string | number>) => string;
}) {
  const mustReread = error !== null && !canRetryCustomImport(error);
  return (
    <section aria-label={t('import.reviewUpdate')} className="bg-white border border-gray-200 rounded-2xl p-5 sm:p-6 space-y-5">
      <h2 className="text-lg font-semibold text-gray-900">{t('import.reviewUpdate')}</h2>
      <p className="text-sm text-gray-600">{t('import.updateDraftsNotice')}</p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {([
          ['import.previousVersion', review.expected.opportunity],
          ['import.newVersion', review.candidate],
        ] as const).map(([label, opportunity]) => (
          <section key={label} aria-label={t(label)} className="min-w-0 rounded-xl border border-gray-200 p-4 space-y-4">
            <h3 className="text-sm font-semibold text-indigo-700">{t(label)}</h3>
            <p className="font-medium text-gray-900 break-words">{opportunity.title}</p>
            {(opportunity.source_url || opportunity.url) && <p className="text-xs text-gray-500 break-all">{opportunity.source_url || opportunity.url}</p>}
            <OpportunityDetails opportunity={opportunity} t={t} />
          </section>
        ))}
      </div>
      {error && <p role="alert" className="text-sm text-red-700">{t(UPDATE_ERROR_KEYS[error])}</p>}
      <div className="flex flex-wrap gap-3">
        <button type="button" onClick={onKeep} disabled={pending} className="rounded-xl border border-gray-300 px-4 py-2 text-sm text-gray-700">
          {t(error ? 'import.cancelUpdate' : 'import.keepSaved')}
        </button>
        {mustReread && <button type="button" onClick={onReread} disabled={pending} className="rounded-xl border border-indigo-300 px-4 py-2 text-sm text-indigo-700">
          {t('import.rereadSaved')}
        </button>}
        <button type="button" onClick={onConfirm} disabled={pending || mustReread} aria-busy={pending}
          className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40 disabled:cursor-not-allowed">
          {t(pending ? 'import.saving' : 'import.confirmUpdate')}
        </button>
      </div>
    </section>
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
