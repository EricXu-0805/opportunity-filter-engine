import type { Opportunity } from '@/lib/types';

export type ProgramTypeFilter = '' | 'fellowship' | 'summer_program';
export type IntlFilter = '' | 'yes' | 'no';
export type PaidFilter = '' | 'paid' | 'unpaid';
export type DeadlineFilter = '' | 'upcoming' | 'rolling';

export interface FellowshipFiltersState {
  type: ProgramTypeFilter;
  international: IntlFilter;
  paid: PaidFilter;
  deadline: DeadlineFilter;
}

export const DEFAULT_FELLOWSHIP_FILTERS: FellowshipFiltersState = {
  type: '',
  international: '',
  paid: '',
  deadline: '',
};

export function fellowshipMatchesType(
  opp: Opportunity,
  type: ProgramTypeFilter,
): boolean {
  return !type || opp.opportunity_type === type;
}

export function fellowshipMatchesIntl(opp: Opportunity, intl: IntlFilter): boolean {
  if (!intl) return true;
  return opp.eligibility?.international_friendly === intl;
}

export function fellowshipMatchesPaid(opp: Opportunity, paid: PaidFilter): boolean {
  if (!paid) return true;
  const value = opp.paid.trim().toLowerCase();
  if (paid === 'paid') return value === 'yes' || value === 'stipend';
  return value === 'no';
}

function isoDateToUtcDay(value: string | null | undefined): number | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (!match) return null;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const utcDay = Date.UTC(year, month - 1, day);
  const parsed = new Date(utcDay);
  if (
    parsed.getUTCFullYear() !== year
    || parsed.getUTCMonth() !== month - 1
    || parsed.getUTCDate() !== day
  ) {
    return null;
  }
  return utcDay;
}

export function fellowshipMatchesDeadline(
  opp: Opportunity,
  deadline: DeadlineFilter,
  now = new Date(),
): boolean {
  if (!deadline) return true;
  if (deadline === 'rolling') return opp.is_rolling === true;
  // "Upcoming" is a promise of a real, confirmed future date — an estimated
  // or unverified deadline must not pass as one.
  if (opp.deadline_is_estimate !== false) return false;

  const deadlineDay = isoDateToUtcDay(opp.deadline);
  if (deadlineDay === null) return false;
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return deadlineDay >= today;
}

export function applyFellowshipFilters(
  list: Opportunity[],
  filters: FellowshipFiltersState,
): Opportunity[] {
  return list.filter((opp) =>
    fellowshipMatchesType(opp, filters.type)
    && fellowshipMatchesIntl(opp, filters.international)
    && fellowshipMatchesPaid(opp, filters.paid)
    && fellowshipMatchesDeadline(opp, filters.deadline),
  );
}
