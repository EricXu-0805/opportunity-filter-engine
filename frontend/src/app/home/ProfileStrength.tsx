'use client';

import type { ProfileData } from '@/lib/types';
import type { TFunc } from './types';

export function ProfileStrength({
  profile,
  hasResume,
  t,
}: {
  profile: ProfileData;
  hasResume: boolean;
  t: TFunc;
}) {
  const checks = [
    { done: !!profile.college && !!profile.major && !!profile.grade, label: t('home.cards.checkAcademic') },
    { done: profile.skills.length >= 2, label: t('home.cards.checkSkills') },
    { done: !!profile.research_interests?.trim(), label: t('home.cards.checkInterests') },
    { done: hasResume, label: t('home.cards.checkResume') },
    { done: !!(profile.seeking_types && profile.seeking_types.length > 0), label: t('home.cards.checkType') },
  ];

  const completed = checks.filter((c) => c.done).length;
  const total = checks.length;
  const pct = Math.round((completed / total) * 100);
  const color = pct >= 80 ? 'emerald' : pct >= 60 ? 'blue' : 'amber';

  const colorMap = { emerald: 'bg-emerald-400', blue: 'bg-indigo-400', amber: 'bg-amber-400' };
  const textMap = { emerald: 'text-emerald-600', blue: 'text-indigo-600', amber: 'text-amber-600' };

  if (completed === total) return null;

  return (
    <div className="max-w-md mx-auto mt-12 px-6 py-5 bg-white rounded-2xl shadow-[0_1px_6px_rgba(0,0,0,0.04)]">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[13px] font-semibold text-gray-700">{t('home.cards.profileStrength')}</span>
        <span className={`text-[13px] font-bold tabular-nums ${textMap[color]}`}>{completed}/{total}</span>
      </div>
      <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden mb-3">
        <div
          className={`h-full rounded-full ${colorMap[color]} transition-all duration-500`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {checks.filter((c) => !c.done).map((c) => (
          <span key={c.label} className="text-[11px] text-gray-400">+ {c.label}</span>
        ))}
      </div>
    </div>
  );
}
