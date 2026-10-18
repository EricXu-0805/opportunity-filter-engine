import { SUPPLEMENT_ANSWER_KEYS, type SupplementAnswers, type SupplementAnswerKey } from './resume-supplement';
import type { ProfileData } from './types';
import { isOwnerTokenValid, readUserScopedEntry, removeUserScopedRaw, writeUserScopedRaw, type OwnerToken } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';

/** Local text recovery only. No confirmation, accepted profile or permission to submit. */
export interface ResumeSupplementDraftSnapshot {
  version: 1; opportunityId: string; targetKey: string; entryId: string; activityId: string;
  answers: SupplementAnswers; selected: SupplementAnswerKey[];
}
export const RESUME_SUPPLEMENT_DRAFT_MAX_LENGTH = 65_536;
function exact(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const proto = Object.getPrototypeOf(value);
  return (proto === Object.prototype || proto === null) && Reflect.ownKeys(value).length === keys.length
    && keys.every(key => { const d = Object.getOwnPropertyDescriptor(value, key); return !!d?.enumerable && Object.hasOwn(d, 'value'); });
}
function text(value: unknown, max: number, blank = false): value is string {
  return typeof value === 'string' && (blank || !!value.trim()) && value.length <= max
    && !Array.from(value).some(c => { const p = c.codePointAt(0)!; return p === 0 || (p >= 0xd800 && p <= 0xdfff); });
}
export function parseResumeSupplementDraft(value: unknown): ResumeSupplementDraftSnapshot | null {
  try {
    if (!exact(value, ['version', 'opportunityId', 'targetKey', 'entryId', 'activityId', 'answers', 'selected']) || value.version !== 1
      || !text(value.opportunityId, 1000) || !text(value.targetKey, RESUME_SUPPLEMENT_DRAFT_MAX_LENGTH, true)
      || !text(value.entryId, 80) || !text(value.activityId, 80, true) || !exact(value.answers, SUPPLEMENT_ANSWER_KEYS)
      || !SUPPLEMENT_ANSWER_KEYS.every(key => text((value.answers as Record<string, unknown>)[key], RESUME_SUPPLEMENT_DRAFT_MAX_LENGTH, true))
      || !Array.isArray(value.selected) || value.selected.length > 5 || Reflect.ownKeys(value.selected).length !== value.selected.length + 1
      || !Array.from({ length: value.selected.length }, (_, i) => i).every(i => { const d = Object.getOwnPropertyDescriptor(value.selected, String(i)); return !!d?.enumerable && Object.hasOwn(d, 'value'); })
      || new Set(value.selected).size !== value.selected.length || !value.selected.every(key => SUPPLEMENT_ANSWER_KEYS.includes(key as SupplementAnswerKey))) return null;
    const result = JSON.parse(JSON.stringify(value)) as ResumeSupplementDraftSnapshot;
    return JSON.stringify(result).length <= RESUME_SUPPLEMENT_DRAFT_MAX_LENGTH ? result : null;
  } catch { return null; }
}
/** Only a freshly read persisted profile can establish that a recovered entry was submitted. */
export function supplementRecorded(profile: ProfileData | null | undefined, draft: ResumeSupplementDraftSnapshot, preview: string): boolean {
  const entry = profile?.experience_entries?.find(item => item.id === draft.entryId);
  const activity = profile?.resume_master?.activities.find(item => item.id === draft.activityId);
  return !!entry && entry.revision === 1 && entry.status === 'confirmed' && entry.source.kind === 'manual' && entry.text === preview
    && !!activity?.details.some(ref => ref.id === entry.id && ref.revision === entry.revision);
}

// The target résumé keeps one unsubmitted supplement per owner uid and opportunity.
// The prefix is user-scoped, so an owner change or sign-out sweeps it with the
// rest of that generation's private data; writes are bound to the owner token.
function storageKey(owner: OwnerToken, opportunityId: string): string {
  return STORAGE_KEYS.RESUME_SUPPLEMENT_DRAFT_PREFIX + encodeURIComponent(JSON.stringify([owner.uid, opportunityId]));
}
export function readResumeSupplementDraft(owner: OwnerToken, opportunityId: string): ResumeSupplementDraftSnapshot | null {
  if (!opportunityId || !isOwnerTokenValid(owner, owner.uid)) return null;
  const entry = readUserScopedEntry(storageKey(owner, opportunityId));
  if (entry.status !== 'present' || entry.value.length > 2 * RESUME_SUPPLEMENT_DRAFT_MAX_LENGTH) return null;
  try {
    const item: unknown = JSON.parse(entry.value);
    if (!exact(item, ['version', 'ownerId', 'draft']) || item.version !== 1 || item.ownerId !== owner.uid) return null;
    const draft = parseResumeSupplementDraft(item.draft);
    return draft?.opportunityId === opportunityId ? draft : null;
  } catch { return null; }
}
/** Stores answers worth recovering; a snapshot without any answer text, or null, removes the copy. */
export function writeResumeSupplementDraft(owner: OwnerToken, opportunityId: string, draft: ResumeSupplementDraftSnapshot | null): boolean {
  if (!opportunityId || !isOwnerTokenValid(owner, owner.uid)) return false;
  const key = storageKey(owner, opportunityId);
  const copy = draft && parseResumeSupplementDraft(draft);
  if (draft && (!copy || copy.opportunityId !== opportunityId)) return false;
  if (!copy || !SUPPLEMENT_ANSWER_KEYS.some(name => copy.answers[name].length > 0)) return removeUserScopedRaw(key, owner);
  return writeUserScopedRaw(key, JSON.stringify({ version: 1, ownerId: owner.uid, draft: copy }), owner);
}
