'use client';

import { useEffect, useState } from 'react';
import { getFellowshipOpportunities } from '@/lib/api';
import type { Opportunity } from '@/lib/types';

interface FellowshipsDataState {
  loading: boolean;
  error: string | null;
  opportunities: Opportunity[];
}

const API_PAGE_SIZE = 500;
const MAX_API_PAGES_PER_TYPE = 100;

async function fetchAllByType(
  opportunityType: 'fellowship' | 'summer_program',
): Promise<Opportunity[]> {
  const opportunities: Opportunity[] = [];
  let offset = 0;
  let total = 0;
  let pageCount = 0;

  do {
    const response = await getFellowshipOpportunities({
      opportunity_type: opportunityType,
      limit: API_PAGE_SIZE,
      offset,
    });

    if (!Number.isSafeInteger(response.total) || response.total < 0) {
      throw new Error('Invalid fellowship pagination response');
    }

    const page = response.opportunities ?? [];
    total = response.total;
    opportunities.push(...page);
    offset += page.length;
    pageCount += 1;

    if (page.length === 0 && offset < total) {
      throw new Error('Incomplete fellowship pagination response');
    }
    if (pageCount >= MAX_API_PAGES_PER_TYPE && offset < total) {
      throw new Error('Fellowship pagination exceeded the safety limit');
    }
  } while (offset < total);

  return opportunities;
}

export function useFellowshipsData(): FellowshipsDataState {
  const [state, setState] = useState<FellowshipsDataState>({
    loading: true,
    error: null,
    opportunities: [],
  });

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchAllByType('fellowship'),
      fetchAllByType('summer_program'),
    ])
      .then(([fellowships, summerPrograms]) => {
        if (cancelled) return;
        const byId = new Map<string, Opportunity>();
        for (const opp of [...fellowships, ...summerPrograms]) {
          if (!byId.has(opp.id)) byId.set(opp.id, opp);
        }
        setState({ loading: false, error: null, opportunities: [...byId.values()] });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : 'Failed to load fellowships';
        setState({ loading: false, error: message, opportunities: [] });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
