import { describe, expect, it } from 'vitest';
import { translateKey } from './home-utils';
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
