'use client';

import { UserCog } from 'lucide-react';
import type { ProfileData } from '@/lib/types';

type Replier = (key: string, vars?: Record<string, string | number>) => string;

interface Props {
  profile: ProfileData;
  onEdit: () => void;
  t: Replier;
}

// The four signals the matcher actually leans on. A thin profile (most of
// these empty) yields a large reach bucket that reads as "no good matches"
// when it really means "tell us more about you" — this non-blocking hint
// makes that legible and links straight to the profile form.
const FIELDS = ['interests', 'skills', 'coursework', 'resume'] as const;

export function ProfileCompletenessHint({ profile, onEdit, t }: Props) {
  const filled: Record<(typeof FIELDS)[number], boolean> = {
    interests: !!profile.research_interests?.trim(),
    skills: (profile.skills?.length ?? 0) > 0,
    coursework: (profile.coursework?.length ?? 0) > 0,
    resume: !!profile.resume_text?.trim(),
  };
  const missing = FIELDS.filter((f) => !filled[f]);
  if (missing.length === 0) return null;

  const complete = FIELDS.length - missing.length;
  const missingLabels = missing.map((f) => t(`results.completeness.fields.${f}`)).join(', ');

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2 mb-3 rounded-xl bg-amber-50/70 border border-amber-100 text-[12.5px] text-amber-800">
      <UserCog className="w-4 h-4 text-amber-500 shrink-0" aria-hidden="true" />
      <span className="leading-snug">
        {t('results.completeness.summary', {
          complete,
          total: FIELDS.length,
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
