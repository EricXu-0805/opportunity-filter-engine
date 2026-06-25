'use client';

import { Sparkles } from 'lucide-react';
import type { TFunc } from './types';

export function HeroSection({ t }: { t: TFunc }) {
  return (
    <div className="text-center mb-16">
      <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-indigo-600/[0.08] text-indigo-600 text-[13px] font-medium mb-6">
        <Sparkles className="w-3.5 h-3.5" />
        {t('home.hero.tagline')}
      </div>
      <h1 className="text-5xl sm:text-6xl font-bold text-gray-900 tracking-tight leading-[1.1]">
        {t('home.hero.title')}{' '}
        <span className="bg-gradient-to-r from-indigo-600 to-indigo-400 bg-clip-text text-transparent">
          {t('home.hero.titleAccent')}
        </span>
      </h1>
      <p className="mt-5 text-lg text-gray-400 max-w-xl mx-auto leading-relaxed">
        {t('home.hero.subtitle')}
      </p>
    </div>
  );
}
