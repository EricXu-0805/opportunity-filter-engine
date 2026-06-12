'use client';

/*
 * Post-switch results-page preview — demonstrates the discovery-scope model
 * (decision 2026-06): home school = identity; what you SEE is decided by each
 * opportunity's own audience. Default = home campus + all 'open' items,
 * ranked by interest fit; other schools' campus-only items are hidden until
 * the user widens scope to 全部 (then shown dimmed + labelled, not actionable).
 *
 * Visual vocabulary copied from the real results page: MatchCard's white
 * rounded card + Building2/Clock meta line + Badge chip palette + ScoreBar's
 * gradient bar; the scope control reuses the import-page segmented control.
 */

import { Building2, Clock, Info } from 'lucide-react';
import { useState } from 'react';
import {
  MOCK_RESULTS,
  NATIONAL_OPPORTUNITY_COUNT,
  type MockOpportunity,
  type UniversityEntry,
} from './universities';

type Scope = 'campus' | 'open' | 'all';

function audienceChip(opp: MockOpportunity, currentId: string): { text: string; cls: string } {
  if (opp.audience === 'open') {
    return { text: `${opp.hostLabel} · 对外开放`, cls: 'bg-emerald-50/80 text-emerald-600' };
  }
  if (opp.audience === 'campus') {
    return opp.hostId === currentId
      ? { text: `${opp.hostLabel} · 校内`, cls: 'bg-blue-50/80 text-blue-600' }
      : { text: `${opp.hostLabel} · 仅限本校`, cls: 'bg-gray-100/80 text-gray-500' };
  }
  return { text: `${opp.hostLabel} · 待确认`, cls: 'bg-gray-100/80 text-gray-500' };
}

function ScopeTab({ active, onClick, label, count }: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors ${
        active ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-800'
      }`}
    >
      {label}
      <span className={`ml-1.5 tabular-nums ${active ? 'text-gray-400' : 'text-gray-400/80'}`}>{count}</span>
    </button>
  );
}

export default function ResultsScopeDemo({ current }: { current: UniversityEntry }) {
  const [scope, setScope] = useState<Scope>('open');

  const isMyCampus = (o: MockOpportunity) => o.hostId === current.id;
  const inDefaultScope = (o: MockOpportunity) => isMyCampus(o) || o.audience === 'open';

  const visible = MOCK_RESULTS.filter((o) => {
    if (scope === 'campus') return isMyCampus(o);
    if (scope === 'open') return inDefaultScope(o);
    return true;
  });

  const campusCount = MOCK_RESULTS.filter(isMyCampus).length;
  const defaultCount = MOCK_RESULTS.filter(inDefaultScope).length;

  const pending = current.dataCoverage.nationalOnly;
  const campusPart = `${current.shortTag} 校内${pending ? '（建设中）' : ''}`;
  const indicator =
    scope === 'campus'
      ? `为你展示：${campusPart}`
      : scope === 'open'
        ? `为你展示：${campusPart} + 全国开放机会`
        : '为你展示：全部机会（含他校「仅限本校」项，已标注且不可申请）';

  return (
    <section className="bg-white rounded-2xl shadow-[0_2px_12px_rgba(0,0,0,0.06)] p-6 sm:p-8 mb-4">
      <p className="text-[11px] font-medium text-gray-400 uppercase tracking-wide mb-2">
        切换后 · Results-page preview after switching
      </p>
      <p className="text-[12px] text-gray-500 leading-relaxed mb-4">
        双概念模型：<span className="font-medium text-gray-700">学校 = 身份</span>
        （驱动学院/专业目录、校内机会、F-1 语境）；
        <span className="font-medium text-gray-700">发现范围 = 机会自身的 audience</span>
        （campus / open / unknown）。默认 = 本校校内 + 全部对外开放，按兴趣匹配度排序——
        用户不会被自己的学校限制在门外。
      </p>

      {pending && (
        <div className="flex items-start gap-3 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 mb-4">
          <Info className="w-4 h-4 text-blue-700 shrink-0 mt-0.5" aria-hidden="true" />
          <div className="flex-1 text-[13px] leading-relaxed">
            <p className="font-semibold text-blue-900">
              {current.shortTag}{' '}campus data is coming — here&rsquo;s everything you can apply to right now
            </p>
            <p className="text-blue-800 mt-0.5">
              {current.shortTag} 校内数据建设中；约 {NATIONAL_OPPORTUNITY_COUNT.toLocaleString()}{' '}
              条对外开放机会（NSF REU、MIT MSRP、Simplify 等）照常按你的兴趣排序展示。
            </p>
          </div>
        </div>
      )}

      <div className="rounded-xl border border-gray-200 bg-gray-50/60 p-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
          <p className="text-[12px] font-medium text-gray-600">{indicator}</p>
          <div role="tablist" aria-label="Discovery scope" className="flex gap-1 p-1 bg-gray-100 rounded-xl w-fit shrink-0">
            <ScopeTab active={scope === 'campus'} onClick={() => setScope('campus')} label="我的学校" count={campusCount} />
            <ScopeTab active={scope === 'open'} onClick={() => setScope('open')} label="+对外开放" count={defaultCount} />
            <ScopeTab active={scope === 'all'} onClick={() => setScope('all')} label="全部" count={MOCK_RESULTS.length} />
          </div>
        </div>

        {visible.length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-200 bg-white px-4 py-8 text-center">
            <p className="text-[13px] font-medium text-gray-600">{current.shortTag} 校内机会建设中 · 0 条</p>
            <p className="mt-1 text-[12px] text-gray-400">
              切到「+对外开放」即可看到你现在就能申请的全国机会
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {visible.map((opp) => {
              const locked = !inDefaultScope(opp);
              const chip = audienceChip(opp, current.id);
              return (
                <div
                  key={opp.id}
                  data-testid={`demo-result-${opp.id}`}
                  className={`bg-white rounded-xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-4 ${locked ? 'opacity-55' : ''}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-[14px] font-semibold text-gray-900 leading-snug">{opp.title}</p>
                      <p className="flex items-center gap-1 text-[12px] text-gray-400 mt-1 min-w-0">
                        <Building2 className="w-3 h-3 shrink-0" aria-hidden="true" />
                        <span className="truncate">{opp.org}</span>
                      </p>
                    </div>
                    <span className="text-sm font-semibold tabular-nums text-emerald-600 shrink-0">
                      {opp.matchScore}%
                    </span>
                  </div>
                  <div className="mt-2.5 bg-black/[0.04] rounded-full overflow-hidden h-1.5">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-emerald-300"
                      style={{ width: `${opp.matchScore}%` }}
                    />
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 mt-2.5">
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium ${chip.cls}`}>
                      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-60" aria-hidden="true" />
                      {chip.text}
                    </span>
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium bg-gray-100/80 text-gray-500">
                      <Clock className="w-3 h-3" aria-hidden="true" />
                      {opp.deadline}
                    </span>
                    {locked && (
                      <span className="text-[11px] text-gray-400">仅限 {opp.hostLabel} 学生 · 对你不可申请</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
