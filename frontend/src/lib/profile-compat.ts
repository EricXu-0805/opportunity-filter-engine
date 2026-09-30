import type { ProfileData } from './types';

/** Read-only compatibility projection. It changes neither the raw mirror nor
 * the CAS baseline/revision. Preserve unknown fields and existing skill objects. */
// Older profiles persisted in localStorage stored skills as plain strings
// instead of { name, level }. Reading them through this union lets the
// migrator widen in one place; everywhere downstream sees ProfileData.
export type LegacyProfileShape = Omit<ProfileData, 'skills'> & {
  skills?: ProfileData['skills'] | string[];
};

export function migrateProfile(raw: LegacyProfileShape | null): ProfileData | null {
  if (!raw) return null;
  if (
    Array.isArray(raw.skills)
    && raw.skills.length > 0
    && typeof raw.skills[0] === 'string'
  ) {
    return {
      ...raw,
      skills: (raw.skills as string[]).map((name) => ({
        name,
        level: 'beginner' as const,
      })),
    } as ProfileData;
  }
  return raw as ProfileData;
}
