'use client';

import { useState } from 'react';
import type { TFunc } from './types';

export function MinScoreFilter({
  value,
  onChange,
  t,
}: {
  value: number;
  onChange: (v: number) => void;
  t: TFunc;
}) {
  const [open, setOpen] = useState(false);
  const active = value > 0;
  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className={`px-3 py-1.5 rounded-lg text-[12px] font-medium border transition-colors cursor-pointer outline-none ${
          active
            ? 'bg-blue-50 border-blue-200 text-blue-700'
            : 'bg-white border-gray-200 text-gray-500 hover:border-gray-300'
        }`}
      >
        {active ? t('results.minScore.buttonActive', { value }) : t('results.minScore.button')}
      </button>
      {open && (
        <div className="absolute z-20 mt-2 right-0 bg-white rounded-xl shadow-lg border border-gray-200 p-4 w-64">
          <div className="flex items-center justify-between text-[11px] text-gray-500 mb-2">
            <span>{t('results.minScore.label')}</span>
            <span className="font-semibold tabular-nums text-gray-700">{value}</span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={value}
            onChange={(e) => onChange(Number(e.target.value))}
            className="w-full accent-blue-600"
          />
          <div className="flex justify-between mt-3">
            <button
              type="button"
              onClick={() => onChange(0)}
              className="text-[11px] text-gray-500 hover:text-gray-700"
            >
              {t('results.minScore.reset')}
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-[11px] font-medium text-blue-600 hover:text-blue-700"
            >
              {t('results.minScore.done')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
