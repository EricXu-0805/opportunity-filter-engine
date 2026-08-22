import type { Opportunity } from '@/lib/types';

export const FEATURED_PREVIEW_LIMIT = 3;
export const FEATURED_FETCH_POOL = 12;

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export function isPastDeadline(deadline: string | undefined, now: Date): boolean {
  if (!deadline) return false;
  // `new Date('2026-06-01')` is UTC midnight, but startOfDay() below reads the
  // LOCAL calendar fields — so anywhere west of UTC the two disagree by a day
  // and a deadline that is still today reads as past. Every deadline in the
  // corpus is a bare YYYY-MM-DD with no timezone, which means the student's own
  // calendar day is the only frame that answers "is this still open"; the
  // `T00:00:00` suffix is what makes the parse use it (same form as
  // match-utils.daysUntil and the two deadline badges).
  const parsed = new Date(deadline + 'T00:00:00');
  if (Number.isNaN(parsed.getTime())) return false;
  return startOfDay(parsed) < startOfDay(now);
}

export function compareUrgency(a: Opportunity, b: Opportunity): number {
  const aHas = typeof a.deadline === 'string' && a.deadline.length > 0;
  const bHas = typeof b.deadline === 'string' && b.deadline.length > 0;
  if (aHas && !bHas) return -1;
  if (!aHas && bHas) return 1;
  if (!aHas && !bHas) return 0;
  const aT = new Date(a.deadline as string).getTime();
  const bT = new Date(b.deadline as string).getTime();
  if (Number.isNaN(aT) && !Number.isNaN(bT)) return 1;
  if (!Number.isNaN(aT) && Number.isNaN(bT)) return -1;
  if (Number.isNaN(aT) && Number.isNaN(bT)) return 0;
  return aT - bT;
}

export function rankFeaturedFellowships(
  items: readonly Opportunity[],
  now: Date,
  limit: number = FEATURED_PREVIEW_LIMIT,
): Opportunity[] {
  return items
    .filter((opp) => !isPastDeadline(opp.deadline, now))
    .slice()
    .sort(compareUrgency)
    .slice(0, limit);
}
