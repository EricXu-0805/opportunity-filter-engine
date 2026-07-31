'use client';

import { ExternalLink, Sparkles, Star, Shield, Mountain } from 'lucide-react';
import type { CompareRow } from './scores';
import { useT } from '@/i18n/client';
import { noDeadlineKind } from '@/app/opportunities/[id]/detail-utils';

interface Props {
  rows: CompareRow[];
}

type DisplayBucket = 'high_priority' | 'good_match' | 'reach' | 'low_fit' | 'unknown';

const BUCKET_STYLE: Record<DisplayBucket, {
  borderClass: string;
  bgClass: string;
  badgeBg: string;
  badgeText: string;
  scoreText: string;
  applyClass: string;
  Icon: typeof Star;
  labelKey: string;
}> = {
  high_priority: {
    borderClass: 'border-2 border-emerald-300',
    bgClass: 'bg-gradient-to-br from-emerald-50 to-white',
    badgeBg: 'bg-emerald-500',
    badgeText: 'text-white',
    scoreText: 'text-emerald-600',
    applyClass: 'bg-emerald-600 hover:bg-emerald-700 text-white',
    Icon: Star,
    labelKey: 'compare.bucket.highPriority',
  },
  good_match: {
    borderClass: 'border border-indigo-200',
    bgClass: 'bg-white',
    badgeBg: 'bg-indigo-500',
    badgeText: 'text-white',
    scoreText: 'text-indigo-600',
    applyClass: 'bg-white border border-gray-300 text-gray-700 hover:bg-gray-50',
    Icon: Shield,
    labelKey: 'compare.bucket.goodMatch',
  },
  reach: {
    borderClass: 'border border-gray-200',
    bgClass: 'bg-gray-50/60',
    badgeBg: 'bg-amber-500',
    badgeText: 'text-white',
    scoreText: 'text-amber-600',
    applyClass: 'bg-white border border-gray-300 text-gray-500 hover:bg-gray-50',
    Icon: Mountain,
    labelKey: 'compare.bucket.reach',
  },
  low_fit: {
    borderClass: 'border border-gray-200',
    bgClass: 'bg-gray-50/60',
    badgeBg: 'bg-gray-500',
    badgeText: 'text-white',
    scoreText: 'text-gray-600',
    applyClass: 'bg-white border border-gray-300 text-gray-500 hover:bg-gray-50',
    Icon: Mountain,
    labelKey: 'compare.bucket.lowFit',
  },
  unknown: {
    borderClass: 'border border-gray-200',
    bgClass: 'bg-white',
    badgeBg: 'bg-gray-400',
    badgeText: 'text-white',
    scoreText: 'text-gray-500',
    applyClass: 'bg-white border border-gray-300 text-gray-600 hover:bg-gray-50',
    Icon: Shield,
    labelKey: 'compare.bucket.unknown',
  },
};

function displayBucket(bucket: string | undefined): DisplayBucket {
  if (bucket === 'high_priority' || bucket === 'good_match' || bucket === 'reach' || bucket === 'low_fit') {
    return bucket;
  }
  return 'unknown';
}

function ScoreBars({ overall, color }: { overall: number; color: string }) {
  const filled = Math.max(0, Math.min(5, Math.round(overall / 20)));
  return (
    <div className="flex gap-0.5" aria-label={`${overall}% match`}>
      {[0, 1, 2, 3, 4].map((i) => (
        <span
          key={i}
          className={`w-1.5 h-3.5 rounded-sm ${i < filled ? color : 'bg-gray-200'}`}
        />
      ))}
    </div>
  );
}

export default function BucketCards({ rows }: Props) {
  const { t } = useT();

  const colsClass = rows.length === 2 ? 'md:grid-cols-2' : rows.length === 3 ? 'md:grid-cols-3' : 'md:grid-cols-4';

  return (
    <section className="mb-8">
      <div className={`grid grid-cols-1 ${colsClass} gap-4`}>
        {rows.map(({ opp, match, status }) => {
          const bucket = displayBucket(match?.bucket);
          const style = BUCKET_STYLE[bucket];
          const isError = status === 'error' || !match;
          const fits = match?.reasons_fit ?? [];
          const gaps = match?.reasons_gap ?? [];
          const applyUrl = opp.application?.application_url || opp.url || opp.source_url;
          const isFacultyProfile = Boolean(
            opp.id.startsWith('faculty-')
            || (opp.source ?? '').toLowerCase().includes('faculty'),
          );
          const actionLabel = isFacultyProfile
            ? t('compare.viewFaculty')
            : opp.application?.application_url
              ? t('compare.apply')
              : t('compare.viewSource');
          // A listed date always beats the `is_rolling` flag (a blanket
          // collector default, not scraped evidence); without a date,
          // "Rolling" renders only on actual rolling evidence — otherwise
          // the honest claim is just "no fixed deadline".
          const deadlineSummary = opp.deadline
            ? `${opp.deadline}${
                opp.deadline_is_estimate === false
                  ? ''
                  : ` · ${t(
                      opp.deadline_is_estimate === true
                        ? 'compare.deadlineEstimated'
                        : 'compare.deadlineVerify',
                    )}`
              }`
            : opp.is_rolling
              ? t(noDeadlineKind(opp) === 'rolling' ? 'compare.rolling' : 'compare.noDeadline')
              : null;

          return (
            <article
              key={opp.id}
              className={`relative ${style.bgClass} ${style.borderClass} rounded-2xl p-5 flex flex-col`}
            >
              <div className="flex items-center justify-between mb-3 gap-2">
                <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${style.badgeBg} ${style.badgeText}`}>
                  <style.Icon className="w-3 h-3" aria-hidden="true" />
                  {t(style.labelKey)}
                </span>
                {match && <ScoreBars overall={match.final_score} color={style.badgeBg} />}
              </div>

              <a
                href={`/opportunities/${encodeURIComponent(opp.id)}`}
                className="text-[15px] font-bold text-gray-900 leading-snug line-clamp-2 hover:text-indigo-600 transition-colors"
              >
                {opp.title}
              </a>
              <p className="text-[12px] text-gray-500 mt-1 truncate">
                {[opp.organization, deadlineSummary]
                  .filter(Boolean).join(' · ')}
              </p>

              {match && (
                <div className="mt-4 flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <div className={`text-3xl font-bold ${style.scoreText}`}>{match.final_score}%</div>
                  <div className="text-[11px] text-gray-500">{t('compare.matchForYou')}</div>
                  {match.method === 'llm' && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] font-semibold text-indigo-700">
                      <Sparkles className="h-3 w-3" aria-hidden="true" />
                      {t('compare.aiAdjustedScore')}
                    </span>
                  )}
                </div>
              )}

              {match && fits.length > 0 && (
                <div className="mt-4">
                  <h4 className="text-[10px] font-bold text-emerald-700 mb-1.5 uppercase tracking-wider">
                    {t('compare.strengths')}
                  </h4>
                  <ul className="space-y-1 text-[12.5px] text-gray-700">
                    {fits.slice(0, 5).map((line, i) => (
                      <li key={i} className="flex gap-1.5">
                        <span className="text-emerald-500 shrink-0">✓</span>
                        <span className="leading-snug">{line}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {match && gaps.length > 0 && (
                <div className="mt-3">
                  <h4 className="text-[10px] font-bold text-amber-700 mb-1.5 uppercase tracking-wider">
                    {t('compare.concerns')}
                  </h4>
                  <ul className="space-y-1 text-[12.5px] text-gray-700">
                    {gaps.slice(0, 3).map((line, i) => (
                      <li key={i} className="flex gap-1.5">
                        <span className="text-amber-500 shrink-0">!</span>
                        <span className="leading-snug">{line}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {match?.method === 'llm' && match.explanation && (
                <p className="mt-3 text-[12px] text-gray-600 italic leading-relaxed border-l-2 border-indigo-200 pl-2 flex items-start gap-1.5">
                  <Sparkles className="w-3 h-3 text-indigo-500 mt-0.5 shrink-0" aria-hidden="true" />
                  <span>{match.explanation}</span>
                </p>
              )}

              {isError && (
                <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-[12px] leading-relaxed text-amber-900">
                  <p className="font-semibold">{t('compare.canonicalUnavailableTitle')}</p>
                  <p className="mt-1">{t('compare.canonicalUnavailableBody')}</p>
                </div>
              )}

              {applyUrl && (
                <a
                  href={applyUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`mt-5 inline-flex items-center justify-center gap-1.5 py-2 rounded-xl text-[13px] font-semibold transition-colors ${style.applyClass}`}
                >
                  <ExternalLink className="w-3.5 h-3.5" aria-hidden="true" />
                  {actionLabel}
                </a>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
