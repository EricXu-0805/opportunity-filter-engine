import { getResponsivenessSignals, type ResponsivenessSignal } from './api';

export type { ResponsivenessSignal };

export const RESPONSIVENESS_MIN_CONTACTED = 3;

// N>=3 gate lives on both sides: the backend suppresses tiny-n aggregates and
// the client re-checks so a badge can never render off an under-threshold
// signal even if the payload changes.
export function showsHeardBackBadge(signal: ResponsivenessSignal | null | undefined): boolean {
  return (
    !!signal &&
    signal.contacted_n >= RESPONSIVENESS_MIN_CONTACTED &&
    signal.replied_n >= 1
  );
}

const TTL_MS = 60 * 60 * 1000;
let cache: Promise<Record<string, ResponsivenessSignal>> | null = null;
let cachedAt = 0;

// One shared fetch for every badge on the page (a results page renders dozens
// of MatchCards); errors clear the cache so the next mount can retry.
export function getResponsivenessSignal(
  opportunityId: string,
): Promise<ResponsivenessSignal | null> {
  const now = Date.now();
  if (!cache || now - cachedAt > TTL_MS) {
    cachedAt = now;
    cache = getResponsivenessSignals().catch(() => {
      cache = null;
      return {};
    });
  }
  return cache.then((signals) => signals[opportunityId] ?? null);
}
