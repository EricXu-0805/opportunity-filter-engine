'use client';

import { useState } from 'react';
import {
  formatCheckedDate,
  useSchoolFreshness,
  type SchoolFreshness,
  type SchoolFreshnessState,
} from '@/lib/school-freshness';
import { bySlug } from '@/lib/schools';

type T = (path: string, vars?: Record<string, string | number>) => string;

const HINT = {
  partly_unchecked: 'schoolFreshness.partlyUnchecked',
  stale: 'schoolFreshness.stale',
} as const;

function checkedDate(entry: SchoolFreshness, locale: string): string | null {
  return entry.lastCheckedAt ? formatCheckedDate(entry.lastCheckedAt, locale) : null;
}

/**
 * Under the school picker: when the selected school's pages were last read
 * successfully, and a one-line hint when that read does not cover the school.
 *
 * Both lines are reserved from the first render, so the answer lands without
 * moving the form below it. A failed read, or a school the ledger does not
 * monitor, leaves them empty.
 */
export function SchoolFreshnessNote({ slug, t, locale, id }: {
  slug: string; t: T; locale: string; id?: string;
}) {
  const freshness = useSchoolFreshness();
  const entry = freshness.status === 'ready' ? freshness.schools.get(slug) : undefined;
  const date = entry ? checkedDate(entry, locale) : null;
  return (
    <div id={id} data-testid="school-freshness" className="mt-2 min-h-[2rem] text-xs leading-4 text-gray-500">
      {entry && (
        <p>{date ? t('schoolFreshness.lastChecked', { date }) : t('schoolFreshness.neverChecked')}</p>
      )}
      {entry && entry.status !== 'current' && (
        <p className={entry.status === 'stale' ? 'text-amber-700' : undefined}>{t(HINT[entry.status])}</p>
      )}
    </div>
  );
}

/** Up to three names, then "N more", joined the way the reader's language joins a list. */
function schoolList(names: string[], locale: string, t: T): string {
  const parts = names.length > 3
    ? [...names.slice(0, 3), t('schoolFreshness.moreSchools', { count: names.length - 3 })]
    : names;
  return new Intl.ListFormat(locale, { style: 'long', type: 'conjunction' }).format(parts);
}

/**
 * On the results page: the home school's line, then the stale schools among
 * the results on screen.
 *
 * "Partly unchecked" is said of the home school only. 87 of the 115 schools
 * carried it in the ledger committed on 2026-10-18, so repeating it for every
 * other school in cross-school results would caveat nearly every card and
 * single out none. Stale was 2 of 115 (Barnard, Swarthmore) and means a
 * school's professors have stopped being observed, which a student should
 * know before writing to one of them.
 *
 * Decided together with the result page it describes. An answer that lands
 * after those results have painted would push every card down, so it waits
 * for the next page of results instead.
 */
export function ResultsSchoolFreshness({ freshness, homeSchool, shownSchools, t, locale }: {
  freshness: SchoolFreshnessState;
  homeSchool: string;
  /** Distinct school slugs of the results on screen; a new array for each new page of results. */
  shownSchools: readonly string[];
  t: T;
  locale: string;
}) {
  const [decided, setDecided] = useState({ shownSchools, freshness });
  if (decided.shownSchools !== shownSchools) setDecided({ shownSchools, freshness });
  const state = decided.shownSchools === shownSchools ? decided.freshness : freshness;
  if (state.status !== 'ready') return null;

  const name = (slug: string) => bySlug(slug)?.shortName ?? slug;
  const home = state.schools.get(homeSchool);
  const date = home ? checkedDate(home, locale) : null;
  const otherStale = shownSchools
    .filter((slug) => slug !== homeSchool && state.schools.get(slug)?.status === 'stale')
    .map(name);
  if (!home && otherStale.length === 0) return null;
  return (
    <div data-testid="results-school-freshness" className="space-y-1 text-[12px] text-gray-600">
      {home && (
        <p>
          {date
            ? t('schoolFreshness.resultsLastChecked', { school: name(homeSchool), date })
            : t('schoolFreshness.resultsNeverChecked', { school: name(homeSchool) })}
          {home.status !== 'current' && (
            <>
              {' '}
              <span className={home.status === 'stale' ? 'text-amber-700' : undefined}>
                {t(HINT[home.status])}
              </span>
            </>
          )}
        </p>
      )}
      {otherStale.length > 0 && (
        <p className="text-amber-700">
          {t(otherStale.length === 1
            ? 'schoolFreshness.resultsOtherStaleOne'
            : 'schoolFreshness.resultsOtherStale', { schools: schoolList(otherStale, locale, t) })}
        </p>
      )}
    </div>
  );
}
