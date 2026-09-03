import { describe, expect, it } from 'vitest';
import {
  SCHOOL_COVERAGE_SCHEMA,
  displayCoverageCount,
  parseCoverageResponse,
  resolveCoverage,
  type SchoolCoverageCounts,
} from './school-coverage';

const counts = (
  listing_count: number,
  faculty_contact_count: number,
): SchoolCoverageCounts => ({
  listing_count,
  faculty_contact_count,
  unreviewed_count: 0,
  total_count: listing_count + faculty_contact_count,
});

const live = (schools: Record<string, SchoolCoverageCounts>) => ({
  schema: SCHOOL_COVERAGE_SCHEMA,
  schools,
});

describe('parseCoverageResponse — the cache/rollout gate', () => {
  it('accepts a body that announces the current schema', () => {
    const body = live({ jhu: counts(27, 4554) });
    expect(parseCoverageResponse(body)).toEqual(body);
  });

  it('rejects the pre-fix listings-only body', () => {
    // The exact payload the old backend served, and the exact payload an HTTP
    // cache or a not-yet-rolled instance can still hand a new client. Reading
    // `counts` from it is the original bug; refusing it is the invalidation.
    const legacy = { counts: { jhu: 27 }, faculty_contacts: { jhu: 4554 } };
    expect(parseCoverageResponse(legacy)).toBeNull();
  });

  it('rejects a body with a stale or missing schema stamp', () => {
    expect(parseCoverageResponse({ schools: { jhu: counts(27, 4554) } })).toBeNull();
    expect(
      parseCoverageResponse({ schema: 'school-coverage-v1', schools: {} }),
    ).toBeNull();
  });

  it('rejects junk without throwing', () => {
    for (const body of [null, undefined, 0, 'nope', [], { schema: SCHOOL_COVERAGE_SCHEMA }]) {
      expect(parseCoverageResponse(body)).toBeNull();
    }
  });
});

describe('resolveCoverage — one number, listings + faculty contacts', () => {
  const staticStats = { jhu: counts(27, 4554), ucd: counts(6, 0) };

  it('renders the backend total, not the listing half', () => {
    const resolved = resolveCoverage('jhu', live({ jhu: counts(27, 4554) }), staticStats);
    expect(resolved.available).toBe(true);
    expect(resolved.count).toBe(4581);
    // The bug, named: 27 is what the chip used to show for this school.
    expect(resolved.count).not.toBe(27);
    expect(resolved.source).toBe('live');
  });

  it('does not double-add faculty contacts to an already-combined total', () => {
    const resolved = resolveCoverage('jhu', live({ jhu: counts(27, 4554) }), staticStats);
    expect(resolved.count).toBe(27 + 4554);
    expect(resolved.count).not.toBe(27 + 4554 + 4554);
  });

  it('falls back to the static number when the live fetch has not resolved', () => {
    const resolved = resolveCoverage('jhu', null, staticStats);
    expect(resolved.count).toBe(4581);
    expect(resolved.source).toBe('static');
  });

  it('falls back rather than understating when a legacy body is rejected', () => {
    // parseCoverageResponse returns null for a pre-v2 body, so the component
    // passes null here. The fallback must be the same definition — the whole
    // point of generating it from the backend's own function.
    const rejected = parseCoverageResponse({ counts: { jhu: 27 } });
    const resolved = resolveCoverage('jhu', rejected, staticStats);
    expect(resolved.count).toBe(4581);
  });

  it('live and static agree for the same school and dataset', () => {
    const fromLive = resolveCoverage('jhu', live({ jhu: counts(27, 4554) }), staticStats);
    const fromStatic = resolveCoverage('jhu', null, staticStats);
    expect(fromLive.count).toBe(fromStatic.count);
  });

  it('reports a verified zero half as a real number', () => {
    // UC Davis: listings collected, faculty directory WAF-blocked. 6 is a
    // measurement, and it is coverage.
    expect(resolveCoverage('ucd', null, staticStats).count).toBe(6);
  });

  it('reports an unmeasured school as unavailable, never as zero', () => {
    const resolved = resolveCoverage('nowhere', live({}), staticStats);
    expect(resolved.available).toBe(false);
    expect(resolved.count).toBeNull();
    expect(resolved.source).toBeNull();
    // The distinction that matters: `count` is null, not 0. A 0 would claim we
    // looked at this campus and found nothing.
    expect(resolved.count === 0).toBe(false);
  });

  it('treats a malformed per-school entry as unavailable rather than NaN', () => {
    const broken = { schema: SCHOOL_COVERAGE_SCHEMA, schools: { jhu: {} } } as never;
    expect(resolveCoverage('jhu', parseCoverageResponse(broken), {}).available).toBe(false);
  });
});

describe('displayCoverageCount — one flooring step for both sources', () => {
  it('floors to a friendly "N+" without overstating', () => {
    expect(displayCoverageCount(4581)).toBe(4500);
    expect(displayCoverageCount(272)).toBe(270);
    expect(displayCoverageCount(6)).toBe(6);
  });

  it('never returns more than it was given', () => {
    for (const n of [0, 1, 99, 100, 999, 1000, 4581, 130316]) {
      expect(displayCoverageCount(n)).toBeLessThanOrEqual(n);
    }
  });

  it('renders live and static identically when the data is identical', () => {
    // The hydration jump this replaces was 4,500 -> 28. A rounding difference
    // between the two sources would put a smaller version of it back.
    const raw = 4581;
    expect(displayCoverageCount(raw)).toBe(displayCoverageCount(raw));
  });
});
