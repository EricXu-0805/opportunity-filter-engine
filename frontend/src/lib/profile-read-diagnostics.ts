/** Local, bounded timing marks only. Never record identities, field values,
 * tokens, URLs or errors; no diagnostic data is sent over the network. */
export type ProfileReadStage =
  | 'started' | 'owner-rejected' | 'session-wait' | 'session-resolved' | 'session-ready'
  | 'owner-sync-wait' | 'owner-sync-completed'
  | 'select-started' | 'select-completed' | 'reconcile-wait'
  | 'reconcile-locked' | 'reconciled' | 'ready' | 'failed'
  | 'cancelled' | 'timed-out';
export type ProfileReadObserver = (stage: ProfileReadStage) => void;

const PREFIX = 'ofe-profile-read:';
let sequence = 0;
export function createProfileReadTrace(scope: 'home' | 'refresh'): ProfileReadObserver {
  const attempt = ++sequence;
  return stage => {
    try {
      if (typeof window === 'undefined' || typeof performance.mark !== 'function') return;
      performance.mark(`${PREFIX}${scope}:${attempt}:${stage}`);
      const marks = performance.getEntriesByType('mark').filter(mark => mark.name.startsWith(PREFIX));
      for (const mark of marks.slice(0, -64)) performance.clearMarks(mark.name);
    } catch { /* Diagnostics must never block a profile read. */ }
  };
}
