'use client';

import type { HistoryEntry } from './types';

export function TrendChart({ history }: { history: HistoryEntry[] }) {
  if (history.length < 2) return null;

  const series = [
    { key: 'empty_majors' as const, label: 'Empty majors', color: '#f59e0b' },
    { key: 'empty_keywords' as const, label: 'Empty keywords', color: '#8b5cf6' },
    { key: 'missing_deadline' as const, label: 'Missing deadline', color: '#6b7280' },
    { key: 'flagged_inactive' as const, label: 'Flagged inactive', color: '#94a3b8' },
  ];

  const W = 720;
  const H = 180;
  const PAD = 30;

  const xMax = history.length - 1;
  const yValues = series.flatMap(s => history.map(h => h[s.key] ?? 0));
  const yMax = Math.max(1, ...yValues);

  const x = (i: number) => PAD + (i / Math.max(1, xMax)) * (W - 2 * PAD);
  const y = (v: number) => H - PAD - (v / yMax) * (H - 2 * PAD);

  const yTicks = [0, Math.round(yMax / 2), yMax];

  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-4">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
        {yTicks.map(tv => (
          <g key={tv}>
            <line x1={PAD} y1={y(tv)} x2={W - PAD} y2={y(tv)} stroke="#f3f4f6" strokeDasharray="2 2" />
            <text x={PAD - 6} y={y(tv) + 3} fontSize="10" fill="#9ca3af" textAnchor="end" className="tabular-nums">{tv}</text>
          </g>
        ))}
        <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="#e5e7eb" />
        {series.map(s => {
          const points = history.map((h, i) => `${x(i)},${y(h[s.key] ?? 0)}`).join(' ');
          return (
            <g key={s.key}>
              <polyline fill="none" stroke={s.color} strokeWidth={2} points={points} />
              {history.map((h, i) => {
                const v = h[s.key] ?? 0;
                const dateLabel = (() => { try { return new Date(h.t).toLocaleDateString(); } catch { return h.t; } })();
                return (
                  <circle key={i} cx={x(i)} cy={y(v)} r={3} fill={s.color}>
                    <title>{`${s.label}: ${v} (${dateLabel})`}</title>
                  </circle>
                );
              })}
            </g>
          );
        })}
      </svg>
      <div className="flex flex-wrap gap-3 mt-3 text-[11px] text-gray-600">
        {series.map(s => (
          <span key={s.key} className="inline-flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}
