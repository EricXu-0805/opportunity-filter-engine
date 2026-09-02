/**
 * The client half of the school-coverage contract.
 *
 * Coverage is `listing_count + faculty_contact_count`, and the backend already
 * adds them (`total_count`). This module's whole job is to make that the only
 * number any surface can render, because the alternative is what shipped:
 * `/api/opportunities/coverage` returned two maps, `counts` (listings) and
 * `faculty_contacts`, and the switcher read `counts` alone. Faculty contacts
 * are ~97% of the corpus, so JHU's chip said 28 where its coverage was 4,581.
 *
 * So: no consumer sees the parts. `resolveCoverage` returns one resolved count
 * or an explicit "unavailable", and the parts are not exported for arithmetic.
 * Adding `faculty_contact_count` to `total_count` is as wrong as omitting it,
 * and a shape nobody can add up twice is the cheapest defence against both.
 *
 * Mirrors backend/lib/school_coverage.py.
 */

/** Mirrors `SCHOOL_COVERAGE_SCHEMA` in backend/lib/school_coverage.py. */
export const SCHOOL_COVERAGE_SCHEMA = 'school-coverage-v2';

export interface SchoolCoverageCounts {
  listing_count: number;
  faculty_contact_count: number;
  /** Records whose source type is unreviewed. NOT part of `total_count`. */
  unreviewed_count: number;
  /** `listing_count + faculty_contact_count`. Render this; add nothing to it. */
  total_count: number;
}

/** Wire shape of `GET /api/opportunities/coverage`. */
export interface SchoolCoverageResponse {
  schema: string;
  /**
   * Keyed by school slug. A school with nothing collected is ABSENT rather than
   * zero — see `resolveCoverage`.
   */
  schools: Record<string, SchoolCoverageCounts>;
}

/** Shape of the committed static fallback, written by scripts/gen_school_stats.py. */
export interface SchoolStatsFile extends SchoolCoverageResponse {
  /** The open pool every school also sees. Never added to a school's total. */
  national_count: number;
}

/**
 * Where a rendered count came from. Surfaced so a caller can tell "we counted
 * 6" from "we have not heard back yet", which the chip needs in order to avoid
 * presenting a stale build-time number as a live one.
 */
export type CoverageSource = 'live' | 'static';

export type ResolvedCoverage =
  | { readonly available: true; readonly count: number; readonly source: CoverageSource }
  /**
   * No trustworthy number exists for this school. Distinct from `count: 0`,
   * which is a verified zero — a school we collected and found nothing for.
   * Callers must render this as a qualitative note, never as "0 opportunities".
   */
  | { readonly available: false; readonly count: null; readonly source: null };

const UNAVAILABLE: ResolvedCoverage = { available: false, count: null, source: null };

/**
 * Narrow an untyped fetch body to a coverage response.
 *
 * The schema check is the cache invalidation. `/api/opportunities/coverage` is
 * a plain GET with no `no-store`, so a browser or intermediary can hold a
 * pre-fix body — `{counts, faculty_contacts}`, listings-only, no `schema` — and
 * an older backend instance can still serve one during a rollout. Either way
 * the numbers under `counts` are the bug. Rejecting anything that does not
 * announce the current schema means a legacy body degrades to the static
 * fallback (same definition, slightly staler) instead of silently understating
 * every school by two orders of magnitude.
 */
export function parseCoverageResponse(body: unknown): SchoolCoverageResponse | null {
  if (!body || typeof body !== 'object') return null;
  const candidate = body as Partial<SchoolCoverageResponse>;
  if (candidate.schema !== SCHOOL_COVERAGE_SCHEMA) return null;
  if (!candidate.schools || typeof candidate.schools !== 'object') return null;
  return { schema: candidate.schema, schools: candidate.schools };
}

/** Whether a value is a usable count for one school. */
function counts(value: SchoolCoverageCounts | undefined): value is SchoolCoverageCounts {
  return typeof value?.total_count === 'number' && Number.isFinite(value.total_count);
}

/**
 * The one place a school's coverage number is decided.
 *
 * Live wins when present, because it is the same definition measured more
 * recently. When it is absent — fetch in flight, fetch failed, legacy payload
 * rejected, or the school genuinely has no records — the static number stands
 * in; both are `listings + faculty contacts`, so a resolution swapping one for
 * the other moves the number by data freshness alone and never by definition.
 * That symmetry is the point: the pre-fix chip jumped 4,581 -> 28 on hydration
 * because the two sides were counting different things.
 */
export function resolveCoverage(
  slug: string,
  live: SchoolCoverageResponse | null,
  staticStats: Record<string, SchoolCoverageCounts | undefined>,
): ResolvedCoverage {
  const liveCounts = live?.schools?.[slug];
  if (counts(liveCounts)) {
    return { available: true, count: liveCounts.total_count, source: 'live' };
  }
  const staticCounts = staticStats?.[slug];
  if (counts(staticCounts)) {
    return { available: true, count: staticCounts.total_count, source: 'static' };
  }
  return UNAVAILABLE;
}

/**
 * Round down for the "N+" chip so the label never overstates.
 *
 * Applied at the render site rather than baked into either data source, so the
 * live number and the static number pass through exactly one identical
 * transform. Flooring only one of them would reintroduce a visible hydration
 * jump (4,500+ -> 4,581+) from nothing but a rounding difference, and the point
 * of this module is that a changing chip means the data changed.
 */
export function displayCoverageCount(count: number): number {
  if (count >= 1000) return Math.floor(count / 100) * 100;
  if (count >= 100) return Math.floor(count / 10) * 10;
  return count;
}
