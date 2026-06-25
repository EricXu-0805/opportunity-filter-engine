'use client';

import { Compass, SlidersHorizontal } from 'lucide-react';
import Card from '@/components/Card';
import type { TFunc } from './types';

export function SearchFocusCard({
  searchWeight,
  setSearchWeight,
  exploring,
  setExploring,
  t,
}: {
  searchWeight: number;
  setSearchWeight: (v: number) => void;
  exploring: boolean;
  setExploring: (v: boolean) => void;
  t: TFunc;
}) {
  return (
    <Card>
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-xl bg-indigo-50 flex items-center justify-center">
          <SlidersHorizontal className="w-5 h-5 text-indigo-600" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-gray-900">{t('home.cards.searchFocusTitle')}</h2>
          <p className="text-sm text-gray-400">{t('home.cards.searchFocusSubtitle')}</p>
        </div>
      </div>

      <div className={exploring ? 'opacity-50 pointer-events-none' : undefined}>
        <div className="flex items-center justify-between text-xs font-medium text-gray-500 mb-3">
          <span className={searchWeight < 50 ? 'text-indigo-600 font-semibold' : ''}>
            {t('home.form.searchWeightLeft')}
          </span>
          <span className={searchWeight > 50 ? 'text-indigo-600 font-semibold' : ''}>
            {t('home.form.searchWeightRight')}
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          value={searchWeight}
          disabled={exploring}
          onChange={(e) => setSearchWeight(Number(e.target.value))}
          className="w-full h-2 rounded-full appearance-none cursor-pointer accent-indigo-600 bg-gray-200 disabled:cursor-not-allowed"
        />
        <p className="mt-2 text-xs text-gray-400 text-center">
          {searchWeight < 40
            ? t('home.form.searchWeightInterests')
            : searchWeight > 60
              ? t('home.form.searchWeightExperience')
              : t('home.form.searchWeightBalanced')}
        </p>
      </div>

      <div className="mt-6 pt-5 border-t border-gray-100 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Compass className="w-5 h-5 text-gray-400 shrink-0" />
          <div>
            <span className="text-sm font-medium text-gray-700">
              {t('home.form.exploringLabel')}
            </span>
            <p className="text-xs text-gray-400">{t('home.form.exploringHint')}</p>
          </div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={exploring}
          aria-label={t('home.form.exploringLabel')}
          onClick={() => setExploring(!exploring)}
          className={`relative inline-flex h-7 w-12 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2
            ${exploring ? 'bg-indigo-600' : 'bg-gray-200'}`}
        >
          <span
            className={`pointer-events-none inline-block h-6 w-6 transform rounded-full bg-white shadow-lg ring-0 transition duration-200 ease-in-out
              ${exploring ? 'translate-x-5' : 'translate-x-0'}`}
          />
        </button>
      </div>
    </Card>
  );
}
