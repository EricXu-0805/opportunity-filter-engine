'use client';

import { SlidersHorizontal } from 'lucide-react';
import Card from '@/components/Card';
import type { TFunc } from './types';

export function SearchFocusCard({
  searchWeight,
  setSearchWeight,
  t,
}: {
  searchWeight: number;
  setSearchWeight: (v: number) => void;
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

      <div>
        <div className="flex items-center justify-between text-xs font-medium text-gray-500 mb-3">
          <span className={searchWeight < 50 ? 'text-blue-600 font-semibold' : ''}>
            {t('home.form.searchWeightLeft')}
          </span>
          <span className={searchWeight > 50 ? 'text-blue-600 font-semibold' : ''}>
            {t('home.form.searchWeightRight')}
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          value={searchWeight}
          onChange={(e) => setSearchWeight(Number(e.target.value))}
          className="w-full h-2 rounded-full appearance-none cursor-pointer accent-blue-600 bg-gray-200"
        />
        <p className="mt-2 text-xs text-gray-400 text-center">
          {searchWeight < 40
            ? t('home.form.searchWeightInterests')
            : searchWeight > 60
              ? t('home.form.searchWeightExperience')
              : t('home.form.searchWeightBalanced')}
        </p>
      </div>
    </Card>
  );
}
