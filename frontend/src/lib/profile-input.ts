/** Shared ProfileRequest limits count Unicode characters, never UTF-16 halves. */
export const PROFILE_INPUT_MAX_CHARACTERS = 160_000;
const strings: Record<string, number> = {
  name: 256, school: 1000, major: 1000, college: 1000, year: 100,
  experience_level: 100, home_school: 50, research_interests_text: 60_000,
  linkedin_url: 2048, github_url: 2048, scholar_url: 2048,
};
const lists: Record<string, [number, number]> = {
  secondary_interests: [512, 1000], desired_fields: [512, 60_000],
  hard_skills: [512, 1000], coursework: [512, 1000], seeking_type: [20, 100],
};
export type ProfileInputIssue = {
  code: 'PROFILE_INPUT_LIMIT_EXCEEDED' | 'PROFILE_INPUT_INVALID';
  field: string; actual?: number; limit?: number; unit?: 'characters' | 'items';
};
export class ProfileInputError extends Error {
  readonly status = 422;
  readonly retryable = false;
  readonly code: ProfileInputIssue['code'];
  constructor(public readonly detail: ProfileInputIssue) {
    super('Check your profile input. Your original content is kept.');
    this.name = 'ProfileInputError'; this.code = detail.code;
  }
}
const length = (text: string) => [...text].length;
function invalid(field: string): never {
  throw new ProfileInputError({ code: 'PROFILE_INPUT_INVALID', field });
}
function limit(field: string, actual: number, maximum: number, unit: 'characters' | 'items') {
  if (actual > maximum) throw new ProfileInputError({ code: 'PROFILE_INPUT_LIMIT_EXCEEDED', field, actual, limit: maximum, unit });
}
function text(value: unknown, field: string, maximum: number) {
  if (typeof value !== 'string' || /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value)) invalid(field);
  limit(field, length(value), maximum, 'characters');
}
/** Validate without changing values. Missing keys support the smaller share wire. */
export function assertProfileInput(profile: object, checkShareSize = false): void {
  const input = profile as Record<string, unknown>;
  for (const [key, max] of Object.entries(strings)) if (key in input) text(input[key], `profile.${key}`, max);
  for (const [key, [count, max]] of Object.entries(lists)) {
    if (!(key in input)) continue;
    const values = input[key];
    if (!Array.isArray(values)) invalid(`profile.${key}`);
    limit(`profile.${key}`, values.length, count, 'items');
    values.forEach((value, index) => {
      const field = `profile.${key}.${index}`;
      if (key === 'hard_skills') {
        if (!value || typeof value !== 'object') invalid(field);
        text(value.name, `${field}.name`, max);
        text(value.level, `${field}.level`, max);
      } else text(value, field, max);
    });
  }
  // API aggregate size belongs to the server: it expands defaults before counting.
  // The smaller share format has its own whole-import bound.
  if (checkShareSize) limit('profile', length(JSON.stringify(input)), PROFILE_INPUT_MAX_CHARACTERS, 'characters');
}
type Translate = (key: string, vars?: Record<string, string | number>) => string;
const fieldKeys: Record<string, string> = {
  international_student: 'international', search_weight: 'weight', profile: 'all', name: 'name', school: 'school', home_school: 'school', college: 'college',
  major: 'major', secondary_interests: 'majors', year: 'year', seeking_type: 'types',
  desired_fields: 'interests', research_interests_text: 'interests', hard_skills: 'skills',
  coursework: 'courses', experience_level: 'experience', linkedin_url: 'linkedin',
  github_url: 'github', scholar_url: 'scholar',
};
/** Only allowlisted labels and numeric counts reach UI; never echo server input/message. */
export function profileInputMessage(error: unknown, t: Translate): string | null {
  if (!error || typeof error !== 'object' || !('code' in error)) return null;
  if (error.code === 'PROFILE_SHARE_TOO_LARGE') return t('profileInput.shareTooLarge');
  if (error.code === 'MATCH_EXPLANATION_INPUT_TOO_LARGE' || error.code === 'MATCH_RERANK_INPUT_TOO_LARGE') return t('profileInput.matchTooLarge');
  if (error.code === 'TAILOR_INPUT_TOO_LARGE' || error.code === 'CHAT_INPUT_TOO_LARGE') {
    return t(error.code === 'TAILOR_INPUT_TOO_LARGE' ? 'profileInput.tailorTooLarge' : 'profileInput.chatTooLarge');
  }
  if (error.code !== 'PROFILE_INPUT_LIMIT_EXCEEDED' && error.code !== 'PROFILE_INPUT_INVALID') return null;
  const detail = 'detail' in error && error.detail && typeof error.detail === 'object'
    ? error.detail as Record<string, unknown> : {};
  const parts = typeof detail.field === 'string' ? detail.field.split('.') : [];
  const key = parts[0] === 'profile' ? (parts[1] ?? 'profile') : '';
  const label = t(`profileInput.fields.${fieldKeys[key] ?? 'all'}`);
  if (key === 'profile' && error.code === 'PROFILE_INPUT_LIMIT_EXCEEDED') return t('profileInput.totalTooLarge');
  const item = /^\d+$/.test(parts[2] ?? '') ? Number(parts[2]) + 1 : null;
  const field = item !== null && Number.isSafeInteger(item) ? t('profileInput.item', { field: label, n: item }) : label;
  if (error.code === 'PROFILE_INPUT_LIMIT_EXCEEDED' && Number.isSafeInteger(detail.actual)
    && Number.isSafeInteger(detail.limit) && Number(detail.actual) > Number(detail.limit)
    && Number(detail.limit) > 0 && (detail.unit === 'characters' || detail.unit === 'items')) {
    return t(`profileInput.${detail.unit}`, { field, actual: Number(detail.actual), limit: Number(detail.limit) });
  }
  return t('profileInput.invalid', { field });
}
