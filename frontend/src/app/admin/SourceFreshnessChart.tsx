'use client';

import { useMemo } from 'react';
import type { CollectorHistoryEntry, TFunc } from './types';

const SOURCE_COLORS = [
  '#2563eb', '#16a34a', '#dc2626', '#f59e0b', '#8b5cf6',
  '#0ea5e9', '#db2777', '#65a30d', '#475569', '#ea580c',
];

export function SourceFreshnessChart({
  history,
  t,
}: {
  history: CollectorHistoryEntry[];
  t: TFunc;
}) {
  const sources = useMemo(() => {
    const set = new Set<string>();
    for (const entry of history) {
      if (!entry.sources) continue;
      for (const name of Object.keys(entry.sources)) set.add(name);
    }
    return Array.from(set).sort();
  }, [history]);

  if (history.length === 0) {
    return (
      <section className="mb-10">
        <h2 className="text-[15px] font-semibold text-gray-900 mb-3">{t('admin.collectorFreshness.title')}</h2>
        <p className="text-[12px] text-gray-400 italic">{t('admin.collectorFreshness.empty')}</p>
      </section>
    );
  }

  if (history.length === 1 || sources.length === 0) {
    return (
      <section className="mb-10">
        <h2 className="text-[15px] font-semibold text-gray-900 mb-3">{t('admin.collectorFreshness.title')}</h2>
        <p className="text-[12px] text-gray-400 italic">{t('admin.collectorFreshness.needMore')}</p>
      </section>
    );
  }

  const W = 720;
  const H = 200;
  const PAD_X = 40;
  const PAD_Y = 24;
  const xMax = history.length - 1;

  const valueAt = (entry: CollectorHistoryEntry, source: string): number =>
    entry.sources?.[source]?.new ?? 0;

  const yMax = Math.max(
    1,
    ...sources.flatMap((s) => history.map((h) => valueAt(h, s))),
  );

  const x = (i: number) => PAD_X + (i / Math.max(1, xMax)) * (W - 2 * PAD_X);
  const y = (v: number) => H - PAD_Y - (v / yMax) * (H - 2 * PAD_Y);

  const yTicks = [0, Math.round(yMax / 2), yMax];

  const labelTime = (iso: string | undefined): string => {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleDateString();
    } catch {
      return iso;
    }
  };

  const xLabelIndices = history.length <= 3
    ? history.map((_, i) => i)
    : [0, Math.floor(history.length / 2), history.length - 1];

  const series = sources.map((name, idx) => ({
    name,
    color: SOURCE_COLORS[idx % SOURCE_COLORS.length],
  }));

  return (
    <section className="mb-10">
      <h2 className="text-[15px] font-semibold text-gray-900 mb-3">{t('admin.collectorFreshness.title')}</h2>
      <p className="text-[12px] text-gray-500 mb-3">{t('admin.collectorFreshness.subtitle')}</p>
      <div className="bg-white rounded-2xl border border-gray-100 p-4">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
          {yTicks.map((tv) => (
            <g key={tv}>
              <line x1={PAD_X} y1={y(tv)} x2={W - PAD_X} y2={y(tv)} stroke="#f3f4f6" strokeDasharray="2 2" />
              <text x={PAD_X - 6} y={y(tv) + 3} fontSize="10" fill="#9ca3af" textAnchor="end" className="tabular-nums">{tv}</text>
            </g>
          ))}
          <line x1={PAD_X} y1={H - PAD_Y} x2={W - PAD_X} y2={H - PAD_Y} stroke="#e5e7eb" />
          {xLabelIndices.map((i) => (
            <text
              key={`xl-${i}`}
              x={x(i)}
              y={H - PAD_Y + 14}
              fontSize="10"
              fill="#9ca3af"
              textAnchor="middle"
            >
              {labelTime(history[i]?.t)}
            </text>
          ))}
          {series.map((s) => {
            const points = history.map((h, i) => `${x(i)},${y(valueAt(h, s.name))}`).join(' ');
            return (
              <g key={s.name}>
                <polyline fill="none" stroke={s.color} strokeWidth={2} points={points} />
                {history.map((h, i) => {
                  const v = valueAt(h, s.name);
                  return (
                    <circle key={i} cx={x(i)} cy={y(v)} r={3} fill={s.color}>
                      <title>{`${s.name}: ${v} new (${labelTime(h.t)})`}</title>
                    </circle>
                  );
                })}
              </g>
            );
          })}
        </svg>
        <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-3 text-[11px] text-gray-600">
          {series.map((s) => (
            <span key={s.name} className="inline-flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: s.color }} />
              <span className="font-mono">{s.name}</span>
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
