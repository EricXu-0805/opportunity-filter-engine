/*
 * Compare-page re-billing guard: every explain call is a paid LLM completion,
 * and BucketCards used to fire one per card on EVERY visit. These tests pin
 * the sessionStorage cache — a second render with the same profile serves from
 * cache (1 fetch total), a different profile misses, errors are never cached.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';

const mockGetMatchExplanation = vi.fn();

vi.mock('@/lib/api', () => ({
  getMatchExplanation: (...args: unknown[]) => mockGetMatchExplanation(...args),
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({ t: (key: string) => key }),
}));

import BucketCards from './BucketCards';
import type { Opportunity, ProfileData } from '@/lib/types';
import type { CompareBucket, OppScore } from './scores';

const PROFILE: ProfileData = {
  institution: 'UIUC',
  college: 'Grainger',
  major: 'ECE',
  grade: 'Sophomore',
  is_international: true,
  research_interests: 'machine learning',
  skills: [{ name: 'Python', level: 'experienced' }],
};

const EXPLANATION = {
  explanation: 'Great topical fit.',
  method: 'llm' as const,
  final_score: 82,
  bucket: 'high_priority',
  reasons_fit: ['Strong ML background'],
  reasons_gap: [],
  eligibility_score: 90,
  readiness_score: 80,
  upside_score: 70,
};

const SCORE: OppScore = {
  axes: {
    skill_match: 80, eligibility: 80, effort: 80,
    compensation: 80, deadline_runway: 80, intl_friendly: 80,
  },
  overall: 82,
};

const ROWS = [{
  opp: { id: 'opp-1', title: 'ML Lab RA', organization: 'Test U' } as Opportunity,
  score: SCORE,
  bucket: 'top' as CompareBucket,
}];

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.clearAllMocks();
});

describe('BucketCards — explanation cache', () => {
  it('second render with the same profile serves from cache: 1 fetch total', async () => {
    mockGetMatchExplanation.mockResolvedValue(EXPLANATION);

    const first = render(<BucketCards rows={ROWS} profile={PROFILE} />);
    await waitFor(() => {
      expect(screen.getByText('Strong ML background')).toBeInTheDocument();
    });
    expect(mockGetMatchExplanation).toHaveBeenCalledTimes(1);
    first.unmount();

    render(<BucketCards rows={ROWS} profile={PROFILE} />);
    await waitFor(() => {
      expect(screen.getByText('Strong ML background')).toBeInTheDocument();
    });
    expect(mockGetMatchExplanation).toHaveBeenCalledTimes(1);
  });

  it('a changed profile misses the cache and re-fetches', async () => {
    mockGetMatchExplanation.mockResolvedValue(EXPLANATION);

    const first = render(<BucketCards rows={ROWS} profile={PROFILE} />);
    await waitFor(() => {
      expect(mockGetMatchExplanation).toHaveBeenCalledTimes(1);
    });
    first.unmount();

    render(<BucketCards rows={ROWS} profile={{ ...PROFILE, major: 'CS' }} />);
    await waitFor(() => {
      expect(mockGetMatchExplanation).toHaveBeenCalledTimes(2);
    });
  });

  it('failed calls are not cached — a later visit retries', async () => {
    mockGetMatchExplanation
      .mockRejectedValueOnce(new Error('500'))
      .mockResolvedValueOnce(EXPLANATION);

    const first = render(<BucketCards rows={ROWS} profile={PROFILE} />);
    await waitFor(() => {
      expect(screen.getByText('compare.analyzeFailed')).toBeInTheDocument();
    });
    first.unmount();

    render(<BucketCards rows={ROWS} profile={PROFILE} />);
    await waitFor(() => {
      expect(screen.getByText('Strong ML background')).toBeInTheDocument();
    });
    expect(mockGetMatchExplanation).toHaveBeenCalledTimes(2);
  });
});
