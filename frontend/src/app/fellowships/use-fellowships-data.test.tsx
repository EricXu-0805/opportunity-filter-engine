import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Opportunity, OpportunitiesResponse } from '@/lib/types';

vi.mock('@/lib/api', () => ({
  getFellowshipOpportunities: vi.fn(),
}));

import { getFellowshipOpportunities } from '@/lib/api';
import { useFellowshipsData } from './use-fellowships-data';

const getFellowshipsMock = vi.mocked(getFellowshipOpportunities);

function makeOpp(id: string, opportunityType: string): Opportunity {
  return {
    id,
    title: `Program ${id}`,
    organization: 'Example University',
    opportunity_type: opportunityType,
    paid: 'unknown',
    location: 'off_campus',
    on_campus: false,
    description_clean: '',
    keywords: [],
    eligibility: {
      international_friendly: 'unknown',
      preferred_year: [],
      majors: [],
      skills_required: [],
      citizenship_required: false,
    },
    application: {
      application_effort: 'unknown',
      requires_resume: 'unknown',
      contact_method: 'website',
    },
    metadata: { is_active: true, confidence_score: 0.8 },
  };
}

function response(
  opportunities: Opportunity[],
  total = opportunities.length,
): OpportunitiesResponse {
  return { opportunities, total };
}

describe('useFellowshipsData', () => {
  beforeEach(() => {
    getFellowshipsMock.mockReset();
  });

  it('fetches fellowships and summer programs, then de-duplicates by id', async () => {
    const fellowship = makeOpp('fellowship-1', 'fellowship');
    const duplicate = makeOpp('shared-id', 'fellowship');
    const summer = makeOpp('summer-1', 'summer_program');
    getFellowshipsMock
      .mockResolvedValueOnce(response([fellowship, duplicate]))
      .mockResolvedValueOnce(response([makeOpp('shared-id', 'summer_program'), summer]));

    const { result } = renderHook(() => useFellowshipsData());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(getFellowshipsMock).toHaveBeenNthCalledWith(1, {
      opportunity_type: 'fellowship',
      limit: 500,
      offset: 0,
    });
    expect(getFellowshipsMock).toHaveBeenNthCalledWith(2, {
      opportunity_type: 'summer_program',
      limit: 500,
      offset: 0,
    });
    expect(result.current.error).toBeNull();
    expect(result.current.opportunities.map((opp) => opp.id)).toEqual([
      'fellowship-1',
      'shared-id',
      'summer-1',
    ]);
    expect(result.current.opportunities[1].opportunity_type).toBe('fellowship');
  });

  it('loads every page reported by total before exposing the results', async () => {
    const firstPage = Array.from(
      { length: 500 },
      (_, index) => makeOpp(`summer-${index}`, 'summer_program'),
    );
    const finalPage = [makeOpp('summer-500', 'summer_program')];
    getFellowshipsMock.mockImplementation(async (query) => {
      const request = query ?? {};
      if (request.opportunity_type === 'fellowship') return response([]);
      if (request.offset === 0) return response(firstPage, 501);
      if (request.offset === 500) return response(finalPage, 501);
      throw new Error(`unexpected offset ${request.offset}`);
    });

    const { result } = renderHook(() => useFellowshipsData());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(getFellowshipsMock).toHaveBeenCalledWith({
      opportunity_type: 'summer_program',
      limit: 500,
      offset: 500,
    });
    expect(result.current.error).toBeNull();
    expect(result.current.opportunities).toHaveLength(501);
    expect(result.current.opportunities.at(-1)?.id).toBe('summer-500');
  });

  it('fails closed when the API reports more records but returns an empty page', async () => {
    getFellowshipsMock.mockImplementation(async (query) => (
      query?.opportunity_type === 'fellowship'
        ? response([], 1)
        : response([])
    ));

    const { result } = renderHook(() => useFellowshipsData());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe('Incomplete fellowship pagination response');
    expect(result.current.opportunities).toEqual([]);
  });

  it('fails closed when either required source request fails', async () => {
    getFellowshipsMock
      .mockResolvedValueOnce(response([makeOpp('fellowship-1', 'fellowship')]))
      .mockRejectedValueOnce(new Error('summer programs unavailable'));

    const { result } = renderHook(() => useFellowshipsData());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe('summer programs unavailable');
    expect(result.current.opportunities).toEqual([]);
  });
});
