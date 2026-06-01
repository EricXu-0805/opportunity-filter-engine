import { describe, it, expect } from 'vitest';
import { diffWords, isWhitespace, type DiffSegment } from './word-diff';

function rebuild(segments: DiffSegment[], side: 'original' | 'tailored'): string {
  const skip = side === 'original' ? 'added' : 'removed';
  return segments
    .filter((s) => s.type !== skip)
    .map((s) => s.value)
    .join('');
}

describe('diffWords', () => {
  it('marks every token equal for identical strings', () => {
    const segs = diffWords('built a parser', 'built a parser');
    expect(segs.every((s) => s.type === 'equal')).toBe(true);
  });

  it('reconstructs both sides exactly from the segments', () => {
    const original = 'Worked on Python projects in CS 225';
    const tailored = 'Implemented Python ML experiments in CS 225 coursework';
    const segs = diffWords(original, tailored);
    expect(rebuild(segs, 'original')).toBe(original);
    expect(rebuild(segs, 'tailored')).toBe(tailored);
  });

  it('flags added words present only in the tailored text', () => {
    const segs = diffWords('built a parser', 'built a fast compiler parser');
    const added = segs.filter((s) => s.type === 'added' && !isWhitespace(s.value)).map((s) => s.value);
    expect(added).toContain('fast');
    expect(added).toContain('compiler');
  });

  it('flags removed words dropped from the original text', () => {
    const segs = diffWords('built a legacy parser quickly', 'built a parser');
    const removed = segs.filter((s) => s.type === 'removed' && !isWhitespace(s.value)).map((s) => s.value);
    expect(removed).toContain('legacy');
    expect(removed).toContain('quickly');
  });

  it('treats a capitalization-only change as equal, not add+remove', () => {
    const segs = diffWords('built a parser', 'Built a parser');
    expect(segs.filter((s) => s.type !== 'equal')).toHaveLength(0);
  });

  it('keeps shared words equal across a reframing', () => {
    const segs = diffWords('made a thing in Python', 'engineered a system in Python');
    const equalWords = segs.filter((s) => s.type === 'equal' && !isWhitespace(s.value)).map((s) => s.value);
    expect(equalWords).toContain('a');
    expect(equalWords).toContain('in');
    expect(equalWords).toContain('Python');
  });

  it('handles empty original (all added) and empty tailored (all removed)', () => {
    expect(diffWords('', 'brand new bullet').every((s) => s.type === 'added')).toBe(true);
    expect(diffWords('old bullet text', '').every((s) => s.type === 'removed')).toBe(true);
  });
});
