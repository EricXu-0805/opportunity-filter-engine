'use client';

import { Download, Sparkles } from 'lucide-react';
import EmailMeButton from '@/components/EmailMeButton';
import { sendMatchesEmail } from '@/lib/api';
import type { MatchResult, MatchesResponse } from '@/lib/types';
import { SemanticToggle } from './SemanticToggle';
import type { Tab, TFunc } from './types';

export interface ResultsHeaderProps {
  loading: boolean;
  showSlowHint: boolean;
  data: MatchesResponse | null;
  filtered: MatchResult[];
  counts: { all: number };
  favs: Set<string>;
  activeTab: Tab;
  semanticRerank: boolean;
  onSemanticChange: (v: boolean) => void;
  onOpenHelp: () => void;
  onExport: () => void;
  loadingMessage?: string;
  t: TFunc;
}

export function ResultsHeader({
  loading,
  showSlowHint,
  data,
  filtered,
  counts,
  favs,
  activeTab,
  semanticRerank,
  onSemanticChange,
  onOpenHelp,
  onExport,
  loadingMessage,
  t,
}: ResultsHeaderProps) {
  return (
    <div className="mb-8 sm:mb-10 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-2xl sm:text-4xl font-bold text-gray-900 tracking-tight">
          {t('results.title')}
        </h1>
        <p
          className="mt-1.5 sm:mt-2 text-[13px] sm:text-[15px] text-gray-400 transition-opacity duration-200"
          aria-busy={loading}
          aria-live="polite"
        >
          {loading
            ? loadingMessage || (semanticRerank ? t('results.analyzingAi') : t('results.analyzing'))
            : data
              ? (
                <>
                  {t('results.rankedFor', { count: counts.all })}
                  {semanticRerank && (
                    <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-violet-50 text-violet-700 align-middle">
                      <Sparkles className="w-2.5 h-2.5" aria-hidden="true" />
                      {t('results.aiBadge')}
                    </span>
                  )}
                </>
              )
              : t('common.loading')}
        </p>
        {!loading && data && typeof data.field_relevant_count === 'number' && data.field_relevant_count > 0 && (
          <p className="mt-1 text-[12px] sm:text-[13px] font-medium text-indigo-700">
            {data.field_relevant_count === 1
              ? t('results.fieldMatchesOne')
              : t('results.fieldMatches', { count: data.field_relevant_count })}
            {data.thin_inventory && (
              <span className="ml-1.5 font-normal text-gray-400">· {t('results.thinInventory')}</span>
            )}
          </p>
        )}
        {loading && showSlowHint && (
          <p className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2.5 py-1">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" aria-hidden="true" />
            {t('results.slowHint')}
          </p>
        )}
      </div>
      <div className="flex items-center gap-2">
        <SemanticToggle value={semanticRerank} onChange={onSemanticChange} disabled={loading} t={t} />
        {!loading && data && (
          <button
            type="button"
            onClick={onOpenHelp}
            className="hidden md:inline-flex items-center justify-center h-6 px-2 text-[10px] font-mono text-gray-400 bg-gray-100 border border-gray-200 rounded hover:bg-gray-200 hover:text-gray-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 transition-colors"
            aria-label={t('results.keyboardHelp.open_aria_show')}
            title={t('results.keyboardHelp.open_title')}
          >
            ?
          </button>
        )}
        {!loading && data && filtered.length > 0 && (
          // R69-D: the sendMatchesEmail path silently caps at the top 50
          // by match score. When the filtered list exceeds that cap the
          // label and tooltip now say so explicitly, so users aren't
          // surprised by a clipped email.
          <EmailMeButton
            label={
              filtered.length > 50
                ? t('email.sendMatchesTop', { count: 50 })
                : t('email.sendMatches')
            }
            title={
              filtered.length > 50
                ? `${t('email.matchesCapNote')} — ${t('email.subtitle')}`
                : t('email.subtitle')
            }
            onSend={async (emailAddr) => {
              const top = filtered.slice(0, 50);
              const items = top.map((m) => ({
                title: m.opportunity.title,
                url: m.opportunity.url || m.opportunity.source_url || '',
                score: m.final_score,
                source: m.opportunity.source || '',
                deadline: m.opportunity.deadline || null,
                organization: m.opportunity.organization || '',
              }));
              const hint = t('email.subjectMatches', { count: items.length });
              return sendMatchesEmail(emailAddr, items, hint);
            }}
          />
        )}
        {!loading && data && favs.size > 0 && (
          <button
            type="button"
            onClick={onExport}
            className="inline-flex items-center gap-2 px-3 py-2 text-[12px] font-medium text-gray-600 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors"
            title={activeTab === 'starred' ? t('results.exportFilteredTitle') : t('results.exportStarredTitle')}
          >
            <Download className="w-3.5 h-3.5" />
            {activeTab === 'starred'
              ? t('results.exportLabelFiltered')
              : t('results.exportLabelStarred', { count: favs.size })}
          </button>
        )}
      </div>
    </div>
  );
}
