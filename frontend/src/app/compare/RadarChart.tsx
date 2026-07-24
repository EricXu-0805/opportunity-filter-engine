'use client';

import { useState } from 'react';
import { useT } from '@/i18n/client';
import { RADAR_AXES, type AxisScores, type CompareRow } from './scores';

interface Props {
  rows: CompareRow[];
}

// Compare is capped at four opportunities. Each receives a stable categorical
// color plus a different dash pattern, so identity does not rely on color alone.
const SERIES_STYLES = [
  { stroke: '#2563eb', dash: undefined },
  { stroke: '#d97706', dash: '9 3' },
  { stroke: '#7c3aed', dash: '3 3' },
  { stroke: '#0f766e', dash: '11 3 2 3' },
] as const;

const MAX_RADIUS = 110;
const AXIS_COUNT = RADAR_AXES.length;
const ANGLE_STEP = (Math.PI * 2) / AXIS_COUNT;

function clamp(value: number): number {
  return Math.max(0, Math.min(100, value));
}

function pointForAxis(axisIndex: number, value: number): { x: number; y: number } {
  const angle = -Math.PI / 2 + axisIndex * ANGLE_STEP;
  const radius = (clamp(value) / 100) * MAX_RADIUS;
  return { x: radius * Math.cos(angle), y: radius * Math.sin(angle) };
}

function gridPolygon(value: number): string {
  return RADAR_AXES.map((_, index) => {
    const point = pointForAxis(index, value);
    return `${point.x.toFixed(2)},${point.y.toFixed(2)}`;
  }).join(' ');
}

function dataPolygon(factors: AxisScores): string {
  return RADAR_AXES.map(({ key }, index) => {
    const value = factors[key];
    if (value === null) return '';
    const point = pointForAxis(index, value);
    return `${point.x.toFixed(2)},${point.y.toFixed(2)}`;
  }).join(' ');
}

export default function RadarChart({ rows }: Props) {
  const { t } = useT();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const activeId = previewId ?? selectedId;
  const labels = RADAR_AXES.map(({ labelKey }) => t(labelKey));

  return (
    <section className="mb-8 rounded-2xl border border-gray-200 bg-white p-3 sm:p-6">
      <div className="px-1">
        <h2 id="compare-radar-title" className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
          {t('compare.radar.decisionTitle')}
        </h2>
        <p id="compare-radar-note" className="mt-2 max-w-3xl text-[12px] leading-relaxed text-gray-600">
          {t('compare.radar.estimateNote')}
        </p>
      </div>

      <div className="mt-5 flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-10">
        <div
          data-testid="radar-scroll-region"
          className="-mx-1 overflow-x-auto overscroll-x-contain px-1 pb-1 lg:mx-0 lg:w-[430px] lg:shrink-0"
        >
          <svg
            viewBox="-175 -165 350 340"
            className="mx-auto aspect-square w-full min-w-[320px] max-w-[430px] shrink-0"
            role="img"
            aria-labelledby="compare-radar-title compare-radar-note"
          >
          <g fill="none" stroke="#d1d5db" strokeWidth="1">
            {[25, 50, 75, 100].map((tick) => (
              <polygon key={tick} points={gridPolygon(tick)} />
            ))}
          </g>
          <g stroke="#9ca3af" strokeWidth="1">
            {RADAR_AXES.map((_, index) => {
              const point = pointForAxis(index, 100);
              return <line key={index} x1="0" y1="0" x2={point.x} y2={point.y} />;
            })}
          </g>

          <g fontSize="10" fill="#6b7280" fontWeight="600" textAnchor="start">
            {[0, 25, 50, 75, 100].map((tick) => (
              <text
                key={tick}
                data-testid={`radar-tick-${tick}`}
                x="4"
                y={tick === 0 ? 10 : -((tick / 100) * MAX_RADIUS) + 3}
              >
                {tick}
              </text>
            ))}
          </g>

          <g fontSize="12" fill="#1f2937" fontWeight="600" textAnchor="middle">
            {RADAR_AXES.map((_, index) => {
              const angle = -Math.PI / 2 + index * ANGLE_STEP;
              const radius = MAX_RADIUS + 25;
              const x = radius * Math.cos(angle);
              const y = radius * Math.sin(angle) + 4;
              return <text key={labels[index]} x={x} y={y}>{labels[index]}</text>;
            })}
          </g>

          {rows.map((row, seriesIndex) => {
            const style = SERIES_STYLES[seriesIndex % SERIES_STYLES.length];
            const active = activeId === row.opp.id;
            const muted = activeId !== null && !active;
            const complete = RADAR_AXES.every(({ key }) => row.factors[key] !== null);
            return (
              <g key={row.opp.id}>
                {complete ? (
                  <polygon
                    data-series-id={row.opp.id}
                    points={dataPolygon(row.factors)}
                    fill="none"
                    stroke={style.stroke}
                    strokeWidth={active ? 4 : 2}
                    strokeDasharray={style.dash}
                    strokeLinejoin="round"
                    opacity={muted ? 0.2 : 1}
                  />
                ) : RADAR_AXES.map(({ key }, axisIndex) => {
                  const nextIndex = (axisIndex + 1) % RADAR_AXES.length;
                  const nextKey = RADAR_AXES[nextIndex].key;
                  const value = row.factors[key];
                  const nextValue = row.factors[nextKey];
                  if (value === null || nextValue === null) return null;
                  const start = pointForAxis(axisIndex, value);
                  const end = pointForAxis(nextIndex, nextValue);
                  return (
                    <line
                      key={`${key}-${nextKey}`}
                      data-series-id={row.opp.id}
                      x1={start.x}
                      y1={start.y}
                      x2={end.x}
                      y2={end.y}
                      stroke={style.stroke}
                      strokeWidth={active ? 4 : 2}
                      strokeDasharray={style.dash}
                      opacity={muted ? 0.2 : 1}
                    />
                  );
                })}
                {RADAR_AXES.map(({ key }, axisIndex) => {
                  const value = row.factors[key];
                  if (value === null) return null;
                  const point = pointForAxis(axisIndex, value);
                  return (
                    <circle
                      key={key}
                      data-series-id={row.opp.id}
                      data-value={value}
                      cx={point.x}
                      cy={point.y}
                      r={active ? 4 : 3}
                      fill="white"
                      stroke={style.stroke}
                      strokeWidth="2"
                      opacity={muted ? 0.2 : 1}
                    />
                  );
                })}
              </g>
            );
          })}
          </svg>
        </div>

        <div className="min-w-0 flex-1 w-full">
          <ul className="space-y-2" aria-label={t('compare.radar.legendLabel')}>
            {rows.map((row, seriesIndex) => {
              const style = SERIES_STYLES[seriesIndex % SERIES_STYLES.length];
              const score = row.match ? `${row.match.final_score}%` : t('compare.scoreUnavailable');
              const active = activeId === row.opp.id;
              const selected = selectedId === row.opp.id;
              return (
                <li key={row.opp.id}>
                  <button
                    type="button"
                    tabIndex={0}
                    aria-label={`${row.opp.title}, ${score}`}
                    aria-pressed={selected}
                    onClick={() => setSelectedId((current) => (
                      current === row.opp.id ? null : row.opp.id
                    ))}
                    onMouseEnter={() => setPreviewId(row.opp.id)}
                    onMouseLeave={() => setPreviewId(null)}
                    onFocus={() => setPreviewId(row.opp.id)}
                    onBlur={() => setPreviewId(null)}
                    className={`w-full flex items-center gap-3 rounded-lg px-2.5 py-2 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${active ? 'bg-gray-100' : 'hover:bg-gray-50'}`}
                  >
                    <svg width="28" height="12" viewBox="0 0 28 12" aria-hidden="true" className="shrink-0">
                      <line
                        x1="1" y1="6" x2="27" y2="6"
                        stroke={style.stroke}
                        strokeWidth="2.5"
                        strokeDasharray={style.dash}
                      />
                      <circle cx="14" cy="6" r="3" fill="white" stroke={style.stroke} strokeWidth="2" />
                    </svg>
                    <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-gray-800">
                      {row.opp.title}
                    </span>
                    <span className="shrink-0 text-[11px] font-semibold tabular-nums text-gray-700">
                      {score}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      </div>

      <div className="mt-6 overflow-x-auto rounded-xl border border-gray-200">
        <table className="w-full min-w-[760px] border-collapse text-[12px] text-gray-700">
          <caption className="sr-only">{t('compare.radar.tableCaption')}</caption>
          <thead className="bg-gray-50 text-gray-600">
            <tr>
              <th scope="col" className="px-3 py-2.5 text-left font-semibold">
                {t('compare.radar.tableOpportunity')}
              </th>
              {labels.map((label) => (
                <th key={label} scope="col" className="px-3 py-2.5 text-right font-semibold">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.opp.id} className="border-t border-gray-100">
                <th scope="row" className="max-w-[240px] px-3 py-2.5 text-left font-medium text-gray-900 truncate">
                  {row.opp.title}
                </th>
                {RADAR_AXES.map(({ key }) => (
                  <td key={key} className="px-3 py-2.5 text-right font-mono tabular-nums">
                    {row.factors[key] ?? t('compare.radar.unknown')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
