import type { MatchVerdict } from '@/lib/match-feedback';

/**
 * Merge a feedback hydration response without overwriting a verdict that the
 * user changed after the request started. Each opportunity id carries a
 * mutation version; a hydrated verdict is applied only when the version the
 * request was issued against is still current.
 */
export function mergeHydratedFeedback(
  current: ReadonlyMap<string, MatchVerdict>,
  hydrated: ReadonlyMap<string, MatchVerdict>,
  requestedVersions: ReadonlyMap<string, number>,
  currentVersions: ReadonlyMap<string, number>,
): Map<string, MatchVerdict> {
  const next = new Map(current);
  hydrated.forEach((verdict, id) => {
    const requestedVersion = requestedVersions.get(id);
    if (requestedVersion === undefined) return;
    if ((currentVersions.get(id) ?? 0) !== requestedVersion) return;
    next.set(id, verdict);
  });
  return next;
}
