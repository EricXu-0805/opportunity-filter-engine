import { describe, expect, it } from 'vitest';
import {
  allowsProfessorFraming,
  cleanCompensation,
  friendlyLabel,
  noDeadlineKind,
} from './detail-utils';
import type { TFunc } from './types';

const t: TFunc = (key) => key;

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

describe('noDeadlineKind', () => {
  const meta = { is_active: true, confidence_score: 0.9 };

  it('classifies faculty records as profiles with no opening deadline', () => {
    expect(noDeadlineKind({ source_type: 'faculty_research', metadata: meta })).toBe('faculty');
    // Faculty beats the note: a directory profile has no listed opening
    // deadline, but that does not prove rolling recruitment.
    expect(
      noDeadlineKind({
        source_type: 'faculty_research',
        metadata: { ...meta, deadline_note: 'Rolling admissions' },
      }),
    ).toBe('faculty');
  });

  it('returns rolling only with scraped rolling evidence in deadline_note', () => {
    expect(
      noDeadlineKind({ source_type: 'campus_program', metadata: { ...meta, deadline_note: 'Rolling admissions' } }),
    ).toBe('rolling');
    expect(
      noDeadlineKind({ source_type: 'campus_program', metadata: { ...meta, deadline_note: 'Applications reviewed on a ROLLING basis' } }),
    ).toBe('rolling');
  });

  it('returns none when the blanket is_rolling default is the only signal', () => {
    expect(noDeadlineKind({ source_type: 'campus_program', metadata: meta })).toBe('none');
    expect(
      noDeadlineKind({ source_type: 'campus_program', metadata: { ...meta, deadline_note: 'See department page' } }),
    ).toBe('none');
    expect(noDeadlineKind({ metadata: meta })).toBe('none');
  });
});

describe('allowsProfessorFraming', () => {
  it('accepts professor-like ranks at any modifier', () => {
    expect(allowsProfessorFraming('Professor')).toBe(true);
    expect(allowsProfessorFraming('Assistant Professor')).toBe(true);
    expect(allowsProfessorFraming('Adjunct Professor')).toBe(true);
    expect(allowsProfessorFraming('associate professor of chemistry')).toBe(true);
  });

  it('does not grant the professor claim to an unknown rank', () => {
    // W11: the honorific is earned by a stated professor rank; unknown
    // stays neutral ("Draft Email", neutral works note).
    expect(allowsProfessorFraming(undefined)).toBe(false);
    expect(allowsProfessorFraming(null)).toBe(false);
    expect(allowsProfessorFraming('')).toBe(false);
    expect(allowsProfessorFraming('   ')).toBe(false);
  });

  it('rejects known non-professor ranks', () => {
    expect(allowsProfessorFraming('Senior Lecturer')).toBe(false);
    expect(allowsProfessorFraming('Research Scientist')).toBe(false);
    expect(allowsProfessorFraming('Instructor')).toBe(false);
    expect(allowsProfessorFraming('Professional Specialist')).toBe(false);
  });

  it('accepts abbreviated professor ranks', () => {
    expect(allowsProfessorFraming('Prof.')).toBe(true);
    expect(allowsProfessorFraming('Asst. Prof')).toBe(true);
  });
});
