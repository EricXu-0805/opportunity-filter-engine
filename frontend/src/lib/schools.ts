/*
 * Single school registry: the .edu domain → school map used by
 * AuthModal's live email detection chip, plus the switcher-facing
 * metadata (location, coverage) consumed by UniversitySwitcherModal
 * and the results scope indicator. One list, no parallel copies.
 */

export interface SchoolCoverage {
  /**
   * Count of campus-hosted opportunity records in the dataset, or
   * 'pending' when no campus collector exists yet (the school still
   * sees every national `audience='open'` record). Hardcoded per the
   * PR #187 decision; deriving from the dataset at build time is a
   * tracked follow-up.
   */
  campusOpportunities: number | 'pending';
  /** i18n key for the coverage chip text shown on the switcher card. */
  note: string;
}

export interface School {
  slug: string;
  /** Primary email domain. Subdomains match too (cs.illinois.edu). */
  domain: string;
  name: string;
  shortName: string;
  nameZh: string;
  /** Official brand color, used for the chip dot. */
  color: string;
  location: string;
  coverage: SchoolCoverage;
  /**
   * College/major catalog counts shown on the switcher card, or null for
   * schools whose catalog hasn't shipped (those fall back to free-text
   * college/major inputs). Static so the cards don't pull every catalog
   * chunk into the main bundle; catalogs.test.ts asserts these numbers
   * exactly match the data behind loadCatalog().
   */
  catalog: { colleges: number; majors: number } | null;
}

const PENDING_COVERAGE: SchoolCoverage = {
  campusOpportunities: 'pending',
  note: 'universitySwitcher.coveragePending',
};

export const SCHOOLS: School[] = [
  {
    slug: 'uiuc',
    domain: 'illinois.edu',
    name: 'University of Illinois Urbana-Champaign',
    shortName: 'UIUC',
    nameZh: '伊利诺伊大学香槟分校',
    color: '#E84A27',
    location: 'Urbana-Champaign, IL',
    coverage: { campusOpportunities: 4700, note: 'universitySwitcher.coverageCampusNational' },
    catalog: { colleges: 12, majors: 141 },
  },
  {
    slug: 'ucb',
    domain: 'berkeley.edu',
    name: 'University of California, Berkeley',
    shortName: 'UC Berkeley',
    nameZh: '加州大学伯克利分校',
    color: '#003262',
    location: 'Berkeley, CA',
    coverage: { campusOpportunities: 200, note: 'universitySwitcher.coverageCampus' },
    catalog: { colleges: 7, majors: 136 },
  },
  {
    slug: 'umich',
    domain: 'umich.edu',
    name: 'University of Michigan',
    shortName: 'Michigan',
    nameZh: '密歇根大学',
    color: '#00274C',
    location: 'Ann Arbor, MI',
    coverage: PENDING_COVERAGE,
    catalog: { colleges: 14, majors: 127 },
  },
  {
    slug: 'gatech',
    domain: 'gatech.edu',
    name: 'Georgia Institute of Technology',
    shortName: 'Georgia Tech',
    nameZh: '佐治亚理工学院',
    color: '#B3A369',
    location: 'Atlanta, GA',
    coverage: PENDING_COVERAGE,
    catalog: { colleges: 6, majors: 43 },
  },
  {
    slug: 'utexas',
    domain: 'utexas.edu',
    name: 'The University of Texas at Austin',
    shortName: 'UT Austin',
    nameZh: '得克萨斯大学奥斯汀分校',
    color: '#BF5700',
    location: 'Austin, TX',
    coverage: PENDING_COVERAGE,
    catalog: { colleges: 14, majors: 113 },
  },
  {
    slug: 'ucla',
    domain: 'ucla.edu',
    name: 'University of California, Los Angeles',
    shortName: 'UCLA',
    nameZh: '加州大学洛杉矶分校',
    color: '#2774AE',
    location: 'Los Angeles, CA',
    coverage: PENDING_COVERAGE,
    catalog: { colleges: 9, majors: 135 },
  },
  {
    slug: 'uw',
    domain: 'washington.edu',
    name: 'University of Washington',
    shortName: 'UW',
    nameZh: '华盛顿大学',
    color: '#4B2E83',
    location: 'Seattle, WA',
    coverage: PENDING_COVERAGE,
    catalog: { colleges: 12, majors: 116 },
  },
  {
    slug: 'wisc',
    domain: 'wisc.edu',
    name: 'University of Wisconsin–Madison',
    shortName: 'UW–Madison',
    nameZh: '威斯康星大学麦迪逊分校',
    color: '#C5050C',
    location: 'Madison, WI',
    coverage: PENDING_COVERAGE,
    catalog: { colleges: 8, majors: 146 },
  },
  {
    slug: 'stanford',
    domain: 'stanford.edu',
    name: 'Stanford University',
    shortName: 'Stanford',
    nameZh: '斯坦福大学',
    color: '#8C1515',
    location: 'Stanford, CA',
    coverage: PENDING_COVERAGE,
    catalog: { colleges: 3, majors: 71 },
  },
];

const BY_SLUG = new Map(SCHOOLS.map((s) => [s.slug, s]));

export function bySlug(slug: string): School | undefined {
  return BY_SLUG.get(slug);
}

export type SchoolDetection =
  | { kind: 'school'; school: School }
  | { kind: 'edu' }
  | { kind: 'none' };

/**
 * Live-as-you-type detection. Requires a non-empty local part so the
 * chip never fires on a bare "@illinois.edu". Subdomains of a known
 * school domain (cs.illinois.edu, eecs.berkeley.edu) match the school.
 */
export function detectSchoolFromEmail(email: string): SchoolDetection {
  const at = email.lastIndexOf('@');
  if (at < 1) return { kind: 'none' };
  const domain = email.slice(at + 1).trim().toLowerCase();
  if (!domain) return { kind: 'none' };
  for (const school of SCHOOLS) {
    if (domain === school.domain || domain.endsWith(`.${school.domain}`)) {
      return { kind: 'school', school };
    }
  }
  if (domain.length > 4 && domain.endsWith('.edu')) return { kind: 'edu' };
  return { kind: 'none' };
}
