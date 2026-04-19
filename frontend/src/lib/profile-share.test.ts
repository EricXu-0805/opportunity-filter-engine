import { describe, it, expect } from 'vitest';
import { encodeProfile, decodeProfile, buildShareUrl } from './profile-share';
import type { ProfileData } from './types';

const FULL_PROFILE: ProfileData = {
  institution: 'UIUC - University of Illinois Urbana-Champaign',
  college: 'Grainger College of Engineering',
  major: 'Computer Science',
  grade: 'sophomore',
  is_international: true,
  research_interests: 'machine learning applications in healthcare',
  skills: [
    { name: 'Python', level: 'experienced' },
    { name: 'PyTorch', level: 'beginner' },
  ],
  coursework: ['CS 124', 'STAT 107'],
  search_weight: 60,
  seeking_types: ['research', 'summer_program'],
};

describe('profile-share encode/decode roundtrip', () => {
  it('preserves all core fields', () => {
    const encoded = encodeProfile(FULL_PROFILE);
    const decoded = decodeProfile(encoded);
    expect(decoded).not.toBeNull();
    expect(decoded!.college).toBe(FULL_PROFILE.college);
    expect(decoded!.major).toBe(FULL_PROFILE.major);
    expect(decoded!.grade).toBe(FULL_PROFILE.grade);
    expect(decoded!.is_international).toBe(true);
    expect(decoded!.research_interests).toBe(FULL_PROFILE.research_interests);
    expect(decoded!.skills).toEqual(FULL_PROFILE.skills);
    expect(decoded!.coursework).toEqual(FULL_PROFILE.coursework);
    expect(decoded!.search_weight).toBe(60);
    expect(decoded!.seeking_types).toEqual(FULL_PROFILE.seeking_types);
  });

  it('produces URL-safe base64 (no +, /, =)', () => {
    const encoded = encodeProfile(FULL_PROFILE);
    expect(encoded).not.toMatch(/[+/=]/);
  });

  it('emits v:1 version marker', () => {
    const encoded = encodeProfile(FULL_PROFILE);
    const padded = encoded.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((encoded.length + 3) % 4);
    const json = decodeURIComponent(escape(atob(padded)));
    expect(JSON.parse(json).v).toBe(1);
  });

  it('handles unicode in research interests', () => {
    const p = { ...FULL_PROFILE, research_interests: '机器学习 + émotions' };
    const decoded = decodeProfile(encodeProfile(p));
    expect(decoded!.research_interests).toBe('机器学习 + émotions');
  });
});

describe('decodeProfile security caps', () => {
  function encodeRaw(payload: unknown): string {
    const b64 = btoa(unescape(encodeURIComponent(JSON.stringify(payload))));
    return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  it('returns null for unknown version', () => {
    expect(decodeProfile(encodeRaw({ v: 99, major: 'CS' }))).toBeNull();
  });

  it('returns null for malformed base64', () => {
    expect(decodeProfile('not!!!valid!!!base64')).toBeNull();
  });

  it('returns null for non-JSON payload', () => {
    const b64 = btoa('this is not json');
    expect(decodeProfile(b64)).toBeNull();
  });

  it('truncates research_interests longer than 2000 chars', () => {
    const huge = 'x'.repeat(5000);
    const decoded = decodeProfile(encodeRaw({ v: 1, interests: huge }));
    expect(decoded!.research_interests!.length).toBe(2000);
  });

  it('truncates college/major/grade', () => {
    const decoded = decodeProfile(encodeRaw({
      v: 1,
      college: 'x'.repeat(500),
      major: 'x'.repeat(500),
      grade: 'x'.repeat(500),
    }));
    expect(decoded!.college!.length).toBe(100);
    expect(decoded!.major!.length).toBe(100);
    expect(decoded!.grade!.length).toBe(30);
  });

  it('caps skills array at 50 entries and names at 50 chars', () => {
    const manySkills = Array.from({ length: 200 }, (_, i) => ({
      n: `skill-${'x'.repeat(100)}-${i}`,
      l: 'beginner',
    }));
    const decoded = decodeProfile(encodeRaw({ v: 1, skills: manySkills }));
    expect(decoded!.skills!.length).toBe(50);
    expect(decoded!.skills![0].name.length).toBe(50);
  });

  it('defaults unknown skill level to beginner', () => {
    const decoded = decodeProfile(encodeRaw({
      v: 1,
      skills: [{ n: 'X', l: 'wizard' }],
    }));
    expect(decoded!.skills![0].level).toBe('beginner');
  });

  it('rejects search_weight out of [0, 100]', () => {
    expect(decodeProfile(encodeRaw({ v: 1, weight: -5 }))!.search_weight).toBeUndefined();
    expect(decodeProfile(encodeRaw({ v: 1, weight: 999 }))!.search_weight).toBeUndefined();
    expect(decodeProfile(encodeRaw({ v: 1, weight: 50 }))!.search_weight).toBe(50);
  });

  it('filters non-string entries in array fields', () => {
    const decoded = decodeProfile(encodeRaw({
      v: 1,
      seeking: ['research', 42, null, 'internship'],
      courses: ['CS 124', { obj: true }, 'MATH 241'],
    }));
    expect(decoded!.seeking_types).toEqual(['research', 'internship']);
    expect(decoded!.coursework).toEqual(['CS 124', 'MATH 241']);
  });

  it('caps coursework at 50 entries', () => {
    const many = Array.from({ length: 200 }, (_, i) => `COURSE ${i}`);
    const decoded = decodeProfile(encodeRaw({ v: 1, courses: many }));
    expect(decoded!.coursework!.length).toBe(50);
  });

  it('coerces non-string primary fields to empty strings', () => {
    const decoded = decodeProfile(encodeRaw({
      v: 1,
      college: 123,
      major: null,
      grade: { obj: true },
    }));
    expect(decoded!.college).toBe('');
    expect(decoded!.major).toBe('');
    expect(decoded!.grade).toBe('');
  });
});

describe('buildShareUrl', () => {
  it('includes share query param', () => {
    const url = buildShareUrl(FULL_PROFILE);
    expect(url).toContain('?share=');
    const encoded = url.split('?share=')[1];
    const decoded = decodeProfile(encoded);
    expect(decoded!.major).toBe(FULL_PROFILE.major);
  });
});
