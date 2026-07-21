import { describe, expect, it } from 'vitest';
import { SCHOOLS, bySlug, detectSchoolFromEmail } from './schools';
import stats from './school-stats.json';

describe('detectSchoolFromEmail — known schools', () => {
  it('matches an exact known domain', () => {
    const d = detectSchoolFromEmail('eric@illinois.edu');
    expect(d.kind).toBe('school');
    if (d.kind === 'school') {
      expect(d.school.slug).toBe('uiuc');
      expect(d.school.name).toBe('University of Illinois Urbana-Champaign');
    }
  });

  it('matches every school in the map by its primary domain', () => {
    for (const school of SCHOOLS) {
      const d = detectSchoolFromEmail(`student@${school.domain}`);
      expect(d.kind, school.slug).toBe('school');
      if (d.kind === 'school') expect(d.school.slug).toBe(school.slug);
    }
  });

  it('matches subdomains of a known domain', () => {
    const cs = detectSchoolFromEmail('oski@cs.berkeley.edu');
    expect(cs).toMatchObject({ kind: 'school', school: { slug: 'ucb' } });
    const eecs = detectSchoolFromEmail('grace@eecs.umich.edu');
    expect(eecs).toMatchObject({ kind: 'school', school: { slug: 'umich' } });
  });

  it('is case-insensitive on the domain', () => {
    expect(detectSchoolFromEmail('eric@ILLINOIS.EDU')).toMatchObject({
      kind: 'school',
      school: { slug: 'uiuc' },
    });
  });

  it('does NOT match lookalike domains that merely contain a school domain', () => {
    expect(detectSchoolFromEmail('x@notillinois.edu').kind).toBe('edu');
    expect(detectSchoolFromEmail('x@illinois.edu.evil.com').kind).toBe('none');
  });
});

describe('detectSchoolFromEmail — unknown .edu', () => {
  it('returns edu for an unmapped .edu domain', () => {
    expect(detectSchoolFromEmail('x@somewhere.edu')).toEqual({ kind: 'edu' });
  });

  it('returns edu for subdomains of unmapped .edu domains', () => {
    expect(detectSchoolFromEmail('x@grad.somewhere.edu')).toEqual({ kind: 'edu' });
  });

  it('does not treat the bare "edu"-ish domains as student email', () => {
    expect(detectSchoolFromEmail('x@.edu').kind).toBe('none');
  });
});

describe('detectSchoolFromEmail — non-.edu and partial input', () => {
  it('returns none for a non-.edu email', () => {
    expect(detectSchoolFromEmail('x@gmail.com')).toEqual({ kind: 'none' });
  });

  it('returns none while the user is still typing (no domain yet)', () => {
    expect(detectSchoolFromEmail('')).toEqual({ kind: 'none' });
    expect(detectSchoolFromEmail('eric')).toEqual({ kind: 'none' });
    expect(detectSchoolFromEmail('eric@')).toEqual({ kind: 'none' });
  });

  it('requires a non-empty local part (no chip on a bare @domain)', () => {
    expect(detectSchoolFromEmail('@illinois.edu')).toEqual({ kind: 'none' });
  });

  it('uses the last @ so display-name pastes still resolve the domain', () => {
    expect(detectSchoolFromEmail('Eric Xu @work@illinois.edu')).toMatchObject({
      kind: 'school',
      school: { slug: 'uiuc' },
    });
  });
});

describe('registry — switcher metadata', () => {
  it('bySlug resolves every registered school and rejects unknown slugs', () => {
    for (const school of SCHOOLS) {
      expect(bySlug(school.slug)).toBe(school);
    }
    expect(bySlug('hogwarts')).toBeUndefined();
    expect(bySlug('')).toBeUndefined();
  });

  it('every school carries a location and coverage with an i18n note key', () => {
    for (const school of SCHOOLS) {
      expect(school.location.length, school.slug).toBeGreaterThan(0);
      expect(school.coverage.note.startsWith('universitySwitcher.'), school.slug).toBe(true);
      const c = school.coverage.campusOpportunities;
      expect(c === 'pending' || (typeof c === 'number' && c > 0), school.slug).toBe(true);
    }
  });

  it('every school ships live campus coverage derived from the corpus stats', () => {
    const entries = Object.values(stats) as { campus: number; national: number }[];
    expect(entries.length).toBeGreaterThan(0);
    const national = entries[0].national;
    expect(national).toBeGreaterThan(0);
    for (const entry of entries) expect(entry.national).toBe(national);

    for (const school of SCHOOLS) {
      const stat = (stats as Record<string, { campus: number; national: number }>)[school.slug];
      expect(stat, school.slug).toBeDefined();
      expect(stat.campus, school.slug).toBeGreaterThan(0);

      const c = school.coverage.campusOpportunities;
      expect(typeof c, school.slug).toBe('number');
      // Every school's chip counts only its own campus records; the shared
      // national open-opportunity pool is explained in the footer, not per card.
      const raw = stat.campus;
      expect(school.coverage.note).toBe('universitySwitcher.coverageCampus');
      // Floored, never overstating, and within one floor step of the raw count.
      expect(c as number, school.slug).toBeLessThanOrEqual(raw);
      expect(raw - (c as number), school.slug).toBeLessThan(100);
    }

    const pending = SCHOOLS.filter((s) => s.coverage.campusOpportunities === 'pending');
    expect(pending).toEqual([]);
    expect(SCHOOLS.length).toBe(100);
  });

  it('slugs are unique', () => {
    const slugs = SCHOOLS.map((s) => s.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
  });

  it('every school ships a catalog with positive counts', () => {
    // Exact count-vs-data parity is asserted in catalogs/catalogs.test.ts.
    for (const school of SCHOOLS) {
      expect(school.catalog, school.slug).not.toBeNull();
      expect(school.catalog!.colleges, school.slug).toBeGreaterThan(0);
      expect(school.catalog!.majors, school.slug).toBeGreaterThan(0);
    }
  });
});
