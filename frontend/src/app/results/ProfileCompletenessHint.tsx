'use client';

import { UserCog } from 'lucide-react';
import type { ProfileData } from '@/lib/types';
import { profileChecks } from '@/app/home/home-utils';

type Replier = (key: string, vars?: Record<string, string | number>) => string;

interface Props {
  profile: ProfileData;
  onEdit: () => void;
  t: Replier;
}

// One list, shared with the home page's strength meter (see profileChecks):
// the two surfaces used to keep their own, and a tester walking production
// read "Profile strength 4/5" on one page and "Profile 2/4 complete" on the
// next for the same profile in the same session.
export function ProfileCompletenessHint({ profile, onEdit, t }: Props) {
  const checks = profileChecks(profile);
  const missing = checks.filter((c) => !c.done).map((c) => c.key);
  if (missing.length === 0) return null;

  const complete = checks.length - missing.length;
  const missingLabels = missing.map((f) => t(`results.completeness.fields.${f}`)).join(', ');

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2 mb-3 rounded-xl bg-amber-50/70 border border-amber-100 text-[12.5px] text-amber-800">
      <UserCog className="w-4 h-4 text-amber-500 shrink-0" aria-hidden="true" />
      <span className="leading-snug">
        {t('results.completeness.summary', {
          complete,
          total: checks.length,
          missing: missingLabels,
        })}
      </span>
      <button
        type="button"
        onClick={onEdit}
        className="font-semibold text-amber-700 underline underline-offset-2 hover:text-amber-900 transition-colors"
      >
        {t('results.completeness.edit')}
      </button>
    </div>
  );
}
