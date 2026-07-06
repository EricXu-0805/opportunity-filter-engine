'use client';

import { BarChart3, MessageSquareText, ThumbsDown } from 'lucide-react';
import { StatCard } from './StatCard';
import type { FeedbackAnalysis, FeedbackRateRow, TFunc, FeedbackInbox } from './types';

function RateBreakdown({ title, rows }: { title: string; rows?: FeedbackRateRow[] }) {
  if (!rows || rows.length === 0) return null;
  return (
    <div>
      <p className="text-[11px] font-medium text-gray-400 mb-1">{title}</p>
      <ul className="space-y-1">
        {rows.map((r) => (
          <li key={r.key} className="flex items-center gap-2 text-[12px] text-gray-600">
            <span className="w-24 truncate shrink-0">{r.key}</span>
            <span className="flex-1 h-1.5 rounded-full bg-gray-100 overflow-hidden">
              <span
                className="block h-full rounded-full bg-indigo-400"
                style={{ width: `${Math.round(r.up_rate * 100)}%` }}
              />
            </span>
            <span className="w-16 text-right tabular-nums text-gray-500">
              {Math.round(r.up_rate * 100)}% · {r.n}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AnalysisBlock({ analysis, t }: { analysis: FeedbackAnalysis; t: TFunc }) {
  const replay = analysis.replay;
  return (
    <div className="mt-4">
      <p className="text-[12px] font-medium text-gray-500 mb-2 flex items-center gap-1">
        <BarChart3 className="w-3 h-3" /> {t('admin.feedback.analysisTitle')}
      </p>
      {analysis.insufficient ? (
        <p className="text-[13px] text-gray-400 italic">
          {t('admin.feedback.analysisInsufficient', {
            n: analysis.sample_n,
            needed: analysis.needed ?? 50,
          })}
        </p>
      ) : (
        <>
          <p className="text-[12px] text-gray-600 mb-2">
            {t('admin.feedback.analysisUpRate', {
              rate: Math.round((analysis.up_rate ?? 0) * 100),
              n: analysis.sample_n,
            })}
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <RateBreakdown title={t('admin.feedback.analysisByBucket')} rows={analysis.by_bucket} />
            <RateBreakdown title={t('admin.feedback.analysisByScore')} rows={analysis.by_score_band} />
            <RateBreakdown title={t('admin.feedback.analysisBySchool')} rows={analysis.by_school} />
            <RateBreakdown title={t('admin.feedback.analysisByPosition')} rows={analysis.by_position} />
          </div>
          {replay && (
            <div className="mt-3 text-[12px] text-gray-600">
              <p>
                {t('admin.feedback.analysisAgreement', {
                  value:
                    replay.current_agreement != null
                      ? `${Math.round(replay.current_agreement * 100)}%`
                      : '—',
                })}
                {replay.mode === 'weight_replay' && replay.best_candidate && (
                  <>
                    {' · '}
                    {t('admin.feedback.analysisReplayBest', {
                      weights: `${replay.best_candidate.eligibility}/${replay.best_candidate.readiness}/${replay.best_candidate.upside}`,
                      delta: `${replay.delta != null && replay.delta > 0 ? '+' : ''}${Math.round((replay.delta ?? 0) * 100)}%`,
                    })}
                  </>
                )}
              </p>
              <p className="mt-0.5 text-[11px] text-gray-400">{replay.note}</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function FeedbackSection({ inbox, t }: { inbox: FeedbackInbox | null; t: TFunc }) {
  if (!inbox) return null;
  const entries = inbox.entries ?? [];
  const mf = inbox.match_feedback;
  return (
    <section className="mt-10">
      <h2 className="text-[15px] font-semibold text-gray-900 mb-3 flex items-center gap-2">
        <MessageSquareText className="w-4 h-4 text-indigo-600" />
        {t('admin.feedback.title')}
      </h2>
      {inbox.status !== 'ok' ? (
        <p className="text-[13px] text-gray-400 italic">{t('admin.feedback.unconfigured')}</p>
      ) : (
        <>
          {mf && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <StatCard label={t('admin.feedback.thumbsUp')} value={mf.up} color="green" />
              <StatCard label={t('admin.feedback.thumbsDown')} value={mf.down} color={mf.down > mf.up ? 'amber' : 'gray'} />
              <StatCard label={t('admin.feedback.thumbsUp7d')} value={mf.up_7d} color="blue" />
              <StatCard label={t('admin.feedback.thumbsDown7d')} value={mf.down_7d} color={mf.down_7d > 0 ? 'amber' : 'gray'} />
            </div>
          )}
          {mf?.analysis && <AnalysisBlock analysis={mf.analysis} t={t} />}
          {mf && mf.top_downvoted.length > 0 && (
            <div className="mt-3">
              <p className="text-[12px] font-medium text-gray-500 mb-1 flex items-center gap-1">
                <ThumbsDown className="w-3 h-3" /> {t('admin.feedback.topDownvoted')}
              </p>
              <ul className="text-[12px] text-gray-600 space-y-0.5">
                {mf.top_downvoted.slice(0, 5).map((d) => (
                  <li key={d.opportunity_id} className="truncate">
                    <span className="font-mono text-gray-400">{d.downs}×</span>{' '}
                    {d.title ?? d.opportunity_id}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="mt-4">
            <p className="text-[12px] font-medium text-gray-500 mb-2">
              {t('admin.feedback.inbox', { count: entries.length })}
            </p>
            {entries.length === 0 ? (
              <p className="text-[13px] text-gray-400 italic">{t('admin.feedback.empty')}</p>
            ) : (
              <ul className="space-y-2">
                {entries.map((e) => (
                  <li key={e.id} className="rounded-xl border border-black/[0.06] bg-white px-3.5 py-2.5">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-gray-400">
                      <span>{new Date(e.created_at).toLocaleString()}</span>
                      {typeof e.props?.path === 'string' && e.props.path && (
                        <span className="font-mono">{e.props.path}</span>
                      )}
                      {e.email && (
                        <a href={`mailto:${e.email}`} className="text-indigo-600 hover:text-indigo-700">
                          {e.email}
                        </a>
                      )}
                    </div>
                    <p className="mt-1 text-[13px] text-gray-800 whitespace-pre-wrap break-words">{e.message}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}
