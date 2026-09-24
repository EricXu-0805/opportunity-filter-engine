import type { Page, TestInfo } from '@playwright/test';

/** Safe failure evidence: only fixed phase names, timings and known lock counts. */
export async function attachProfileReadDiagnostics(page: Page, info: TestInfo, label: string) {
  if (page.isClosed()) return;
  try {
    const data = await page.evaluate(async () => {
      const marks = performance.getEntriesByType('mark')
        .filter(mark => /^ofe-profile-read:(home|refresh):\d+:[a-z-]+$/.test(mark.name))
        .slice(-64).map(mark => ({ name: mark.name, startTime: mark.startTime }));
      const locks = typeof navigator.locks?.query === 'function' ? await navigator.locks.query() : null;
      const known = ['lock:ofe_auth', 'ofe-profile-local-storage'];
      return { marks, locks: locks ? known.map(name => ({ name,
        held: locks.held?.filter(lock => lock.name === name).length ?? 0,
        pending: locks.pending?.filter(lock => lock.name === name).length ?? 0,
      })) : null };
    });
    await info.attach(`profile-read-${label}`, { body: JSON.stringify(data), contentType: 'application/json' });
  } catch { /* A crashed/closed page cannot supply diagnostics; keep the original failure. */ }
}
