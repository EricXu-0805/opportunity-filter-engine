import { describe, it, expect } from 'vitest';
import { COLLEGE_MAJORS, COLLEGES, GRADES } from './colleges';

const EXPECTED_COLLEGES = [
  'Division of General Studies (DGS)',
  'Grainger College of Engineering',
  'Liberal Arts & Sciences (LAS)',
  'Gies College of Business',
  'College of ACES',
  'College of Fine & Applied Arts',
  'School of Information Sciences (iSchool)',
  'College of Applied Health Sciences',
  'College of Education',
  'College of Media',
  'School of Social Work',
  'College of Veterinary Medicine',
];

describe('COLLEGE_MAJORS', () => {
  it('exposes exactly the expected set of colleges in insertion order', () => {
    expect(Object.keys(COLLEGE_MAJORS)).toEqual(EXPECTED_COLLEGES);
  });

  it('maps every college to a non-empty array of majors', () => {
    for (const [college, majors] of Object.entries(COLLEGE_MAJORS)) {
      expect(Array.isArray(majors), `${college} should map to an array`).toBe(true);
      expect(majors.length, `${college} should have at least one major`).toBeGreaterThan(0);
    }
  });

  it('has only non-empty, trimmed major strings', () => {
    for (const majors of Object.values(COLLEGE_MAJORS)) {
      for (const major of majors) {
        expect(typeof major).toBe('string');
        expect(major.length).toBeGreaterThan(0);
        expect(major).toBe(major.trim());
      }
    }
  });

  it('has no duplicate majors within a single college', () => {
    for (const [college, majors] of Object.entries(COLLEGE_MAJORS)) {
      expect(new Set(majors).size, `${college} has a duplicated major`).toBe(majors.length);
    }
  });

  it('lists Computer Science and Electrical Engineering under Grainger Engineering', () => {
    const grainger = COLLEGE_MAJORS['Grainger College of Engineering'];
    expect(grainger).toContain('Computer Science');
    // ECE is the department; the undergraduate majors are Electrical Engineering
    // and Computer Engineering (both listed separately), not a combined "ECE".
    expect(grainger).toContain('Electrical Engineering');
    expect(grainger).toContain('Computer Engineering');
  });

  it('lists the cross-listed Statistics & Computer Science under LAS', () => {
    expect(COLLEGE_MAJORS['Liberal Arts & Sciences (LAS)']).toContain(
      'Statistics & Computer Science',
    );
  });

  it('preserves special characters (ampersands, apostrophes, commas) in major names verbatim', () => {
    const las = COLLEGE_MAJORS['Liberal Arts & Sciences (LAS)'];
    expect(las).toContain("Gender & Women's Studies");
    expect(las).toContain('Earth, Society & Environmental Sustainability');
  });

  it('keeps single-major colleges to exactly one entry', () => {
    expect(COLLEGE_MAJORS['School of Social Work']).toEqual(['Social Work']);
    expect(COLLEGE_MAJORS['College of Veterinary Medicine']).toEqual(['Veterinary Medicine']);
  });
});

describe('COLLEGES', () => {
  it('is derived from the keys of COLLEGE_MAJORS', () => {
    expect(COLLEGES).toEqual(Object.keys(COLLEGE_MAJORS));
  });

  it('contains exactly twelve colleges', () => {
    expect(COLLEGES).toHaveLength(12);
  });

  it('round-trips: every listed college resolves to a major array', () => {
    for (const college of COLLEGES) {
      expect(COLLEGE_MAJORS[college]).toBeDefined();
      expect(COLLEGE_MAJORS[college].length).toBeGreaterThan(0);
    }
  });

  it('leads with Division of General Studies as the default option', () => {
    expect(COLLEGES[0]).toBe('Division of General Studies (DGS)');
  });

  it('has no duplicate college names', () => {
    expect(new Set(COLLEGES).size).toBe(COLLEGES.length);
  });
});

describe('GRADES', () => {
  it('lists the undergraduate years in order, then the graduate levels', () => {
    expect(GRADES).toEqual(['Freshman', 'Sophomore', 'Junior', 'Senior', 'Masters', 'PhD']);
  });

  it('starts at Freshman (undergrad) and ends at PhD (grad)', () => {
    expect(GRADES[0]).toBe('Freshman');
    expect(GRADES[GRADES.length - 1]).toBe('PhD');
  });
});
