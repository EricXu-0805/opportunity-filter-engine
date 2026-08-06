'use client';

import { Check, CheckCircle2, Cloud, CloudOff, Share2, Sparkles } from 'lucide-react';
import type { HydrationState, SaveStatus, TFunc } from './types';

export function SubmitRow({
  isValid,
  shareCopied,
  saveStatus,
  hydrationState,
  isSubmitting,
  hasConflict,
  canRetrySync,
  onRetrySync,
  onKeepMyChanges,
  onUseCloudVersion,
  onSubmit,
  onShare,
  t,
}: {
  isValid: boolean;
  shareCopied: boolean;
  saveStatus: SaveStatus;
  hydrationState: HydrationState;
  isSubmitting: boolean;
  /** Whether a disagreement is still open. Independent of `saveStatus`: an
   *  unrelated clean save, or a rejected answer, moves the wording on while
   *  the question itself is exactly where it was. */
  hasConflict: boolean;
  /** Whether `onRetrySync` has a write to replay. False draws no button. */
  canRetrySync: boolean;
  onRetrySync: () => void;
  onKeepMyChanges: () => void;
  onUseCloudVersion: () => void;
  onSubmit: () => void;
  onShare: () => void;
  t: TFunc;
}) {
  // Generating matches writes the whole profile row. Until this identity's
  // stored row has been read, that write would replace fields the form has
  // never seen — so the action is unavailable, with the reason spelled out
  // rather than a button that silently does nothing.
  const canSubmit = isValid && hydrationState === 'ready' && !isSubmitting;
  // A generic Retry cannot unlock a conflicted key (see the coordinator's
  // lock rule), so while a question is open it is not a way out — it is a
  // second button next to the real one that would replay the same locked
  // write. A conflict result arms a retryable, so without this a rejected
  // answer's 'cloud-failed' drew exactly that.
  const showRetry = canRetrySync && !hasConflict;
  return (
    <>
      <div className="flex flex-col sm:flex-row items-center justify-center mt-8 gap-3">
        <button
          type="button"
          disabled={!canSubmit}
          data-testid="generate-matches"
          onClick={onSubmit}
          className="group inline-flex items-center justify-center gap-2.5 w-full sm:w-auto px-8 py-3.5 text-[15px] font-semibold text-white bg-indigo-600 rounded-full hover:bg-indigo-700 transition-all duration-300 disabled:opacity-40 disabled:cursor-not-allowed shadow-[0_2px_12px_rgba(79,70,229,0.25)] hover:shadow-[0_4px_20px_rgba(79,70,229,0.35)]"
        >
          <Sparkles className="w-4 h-4 group-hover:rotate-12 transition-transform duration-300" />
          {t(isSubmitting ? 'home.actions.generating' : 'home.actions.generate')}
        </button>
        {isValid && (
          <button
            type="button"
            onClick={onShare}
            className="inline-flex items-center justify-center gap-2 w-full sm:w-auto px-5 py-3.5 text-[13px] font-medium text-gray-600 bg-white border border-gray-200 rounded-full hover:bg-gray-50 transition-colors"
            title={t('home.actions.shareProfile')}
          >
            {shareCopied ? (
              <>
                <Check className="w-4 h-4 text-emerald-500" />
                {t('home.actions.shareCopied')}
              </>
            ) : (
              <>
                <Share2 className="w-4 h-4" />
                {t('home.actions.shareProfile')}
              </>
            )}
          </button>
        )}
      </div>

      {hydrationState !== 'ready' && (
        <p
          data-testid="hydration-note"
          className={`text-center text-[13px] mt-4 ${hydrationState === 'failed' ? 'text-amber-600' : 'text-gray-400'}`}
        >
          {t(hydrationState === 'failed' ? 'home.actions.profileLoadFailed' : 'home.actions.profileLoading')}
        </p>
      )}
      {!isValid && (
        <p className="text-center text-[13px] text-gray-400 mt-4">
          {t('home.validation.requiredFields')}
        </p>
      )}
      {/* Save/sync state is never hidden behind form validity: a failed
          cloud sync is exactly as true (and as retriable) on an incomplete
          profile as on a complete one. */}
      <div className="flex justify-center items-center gap-2 mt-4 min-h-5" role="status" aria-live="polite">
        {saveStatus === 'saving' && (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-gray-400 animate-pulse">
            <Cloud className="w-3.5 h-3.5" aria-hidden="true" />
            {t('common.saving')}
          </span>
        )}
        {saveStatus === 'saved' && (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-emerald-500">
            <CheckCircle2 className="w-3.5 h-3.5" aria-hidden="true" />
            {t('home.actions.profileSaved')}
          </span>
        )}
        {saveStatus === 'device-only' && (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-gray-500">
            <Cloud className="w-3.5 h-3.5" aria-hidden="true" />
            {t('home.actions.profileDeviceOnly')}
          </span>
        )}
        {saveStatus === 'cloud-failed' && (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-amber-600">
            <CloudOff className="w-3.5 h-3.5" aria-hidden="true" />
            {t('home.actions.profileCloudFailed')}
            {showRetry && (
              <button
                type="button"
                data-testid="retry-sync"
                onClick={onRetrySync}
                className="underline underline-offset-2 hover:text-amber-700"
              >
                {t('home.actions.retrySync')}
              </button>
            )}
          </span>
        )}
        {saveStatus === 'device-failed' && (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-amber-600">
            <CloudOff className="w-3.5 h-3.5" aria-hidden="true" />
            {t('home.actions.profileDeviceFailed')}
            {showRetry && (
              <button
                type="button"
                data-testid="retry-sync"
                onClick={onRetrySync}
                className="underline underline-offset-2 hover:text-amber-700"
              >
                {t('home.actions.retrySync')}
              </button>
            )}
          </span>
        )}
        {saveStatus === 'conflict' && (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-amber-600">
            <CloudOff className="w-3.5 h-3.5" aria-hidden="true" />
            {t('home.actions.profileConflict')}
          </span>
        )}
        {/* The question is gone — answered in another tab, or settled by a
            reload. Nothing was sent and there is nothing to retry; what the
            form shows IS the version that was kept, and saying so is the
            difference between "your click did nothing" and "your click was
            about something that had already been decided". */}
        {saveStatus === 'conflict-stale' && (
          <span
            className="inline-flex items-center gap-1.5 text-[12px] text-slate-500"
            data-testid="conflict-stale"
          >
            <CloudOff className="w-3.5 h-3.5" aria-hidden="true" />
            {t('home.actions.profileConflictStale')}
          </span>
        )}
        {/* No Retry: the row is gone, and re-sending would recreate a profile
            the account no longer has. */}
        {saveStatus === 'stale' && (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-red-600">
            <CloudOff className="w-3.5 h-3.5" aria-hidden="true" />
            {t('home.actions.profileStale')}
          </span>
        )}
        {saveStatus === 'error' && (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-red-600">
            <CloudOff className="w-3.5 h-3.5" aria-hidden="true" />
            {t('home.actions.profileSaveFailed')}
            {showRetry && (
              <button
                type="button"
                data-testid="retry-sync"
                onClick={onRetrySync}
                className="underline underline-offset-2 hover:text-red-700"
              >
                {t('home.actions.retrySync')}
              </button>
            )}
          </span>
        )}
        {/* A conflict is a CHOICE, not a retry: the other device's value is
            just as real as this one's, so the two paths are spelled out. A
            plain Retry is deliberately absent — it cannot unlock these keys
            (see the coordinator's lock rule) and offering it would look like
            a way out that silently does nothing.

            Driven by the QUESTION, never by the wording. `saveStatus` says
            what the last save did, and plenty of things move it while the
            disagreement stands: an unrelated clean save says 'saved' (and
            two seconds later 'idle'), a rejected answer says 'cloud-failed'.
            Every one of those used to take the only way out of the question
            off the screen and leave it unanswerable. The two can be true at
            once, and are shown at once. */}
        {hasConflict && (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-amber-600">
            <button
              type="button"
              data-testid="conflict-keep-mine"
              onClick={() => onKeepMyChanges()}
              className="underline underline-offset-2 hover:text-amber-700"
            >
              {t('home.actions.conflictKeepMine')}
            </button>
            <button
              type="button"
              data-testid="conflict-use-cloud"
              onClick={() => onUseCloudVersion()}
              className="underline underline-offset-2 hover:text-amber-700"
            >
              {t('home.actions.conflictUseCloud')}
            </button>
          </span>
        )}
      </div>
    </>
  );
}
