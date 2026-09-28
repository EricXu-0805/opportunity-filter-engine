import type { ExperienceEntry, ProfileData } from './types';
import { isActiveExperience, sourceDigest, validateExperienceEntries } from './experience-evidence';
import { validateResumeMaster } from './resume-master';

export interface ExistingExperienceAssignment { entryId: string; entryRevision: number; activityId: string }
export type ExperienceAssignmentResult = { ok: true; entry: ExperienceEntry; desired: ProfileData } | { ok: false; reason: string };
/** Exact references anywhere in the master are not silently reassigned. */
export async function unassignedConfirmedExperiences(profile: ProfileData): Promise<ExperienceEntry[]> {
  const master = validateResumeMaster(profile.resume_master), entries = validateExperienceEntries(profile.experience_entries);
  if (!master.ok || !master.value || !entries.ok) return [];
  const raw = profile.resume_text ?? '', expectedDigest = await sourceDigest(raw);
  const referenced = new Set([...master.value.activities, ...master.value.education, ...master.value.publications].flatMap(item => item.details.map(ref => ref.id)));
  return entries.value.filter(entry => !referenced.has(entry.id) && isActiveExperience(entry, { rawText: raw, expectedDigest }));
}
/** Only adds the user's chosen relation; the original fact and source are kept. */
export async function prepareExperienceAssignment(profile: ProfileData, assignment: ExistingExperienceAssignment): Promise<ExperienceAssignmentResult> {
  try {
    if (!assignment || Object.keys(assignment).length !== 3 || !['entryId', 'entryRevision', 'activityId'].every(key => Object.hasOwn(assignment, key))) return { ok: false, reason: 'invalid' };
    const master = validateResumeMaster(profile.resume_master);
    if (!master.ok || !master.value) return { ok: false, reason: 'missing-master' };
    if (!master.value.activities.some(item => item.id === assignment.activityId)) return { ok: false, reason: 'missing-activity' };
    const entry = (await unassignedConfirmedExperiences(profile)).find(item => item.id === assignment.entryId && item.revision === assignment.entryRevision);
    if (!entry) return { ok: false, reason: 'entry-changed-or-linked' };
    if (master.value.revision === Number.MAX_SAFE_INTEGER) return { ok: false, reason: 'revision-limit' };
    const next = { ...master.value, revision: master.value.revision + 1, activities: master.value.activities.map(item => item.id === assignment.activityId
      ? { ...item, details: [...item.details, { id: entry.id, revision: entry.revision }] } : item) };
    if (!validateResumeMaster(next).ok) return { ok: false, reason: 'invalid' };
    return { ok: true, entry: structuredClone(entry), desired: structuredClone({ ...profile, resume_master: next }) };
  } catch { return { ok: false, reason: 'invalid' }; }
}
