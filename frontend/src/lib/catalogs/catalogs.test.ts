import { describe, expect, it } from 'vitest';
import { loadCatalog } from './index';
import { COLLEGE_MAJORS as UIUC_COLLEGE_MAJORS } from '@/lib/colleges';
import { SCHOOLS } from '@/lib/schools';
import { en, zh } from '@/i18n/dictionaries';

const NEW_CATALOG_SLUGS = ['ucb', 'umich', 'gatech', 'utexas', 'ucla', 'uw', 'wisc', 'stanford', 'ucsd', 'uchicago', 'uci', 'ucsb', 'boulder', 'jhu', 'northwestern', 'upenn', 'caltech', 'cornell', 'brown', 'rice', 'vanderbilt', 'dartmouth', 'columbia', 'mit', 'harvard', 'usc', 'umn', 'osu', 'nd', 'rochester', 'uf', 'umass', 'yale', 'vt', 'tamu', 'umd', 'neu', 'sbu', 'bu', 'washu', 'rutgers', 'ncsu', 'psu', 'nyu', 'georgetown', 'emory', 'uva', 'unc', 'tufts', 'uga', 'bc'];

// Anything html.unescape would have missed in the generated data files.
const HTML_ENTITY = /&[a-zA-Z]+\d*;|&#\d+;/;

describe('catalog data quality — generated school catalogs', () => {
  it.each(NEW_CATALOG_SLUGS)('%s: colleges and majors are non-empty, trimmed, entity-free', async (slug) => {
    const catalog = await loadCatalog(slug);
    expect(catalog).not.toBeNull();
    for (const [college, majors] of Object.entries(catalog!)) {
      expect(college.trim().length, `${slug}: empty college name`).toBeGreaterThan(0);
      expect(college, `${slug}: untrimmed college ${college}`).toBe(college.trim());
      expect(HTML_ENTITY.test(college), `${slug}: HTML entity left in ${college}`).toBe(false);
      expect(majors.length, `${slug}/${college}: no majors`).toBeGreaterThan(0);
      for (const major of majors) {
        expect(major.trim().length, `${slug}/${college}: empty major`).toBeGreaterThan(0);
        expect(major, `${slug}/${college}: untrimmed major ${major}`).toBe(major.trim());
        expect(HTML_ENTITY.test(major), `${slug}/${college}: HTML entity left in ${major}`).toBe(false);
      }
    }
  });

  it.each(NEW_CATALOG_SLUGS)('%s: no duplicate majors within a college', async (slug) => {
    const catalog = await loadCatalog(slug);
    for (const [college, majors] of Object.entries(catalog!)) {
      expect(new Set(majors).size, `${slug}/${college} has a duplicated major`).toBe(majors.length);
    }
  });

  it.each(NEW_CATALOG_SLUGS)('%s: has at least 3 colleges and 20 majors', async (slug) => {
    const catalog = await loadCatalog(slug);
    const colleges = Object.keys(catalog!);
    const majorCount = Object.values(catalog!).reduce((sum, m) => sum + m.length, 0);
    expect(colleges.length, `${slug} colleges`).toBeGreaterThanOrEqual(3);
    expect(majorCount, `${slug} majors`).toBeGreaterThanOrEqual(20);
  });

  it('keeps legitimate cross-college joint offerings (gatech Computational Media)', async () => {
    const gatech = await loadCatalog('gatech');
    expect(gatech!['College of Computing']).toContain('Computational Media');
    expect(gatech!['Ivan Allen College of Liberal Arts']).toContain('Computational Media');
  });

  it('unescaped HTML entities render as real characters (ucb M.E.T. majors)', async () => {
    const ucb = await loadCatalog('ucb');
    expect(ucb!['College of Engineering']).toContain('Electrical Engineering & Computer Sciences');
  });
});

describe('loadCatalog — loader contract', () => {
  it('uiuc resolves to the exact existing colleges.ts data (re-export, not a copy)', async () => {
    expect(await loadCatalog('uiuc')).toBe(UIUC_COLLEGE_MAJORS);
  });

  it('returns null for slugs without a catalog', async () => {
    expect(await loadCatalog('future-school')).toBeNull();
    expect(await loadCatalog('')).toBeNull();
  });
});

describe('zh catalog parity — every catalog label has dictionary entries', () => {
  it('every college and major of every registered school exists in en and zh colleges/majors namespaces', async () => {
    const enColleges = en.colleges as Record<string, string>;
    const zhColleges = zh.colleges as Record<string, string>;
    const enMajors = en.majors as Record<string, string>;
    const zhMajors = zh.majors as Record<string, string>;
    const missing: string[] = [];
    for (const school of SCHOOLS) {
      const catalog = await loadCatalog(school.slug);
      for (const [college, majors] of Object.entries(catalog!)) {
        if (!enColleges[college]) missing.push(`en colleges: ${school.slug}/${college}`);
        if (!zhColleges[college]) missing.push(`zh colleges: ${school.slug}/${college}`);
        for (const major of majors) {
          if (!enMajors[major]) missing.push(`en majors: ${school.slug}/${major}`);
          if (!zhMajors[major]) missing.push(`zh majors: ${school.slug}/${major}`);
        }
      }
    }
    expect(missing).toEqual([]);
  });
});

describe('registry counts match catalog data exactly', () => {
  it('every registered school has a catalog and honest static counts', async () => {
    for (const school of SCHOOLS) {
      expect(school.catalog, `${school.slug} should ship a catalog`).not.toBeNull();
      const catalog = await loadCatalog(school.slug);
      expect(catalog, `${school.slug} registry/loader mismatch`).not.toBeNull();
      const colleges = Object.keys(catalog!).length;
      const majors = Object.values(catalog!).reduce((sum, m) => sum + m.length, 0);
      expect(school.catalog, `${school.slug} counts drifted from data`).toEqual({ colleges, majors });
    }
  });
});
