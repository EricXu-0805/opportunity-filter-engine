import { describe, it, expect } from 'vitest';
import { encodeProfile, decodeProfile, decodeProfileResult, buildShareUrl, profileShareUrlFits, PROFILE_SHARE_MAX_URL_CHARACTERS } from './profile-share';
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
    // Names and levels survive the round trip; every decoded skill also gains
    // `source: 'shared'`. A share link is somebody else's self-assessment, so
    // it can never authorise a first-person claim in the RECIPIENT's email
    // until they set the level themselves.
    expect(decoded!.skills).toEqual(
      FULL_PROFILE.skills.map((s) => ({ ...s, source: 'shared' })),
    );
    expect(decoded!.skills?.every((s) => !s.confirmed)).toBe(true);
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

  it('preserves interests after the old 2000-character boundary', () => {
    const huge = 'x'.repeat(5000);
    const decoded = decodeProfile(encodeRaw({ v: 1, interests: huge }));
    expect(decoded!.research_interests!.length).toBe(5000);
  });

  it('preserves long names and rejects the whole import for an overlong year', () => {
    const decoded = decodeProfile(encodeRaw({
      v: 1,
      college: 'x'.repeat(500),
      major: 'x'.repeat(500),
      grade: 'x'.repeat(500),
    }));
    expect(decoded).toBeNull();
    expect(decodeProfile(encodeRaw({ v: 1, college: 'x'.repeat(500), major: 'y'.repeat(500), grade: 'x'.repeat(100) }))).toMatchObject({college: 'x'.repeat(500), major: 'y'.repeat(500), grade: 'x'.repeat(100)});
  });

  it('preserves all 200 skills and their complete names', () => {
    const manySkills = Array.from({ length: 200 }, (_, i) => ({
      n: `skill-${'x'.repeat(100)}-${i}`,
      l: 'beginner',
    }));
    const decoded = decodeProfile(encodeRaw({ v: 1, skills: manySkills }));
    expect(decoded!.skills!.length).toBe(200);
    expect(decoded!.skills![199].name).toBe(manySkills[199].n);
  });

  it('defaults unknown skill level to beginner', () => {
    const decoded = decodeProfile(encodeRaw({
      v: 1,
      skills: [{ n: 'X', l: 'wizard' }],
    }));
    expect(decoded!.skills![0].level).toBe('beginner');
  });

  it('rejects search_weight out of [0, 100]', () => {
    expect(decodeProfile(encodeRaw({ v: 1, weight: -5 }))).toBeNull();
    expect(decodeProfile(encodeRaw({ v: 1, weight: 999 }))).toBeNull();
    expect(decodeProfile(encodeRaw({ v: 1, weight: 50 }))!.search_weight).toBe(50);
  });

  it('rejects an invalid list without importing only the valid subset', () => {
    const decoded = decodeProfile(encodeRaw({
      v: 1,
      seeking: ['research', 42, null, 'internship'],
      courses: ['CS 124', { obj: true }, 'MATH 241'],
    }));
    expect(decoded).toBeNull();
  });

  it('preserves all 200 coursework items', () => {
    const many = Array.from({ length: 200 }, (_, i) => `COURSE ${i}`);
    const decoded = decodeProfile(encodeRaw({ v: 1, courses: many }));
    expect(decoded!.coursework).toEqual(many);
  });

  it('rejects invalid primary fields instead of replacing them with empty strings', () => {
    const decoded = decodeProfile(encodeRaw({
      v: 1,
      college: 123,
      major: null,
      grade: { obj: true },
    }));
    expect(decoded).toBeNull();
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

 it('provides a safe specific issue for an entire rejected share and never clips Unicode', () => {
   const profile = { ...FULL_PROFILE, research_interests: '🧪'.repeat(60000) };
   expect(decodeProfile(encodeProfile(profile))?.research_interests).toBe(profile.research_interests);
   const encoded = btoa(unescape(encodeURIComponent(JSON.stringify({v:1,interests:'🧪'.repeat(60001)}))));
   const result = decodeProfileResult(encoded);
   expect(result).toMatchObject({ok:false,error:{code:'PROFILE_INPUT_LIMIT_EXCEEDED',detail:{field:'profile.research_interests_text',actual:60001,limit:60000}}});
   expect(() => encodeProfile({...FULL_PROFILE,coursework:Array(513).fill('CS 101')})).toThrow();
 });

 it('rejects a string international flag without turning false into true; legacy absence stays false', () => {
   const raw = (x: unknown) => btoa(JSON.stringify(x));
   expect(decodeProfile(raw({v:1,intl:'false'}))).toBeNull();
   expect(decodeProfile(raw({v:1,intl:false}))?.is_international).toBe(false);
   expect(decodeProfile(raw({v:1}))?.is_international).toBe(false);
   expect(decodeProfile(raw({v:1,weight:50.5}))).toBeNull();
 });

 describe('share link transport budget', () => {
   it('accepts exactly the conservative URL budget and rejects one character more', () => {
     expect(profileShareUrlFits('x'.repeat(PROFILE_SHARE_MAX_URL_CHARACTERS))).toBe(true);
     expect(profileShareUrlFits('x'.repeat(PROFILE_SHARE_MAX_URL_CHARACTERS + 1))).toBe(false);
   });
   it('counts the complete encoded Unicode URL rather than original text length', () => {
     const ascii={...FULL_PROFILE,research_interests:'a'.repeat(2000)};
     expect(buildShareUrl(ascii).length).toBeLessThan(8000);
     const unicode={...FULL_PROFILE,research_interests:'🧪'.repeat(2000)};
     const original=JSON.stringify(unicode);
     expect(encodeProfile(unicode).length).toBeGreaterThan(8000);
     expect(()=>buildShareUrl(unicode)).toThrow('too long');
     expect(JSON.stringify(unicode)).toBe(original);
   });
 });
