'use client';

import { Check, CheckCircle2, Cloud, Share2, Sparkles } from 'lucide-react';
import type { SaveStatus, TFunc } from './types';

export function SubmitRow({
  isValid,
  shareCopied,
  saveStatus,
  onSubmit,
  onShare,
  t,
}: {
  isValid: boolean;
  shareCopied: boolean;
  saveStatus: SaveStatus;
  onSubmit: () => void;
  onShare: () => void;
  t: TFunc;
}) {
  return (
    <>
      <div className="flex flex-col sm:flex-row items-center justify-center mt-8 gap-3">
        <button
          type="button"
          disabled={!isValid}
          onClick={onSubmit}
          className="group inline-flex items-center justify-center gap-2.5 w-full sm:w-auto px-8 py-3.5 text-[15px] font-semibold text-white bg-indigo-600 rounded-full hover:bg-indigo-700 transition-all duration-300 disabled:opacity-40 disabled:cursor-not-allowed shadow-[0_2px_12px_rgba(79,70,229,0.25)] hover:shadow-[0_4px_20px_rgba(79,70,229,0.35)]"
        >
          <Sparkles className="w-4 h-4 group-hover:rotate-12 transition-transform duration-300" />
          {t('home.actions.generate')}
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

      {!isValid ? (
        <p className="text-center text-[13px] text-gray-400 mt-4">
          {t('home.validation.requiredFields')}
        </p>
      ) : (
        <div className="flex justify-center items-center gap-2 mt-4 h-5" role="status" aria-live="polite">
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
        </div>
      )}
    </>
  );
}
