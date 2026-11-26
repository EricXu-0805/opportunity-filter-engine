import { validateExperienceEntries } from './experience-evidence';
import type { ExperienceEntry } from './types';

export interface MatchExperience {
  id: string;
  revision: number;
  status: 'confirmed';
  source: 'manual' | 'github';
  text: string;
}

export function matchExperienceRows(entries?: ExperienceEntry[]): MatchExperience[] | null {
  const checked = validateExperienceEntries(entries);
  if (!checked.ok) return null;
  return checked.value.flatMap((entry) => {
    if (entry.status !== 'confirmed' || entry.source.kind === 'resume') return [];
    return [{ id: entry.id, revision: entry.revision, status: 'confirmed', source: entry.source.kind, text: entry.text }];
  });
}
