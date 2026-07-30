import type { MatchViewRequestState } from '@/lib/api';
import type { MatchResult } from '@/lib/types';
import type { Tab } from './types';

/** Fetch only favorites while preserving every active field/search predicate.
 *
 * Walking a broad bucket can require 50+ full-view requests even when the user
 * has only a handful of favorites. The server already applies favorites
 * exactly in the starred tab; bucket intersection remains exact because each
 * returned row carries its canonical bucket.
 */
export function favoriteExportView(
  view: MatchViewRequestState,
): MatchViewRequestState {
  return { ...view, tab: 'starred' };
}

export function favoriteRowsForTab(
  rows: MatchResult[],
  activeTab: Tab,
): MatchResult[] {
  if (
    activeTab === 'high_priority'
    || activeTab === 'good_match'
    || activeTab === 'reach'
  ) {
    return rows.filter((match) => match.bucket === activeTab);
  }
  return rows;
}
