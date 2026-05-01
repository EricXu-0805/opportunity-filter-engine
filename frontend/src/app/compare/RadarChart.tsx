'use client';

import type { Opportunity } from '@/lib/types';
import { RADAR_AXES, type AxisScores, type CompareBucket, type OppScore } from './scores';
import { useT } from '@/i18n/client';

interface Row {
  opp: Opportunity;
  score: OppScore;
  bucket: CompareBucket;
}

interface Props {
  rows: Row[];
}

const COLORS: Record<CompareBucket, { stroke: string; fill: string; bullet: string; text: string }> = {
  top:    { stroke: '#10b981', fill: 'rgba(16,185,129,0.22)', bullet: 'bg-emerald-500', text: 'text-emerald-700' },
  backup: { stroke: '#3b82f6', fill: 'rgba(59,130,246,0.18)', bullet: 'bg-blue-500',    text: 'text-blue-700' },
  reach:  { stroke: '#f59e0b', fill: 'rgba(245,158,11,0.18)', bullet: 'bg-amber-500',   text: 'text-amber-700' },
};

const MAX_RADIUS = 110;
const AXIS_COUNT = 6;
const ANGLE_STEP = (Math.PI * 2) / AXIS_COUNT;

function pointForAxis(axisIndex: number, value: number): { x: number; y: number } {
  const angle = -Math.PI / 2 + axisIndex * ANGLE_STEP;
  const r = (Math.max(0, Math.min(100, value)) / 100) * MAX_RADIUS;
  return { x: r * Math.cos(angle), y: r * Math.sin(angle) };
}

function gridPolygon(scale: number): string {
  const pts: string[] = [];
  for (let i = 0; i < AXIS_COUNT; i += 1) {
    const angle = -Math.PI / 2 + i * ANGLE_STEP;
    const r = MAX_RADIUS * scale;
    pts.push(`${(r * Math.cos(angle)).toFixed(2)},${(r * Math.sin(angle)).toFixed(2)}`);
  }
  return pts.join(' ');
}

function dataPolygon(axes: AxisScores): string {
  return RADAR_AXES.map(({ key }, i) => {
    const p = pointForAxis(i, axes[key]);
    return `${p.x.toFixed(2)},${p.y.toFixed(2)}`;
  }).join(' ');
}

export default function RadarChart({ rows }: Props) {
  const { t } = useT();
  const sortedForLegend = [...rows].sort((a, b) => b.score.overall - a.score.overall);

  return (
    <section className="bg-gradient-to-br from-gray-50 to-blue-50/30 rounded-2xl p-6 mb-8">
      <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-4 px-1">
        {t('compare.radar.title')}
      </h2>
      <div className="flex flex-col lg:flex-row items-center justify-center gap-8">
        <svg viewBox="-160 -160 320 320" className="w-80 h-80 lg:w-96 lg:h-96 shrink-0" aria-hidden="true">
          <g stroke="#d1d5db" fill="none" strokeWidth="1">
            {[1.0, 0.75, 0.5, 0.25].map((s) => (
              <polygon key={s} points={gridPolygon(s)} />
            ))}
          </g>
          <g stroke="#9ca3af" strokeWidth="1">
            {RADAR_AXES.map((_, i) => {
              const p = pointForAxis(i, 100);
              return <line key={i} x1="0" y1="0" x2={p.x.toFixed(2)} y2={p.y.toFixed(2)} />;
            })}
          </g>
          <g fontSize="11" fill="#374151" fontWeight="600" textAnchor="middle">
            {RADAR_AXES.map(({ labelKey }, i) => {
              const angle = -Math.PI / 2 + i * ANGLE_STEP;
              const r = MAX_RADIUS + 20;
              const x = r * Math.cos(angle);
              const y = r * Math.sin(angle) + 4;
              return (
                <text key={labelKey} x={x.toFixed(2)} y={y.toFixed(2)}>
                  {t(labelKey)}
                </text>
              );
            })}
          </g>
          {rows.map(({ opp, score, bucket }) => {
            const c = COLORS[bucket];
            return (
              <polygon
                key={opp.id}
                points={dataPolygon(score.axes)}
                fill={c.fill}
                stroke={c.stroke}
                strokeWidth="2"
                strokeLinejoin="round"
              />
            );
          })}
        </svg>

        <ul className="space-y-2.5 max-w-xs">
          {sortedForLegend.map(({ opp, score, bucket }) => (
            <li key={opp.id} className="flex items-center gap-3">
              <span className={`w-3 h-3 rounded-full shrink-0 ${COLORS[bucket].bullet}`} aria-hidden="true" />
              <span className="text-[13px] font-medium text-gray-800 line-clamp-1 flex-1">
                {opp.title}
              </span>
              <span className={`text-[11px] font-semibold tabular-nums ${COLORS[bucket].text}`}>
                {score.overall}%
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
