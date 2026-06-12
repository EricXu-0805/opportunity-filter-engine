/*
 * Known .edu domain → school map, used by AuthModal's live email
 * detection chip. The detected slug is not persisted yet — Phase A2
 * will consume it for home_school, which is why `detectSchoolFromEmail`
 * is exported as a standalone reusable function rather than living
 * inside the modal.
 */

export interface School {
  slug: string;
  /** Primary email domain. Subdomains match too (cs.illinois.edu). */
  domain: string;
  name: string;
  shortName: string;
  nameZh: string;
  /** Official brand color, used for the chip dot. */
  color: string;
}

export const SCHOOLS: School[] = [
  {
    slug: 'uiuc',
    domain: 'illinois.edu',
    name: 'University of Illinois Urbana-Champaign',
    shortName: 'UIUC',
    nameZh: '伊利诺伊大学香槟分校',
    color: '#E84A27',
  },
  {
    slug: 'ucb',
    domain: 'berkeley.edu',
    name: 'University of California, Berkeley',
    shortName: 'UC Berkeley',
    nameZh: '加州大学伯克利分校',
    color: '#003262',
  },
  {
    slug: 'umich',
    domain: 'umich.edu',
    name: 'University of Michigan',
    shortName: 'Michigan',
    nameZh: '密歇根大学',
    color: '#00274C',
  },
  {
    slug: 'gatech',
    domain: 'gatech.edu',
    name: 'Georgia Institute of Technology',
    shortName: 'Georgia Tech',
    nameZh: '佐治亚理工学院',
    color: '#B3A369',
  },
  {
    slug: 'utexas',
    domain: 'utexas.edu',
    name: 'The University of Texas at Austin',
    shortName: 'UT Austin',
    nameZh: '得克萨斯大学奥斯汀分校',
    color: '#BF5700',
  },
  {
    slug: 'ucla',
    domain: 'ucla.edu',
    name: 'University of California, Los Angeles',
    shortName: 'UCLA',
    nameZh: '加州大学洛杉矶分校',
    color: '#2774AE',
  },
  {
    slug: 'uw',
    domain: 'washington.edu',
    name: 'University of Washington',
    shortName: 'UW',
    nameZh: '华盛顿大学',
    color: '#4B2E83',
  },
  {
    slug: 'wisc',
    domain: 'wisc.edu',
    name: 'University of Wisconsin–Madison',
    shortName: 'UW–Madison',
    nameZh: '威斯康星大学麦迪逊分校',
    color: '#C5050C',
  },
  {
    slug: 'stanford',
    domain: 'stanford.edu',
    name: 'Stanford University',
    shortName: 'Stanford',
    nameZh: '斯坦福大学',
    color: '#8C1515',
  },
];

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
