import type { ProfileData } from '@/lib/types';
import type { TFunc } from './types';

// formatRelativeAge lived here and returned hardcoded English. It is now
// lib/humanize-time.formatAgo, which renders through the dictionary.

export function translateKey(t: TFunc, namespace: string, name: string): string {
  const key = `${namespace}.${name}`;
  const out = t(key);
  return out === key ? name : out;
}

export type ProfileCheckKey = 'academic' | 'skills' | 'interests' | 'resume' | 'type';

/**
 * The one list of what a complete profile has. The home page's strength
 * meter and the results page's completeness hint both read it — a tester
 * walking production saw "Profile strength 4/5, + Resume uploaded" on one
 * page and "Profile 2/4 complete — add coursework, résumé" on the next, for
 * the same profile in the same session, because each surface kept its own
 * list with its own denominator and its own thresholds.
 */
export function profileChecks(profile: ProfileData): Array<{ key: ProfileCheckKey; done: boolean }> {
  return [
    { key: 'academic', done: !!profile.college && !!profile.major && !!profile.grade },
    { key: 'skills', done: (profile.skills?.length ?? 0) >= 2 },
    { key: 'interests', done: !!profile.research_interests?.trim() },
    { key: 'resume', done: !!profile.resume_text?.trim() },
    { key: 'type', done: (profile.seeking_types?.length ?? 0) > 0 },
  ];
}
