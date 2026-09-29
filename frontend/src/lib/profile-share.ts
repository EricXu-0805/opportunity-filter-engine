import { assertProfileInput, ProfileInputError } from './profile-input';
import type { ProfileData } from './types';

interface SharedProfile {
  v: 1;
  college: string;
  major: string;
  grade: string;
  intl: boolean;
  interests: string;
  skills: Array<{ n: string; l: 'beginner' | 'experienced' | 'expert' }>;
  seeking?: string[];
  weight?: number;
  courses?: string[];
}

function toShared(profile: ProfileData): SharedProfile {
  return {
    v: 1,
    college: profile.college,
    major: profile.major,
    grade: profile.grade,
    intl: profile.is_international,
    interests: profile.research_interests,
    skills: profile.skills.map(s => ({ n: s.name, l: s.level })),
    seeking: profile.seeking_types,
    weight: profile.search_weight,
    courses: profile.coursework,
  };
}

function shareText(v: unknown): string {
  if (v === undefined) return '';
  if (typeof v !== 'string') throw new Error('Invalid shared text');
  return v;
}

function assertShared(shared: SharedProfile): void {
  if (shared.intl !== undefined && typeof shared.intl !== 'boolean') throw new ProfileInputError({ code: 'PROFILE_INPUT_INVALID', field: 'profile.international_student' });
  if (shared.weight !== undefined && (typeof shared.weight !== 'number' || !Number.isInteger(shared.weight) || shared.weight < 0 || shared.weight > 100)) throw new ProfileInputError({ code: 'PROFILE_INPUT_INVALID', field: 'profile.search_weight' });
  assertProfileInput({
    college: shareText(shared.college), major: shareText(shared.major), year: shareText(shared.grade),
    research_interests_text: shareText(shared.interests),
    hard_skills: shared.skills === undefined ? [] : Array.isArray(shared.skills)
      ? shared.skills.map(s => ({ name: s?.n, level: s?.l ?? 'beginner' })) : shared.skills,
    ...(shared.seeking !== undefined ? { seeking_type: shared.seeking } : {}),
    ...(shared.courses !== undefined ? { coursework: shared.courses } : {}),
  }, true);
}

function fromShared(shared: SharedProfile): Partial<ProfileData> {
  if (shared.v !== 1) throw new Error('Unsupported share version');
  assertShared(shared);
  return {
    institution: 'UIUC - University of Illinois Urbana-Champaign',
    college: shareText(shared.college),
    major: shareText(shared.major),
    grade: shareText(shared.grade),
    is_international: Boolean(shared.intl),
    research_interests: shareText(shared.interests),
    skills: Array.isArray(shared.skills)
      ? shared.skills
          .map(s => ({
            name: shareText(s.n),
            level: (['beginner', 'experienced', 'expert'].includes(s.l) ? s.l : 'beginner'),
            // Somebody else's self-assessment. A share link is definitionally
            // not the recipient's own statement about themselves, so it can
            // never authorise a first-person claim in THEIR email until they
            // say so — marked, never `confirmed`.
            source: 'shared' as const,
          }))
      : [],
    seeking_types: Array.isArray(shared.seeking)
      ? shared.seeking
          .map(x => shareText(x))
      : undefined,
    search_weight: typeof shared.weight === 'number' && shared.weight >= 0 && shared.weight <= 100
      ? shared.weight
      : undefined,
    coursework: Array.isArray(shared.courses)
      ? shared.courses
          .map(x => shareText(x))
      : undefined,
  };
}

function base64UrlEncode(str: string): string {
  const b64 = btoa(unescape(encodeURIComponent(str)));
  return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function base64UrlDecode(str: string): string {
  const padded = str.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((str.length + 3) % 4);
  return decodeURIComponent(escape(atob(padded)));
}

export function encodeProfile(profile: ProfileData): string {
  const shared = toShared(profile);
  assertShared(shared);
  return base64UrlEncode(JSON.stringify(shared));
}

/** The ProfileData keys the share WIRE format actually carries. `institution`
 *  is deliberately absent: fromShared injects a constant so the draft renders,
 *  but it is not something the sharer transmitted — and a Generate that
 *  treated it as shared content would write it over the visitor's own school.
 *  Home builds its save patch from this list intersected with what the payload
 *  really contained, never from Object.keys() of the decoded object. */
export const SHARE_WIRE_KEYS = [
  'college', 'major', 'grade', 'is_international', 'research_interests',
  'skills', 'seeking_types', 'search_weight', 'coursework',
] as const satisfies readonly (keyof ProfileData)[];

/** The decoded draft PLUS exactly which of SHARE_WIRE_KEYS the payload
 *  actually carried (the optional ones may be absent). */
export function decodeProfileWithKeys(
  encoded: string,
): { profile: Partial<ProfileData>; keys: (keyof ProfileData)[] } | null {
  const profile = decodeProfile(encoded);
  if (!profile) return null;
  const keys = SHARE_WIRE_KEYS.filter(
    (k) => (profile as Record<string, unknown>)[k] !== undefined,
  );
  return { profile, keys };
}

export function decodeProfileResult(encoded: string):
  | { ok: true; profile: Partial<ProfileData>; keys: (keyof ProfileData)[] }
  | { ok: false; error: unknown } {
  try {
    // Bound decoding itself without ever accepting a prefix of the link.
    if (encoded.length > 1_000_000) throw new ProfileInputError({ code: 'PROFILE_INPUT_INVALID', field: 'profile' });
    const parsed = JSON.parse(base64UrlDecode(encoded)) as SharedProfile;
    const profile = fromShared(parsed);
    const keys = SHARE_WIRE_KEYS.filter(k => (profile as Record<string, unknown>)[k] !== undefined);
    return { ok: true, profile, keys };
  } catch (error) {
    return { ok: false, error };
  }
}

export function decodeProfile(encoded: string): Partial<ProfileData> | null {
  const result = decodeProfileResult(encoded);
  return result.ok ? result.profile : null;
}

/** A conservative product bound, not a promise about every browser or proxy. */
export const PROFILE_SHARE_MAX_URL_CHARACTERS = 8_000;
export const profileShareUrlFits = (url: string): boolean => url.length <= PROFILE_SHARE_MAX_URL_CHARACTERS;
export class ProfileShareTooLargeError extends Error {
  readonly code = 'PROFILE_SHARE_TOO_LARGE';
  constructor() { super('This profile is too long to put in a share link.'); this.name = 'ProfileShareTooLargeError'; }
}
export function buildShareUrl(profile: ProfileData): string {
  const encoded = encodeProfile(profile);
  const origin = typeof window !== 'undefined' ? window.location.origin : '';
  const url = `${origin}/?share=${encoded}`;
  if (!profileShareUrlFits(url)) throw new ProfileShareTooLargeError();
  return url;
}
