import type { Opportunity } from '@/lib/types';

export type FellowshipYear = 'freshman' | 'sophomore' | 'junior' | 'senior';
export type IntlFilter = '' | 'yes' | 'no';

export const FELLOWSHIP_YEARS: FellowshipYear[] = [
  'freshman', 'sophomore', 'junior', 'senior',
];

export const COLLEGE_KEYS = [
  'any', 'grainger', 'siebel', 'las', 'aces', 'gies',
  'media', 'appliedHealth', 'fineArts', 'education', 'beckman',
] as const;
export type CollegeKey = typeof COLLEGE_KEYS[number];

export interface FellowshipFiltersState {
  year: FellowshipYear | '';
  international: IntlFilter;
  college: CollegeKey;
}

export const DEFAULT_FELLOWSHIP_FILTERS: FellowshipFiltersState = {
  year: '',
  international: '',
  college: 'any',
};

const COLLEGE_MATCHERS: Record<Exclude<CollegeKey, 'any'>, RegExp> = {
  grainger: /grainger|engineering|aerospace|mech\.? eng|civil eng|electrical|computer eng|materials/i,
  siebel: /siebel|computer science|computing|data science|\bcs\b/i,
  las: /\blas\b|liberal arts|biology|chemistry|physics|math|psychology|sociology|economics/i,
  aces: /\baces\b|agricultural|consumer|environmental|food science|nutrition|animal science/i,
  gies: /\bgies\b|business|finance|accounting|marketing|management/i,
  media: /\bmedia\b|journalism|communication/i,
  appliedHealth: /applied health|kinesiology|speech|recreation|community health/i,
  fineArts: /fine.{0,3}arts|theater|theatre|music|dance|design/i,
  education: /\beducation\b|teacher|pedagogy|curriculum/i,
  beckman: /beckman/i,
};

export function fellowshipMatchesCollege(opp: Opportunity, college: CollegeKey): boolean {
  if (college === 'any') return true;
  const matcher = COLLEGE_MATCHERS[college];
  if (!matcher) return true;
  const haystack = [
    opp.department,
    opp.organization,
    opp.lab_or_program,
    opp.title,
    ...(opp.eligibility?.majors ?? []),
  ].filter(Boolean).join(' ');
  return matcher.test(haystack);
}

export function fellowshipMatchesYear(opp: Opportunity, year: FellowshipYear | ''): boolean {
  if (!year) return true;
  const preferred = opp.eligibility?.preferred_year ?? [];
  if (preferred.length === 0) return true;
  return preferred.some((p) => p.toLowerCase().includes(year));
}

export function fellowshipMatchesIntl(opp: Opportunity, intl: IntlFilter): boolean {
  if (!intl) return true;
  const flag = opp.eligibility?.international_friendly;
  if (intl === 'yes') return flag === 'yes';
  return flag !== 'no';
}

export function applyFellowshipFilters(
  list: Opportunity[],
  filters: FellowshipFiltersState,
): Opportunity[] {
  return list.filter((opp) =>
    fellowshipMatchesYear(opp, filters.year)
    && fellowshipMatchesIntl(opp, filters.international)
    && fellowshipMatchesCollege(opp, filters.college),
  );
}
