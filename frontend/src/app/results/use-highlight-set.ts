'use client';

import { useState } from 'react';
import type { ReadonlyURLSearchParams } from 'next/navigation';

// Read ?highlight=a,b,c once at mount. The URL writer in use-results-url
// strips this param on the first filter edit (cross-file contract in
// lib/saved-searches.ts) so re-reading on URL change would race itself —
// the param disappears the moment the user touches any filter and the
// amber ring would vanish mid-interaction.
export function useHighlightSet(
  searchParams: URLSearchParams | ReadonlyURLSearchParams,
): Set<string> {
  const [highlightSet] = useState<Set<string>>(() => {
    const raw = searchParams.get('highlight');
    if (!raw) return new Set();
    return new Set(raw.split(',').filter(Boolean));
  });
  return highlightSet;
}
