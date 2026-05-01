'use client';

import { useEffect, useState } from 'react';
import { ExternalLink, Loader2, Sparkles, Star, Shield, Mountain } from 'lucide-react';
import type { Opportunity, ProfileData } from '@/lib/types';
import { getMatchExplanation, type MatchExplanationResponse } from '@/lib/api';
import type { CompareBucket, OppScore } from './scores';
import { useT } from '@/i18n/client';

type BucketRow = {
  opp: Opportunity;
  score: OppScore;
  bucket: CompareBucket;
};

interface Props {
  rows: BucketRow[];
  profile: ProfileData | null;
}

const BUCKET_STYLE: Record<CompareBucket, {
  borderClass: string;
  bgClass: string;
  badgeBg: string;
  badgeText: string;
  scoreText: string;
  applyClass: string;
  Icon: typeof Star;
  labelKey: string;
}> = {
  top: {
    borderClass: 'border-2 border-emerald-300',
    bgClass: 'bg-gradient-to-br from-emerald-50 to-white',
    badgeBg: 'bg-emerald-500',
    badgeText: 'text-white',
    scoreText: 'text-emerald-600',
    applyClass: 'bg-emerald-600 hover:bg-emerald-700 text-white',
    Icon: Star,
    labelKey: 'compare.bucket.top',
  },
  backup: {
    borderClass: 'border border-blue-200',
    bgClass: 'bg-white',
    badgeBg: 'bg-blue-500',
    badgeText: 'text-white',
    scoreText: 'text-blue-600',
    applyClass: 'bg-white border border-gray-300 text-gray-700 hover:bg-gray-50',
    Icon: Shield,
    labelKey: 'compare.bucket.backup',
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
};

function ScoreBars({ overall, color }: { overall: number; color: string }) {
  const filled = Math.max(1, Math.min(5, Math.round(overall / 20)));
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

export default function BucketCards({ rows, profile }: Props) {
  const { t } = useT();
  const [explanations, setExplanations] = useState<Map<string, MatchExplanationResponse | 'error'>>(new Map());

  useEffect(() => {
    if (!profile) return;
    const ids = rows.map((r) => r.opp.id);
    let cancelled = false;
    (async () => {
      await Promise.all(
        ids.map(async (id) => {
          try {
            const resp = await getMatchExplanation(profile, id);
            if (!cancelled) {
              setExplanations((prev) => {
                const next = new Map(prev);
                next.set(id, resp);
                return next;
              });
            }
          } catch {
            if (!cancelled) {
              setExplanations((prev) => {
                const next = new Map(prev);
                next.set(id, 'error');
                return next;
              });
            }
          }
        }),
      );
    })();
    return () => { cancelled = true; };
  }, [rows, profile]);

  const colsClass = rows.length === 2 ? 'md:grid-cols-2' : rows.length === 3 ? 'md:grid-cols-3' : 'md:grid-cols-4';

  return (
    <section className="mb-8">
      <div className={`grid grid-cols-1 ${colsClass} gap-4`}>
        {rows.map(({ opp, score, bucket }) => {
          const style = BUCKET_STYLE[bucket];
          const data = explanations.get(opp.id);
          const isLoading = data === undefined;
          const isError = data === 'error';
          const exp = !isLoading && !isError ? data : null;
          const fits = exp?.reasons_fit ?? [];
          const gaps = exp?.reasons_gap ?? [];
          const applyUrl = opp.application?.application_url || opp.url || opp.source_url;

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
                <ScoreBars overall={score.overall} color={style.badgeBg} />
              </div>

              <a
                href={`/opportunities/${encodeURIComponent(opp.id)}`}
                className="text-[15px] font-bold text-gray-900 leading-snug line-clamp-2 hover:text-blue-600 transition-colors"
              >
                {opp.title}
              </a>
              <p className="text-[12px] text-gray-500 mt-1 truncate">
                {[opp.organization, opp.is_rolling ? t('compare.rolling') : opp.deadline]
                  .filter(Boolean).join(' · ')}
              </p>

              <div className="flex items-baseline gap-2 mt-4">
                <div className={`text-3xl font-bold ${style.scoreText}`}>{score.overall}%</div>
                <div className="text-[11px] text-gray-500">{t('compare.matchForYou')}</div>
              </div>

              {isLoading && (
                <div className="mt-4 flex items-center gap-2 text-[12px] text-gray-400">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  {t('compare.analyzing')}
                </div>
              )}

              {!isLoading && exp && fits.length > 0 && (
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

              {!isLoading && exp && gaps.length > 0 && (
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

              {!isLoading && exp && exp.method === 'llm' && exp.explanation && (
                <p className="mt-3 text-[12px] text-gray-600 italic leading-relaxed border-l-2 border-indigo-200 pl-2 flex items-start gap-1.5">
                  <Sparkles className="w-3 h-3 text-indigo-500 mt-0.5 shrink-0" aria-hidden="true" />
                  <span>{exp.explanation}</span>
                </p>
              )}

              {isError && (
                <p className="mt-4 text-[12px] text-red-600">{t('compare.analyzeFailed')}</p>
              )}

              {applyUrl && (
                <a
                  href={applyUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`mt-5 inline-flex items-center justify-center gap-1.5 py-2 rounded-xl text-[13px] font-semibold transition-colors ${style.applyClass}`}
                >
                  <ExternalLink className="w-3.5 h-3.5" aria-hidden="true" />
                  {t('compare.apply')}
                </a>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
