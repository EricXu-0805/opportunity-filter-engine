import { describe, expect, it } from 'vitest';
import { cleanCompensation, formatType, friendlyLabel } from './detail-utils';
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

describe('cleanCompensation', () => {
  it('passes a clean short value through untouched', () => {
    expect(cleanCompensation('$5,000')).toBe('$5,000');
    expect(cleanCompensation('Stipend provided')).toBe('Stipend provided');
    expect(cleanCompensation('Unpaid')).toBe('Unpaid');
  });

  it('extracts the dollar amount from a scraped metadata blob', () => {
    const blob =
      '(40 hours/week maximum) and provides a stipend and housing allowance. Students ' +
      'awarded | d housing allowance. Students awarded a paid fellowship are responsible ' +
      'for securing | Science & Technology Duration 10 weeks Compensation $7,000 ' +
      'Citizenship Requirement No Citiz';
    expect(cleanCompensation(blob)).toBe('$7,000');
  });

  it('extracts a qualitative value when there is no dollar amount', () => {
    const blob =
      '& Behavior Duration Varies Compensation Paid Program Citizenship Requirement No Citi | ial Sciences & Behavior';
    expect(cleanCompensation(blob)).toBe('Paid Program');
  });

  it('returns empty when the blob has no usable pay value (caller falls back)', () => {
    expect(
      cleanCompensation('Some Department Duration 8 weeks Citizenship Requirement US Citiz | x'),
    ).toBe('');
  });

  it('handles missing input', () => {
    expect(cleanCompensation(undefined)).toBe('');
    expect(cleanCompensation('')).toBe('');
    expect(cleanCompensation(null)).toBe('');
  });
});
