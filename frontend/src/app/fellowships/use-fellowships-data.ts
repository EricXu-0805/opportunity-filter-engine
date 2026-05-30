'use client';

import { useEffect, useState } from 'react';
import { getFellowshipOpportunities } from '@/lib/api';
import type { Opportunity } from '@/lib/types';

interface FellowshipsDataState {
  loading: boolean;
  error: string | null;
  opportunities: Opportunity[];
}

export function useFellowshipsData(): FellowshipsDataState {
  const [state, setState] = useState<FellowshipsDataState>({
    loading: true,
    error: null,
    opportunities: [],
  });

  useEffect(() => {
    let cancelled = false;
    getFellowshipOpportunities({ opportunity_type: 'summer_program' })
      .then((resp) => {
        if (cancelled) return;
        const opps = (resp.opportunities ?? []) as unknown as Opportunity[];
        setState({ loading: false, error: null, opportunities: opps });
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
