// Page-local types + constants shared across the /results sub-components
// and hooks. Kept in this directory (not src/lib) because the Filters
// shape is intentionally stricter than the SavedSearchFilters in
// lib/saved-searches.ts (source is a union here, plain string there) —
// the saved-searches loader widens at the boundary.

import { Filter, Zap, Target, TrendingUp, Star } from 'lucide-react';
import type { ProfileData } from '@/lib/types';

export type Tab = 'all' | 'high_priority' | 'good_match' | 'reach' | 'starred';

export type SortKey = 'score' | 'deadline' | 'newest';

export interface Filters {
  paid: '' | 'yes' | 'no';
  intl: '' | 'yes' | 'no';
  // Any source key present in the corpus ('' = all). Options are derived from
  // the actual match results (see sourceLabel + the FilterRail sourceOptions
  // prop) so newer sources like 'simplify_internships' aren't silently
  // un-filterable; equality-matched in use-results-filters, so a plain string.
  source: string;
  onCampus: '' | 'yes' | 'no';
  deadline: '' | '7' | '14' | '30' | 'passed';
  minScore: number;
}

export const DEFAULT_FILTERS: Filters = {
  paid: '',
  intl: '',
  source: '',
  onCampus: '',
  deadline: '',
  minScore: 0,
};

export const TABS: {
  key: Tab;
  labelKey: string;
  icon: React.ElementType;
  color: string;
}[] = [
  { key: 'all', labelKey: 'results.tabs.all', icon: Filter, color: 'text-gray-600' },
  { key: 'high_priority', labelKey: 'results.tabs.highPriority', icon: Zap, color: 'text-emerald-600' },
  { key: 'good_match', labelKey: 'results.tabs.goodMatch', icon: Target, color: 'text-blue-600' },
  { key: 'reach', labelKey: 'results.tabs.reach', icon: TrendingUp, color: 'text-amber-600' },
  { key: 'starred', labelKey: 'results.tabs.starred', icon: Star, color: 'text-amber-500' },
];

// Subset of match-utils SEARCH_ALIASES surfaced in the "(also matching: …)"
// hint under the search box. Intentionally narrower than the expansion
// table — only the bigrams we want to advertise to users live here.
export const SEARCH_ALIASES_FOR_HINT: Record<string, string[]> = {
  ml: ['machine learning'],
  ai: ['artificial intelligence'],
  nlp: ['natural language processing'],
  cv: ['computer vision'],
  dl: ['deep learning'],
  rl: ['reinforcement learning'],
  ds: ['data science'],
  se: ['software engineering'],
  db: ['database'],
  hci: ['human computer interaction'],
  cs: ['computer science'],
  ece: ['electrical'],
};

// Older profiles persisted in localStorage stored skills as plain strings
// instead of { name, level }. Reading them through this union lets the
// migrator widen in one place; everywhere downstream sees ProfileData.
export type LegacyProfileShape = Omit<ProfileData, 'skills'> & {
  skills?: ProfileData['skills'] | string[];
};

export function migrateProfile(raw: LegacyProfileShape | null): ProfileData | null {
  if (!raw) return null;
  if (
    Array.isArray(raw.skills)
    && raw.skills.length > 0
    && typeof raw.skills[0] === 'string'
  ) {
    return {
      ...raw,
      skills: (raw.skills as string[]).map((name) => ({
        name,
        level: 'beginner' as const,
      })),
    } as ProfileData;
  }
  return raw as ProfileData;
}

// i18n translator signature used by every leaf in /results. Kept narrow
// (only the shape callers actually use) so the sub-components don't have
// to import the full useT type surface.
export type TFunc = (
  path: string,
  vars?: Record<string, string | number>,
) => string;

// Known source keys map to a translated label; anything else (newer/RSS
// sources) is humanized from the key so it still reads cleanly in the filter.
const SOURCE_LABEL_KEY: Record<string, string> = {
  uiuc_sro: 'results.filters.sourceUiucSro',
  nsf_reu: 'results.filters.sourceNsfReu',
  uiuc_faculty: 'results.filters.sourceUiucFaculty',
  handshake: 'results.filters.sourceHandshake',
  manual: 'results.filters.sourceManual',
  uiuc_our_rss: 'results.filters.sourceOurRss',
  ucb_urap: 'results.filters.sourceUcbUrap',
  ucb_eecs_faculty: 'results.filters.sourceUcbEecsFaculty',
  ucb_stat_faculty: 'results.filters.sourceUcbStatFaculty',
};

export function sourceLabel(source: string, t: TFunc): string {
  const key = SOURCE_LABEL_KEY[source];
  if (key) return t(key);
  return source.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
