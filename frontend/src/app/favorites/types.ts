import type { CustomImport } from '@/lib/custom-imports';
import type { SavedSearch } from '@/lib/saved-searches';
import { humanizeTime } from '@/lib/humanize-time';
import type { FacultyAvailabilityStatus, PublicTargetTruth } from '@/lib/types';

export interface Opp {
  id: string;
  title: string;
  organization?: string;
  department?: string;
  opportunity_type?: string;
  paid?: string;
  location?: string;
  url?: string;
  // The page the collector actually read. A historical record may carry only
  // this, so a card that reads `url` alone can end up keeping the card while
  // losing the one link it is still allowed to offer.
  source_url?: string;
  source?: string;
  source_type?: string;
  // Carried through the saved-view projection: a target can close after it was
  // favorited, and the card gates its actions on this. Absent/null resolves to
  // `unknown`, which suspends them.
  target_truth?: PublicTargetTruth | null;
  faculty_availability_status?: FacultyAvailabilityStatus;
  school?: string;
  on_campus?: boolean | null;
  deadline?: string;
  // NSF-style projected date marker — DeadlineBadge must not assert a
  // confident "passed"/countdown on an estimated date.
  deadline_is_estimate?: boolean | null;
  description_clean?: string;
  description_raw?: string;
  keywords?: string[];
  pi_name?: string;
  lab_or_program?: string;
  eligibility?: {
    international_friendly?: string;
    skills_required?: string[];
    years?: string[];
  };
  _customId?: string;
}

export const MIN_COMPARE = 2;
export const MAX_COMPARE = 3;

export type TFunc = (
  key: string,
  vars?: Record<string, string | number>,
) => string;

export function customImportToOpp(c: CustomImport): Opp {
  const e = c.opportunity;
  const extra = (e.extra_fields ?? {}) as Record<string, unknown>;
  const oppType = typeof extra.opportunity_type === 'string' ? extra.opportunity_type : undefined;
  const paid = typeof extra.paid === 'string' ? extra.paid : undefined;
  const onCampus = typeof extra.on_campus === 'boolean' ? extra.on_campus : undefined;
  const intl = typeof extra.international_friendly === 'string' ? extra.international_friendly : undefined;
  const skills = Array.isArray(extra.skills_required) ? (extra.skills_required as string[]) : undefined;
  return {
    id: c.id,
    _customId: c.id,
    title: e.title || 'Untitled import',
    organization: e.organization || undefined,
    opportunity_type: oppType,
    paid,
    location: e.location || undefined,
    // Kept as two distinct fields rather than collapsed into `url`: every
    // reader goes through opportunitySourceUrl, which prefers source_url, and
    // flattening them here would silently hand it the display link instead.
    url: e.url || undefined,
    source_url: e.source_url || undefined,
    source: undefined,
    on_campus: onCampus,
    deadline: e.deadline || undefined,
    description_raw: e.description_raw || undefined,
    eligibility: skills || intl ? {
      international_friendly: intl,
      skills_required: skills,
    } : undefined,
  };
}

export function summarizeSavedSearchFilters(search: SavedSearch, t: TFunc): string {
  const parts: string[] = [];
  if (search.query) parts.push(`"${search.query}"`);
  if (search.filters.paid === 'yes') parts.push('paid');
  if (search.filters.paid === 'no') parts.push('unpaid');
  if (search.filters.intl === 'yes') parts.push('intl');
  if (search.filters.onCampus === 'yes') parts.push('on-campus');
  if (search.filters.deadline === 'passed') parts.push('past-due');
  else if (search.filters.deadline) parts.push(`≤${search.filters.deadline}d`);
  if (search.filters.minScore > 0) parts.push(`≥${search.filters.minScore}`);
  if (search.filters.source) parts.push(search.filters.source);
  if (search.tab && search.tab !== 'all') parts.push(search.tab);
  if (search.sort_by && search.sort_by !== 'score') parts.push(`by ${search.sort_by}`);
  return parts.length > 0 ? parts.join(' · ') : t('favorites.savedSearches.filtersFallback');
}

export function formatSavedSearchTimestamp(iso: string | null, t: TFunc): string {
  const result = humanizeTime(iso);
  if (!result) return t('favorites.savedSearches.pendingSync');
  let ago: string;
  switch (result.kind) {
    case 'just-now':
      ago = t('favorites.savedSearches.justNow');
      break;
    case 'minutes':
      ago = t('favorites.savedSearches.minutesAgo', { n: result.n });
      break;
    case 'hours':
      ago = t('favorites.savedSearches.hoursAgo', { n: result.n });
      break;
    case 'days':
      ago = t('favorites.savedSearches.daysAgo', { n: result.n });
      break;
    case 'date':
      ago = t('favorites.savedSearches.onDate', { date: result.iso });
      break;
  }
  return t('favorites.savedSearches.checkedAgo', { ago });
}
