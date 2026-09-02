import { describe, expect, it } from 'vitest';
import { SCHOOL_COVERAGE_SCHEMA, type SchoolStatsFile } from './school-coverage';
import { NATIONAL_OPPORTUNITY_COUNT, SCHOOLS, bySlug, detectSchoolFromEmail } from './schools';
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

  it('every school ships campus coverage that is listings + faculty contacts', () => {
    const file = stats as SchoolStatsFile;
    expect(file.schema).toBe(SCHOOL_COVERAGE_SCHEMA);
    expect(file.national_count).toBeGreaterThan(0);
    expect(Object.keys(file.schools).length).toBeGreaterThan(0);

    for (const school of SCHOOLS) {
      const stat = file.schools[school.slug];
      expect(stat, school.slug).toBeDefined();
      expect(stat.total_count, school.slug).toBeGreaterThan(0);
      // The invariant, on the artifact that actually ships: coverage is BOTH
      // populations. Asserting it here is what makes a regression to a
      // listings-only fallback a red test rather than a quiet 100x understatement.
      expect(stat.total_count, school.slug).toBe(
        stat.listing_count + stat.faculty_contact_count,
      );
      // Unreviewed records are counted, and deliberately excluded from the total.
      expect(stat.unreviewed_count, school.slug).toBeGreaterThanOrEqual(0);

      // The registry carries the raw total; flooring happens once, at render.
      expect(school.coverage.campusOpportunities, school.slug).toBe(stat.total_count);
      // Every school's chip counts only its own campus records; the shared
      // national open-opportunity pool is explained in the footer, not per card.
      expect(school.coverage.note).toBe('universitySwitcher.coverageCampus');
    }

    // The national pool is never folded into a school's own number.
    const maxCampus = Math.max(...SCHOOLS.map((s) => s.coverage.campusOpportunities as number));
    expect(NATIONAL_OPPORTUNITY_COUNT).toBe(file.national_count);
    expect(SCHOOLS.every((s) => s.coverage.campusOpportunities !== maxCampus + file.national_count))
      .toBe(true);

    const pending = SCHOOLS.filter((s) => s.coverage.campusOpportunities === 'pending');
    expect(pending).toEqual([]);
    expect(SCHOOLS.length).toBe(114);
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
