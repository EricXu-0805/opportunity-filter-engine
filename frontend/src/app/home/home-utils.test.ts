import { describe, expect, it } from 'vitest';
import { profileChecks, translateKey } from './home-utils';
import type { TFunc } from './types';

// formatRelativeAge moved to lib/humanize-time.formatAgo, where it renders
// through the dictionary instead of returning hardcoded English; its tests
// live in lib/humanize-time.test.ts alongside the bucketing they exercise.

describe('translateKey', () => {
  const t: TFunc = (key) => {
    if (key === 'majors.CS') return 'Computer Science';
    return key;
  };

  it('returns the translation when one exists', () => {
    expect(translateKey(t, 'majors', 'CS')).toBe('Computer Science');
  });

  it('falls back to the raw name when no translation exists', () => {
    expect(translateKey(t, 'colleges', 'Unknown School')).toBe('Unknown School');
  });

  it('combines namespace and name with a dot', () => {
    const captured: string[] = [];
    const spy: TFunc = (key) => {
      captured.push(key);
      return key;
    };
    translateKey(spy, 'grades', 'Sophomore');
    expect(captured[0]).toBe('grades.Sophomore');
  });
});

describe('profileChecks', () => {
  const base = {
    institution: 'UIUC', home_school: 'uiuc', college: 'Grainger', major: 'CS', grade: 'Sophomore',
    is_international: false, research_interests: '', skills: [], search_weight: 50,
  };
  const done = (profile: object) =>
    Object.fromEntries(profileChecks(profile as never).map((c) => [c.key, c.done]));

  it('is the one list both meters read, in a fixed order', () => {
    expect(profileChecks(base as never).map((c) => c.key))
      .toEqual(['academic', 'skills', 'interests', 'resume', 'type']);
  });

  it('applies the home meter thresholds: two skills, a non-blank interest, a stored résumé, a chosen type', () => {
    expect(done(base)).toEqual({ academic: true, skills: false, interests: false, resume: false, type: false });
    expect(done({ ...base, skills: [{ name: 'Python', level: 'expert' }] }).skills).toBe(false);
    expect(done({ ...base, skills: [{ name: 'Python', level: 'expert' }, { name: 'R', level: 'beginner' }] }).skills).toBe(true);
    expect(done({ ...base, research_interests: '   ' }).interests).toBe(false);
    expect(done({ ...base, research_interests: 'MRI' }).interests).toBe(true);
    expect(done({ ...base, resume_text: 'x' }).resume).toBe(true);
    expect(done({ ...base, seeking_types: ['research'] }).type).toBe(true);
    expect(done({ ...base, major: '' }).academic).toBe(false);
  });
});
