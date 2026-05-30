import { describe, expect, it } from 'vitest';
import { formatType, friendlyLabel } from './detail-utils';
import type { TFunc } from './types';

const t: TFunc = (key) => key;

describe('formatType', () => {
  it('replaces underscores with spaces', () => {
    expect(formatType('summer_program')).toBe('Summer Program');
  });

  it('title-cases each word', () => {
    expect(formatType('research_internship')).toBe('Research Internship');
  });

  it('handles single-word input', () => {
    expect(formatType('research')).toBe('Research');
  });

  it('handles empty string', () => {
    expect(formatType('')).toBe('');
  });

  it('preserves already-capitalised letters', () => {
    expect(formatType('REU_program')).toBe('REU Program');
  });
});

describe('friendlyLabel', () => {
  it('returns the common.yes key for "yes"', () => {
    expect(friendlyLabel('yes', t)).toBe('common.yes');
  });

  it('returns the common.no key for "no"', () => {
    expect(friendlyLabel('no', t)).toBe('common.no');
  });

  it('returns the common.notSpecified key for "unknown"', () => {
    expect(friendlyLabel('unknown', t)).toBe('common.notSpecified');
  });

  it('returns the raw string for any other value', () => {
    expect(friendlyLabel('weekly', t)).toBe('weekly');
    expect(friendlyLabel('Strong', t)).toBe('Strong');
  });

  it('does not translate the empty string', () => {
    expect(friendlyLabel('', t)).toBe('');
  });
});
