'use client';

import type { ProfileData } from '@/lib/types';
import { profileChecks, type ProfileCheckKey } from './home-utils';
import type { TFunc } from './types';

const LABEL_KEY: Record<ProfileCheckKey, string> = {
  academic: 'home.cards.checkAcademic',
  skills: 'home.cards.checkSkills',
  interests: 'home.cards.checkInterests',
  resume: 'home.cards.checkResume',
  type: 'home.cards.checkType',
};

export function ProfileStrength({
  profile,
  t,
}: {
  profile: ProfileData;
  t: TFunc;
}) {
  const checks = profileChecks(profile).map((c) => ({ done: c.done, label: t(LABEL_KEY[c.key]) }));

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
