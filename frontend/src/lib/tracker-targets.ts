import { getShortlistOpportunities } from './api';
import { PRIVATE_TRACKER_BATCH_LIMIT, resolvePrivateImportTrackerTargets } from './private-import-target-api';
import type { OwnerToken } from './identity-owner';
import type { Opp } from '@/app/favorites/types';

/** Public IDs never include private IDs. An infrastructure error is not a missing record. */
export async function loadTrackerTargets(ids: string[], owner: OwnerToken): Promise<{ opportunities: Opp[]; unavailableIds: string[] }> {
  const origin = { ...owner };
  const privateIds = [...new Set(ids.filter(id => id.startsWith('private-import:')))];
  const publicIds = ids.filter(id => !id.startsWith('private-import:'));
  const publicResult = publicIds.length ? await getShortlistOpportunities(publicIds) : { opportunities: [], unavailableIds: [] };
  const opportunities = [...publicResult.opportunities] as unknown as Opp[];
  const unavailableIds = [...publicResult.unavailableIds];
  // One request per batch, not per target: the per-IP budget is shared with every other route.
  for (let start = 0; start < privateIds.length; start += PRIVATE_TRACKER_BATCH_LIMIT) {
    for (const item of await resolvePrivateImportTrackerTargets(privateIds.slice(start, start + PRIVATE_TRACKER_BATCH_LIMIT), { owner: origin })) {
      if (item.status !== 'resolved') { unavailableIds.push(item.id); continue; }
      const { tracker } = item;
      opportunities.push({ id: tracker.id, title: tracker.title, organization: tracker.organization ?? undefined,
        source_url: tracker.source_url ?? undefined, url: tracker.url ?? undefined });
    }
  }
  return { opportunities, unavailableIds };
}
