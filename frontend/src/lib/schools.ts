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
    catalog: { colleges: 10, majors: 70 },
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
  {
    slug: 'upenn',
    domain: 'upenn.edu',
    name: 'University of Pennsylvania',
    shortName: 'Penn',
    nameZh: '宾夕法尼亚大学',
    color: '#011F5B',
    location: 'Philadelphia, PA',
    coverage: campusCoverage('upenn'),
    catalog: { colleges: 4, majors: 66 },
  },
  {
    slug: 'caltech',
    domain: 'caltech.edu',
    name: 'California Institute of Technology',
    shortName: 'Caltech',
    nameZh: '加州理工学院',
    color: '#FF6C0C',
    location: 'Pasadena, CA',
    coverage: campusCoverage('caltech'),
    catalog: { colleges: 6, majors: 28 },
  },
  {
    slug: 'cornell',
    domain: 'cornell.edu',
    name: 'Cornell University',
    shortName: 'Cornell',
    nameZh: '康奈尔大学',
    color: '#B31B1B',
    location: 'Ithaca, NY',
    coverage: campusCoverage('cornell'),
    catalog: { colleges: 9, majors: 99 },
  },
  {
    slug: 'brown',
    domain: 'brown.edu',
    name: 'Brown University',
    shortName: 'Brown',
    nameZh: '布朗大学',
    color: '#4E3629',
    location: 'Providence, RI',
    coverage: campusCoverage('brown'),
    catalog: { colleges: 7, majors: 88 },
  },
  {
    slug: 'rice',
    domain: 'rice.edu',
    name: 'Rice University',
    shortName: 'Rice',
    nameZh: '莱斯大学',
    color: '#00205B',
    location: 'Houston, TX',
    coverage: campusCoverage('rice'),
    catalog: { colleges: 7, majors: 62 },
  },
  {
    slug: 'vanderbilt',
    domain: 'vanderbilt.edu',
    name: 'Vanderbilt University',
    shortName: 'Vanderbilt',
    nameZh: '范德堡大学',
    color: '#866D4B',
    location: 'Nashville, TN',
    coverage: campusCoverage('vanderbilt'),
    catalog: { colleges: 4, majors: 66 },
  },
  {
    slug: 'dartmouth',
    domain: 'dartmouth.edu',
    name: 'Dartmouth College',
    shortName: 'Dartmouth',
    nameZh: '达特茅斯学院',
    color: '#00693E',
    location: 'Hanover, NH',
    coverage: campusCoverage('dartmouth'),
    catalog: { colleges: 5, majors: 41 },
  },
  {
    slug: 'columbia',
    domain: 'columbia.edu',
    name: 'Columbia University',
    shortName: 'Columbia',
    nameZh: '哥伦比亚大学',
    color: '#0077C8',
    location: 'New York, NY',
    coverage: campusCoverage('columbia'),
    catalog: { colleges: 3, majors: 65 },
  },
  {
    slug: 'mit',
    domain: 'mit.edu',
    name: 'Massachusetts Institute of Technology',
    shortName: 'MIT',
    nameZh: '麻省理工学院',
    color: '#A31F34',
    location: 'Cambridge, MA',
    coverage: campusCoverage('mit'),
    catalog: { colleges: 6, majors: 36 },
  },
  {
    slug: 'harvard',
    domain: 'harvard.edu',
    name: 'Harvard University',
    shortName: 'Harvard',
    nameZh: '哈佛大学',
    color: '#A51C30',
    location: 'Cambridge, MA',
    coverage: campusCoverage('harvard'),
    catalog: { colleges: 4, majors: 39 },
  },
  {
    slug: 'usc',
    domain: 'usc.edu',
    name: 'University of Southern California',
    shortName: 'USC',
    nameZh: '南加州大学',
    color: '#990000',
    location: 'Los Angeles, CA',
    coverage: campusCoverage('usc'),
    catalog: { colleges: 14, majors: 48 },
  },
  {
    slug: 'umn',
    domain: 'umn.edu',
    name: 'University of Minnesota Twin Cities',
    shortName: 'UMN',
    nameZh: '明尼苏达大学双城分校',
    color: '#7A0019',
    location: 'Minneapolis, MN',
    coverage: campusCoverage('umn'),
    catalog: { colleges: 9, majors: 67 },
  },
  {
    slug: 'osu',
    domain: 'osu.edu',
    name: 'Ohio State University',
    shortName: 'Ohio State',
    nameZh: '俄亥俄州立大学',
    color: '#BB0000',
    location: 'Columbus, OH',
    coverage: campusCoverage('osu'),
    catalog: { colleges: 12, majors: 67 },
  },
  {
    slug: 'nd',
    domain: 'nd.edu',
    name: 'University of Notre Dame',
    shortName: 'Notre Dame',
    nameZh: '圣母大学',
    color: '#0C2340',
    location: 'Notre Dame, IN',
    coverage: campusCoverage('nd'),
    catalog: { colleges: 6, majors: 34 },
  },
  {
    slug: 'rochester',
    domain: 'rochester.edu',
    name: 'University of Rochester',
    shortName: 'Rochester',
    nameZh: '罗切斯特大学',
    color: '#003B71',
    location: 'Rochester, NY',
    coverage: campusCoverage('rochester'),
    catalog: { colleges: 4, majors: 22 },
  },
  {
    slug: 'uf',
    domain: 'ufl.edu',
    name: 'University of Florida',
    shortName: 'UF',
    nameZh: '佛罗里达大学',
    color: '#0021A5',
    location: 'Gainesville, FL',
    coverage: campusCoverage('uf'),
    catalog: { colleges: 12, majors: 53 },
  },
  {
    slug: 'umass',
    domain: 'umass.edu',
    name: 'University of Massachusetts Amherst',
    shortName: 'UMass',
    nameZh: '马萨诸塞大学阿默斯特分校',
    color: '#881C1C',
    location: 'Amherst, MA',
    coverage: campusCoverage('umass'),
    catalog: { colleges: 10, majors: 79 },
  },
  {
    slug: 'yale',
    domain: 'yale.edu',
    name: 'Yale University',
    shortName: 'Yale',
    nameZh: '耶鲁大学',
    color: '#00356B',
    location: 'New Haven, CT',
    coverage: campusCoverage('yale'),
    catalog: { colleges: 4, majors: 62 },
  },
  {
    slug: 'vt',
    domain: 'vt.edu',
    name: 'Virginia Tech',
    shortName: 'Virginia Tech',
    nameZh: '弗吉尼亚理工',
    color: '#861F41',
    location: 'Blacksburg, VA',
    coverage: campusCoverage('vt'),
    catalog: { colleges: 7, majors: 61 },
  },
  {
    slug: 'tamu',
    domain: 'tamu.edu',
    name: 'Texas A&M University',
    shortName: 'Texas A&M',
    nameZh: '得克萨斯农工大学',
    color: '#500000',
    location: 'College Station, TX',
    coverage: campusCoverage('tamu'),
    catalog: { colleges: 12, majors: 65 },
  },
  {
    slug: 'umd',
    domain: 'umd.edu',
    name: 'University of Maryland, College Park',
    shortName: 'Maryland',
    nameZh: '马里兰大学帕克分校',
    color: '#E21833',
    location: 'College Park, MD',
    coverage: campusCoverage('umd'),
    catalog: { colleges: 12, majors: 63 },
  },
  {
    slug: 'neu',
    domain: 'northeastern.edu',
    name: 'Northeastern University',
    shortName: 'Northeastern',
    nameZh: '美国东北大学',
    color: '#D41B2C',
    location: 'Boston, MA',
    coverage: campusCoverage('neu'),
    catalog: { colleges: 7, majors: 48 },
  },
  {
    slug: 'sbu',
    domain: 'stonybrook.edu',
    name: 'Stony Brook University',
    shortName: 'Stony Brook',
    nameZh: '石溪大学',
    color: '#990000',
    location: 'Stony Brook, NY',
    coverage: campusCoverage('sbu'),
    catalog: { colleges: 8, majors: 39 },
  },
  {
    slug: 'bu',
    domain: 'bu.edu',
    name: 'Boston University',
    shortName: 'BU',
    nameZh: '波士顿大学',
    color: '#CC0000',
    location: 'Boston, MA',
    coverage: campusCoverage('bu'),
    catalog: { colleges: 11, majors: 45 },
  },
  {
    slug: 'washu',
    domain: 'wustl.edu',
    name: 'Washington University in St. Louis',
    shortName: 'WashU',
    nameZh: '圣路易斯华盛顿大学',
    color: '#A51417',
    location: 'St. Louis, MO',
    coverage: campusCoverage('washu'),
    catalog: { colleges: 4, majors: 35 },
  },
  {
    slug: 'rutgers',
    domain: 'rutgers.edu',
    name: 'Rutgers University-New Brunswick',
    shortName: 'Rutgers',
    nameZh: '罗格斯大学新布朗斯维克分校',
    color: '#CC0033',
    location: 'New Brunswick, NJ',
    coverage: campusCoverage('rutgers'),
    catalog: { colleges: 10, majors: 53 },
  },
  {
    slug: 'ncsu',
    domain: 'ncsu.edu',
    name: 'North Carolina State University',
    shortName: 'NC State',
    nameZh: '北卡罗来纳州立大学',
    color: '#CC0000',
    location: 'Raleigh, NC',
    coverage: campusCoverage('ncsu'),
    catalog: { colleges: 9, majors: 59 },
  },
  {
    slug: 'psu',
    domain: 'psu.edu',
    name: 'Penn State University Park',
    shortName: 'Penn State',
    nameZh: '宾夕法尼亚州立大学',
    color: '#041E42',
    location: 'University Park, PA',
    coverage: campusCoverage('psu'),
    catalog: { colleges: 12, majors: 73 },
    slug: 'uga',
    domain: 'uga.edu',
    name: 'University of Georgia',
    shortName: 'UGA',
    nameZh: '佐治亚大学',
    color: '#BA0C2F',
    location: 'Athens, GA',
    coverage: campusCoverage('uga'),
    catalog: { colleges: 14, majors: 97 },
  },
  {
    slug: 'ucsc',
    domain: 'ucsc.edu',
    name: 'University of California, Santa Cruz',
    shortName: 'UC Santa Cruz',
    nameZh: '加州大学圣克鲁兹分校',
    color: '#003C6C',
    location: 'Santa Cruz, CA',
    coverage: campusCoverage('ucsc'),
    catalog: { colleges: 5, majors: 49 },
  },
  {
    slug: 'arizona',
    domain: 'arizona.edu',
    name: 'University of Arizona',
    shortName: 'Arizona',
    nameZh: '亚利桑那大学',
    color: '#AB0520',
    location: 'Tucson, AZ',
    coverage: campusCoverage('arizona'),
    catalog: { colleges: 12, majors: 86 },
  },
  {
    slug: 'ucr',
    domain: 'ucr.edu',
    name: 'University of California, Riverside',
    shortName: 'UC Riverside',
    nameZh: '加州大学河滨分校',
    color: '#003DA5',
    location: 'Riverside, CA',
    coverage: campusCoverage('ucr'),
    catalog: { colleges: 6, majors: 57 },
  },
  {
    slug: 'asu',
    domain: 'asu.edu',
    name: 'Arizona State University',
    shortName: 'ASU',
    nameZh: '亚利桑那州立大学',
    color: '#8C1D40',
    location: 'Tempe, AZ',
    coverage: campusCoverage('asu'),
    catalog: { colleges: 10, majors: 82 },
  },
  {
    slug: 'pitt',
    domain: 'pitt.edu',
    name: 'University of Pittsburgh',
    shortName: 'Pitt',
    nameZh: '匹兹堡大学',
    color: '#003594',
    location: 'Pittsburgh, PA',
    coverage: campusCoverage('pitt'),
    catalog: { colleges: 8, majors: 63 },
  },
  {
    slug: 'msu',
    domain: 'msu.edu',
    name: 'Michigan State University',
    shortName: 'Michigan State',
    nameZh: '密歇根州立大学',
    color: '#18453B',
    location: 'East Lansing, MI',
    coverage: campusCoverage('msu'),
    catalog: { colleges: 10, majors: 78 },
  },
  {
    slug: 'cmu',
    domain: 'cmu.edu',
    name: 'Carnegie Mellon University',
    shortName: 'CMU',
    nameZh: '卡内基梅隆大学',
    color: '#C41230',
    location: 'Pittsburgh, PA',
    coverage: campusCoverage('cmu'),
    catalog: { colleges: 6, majors: 37 },
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
