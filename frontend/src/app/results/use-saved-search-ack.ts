'use client';

import { useEffect } from 'react';
import type { ReadonlyURLSearchParams } from 'next/navigation';
import { markSavedSearchSeen } from '@/lib/saved-searches';

// Mount-once ack of the saved-search hand-off. /favorites does an
// onClick optimistic clear for same-device latency; this clears the
// server row so the badge stays gone on the next visit anywhere.
// The empty-deps array is intentional — we ack once per page load,
// not every time searchParams identity changes.
export function useSavedSearchAck(
  searchParams: URLSearchParams | ReadonlyURLSearchParams,
  highlightSet: Set<string>,
): void {
  useEffect(() => {
    const sid = searchParams.get('savedSearchId');
    if (sid && highlightSet.size > 0) {
      markSavedSearchSeen(sid).catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
