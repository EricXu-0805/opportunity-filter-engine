/*
 * Mock university catalog for the /labs/university design prototype.
 *
 * NOT production data. Only UIUC carries real numbers (colleges/majors
 * counted from src/lib/colleges.ts; opportunity count from the live
 * dataset). UC Berkeley's 200 faculty opportunities are real but it has
 * no college/major catalog yet (catalog: null demonstrates that state).
 * The remaining seven schools carry plausible placeholder counts to
 * exercise the card layout — production would source these from the
 * catalog pipeline described in the PR.
 */

export interface UniversityEntry {
  id: string;
  name: string;
  nameZh: string;
  shortTag: string;
  location: string;
  /** null = no college/major catalog built yet (e.g. UCB today). */
  catalog: { colleges: number; majors: number } | null;
  dataCoverage: {
    campusOpportunities: number;
    nationalOnly: boolean;
  };
}

/** NSF REU (~570) + Simplify internships (~1,500) — every school sees these. */
export const NATIONAL_OPPORTUNITY_COUNT = 2070;

export const UNIVERSITIES: UniversityEntry[] = [
  {
    id: 'uiuc',
    name: 'University of Illinois Urbana-Champaign',
    nameZh: '伊利诺伊大学香槟分校',
    shortTag: 'UIUC',
    location: 'Urbana-Champaign, IL',
    catalog: { colleges: 12, majors: 141 },
    dataCoverage: { campusOpportunities: 4700, nationalOnly: false },
  },
  {
    id: 'ucb',
    name: 'University of California, Berkeley',
    nameZh: '加州大学伯克利分校',
    shortTag: 'UCB',
    location: 'Berkeley, CA',
    catalog: null,
    dataCoverage: { campusOpportunities: 200, nationalOnly: false },
  },
  {
    id: 'umich',
    name: 'University of Michigan',
    nameZh: '密歇根大学',
    shortTag: 'UMich',
    location: 'Ann Arbor, MI',
    catalog: { colleges: 14, majors: 280 },
    dataCoverage: { campusOpportunities: 0, nationalOnly: true },
  },
  {
    id: 'gatech',
    name: 'Georgia Institute of Technology',
    nameZh: '佐治亚理工学院',
    shortTag: 'GT',
    location: 'Atlanta, GA',
    catalog: { colleges: 6, majors: 44 },
    dataCoverage: { campusOpportunities: 0, nationalOnly: true },
  },
  {
    id: 'utaustin',
    name: 'University of Texas at Austin',
    nameZh: '德克萨斯大学奥斯汀分校',
    shortTag: 'UT Austin',
    location: 'Austin, TX',
    catalog: { colleges: 13, majors: 170 },
    dataCoverage: { campusOpportunities: 0, nationalOnly: true },
  },
  {
    id: 'ucla',
    name: 'University of California, Los Angeles',
    nameZh: '加州大学洛杉矶分校',
    shortTag: 'UCLA',
    location: 'Los Angeles, CA',
    catalog: { colleges: 7, majors: 125 },
    dataCoverage: { campusOpportunities: 0, nationalOnly: true },
  },
  {
    id: 'uw',
    name: 'University of Washington',
    nameZh: '华盛顿大学',
    shortTag: 'UW',
    location: 'Seattle, WA',
    catalog: { colleges: 16, majors: 180 },
    dataCoverage: { campusOpportunities: 0, nationalOnly: true },
  },
  {
    id: 'uwmadison',
    name: 'University of Wisconsin–Madison',
    nameZh: '威斯康星大学麦迪逊分校',
    shortTag: 'UW–Madison',
    location: 'Madison, WI',
    catalog: { colleges: 9, majors: 130 },
    dataCoverage: { campusOpportunities: 0, nationalOnly: true },
  },
  {
    id: 'stanford',
    name: 'Stanford University',
    nameZh: '斯坦福大学',
    shortTag: 'Stanford',
    location: 'Stanford, CA',
    catalog: { colleges: 7, majors: 65 },
    dataCoverage: { campusOpportunities: 0, nationalOnly: true },
  },
];

export function findUniversity(id: string): UniversityEntry {
  const found = UNIVERSITIES.find((u) => u.id === id);
  if (!found) throw new Error(`Unknown university id: ${id}`);
  return found;
}
