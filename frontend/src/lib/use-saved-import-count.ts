'use client';

import { useEffect, useState } from 'react';
import type { CustomImport } from './custom-imports';
import { captureOwnerToken, isOwnerTokenValid } from './identity-owner';
import { derivePrivateImportTargetId } from './private-import-adoption';
import { listPrivateImportTargets } from './private-import-target-api';
import type { PrivateImportListView } from './use-private-import-list';

type Result = { status: 'ready' | 'loading' | 'error'; cloudOnly: number };
const loading: Result = { status: 'loading', cloudOnly: 0 };
const failed: Result = { status: 'error', cloudOnly: 0 };
const none: Result = { status: 'ready', cloudOnly: 0 };

/** Count an account copy and the browser record it came from once. Names and
 * source URLs cannot establish identity. Only summaries are read for counting. */
export function useSavedImportCount(list: PrivateImportListView, local: CustomImport[]): Result {
  const { items, cursor, status } = list;
  const [finished, setFinished] = useState<{ items: typeof items; cursor: typeof cursor; local: typeof local; result: Result } | null>(null);
  const needsRead = status === 'ready' && Boolean(cursor || (items.length && local.length));

  useEffect(() => {
    if (!needsRead) return;
    const controller = new AbortController();
    const owner = captureOwnerToken();
    const finish = (result: Result) => {
      if (!controller.signal.aborted && isOwnerTokenValid(owner, owner.uid)) setFinished({ items, cursor, local, result });
    };
    async function count() {
      if (!owner.uid) throw new Error('Missing account identity');
      const uid = owner.uid;
      const ids = new Set(items.map(item => item.id));
      let next = cursor;
      while (next) {
        const page = await listPrivateImportTargets({ owner, cursor: next, limit: 50, signal: controller.signal });
        // A record may move while the reader pages. Present an unavailable
        // total until the reader refreshes, rather than publishing a partial one.
        if (page.items.some(item => ids.has(item.id))) throw new Error('Account list changed during pagination');
        page.items.forEach(item => ids.add(item.id));
        next = page.next_cursor;
      }
      const localKeys = await Promise.all(local.map(entry => derivePrivateImportTargetId(uid, entry.account_copy_key ?? entry.id)));
      localKeys.forEach(id => ids.delete(id));
      finish({ status: 'ready', cloudOnly: ids.size });
    }
    void count().catch(() => finish(failed));
    return () => controller.abort();
  }, [needsRead, items, cursor, local]);
  if (status === 'sign_in_required') return none;
  if (status === 'error') return failed;
  if (status === 'loading') return loading;
  if (!needsRead) return { status: 'ready', cloudOnly: items.length };
  return finished?.items === items && finished.cursor === cursor && finished.local === local ? finished.result : loading;
}
