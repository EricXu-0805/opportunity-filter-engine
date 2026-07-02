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

/**
 * UC Berkeley campus coverage, broken out by source family so the headline
 * count is a transparent, config-driven estimate rather than a magic literal.
 * Refresh these as the active UCB collector set changes (the previous single
 * hardcoded 200 went stale the moment the campus graph + faculty directories
 * landed). Deriving the count from the dataset at build time remains the
 * tracked follow-up — the frontend bundle doesn't load the opportunities
 * corpus — so this stays a maintained estimate.
 *
 * Calibrated against the shipped dataset (~2,900 active `school='ucb'` records:
 * faculty ~1,985 across 52 departments — the original 38 plus the L&S
 * humanities/language block, Goldman, the Helen Wills Neuroscience Institute,
 * and the CDSS / Data Science college; campus programs/dept pages 58; labs 16;
 * plus ~860 URAP project-database entries — individual faculty-posted research
 * projects). Rounded down to conservative figures so the chip never overstates.
 */
const UCB_CAMPUS_COVERAGE = {
  /** ucb_*_faculty directories — 52 departments scraped. */
  facultyDirectories: 1984,
  /** ucb_research_programs: OURS programs, dept research pages, career/RA boards (news/email/grad-nav noise filtered out). */
  campusPrograms: 58,
  /** ucb_labs: lab / research-center recruiting pages. */
  labs: 16,
  /**
   * ucb_urap_projects: individual faculty-posted projects from the URAP project
   * database. Live openings appear during the application window; off-season the
   * count is the seeded past-project archive (non-actionable references).
   */
  urapProjects: 860,
} as const;

export const UCB_CAMPUS_OPPORTUNITIES: number =
  UCB_CAMPUS_COVERAGE.facultyDirectories +
  UCB_CAMPUS_COVERAGE.campusPrograms +
  UCB_CAMPUS_COVERAGE.labs +
  UCB_CAMPUS_COVERAGE.urapProjects;

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
    coverage: { campusOpportunities: UCB_CAMPUS_OPPORTUNITIES, note: 'universitySwitcher.coverageCampus' },
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
    // Campus-graph engine (UROP hub/programs/dept research/career/institutes,
    // ~9 records) plus the curated faculty directory (~103 professors across 14
    // departments). Conservative maintained estimate, rounded down, like UCB.
    coverage: { campusOpportunities: 110, note: 'universitySwitcher.coverageCampus' },
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
    // Campus-graph engine (8 program/office/lab records) plus the live-scraped
    // faculty directory (~1,300 professors across 36 departments — UIUC-parity
    // coverage): the full College of Computing, College of Engineering (Aero,
    // Biomedical, ISyE, Mechanical + ECE/Civil/Materials/Chemical), College of
    // Sciences (Chemistry, Math, Biological Sciences, Earth & Atmospheric,
    // Physics, Psychology), the Scheller College of Business (its JSON directory
    // feed split into eight academic areas), the College of Design, and the Ivan
    // Allen College of Liberal Arts. SURE/REU programs are national, not counted.
    coverage: { campusOpportunities: 1301, note: 'universitySwitcher.coverageCampus' },
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
    // Campus-graph engine (10 program/office records) plus the live-scraped
    // faculty directory (~2,300 professors across 70 departments — UIUC-parity
    // coverage): Cockrell Engineering (CS/ECE/ME + the WordPress Cockrell depts +
    // Petroleum), the full College of Natural Sciences (Algolia: Physics through
    // Astronomy, Neuroscience, Molecular Biosciences, Statistics & Data Sciences,
    // and the iSchool), the entire College of Liberal Arts (the shared
    // webeditor.la JSON:API, one division each, ladder-filtered), and the
    // professional schools — McCombs, Moody Communication, Fine Arts, Education,
    // Architecture, LBJ, Pharmacy, Nursing, Social Work, and Law.
    coverage: { campusOpportunities: 2351, note: 'universitySwitcher.coverageCampus' },
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
    // Campus-graph engine (10 records: the two Undergraduate Research Centers,
    // URSP, the URC summer program, Dean's Research Fellowship, SRP-99, the
    // Samueli engineering research page, the career center, the CNSI institute)
    // plus the live-scraped faculty directory (~2,000 professors across 46
    // departments — UIUC-parity coverage): WordPress-REST + Samueli AJAX for the
    // sciences and engineering, plus the full College of Letters & Science
    // (Humanities ladder pages, the social sciences, and the life sciences) and
    // the professional schools (Anderson, Law, Public Affairs, Nursing, the Herb
    // Alpert School of Music, Architecture & Urban Design, and the Arts).
    coverage: { campusOpportunities: 2033, note: 'universitySwitcher.coverageCampus' },
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
    // Campus-graph engine (10 program/office/lab records) plus the live-scraped
    // faculty directory (~2,250 professors across 61 departments — UIUC-parity
    // coverage): Engineering (Allen CSE + facultyfinder depts, keyworded), the
    // full College of Arts & Sciences (Drupal grids), the College of the
    // Environment, Education, Foster Business, Nursing, Pharmacy, Public Health,
    // Social Work, Evans, the iSchool, Built Environments, and School of Medicine
    // basic sciences. The Institute for Protein Design program is national/open.
    coverage: { campusOpportunities: 2259, note: 'universitySwitcher.coverageCampus' },
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
    // Campus-graph engine (9 program/office records) plus the live-scraped
    // faculty directory (~1,780 professors across 69 departments — UIUC-parity
    // coverage): the full College of Engineering (home rosters on
    // engineering.wisc.edu), all of Letters & Science (social sciences,
    // humanities, natural sciences), the College of Agricultural & Life Sciences,
    // the Wisconsin School of Business, the School of Education, the professional
    // schools (Law, Nursing, Pharmacy, Social Work, Public Affairs), Human
    // Ecology, the Nelson Institute, and Veterinary Medicine. Chemistry stays
    // deferred (an AWS bot-challenge blocks the scraper). IBS-SRP REU is national.
    coverage: { campusOpportunities: 1781, note: 'universitySwitcher.coverageCampus' },
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
    // Campus-graph engine (10 program/office/lab records) plus the live-scraped
    // faculty directory (~1,440 professors across 52 departments — UIUC-parity
    // coverage): the full School of Engineering (incl. EE, MS&E, ICME), all of
    // Humanities & Sciences (the sciences keyworded per research-area taxonomy,
    // the social sciences, and the humanities incl. the DLCL languages), the
    // Doerr School of Sustainability, the Graduate School of Education, the Law
    // School (WordPress REST), and the School of Medicine's basic-science
    // departments. SSRP/Amgen is national; GSB WAFs the scraper (left out).
    coverage: { campusOpportunities: 1422, note: 'universitySwitcher.coverageCampus' },
    catalog: { colleges: 3, majors: 71 },
  },
  {
    slug: 'princeton',
    domain: 'princeton.edu',
    name: 'Princeton University',
    shortName: 'Princeton',
    nameZh: '普林斯顿大学',
    color: '#E77500',
    location: 'Princeton, NJ',
    // Campus-graph engine (9 curated OUR programs, dept research, career,
    // institutes) plus the live-scraped faculty directory (~286 professors across
    // 7 departments: Mathematics (central Drupal) + CS, Physics, MAE, CBE, CEE,
    // and EEB via the engine's headless-render mode that clears Cloudflare/JS —
    // CS keyworded, MAE/CBE emailed). More Princeton depts get added over time.
    coverage: { campusOpportunities: 295, note: 'universitySwitcher.coverageCampus' },
    catalog: { colleges: 5, majors: 37 },
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
