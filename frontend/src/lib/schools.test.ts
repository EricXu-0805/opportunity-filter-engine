import { describe, expect, it } from 'vitest';
import { SCHOOLS, UCB_CAMPUS_OPPORTUNITIES, bySlug, detectSchoolFromEmail } from './schools';

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
    expect(bySlug('mit')).toBeUndefined();
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

  it('every school ships live campus coverage — no pending left', () => {
    expect(bySlug('uiuc')?.coverage.campusOpportunities).toBe(4700);
    // UCB coverage is the config-driven estimate, not a magic literal — assert
    // it tracks the computed constant and clears a conservative floor that the
    // shipped dataset (~369 school='ucb' records) already exceeds, so the chip
    // can't silently revert to the stale 200.
    expect(bySlug('ucb')?.coverage.campusOpportunities).toBe(UCB_CAMPUS_OPPORTUNITIES);
    expect(UCB_CAMPUS_OPPORTUNITIES).toBeGreaterThanOrEqual(300);
    // Campus-graph schools (US-News Top-50 rollout): conservative seed-floor
    // counts of school=<slug> records (campus + lab buckets; the open/national
    // programs are not counted), not 'pending'.
    expect(bySlug('princeton')?.coverage.campusOpportunities).toBe(9);
    expect(bySlug('umich')?.coverage.campusOpportunities).toBe(110);
    expect(bySlug('uw')?.coverage.campusOpportunities).toBe(2259);
    expect(bySlug('gatech')?.coverage.campusOpportunities).toBe(460);
    expect(bySlug('stanford')?.coverage.campusOpportunities).toBe(1422);
    expect(bySlug('utexas')?.coverage.campusOpportunities).toBe(2351);
    expect(bySlug('wisc')?.coverage.campusOpportunities).toBe(380);
    expect(bySlug('ucla')?.coverage.campusOpportunities).toBe(2033);
    // All ten registered schools now have a live campus collector.
    const pending = SCHOOLS.filter((s) => s.coverage.campusOpportunities === 'pending');
    expect(pending).toEqual([]);
    expect(SCHOOLS.length).toBe(10);
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
