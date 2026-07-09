/*
 * Single school registry: the .edu domain → school map used by
 * AuthModal's live email detection chip, plus the switcher-facing
 * metadata (location, coverage) consumed by UniversitySwitcherModal
 * and the results scope indicator. One list, no parallel copies.
 */

/*
 * Per-school corpus counts, regenerated from data/processed/opportunities.json
 * by scripts/gen-school-stats.mjs on every `npm run build` (prebuild hook) and
 * committed so dev/test work without the corpus. The JSON is a few hundred
 * bytes — the corpus itself never enters the bundle.
 */
import schoolStats from './school-stats.json';

export interface SchoolCoverage {
  /**
   * Count of campus-hosted opportunity records in the dataset, or
   * 'pending' when no campus collector exists yet (the school still
   * sees every national `audience='open'` record). Derived from the
   * corpus via scripts/gen-school-stats.mjs (npm `prebuild`), then
   * floored to a friendly "N+" display so the chip never overstates.
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

const SCHOOL_STATS: Record<string, { campus: number; national: number } | undefined> =
  schoolStats;

/** Round down to a friendly floor so the "N+" chip never overstates. */
function friendlyFloor(n: number): number {
  if (n >= 1000) return Math.floor(n / 100) * 100;
  if (n >= 100) return Math.floor(n / 10) * 10;
  return n;
}

/*
 * The chip counts only this school's own campus-hosted records. The national
 * `audience='open'` pool is shared by every school, so folding it into any one
 * card's number both overstates that card and reads inconsistently across the
 * grid — it's explained once in the switcher footer instead.
 */
function campusCoverage(slug: string): SchoolCoverage {
  const stat = SCHOOL_STATS[slug];
  if (!stat?.campus) {
    return { campusOpportunities: 'pending', note: 'universitySwitcher.coveragePending' };
  }
  return {
    campusOpportunities: friendlyFloor(stat.campus),
    note: 'universitySwitcher.coverageCampus',
  };
}

export const SCHOOLS: School[] = [
  {
    slug: 'uiuc',
    domain: 'illinois.edu',
    name: 'University of Illinois Urbana-Champaign',
    shortName: 'UIUC',
    nameZh: '伊利诺伊大学香槟分校',
    color: '#E84A27',
    location: 'Urbana-Champaign, IL',
    coverage: campusCoverage('uiuc'),
    catalog: { colleges: 12, majors: 142 },
  },
  {
    slug: 'ucb',
    domain: 'berkeley.edu',
    name: 'University of California, Berkeley',
    shortName: 'UC Berkeley',
    nameZh: '加州大学伯克利分校',
    color: '#003262',
    location: 'Berkeley, CA',
    coverage: campusCoverage('ucb'),
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
    coverage: campusCoverage('umich'),
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
    coverage: campusCoverage('gatech'),
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
    coverage: campusCoverage('utexas'),
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
    coverage: campusCoverage('ucla'),
    catalog: { colleges: 9, majors: 135 },
  },
  {
    slug: 'ucsd',
    domain: 'ucsd.edu',
    name: 'University of California, San Diego',
    shortName: 'UC San Diego',
    nameZh: '加州大学圣地亚哥分校',
    color: '#182B49',
    location: 'La Jolla, CA',
    coverage: campusCoverage('ucsd'),
    catalog: { colleges: 8, majors: 165 },
  },
  {
    slug: 'purdue',
    domain: 'purdue.edu',
    name: 'Purdue University',
    shortName: 'Purdue',
    nameZh: '普渡大学',
    color: '#CEB888',
    location: 'West Lafayette, IN',
    coverage: campusCoverage('purdue'),
    catalog: { colleges: 9, majors: 58 },
  },
  {
    slug: 'duke',
    domain: 'duke.edu',
    name: 'Duke University',
    shortName: 'Duke',
    nameZh: '杜克大学',
    color: '#00539B',
    location: 'Durham, NC',
    coverage: campusCoverage('duke'),
    catalog: { colleges: 2, majors: 25 },
  },
  {
    slug: 'jhu',
    domain: 'jhu.edu',
    name: 'Johns Hopkins University',
    shortName: 'Johns Hopkins',
    nameZh: '约翰斯·霍普金斯大学',
    color: '#002D72',
    location: 'Baltimore, MD',
    coverage: campusCoverage('jhu'),
    catalog: { colleges: 7, majors: 52 },
  },
  {
    slug: 'northwestern',
    domain: 'northwestern.edu',
    name: 'Northwestern University',
    shortName: 'Northwestern',
    nameZh: '西北大学',
    color: '#4E2A84',
    location: 'Evanston, IL',
    coverage: campusCoverage('northwestern'),
    catalog: { colleges: 7, majors: 48 },
  },
  {
    slug: 'uchicago',
    domain: 'uchicago.edu',
    name: 'University of Chicago',
    shortName: 'UChicago',
    nameZh: '芝加哥大学',
    color: '#800000',
    location: 'Chicago, IL',
    coverage: campusCoverage('uchicago'),
    catalog: { colleges: 4, majors: 56 },
  },
  {
    slug: 'uw',
    domain: 'washington.edu',
    name: 'University of Washington',
    shortName: 'UW',
    nameZh: '华盛顿大学',
    color: '#4B2E83',
    location: 'Seattle, WA',
    coverage: campusCoverage('uw'),
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
    coverage: campusCoverage('wisc'),
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
    coverage: campusCoverage('stanford'),
    catalog: { colleges: 3, majors: 72 },
  },
  {
    slug: 'princeton',
    domain: 'princeton.edu',
    name: 'Princeton University',
    shortName: 'Princeton',
    nameZh: '普林斯顿大学',
    color: '#E77500',
    location: 'Princeton, NJ',
    coverage: campusCoverage('princeton'),
    catalog: { colleges: 5, majors: 38 },
  },
  {
    slug: 'uci',
    domain: 'uci.edu',
    name: 'University of California, Irvine',
    shortName: 'UC Irvine',
    nameZh: '加州大学欧文分校',
    color: '#0064A4',
    location: 'Irvine, CA',
    coverage: campusCoverage('uci'),
    catalog: { colleges: 14, majors: 84 },
  },
  {
    slug: 'ucsb',
    domain: 'ucsb.edu',
    name: 'University of California, Santa Barbara',
    shortName: 'UC Santa Barbara',
    nameZh: '加州大学圣塔芭芭拉分校',
    color: '#003660',
    location: 'Santa Barbara, CA',
    coverage: campusCoverage('ucsb'),
    catalog: { colleges: 3, majors: 73 },
  },
  {
    slug: 'boulder',
    domain: 'colorado.edu',
    name: 'University of Colorado Boulder',
    shortName: 'CU Boulder',
    nameZh: '科罗拉多大学博尔德分校',
    color: '#CFB87C',
    location: 'Boulder, CO',
    coverage: campusCoverage('boulder'),
    catalog: { colleges: 6, majors: 79 },
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
