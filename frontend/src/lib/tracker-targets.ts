import { getShortlistOpportunities } from './api';
import { getResolvedPrivateImportTarget, PrivateTargetError } from './private-import-target-api';
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
  let next = 0; let failed = false; let failure: unknown;
  const controller = new AbortController();
  await Promise.all(Array.from({ length: Math.min(4, privateIds.length) }, async () => {
    while (!failed && next < privateIds.length) {
      const id = privateIds[next++];
      try {
        const { tracker } = await getResolvedPrivateImportTarget(id, { owner: origin, signal: controller.signal });
        if (failed) return;
        opportunities.push({ id: tracker.id, title: tracker.title, organization: tracker.organization ?? undefined,
          source_url: tracker.source_url ?? undefined, url: tracker.url ?? undefined });
      } catch (error) {
        if (failed) return;
        if (error instanceof PrivateTargetError && ['not_found', 'deleted'].includes(error.code)) unavailableIds.push(id);
        else { failed = true; failure = error; controller.abort(); }
      }
    }
  }));
  if (failed) throw failure;
  return { opportunities, unavailableIds };
}
