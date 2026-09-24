'use client';

import { useEffect, useState } from 'react';
import { getStats } from '@/lib/api';

export interface DatabaseStats {
  oppCount: number | null;
  facultyCount: number | null;
  lastUpdated: string | null;
  status: 'loading' | 'ready' | 'error';
}

const EMPTY_COUNTS = { oppCount: null, facultyCount: null, lastUpdated: null };

function measuredCount(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
    ? value : null;
}

/** Public corpus statistics have no dependency on the student's profile. */
export function useDatabaseStats(): DatabaseStats {
  const [stats, setStats] = useState<DatabaseStats>({ ...EMPTY_COUNTS, status: 'loading' });
  useEffect(() => {
    let cancelled = false;
    getStats().then((response) => {
      if (cancelled) return;
      const oppCount = measuredCount(response?.total);
      const facultyCount = measuredCount(response?.faculty_contact_total);
      setStats({
        oppCount,
        facultyCount,
        lastUpdated: typeof response?.last_updated_at === 'string' ? response.last_updated_at : null,
        status: oppCount === null && facultyCount === null ? 'error' : 'ready',
      });
    }).catch(() => {
      if (!cancelled) setStats({ ...EMPTY_COUNTS, status: 'error' });
    });
    return () => { cancelled = true; };
  }, []);
  return stats;
}
