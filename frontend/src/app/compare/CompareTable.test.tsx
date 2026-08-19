import { afterEach, describe, it, expect, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import CompareTable from './CompareTable';
import { useHasLocalStorageKey, useLocalStorageJSON } from '@/lib/use-local-storage-json';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { hashProfile } from '@/lib/match-utils';
import type { Opportunity, ProfileData } from '@/lib/types';
import type { CompareRow } from './scores';

const mockGetMatchExplanation = vi.fn();

vi.mock('@/lib/api', () => ({
  getMatchExplanation: (...args: unknown[]) => mockGetMatchExplanation(...args),
}));
vi.mock('@/lib/use-local-storage-json', () => ({
  useHasLocalStorageKey: vi.fn(),
  useLocalStorageJSON: vi.fn(),
}));

// A mutable ref, not a literal `true`/`false`: RELEASE_SCOPE is a frozen,
// source-controlled const in production, but the AI-refine toggle tests
// below need to exercise BOTH the accepted-release and dormant-feature
// paths, matching how use-results-url.test.ts frames its own coverage.
const releaseScopeRef = vi.hoisted(() => ({ matchAiRefine: false }));
vi.mock('@/lib/release-scope', () => ({
  RELEASE_SCOPE: releaseScopeRef,
}));

let lastBucketRows: CompareRow[] | null = null;
vi.mock('./BucketCards', () => ({
  default: ({ rows }: { rows: CompareRow[] }) => {
    lastBucketRows = rows;
    return <div data-testid="bucket-cards" />;
  },
}));
vi.mock('./RadarChart', () => ({
  default: () => <div data-testid="radar-chart" />,
}));

const opps = [
  { id: 'a', title: 'Lab A', organization: 'Org A' },
  { id: 'b', title: 'Lab B', organization: 'Org B' },
] as Opportunity[];

const profile = {
  major: 'CS',
  grade: 'Sophomore',
  is_international: false,
  skills: [{ name: 'Python', level: 'expert' }],
} as ProfileData;

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

function setStorage(
  hasProfile: boolean | undefined,
  value: ProfileData | null,
  semanticExists = false,
  semanticValue: string | null = null,
) {
  vi.mocked(useHasLocalStorageKey).mockImplementation((key) => (
    key === STORAGE_KEYS.PROFILE ? hasProfile : semanticExists
  ));
  vi.mocked(useLocalStorageJSON).mockImplementation((key) => (
    key === STORAGE_KEYS.PROFILE ? value : semanticValue
  ));
}

afterEach(() => {
  cleanup();
  localStorage.clear();
  sessionStorage.clear();
  vi.clearAllMocks();
  lastBucketRows = null;
  releaseScopeRef.matchAiRefine = false;
});

describe('CompareTable', () => {
  it('shows a loading card while storage is hydrating', () => {
    setStorage(undefined, null);
    render(<CompareTable opps={opps} />);
    expect(screen.getByText('Loading your profile…')).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('shows a create-profile CTA plus the profile-independent sections when no profile is stored', () => {
    setStorage(false, null);
    render(<CompareTable opps={opps} />);
    expect(
      screen.getByText('Create a profile to see how these opportunities rank for you.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Create your profile' })).toHaveAttribute('href', '/');
    expect(screen.getByText('Differences')).toBeInTheDocument();
    expect(screen.queryByText('Loading your profile…')).not.toBeInTheDocument();
    expect(screen.queryByTestId('bucket-cards')).not.toBeInTheDocument();
    expect(screen.queryByTestId('radar-chart')).not.toBeInTheDocument();
    expect(mockGetMatchExplanation).not.toHaveBeenCalled();
  });

  it('renders the ranked comparison from canonical matcher scores once every row settles', async () => {
    setStorage(true, profile);
    mockGetMatchExplanation
      .mockResolvedValueOnce({ ...EXPLANATION, final_score: 40, bucket: 'reach' })
      .mockResolvedValueOnce({ ...EXPLANATION, final_score: 90 });

    render(<CompareTable opps={opps} />);
    expect(screen.getByText('Analyzing fit…')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId('bucket-cards')).toBeInTheDocument();
    });
    expect(screen.getByTestId('radar-chart')).toBeInTheDocument();
    expect(mockGetMatchExplanation).toHaveBeenCalledTimes(2);
    expect(mockGetMatchExplanation).toHaveBeenNthCalledWith(
      1,
      profile,
      'a',
      { llm: false },
    );
    // Sorted by canonical final_score: b (90) before a (40).
    expect(lastBucketRows?.map((r) => r.opp.id)).toEqual(['b', 'a']);
    expect(lastBucketRows?.map((r) => r.match?.final_score)).toEqual([90, 40]);
  });

  it('uses AI only after the current-version preference is explicitly enabled AND the release accepts it', async () => {
    releaseScopeRef.matchAiRefine = true;
    setStorage(true, profile, true, '1');
    mockGetMatchExplanation.mockResolvedValue(EXPLANATION);

    render(<CompareTable opps={opps} />);
    await waitFor(() => {
      expect(screen.getByTestId('bucket-cards')).toBeInTheDocument();
    });
    expect(mockGetMatchExplanation).toHaveBeenNthCalledWith(
      1,
      profile,
      'a',
      { llm: true },
    );
  });

  it('a stale enabled preference does NOT force llm:true while AI-refine is outside the accepted release — the flag wins regardless of what is stored', async () => {
    releaseScopeRef.matchAiRefine = false; // dormant, same as the CURRENT real release
    setStorage(true, profile, true, '1');
    mockGetMatchExplanation.mockResolvedValue(EXPLANATION);

    render(<CompareTable opps={opps} />);
    await waitFor(() => {
      expect(screen.getByTestId('bucket-cards')).toBeInTheDocument();
    });
    expect(mockGetMatchExplanation).toHaveBeenNthCalledWith(
      1,
      profile,
      'a',
      { llm: false },
    );
  });

  it('keeps failed rows visible as unavailable instead of substituting a local score', async () => {
    setStorage(true, profile);
    mockGetMatchExplanation
      .mockRejectedValueOnce(new Error('500'))
      .mockResolvedValueOnce(EXPLANATION);

    render(<CompareTable opps={opps} />);
    await waitFor(() => {
      expect(screen.getByTestId('bucket-cards')).toBeInTheDocument();
    });
    const failed = lastBucketRows?.find((r) => r.opp.id === 'a');
    expect(failed?.status).toBe('error');
    expect(failed?.match).toBeNull();
  });

  // Re-billing guard: every explain call is a paid LLM completion. The
  // sessionStorage cache keyed by (opportunity, profile-hash) means a second
  // visit within the hour renders instantly and bills nothing.
  it('second render with the same profile serves from cache: one fetch per opportunity total', async () => {
    setStorage(true, profile);
    mockGetMatchExplanation.mockResolvedValue(EXPLANATION);

    const first = render(<CompareTable opps={opps} />);
    await waitFor(() => {
      expect(screen.getByTestId('bucket-cards')).toBeInTheDocument();
    });
    expect(mockGetMatchExplanation).toHaveBeenCalledTimes(2);
    first.unmount();

    render(<CompareTable opps={opps} />);
    await waitFor(() => {
      expect(screen.getByTestId('bucket-cards')).toBeInTheDocument();
    });
    expect(mockGetMatchExplanation).toHaveBeenCalledTimes(2);
  });

  it('does not serve an unversioned pre-contact-trust explain cache', async () => {
    setStorage(true, profile);
    const oldKey = `ofe_explain_a_${hashProfile(profile)}_ai0`;
    sessionStorage.setItem(
      oldKey,
      JSON.stringify({
        savedAt: Date.now(),
        data: {
          ...EXPLANATION,
          explanation: 'Write jane@example.edu',
          reasons_fit: ['Contact jane@example.edu'],
        },
      }),
    );
    mockGetMatchExplanation.mockResolvedValue(EXPLANATION);

    render(<CompareTable opps={opps} />);
    await waitFor(() => {
      expect(screen.getByTestId('bucket-cards')).toBeInTheDocument();
    });

    expect(mockGetMatchExplanation).toHaveBeenCalledTimes(2);
    expect(lastBucketRows?.find((row) => row.opp.id === 'a')?.match?.explanation)
      .toBe('Great topical fit.');
  });

  it('strands the old ai0 cache that could contain a paid AI explanation', async () => {
    setStorage(true, profile);
    const oldKey = `ofe_explain_contact_trust_v1_a_${hashProfile(profile)}_ai0`;
    sessionStorage.setItem(
      oldKey,
      JSON.stringify({
        savedAt: Date.now(),
        data: {
          ...EXPLANATION,
          method: 'llm',
          explanation: 'Legacy AI text from the deterministic slot.',
        },
      }),
    );
    mockGetMatchExplanation.mockResolvedValue({ ...EXPLANATION, method: 'local' });

    render(<CompareTable opps={opps} />);
    await waitFor(() => {
      expect(screen.getByTestId('bucket-cards')).toBeInTheDocument();
    });

    expect(mockGetMatchExplanation).toHaveBeenCalledTimes(2);
    expect(mockGetMatchExplanation).toHaveBeenCalledWith(profile, 'a', { llm: false });
    expect(lastBucketRows?.find((row) => row.opp.id === 'a')?.match?.method)
      .toBe('local');
  });

  it('failed calls are not cached — a later visit retries', async () => {
    setStorage(true, profile);
    mockGetMatchExplanation
      .mockRejectedValueOnce(new Error('500'))
      .mockRejectedValueOnce(new Error('500'))
      .mockResolvedValue(EXPLANATION);

    const first = render(<CompareTable opps={opps} />);
    await waitFor(() => {
      expect(screen.getByTestId('bucket-cards')).toBeInTheDocument();
    });
    expect(mockGetMatchExplanation).toHaveBeenCalledTimes(2);
    first.unmount();

    render(<CompareTable opps={opps} />);
    await waitFor(() => {
      expect(mockGetMatchExplanation).toHaveBeenCalledTimes(4);
    });
  });
});
