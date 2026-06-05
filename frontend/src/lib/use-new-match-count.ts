'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';

import { getTotalNewMatchCount } from '@/lib/saved-searches';

// App-wide count of unseen saved-search matches, for the header badge. Re-reads
// on route change so the badge clears after the user views the matches (the
// existing /results ack + /favorites optimistic clear zero out new_match_ids).
export function useNewMatchCount(): number {
  const pathname = usePathname();
  const [count, setCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getTotalNewMatchCount()
      .then((n) => { if (!cancelled) setCount(n); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [pathname]);

  return count;
}
