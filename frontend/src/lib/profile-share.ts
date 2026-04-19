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

function clampStr(v: unknown, max: number): string {
  return typeof v === 'string' ? v.slice(0, max) : '';
}

function fromShared(shared: SharedProfile): Partial<ProfileData> {
  if (shared.v !== 1) throw new Error('Unsupported share version');
  return {
    institution: 'UIUC - University of Illinois Urbana-Champaign',
    college: clampStr(shared.college, 100),
    major: clampStr(shared.major, 100),
    grade: clampStr(shared.grade, 30),
    is_international: Boolean(shared.intl),
    research_interests: clampStr(shared.interests, 2000),
    skills: Array.isArray(shared.skills)
      ? shared.skills
          .filter(s => s && typeof s.n === 'string')
          .slice(0, 50)
          .map(s => ({
            name: clampStr(s.n, 50),
            level: (['beginner', 'experienced', 'expert'].includes(s.l) ? s.l : 'beginner'),
          }))
      : [],
    seeking_types: Array.isArray(shared.seeking)
      ? shared.seeking
          .filter(x => typeof x === 'string')
          .slice(0, 10)
          .map(x => clampStr(x, 30))
      : undefined,
    search_weight: typeof shared.weight === 'number' && shared.weight >= 0 && shared.weight <= 100
      ? shared.weight
      : undefined,
    coursework: Array.isArray(shared.courses)
      ? shared.courses
          .filter(x => typeof x === 'string')
          .slice(0, 50)
          .map(x => clampStr(x, 50))
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
  return base64UrlEncode(JSON.stringify(toShared(profile)));
}

export function decodeProfile(encoded: string): Partial<ProfileData> | null {
  try {
    const json = base64UrlDecode(encoded);
    const parsed = JSON.parse(json) as SharedProfile;
    return fromShared(parsed);
  } catch {
    return null;
  }
}

export function buildShareUrl(profile: ProfileData): string {
  const encoded = encodeProfile(profile);
  const origin = typeof window !== 'undefined' ? window.location.origin : '';
  return `${origin}/?share=${encoded}`;
}
