import type { ExperienceEntry, ProfileData } from './types';
import { MAX_EXPERIENCE_ENTRY_CHARACTERS, validateExperienceEntries } from './experience-evidence';
import { validateResumeMaster } from './resume-master';
import { MAX_RESUME_TEXT_CHARACTERS, resumeTextCharacters } from './resume-input';

export const SUPPLEMENT_ANSWER_KEYS = ['task', 'method', 'personalRole', 'outcome', 'outcomeBasis'] as const;
export type SupplementAnswerKey = typeof SUPPLEMENT_ANSWER_KEYS[number];
export type SupplementAnswers = Record<SupplementAnswerKey, string>;
export interface SupplementDraft {
  entryId: string;
  activityId: string;
  answers: SupplementAnswers;
  selected: SupplementAnswerKey[];
}
export type SupplementPreviewResult =
  | { ok: true; previewText: string }
  | { ok: false; reason: 'empty' | 'invalid' | 'limit' };
export type SupplementFailureReason =
  | 'empty' | 'invalid' | 'limit' | 'missing-master' | 'missing-activity' | 'duplicate-id' | 'revision-limit';
export type ConfirmedSupplementResult =
  | { ok: true; entry: ExperienceEntry; desired: ProfileData; previewText: string }
  | { ok: false; reason: SupplementFailureReason };

const LABELS: Record<SupplementAnswerKey, string> = {
  task: 'Task', method: 'Method', personalRole: 'My role', outcome: 'Outcome', outcomeBasis: 'Outcome basis',
};
const LIMIT_CODES = new Set(['too_many_entries', 'text_limit', 'quote_limit', 'too_many_facts', 'too_many_records', 'value_limit']);
function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
    && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
}
function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}
function validUnicode(value: string): boolean {
  for (const character of value) {
    const point = character.codePointAt(0)!;
    // jsonb cannot persist NUL. Never silently remove it or replace a surrogate.
    if (point === 0 || (point >= 0xd800 && point <= 0xdfff)) return false;
  }
  return true;
}
function validId(value: unknown): value is string {
  return typeof value === 'string' && !!value.trim() && validUnicode(value) && resumeTextCharacters(value) <= 80;
}
function validationReason(code: string): SupplementFailureReason {
  return LIMIT_CODES.has(code) ? 'limit' : 'invalid';
}

/** Literal, unconfirmed preview. Selection changes only which complete answers
 * appear, never their wording. Labels and separators also consume the budget. */
export function previewSupplement(draft: Pick<SupplementDraft, 'answers' | 'selected'>): SupplementPreviewResult {
  try {
    if (!record(draft) || !record(draft.answers) || !exactKeys(draft.answers, SUPPLEMENT_ANSWER_KEYS)
      || !Array.isArray(draft.selected)) return { ok: false, reason: 'invalid' };
    for (const key of SUPPLEMENT_ANSWER_KEYS) {
      if (typeof draft.answers[key] !== 'string' || !validUnicode(draft.answers[key])) return { ok: false, reason: 'invalid' };
    }
    const selected = new Set<SupplementAnswerKey>();
    for (const key of draft.selected) {
      if (!SUPPLEMENT_ANSWER_KEYS.includes(key) || selected.has(key)) return { ok: false, reason: 'invalid' };
      selected.add(key);
    }
    const previewText = SUPPLEMENT_ANSWER_KEYS.filter((key) => selected.has(key) && draft.answers[key].trim())
      .map((key) => `${LABELS[key]}: ${draft.answers[key]}`).join('\n');
    if (!previewText) return { ok: false, reason: 'empty' };
    if (resumeTextCharacters(previewText) > MAX_EXPERIENCE_ENTRY_CHARACTERS) return { ok: false, reason: 'limit' };
    return { ok: true, previewText };
  } catch {
    return { ok: false, reason: 'invalid' };
  }
}

/** Call only after explicit review confirmation. This is a pure construction:
 * the coordinator must still fence the accepted view/owner and commit both
 * changed fields together. No persistence or target-draft regeneration occurs. */
export function prepareConfirmedSupplement(profile: ProfileData, draft: SupplementDraft): ConfirmedSupplementResult {
  try {
    if (!record(profile) || !record(draft) || !exactKeys(draft, ['entryId', 'activityId', 'answers', 'selected'])
      || !validId(draft.entryId) || !validId(draft.activityId)) return { ok: false, reason: 'invalid' };
    const preview = previewSupplement(draft);
    if (!preview.ok) return preview;
    if (profile.resume_text !== undefined) {
      if (typeof profile.resume_text !== 'string' || !validUnicode(profile.resume_text)) return { ok: false, reason: 'invalid' };
      if (resumeTextCharacters(profile.resume_text) > MAX_RESUME_TEXT_CHARACTERS) return { ok: false, reason: 'limit' };
    }
    const entries = validateExperienceEntries(profile.experience_entries);
    if (!entries.ok) return { ok: false, reason: validationReason(entries.code) };
    const master = validateResumeMaster(profile.resume_master);
    if (!master.ok) return { ok: false, reason: validationReason(master.code) };
    if (!master.value) return { ok: false, reason: 'missing-master' };
    if (!master.value.activities.some((activity) => activity.id === draft.activityId)) return { ok: false, reason: 'missing-activity' };
    // A historical dangling ref must not become bound to an unrelated new entry.
    const existingRefs = [...master.value.education, ...master.value.activities, ...master.value.publications]
      .flatMap((item) => item.details);
    if (entries.value.some((entry) => entry.id === draft.entryId) || existingRefs.some((ref) => ref.id === draft.entryId)) {
      return { ok: false, reason: 'duplicate-id' };
    }
    if (master.value.revision === Number.MAX_SAFE_INTEGER) return { ok: false, reason: 'revision-limit' };
    const entry: ExperienceEntry = {
      id: draft.entryId, revision: 1, status: 'confirmed', text: preview.previewText, source: { kind: 'manual' },
    };
    const nextEntries = [...entries.value, entry];
    const nextMaster = {
      ...master.value, revision: master.value.revision + 1,
      activities: master.value.activities.map((activity) => activity.id === draft.activityId
        ? { ...activity, details: [...activity.details, { id: entry.id, revision: entry.revision }] } : activity),
    };
    const checkedEntries = validateExperienceEntries(nextEntries);
    if (!checkedEntries.ok) return { ok: false, reason: validationReason(checkedEntries.code) };
    const checkedMaster = validateResumeMaster(nextMaster);
    if (!checkedMaster.ok) return { ok: false, reason: validationReason(checkedMaster.code) };
    // structuredClone preserves optional undefined fields as well as every
    // nested source/revision. Neither result shares mutable objects with input.
    const desired = structuredClone({ ...profile, experience_entries: nextEntries, resume_master: nextMaster });
    return { ok: true, entry: structuredClone(entry), desired, previewText: preview.previewText };
  } catch {
    return { ok: false, reason: 'invalid' };
  }
}
