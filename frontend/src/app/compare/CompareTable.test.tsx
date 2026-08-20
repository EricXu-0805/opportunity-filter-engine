import { afterEach, describe, it, expect, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
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
vi.mock('./BucketCards', async () => {
  // The reference card is NOT stubbed: its content is the whole assertion on
  // the fail-close path, and a stub would let "shows only title, status and
  // source" pass against an empty div.
  const actual = await vi.importActual<typeof import('./BucketCards')>('./BucketCards');
  return {
    default: ({ rows }: { rows: CompareRow[] }) => {
      lastBucketRows = rows;
      return <div data-testid="bucket-cards" />;
    },
    ReferenceOnlyCard: actual.ReferenceOnlyCard,
  };
});
// Captured, not just rendered: Differences and the radar read the row list
// directly and never look at `status`, so what they are HANDED is the only
// place an excluded row's pay/deadline/eligibility/factors can be caught.
let lastRadarRows: CompareRow[] | null = null;
vi.mock('./RadarChart', () => ({
  default: ({ rows }: { rows: CompareRow[] }) => {
    lastRadarRows = rows;
    return <div data-testid="radar-chart" />;
  },
}));

let lastDifferencesRows: { opp: { id: string } }[] | null = null;
vi.mock('./DifferencesSection', () => ({
  default: ({ rows }: { rows: { opp: { id: string } }[] }) => {
    lastDifferencesRows = rows;
    return <div data-testid="differences-section">Differences</div>;
  },
}));

export const ACTIONABLE_TRUTH = {
  listing_state: 'open',
  reference_only: false,
  actionable: true,
  accepting_state: 'accepting',
  reason_code: null,
  verified_at: null,
  expires_at: null,
} as const;

// Both live: /compare only computes for targets the server still vouches for,
// so the baseline pair has to be that, or every assertion below would be
// measuring the reference-only path.
const LISTING_KIND = { source_type: 'campus_program', record_kind: 'listing' } as const;
const opps = [
  { id: 'a', title: 'Lab A', organization: 'Org A', ...LISTING_KIND, target_truth: { ...ACTIONABLE_TRUTH } },
  { id: 'b', title: 'Lab B', organization: 'Org B', ...LISTING_KIND, target_truth: { ...ACTIONABLE_TRUTH } },
] as unknown as Opportunity[];

const profile = {
  major: 'CS',
  grade: 'Sophomore',
  is_international: false,
  skills: [{ name: 'Python', level: 'expert' }],
} as ProfileData;

// The real response shape. The echoed id, `in_results` and `matcher_version`
// are not optional extras: a verdict that does not name its target, does not
// say whether the target is in these results, or does not name the generation
// that produced it, is one this surface refuses. The fixture carries them so
// the positive tests exercise the contract rather than a lenient subset.
const MATCHER_VERSION = 'test-matcher-v1';
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
  in_results: true,
  matcher_version: MATCHER_VERSION,
};

/** The response for one requested id, echoing it as the server does. */
function explanationFor(id: string, overrides: Record<string, unknown> = {}) {
  return { ...EXPLANATION, opportunity_id: id, ...overrides };
}

/**
 * Answer every request the way the backend does — echoing the id it was
 * asked about.
 *
 * A single shared response object cannot be used any more, and that is the
 * point: with the echo checked exactly, one fixture reused for two ids is
 * itself a mismatch. Tests that want a mismatch now have to construct one
 * deliberately.
 */
function answerCanonically(overrides: Record<string, unknown> = {}) {
  mockGetMatchExplanation.mockImplementation(
    async (_p: unknown, id: string) => explanationFor(id, overrides),
  );
}

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
  // Backstop for the storage spies below: an assertion that throws skips the
  // explicit restore, and a leaked spy silently rewrites the next test's
  // storage. Runs before clear so the spy is gone either way.
  vi.restoreAllMocks();
  vi.clearAllMocks();
  lastBucketRows = null;
  lastRadarRows = null;
  lastDifferencesRows = null;
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
    // Keyed by id, not by call order: with the echoed id checked exactly, a
    // response must name the target it describes.
    mockGetMatchExplanation.mockImplementation(async (_p: unknown, id: string) => (
      id === 'a'
        ? explanationFor(id, { final_score: 40, bucket: 'reach' })
        : explanationFor(id, { final_score: 90 })
    ));

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
    answerCanonically();

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
    answerCanonically();

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
    const alreadyFailed = new Set<string>();
    mockGetMatchExplanation.mockImplementation(async (_p: unknown, id: string) => {
      if (!alreadyFailed.size) { alreadyFailed.add(id); throw new Error('500'); }
      return explanationFor(id);
    });

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
    answerCanonically();

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
    answerCanonically();

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
    answerCanonically({ method: 'local' });

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
    let failNext = 2;
    mockGetMatchExplanation.mockImplementation(async (_p: unknown, id: string) => {
      if (failNext > 0) { failNext -= 1; throw new Error('500'); }
      return explanationFor(id);
    });

    const first = render(<CompareTable opps={opps} />);
    await waitFor(() => {
      expect(screen.getByTestId('bucket-cards')).toBeInTheDocument();
    });
    expect(mockGetMatchExplanation).toHaveBeenCalledTimes(2);
    // Both failed, and neither was cached — that is what makes the retry below
    // a retry rather than a cache miss.
    expect(lastBucketRows?.every((row) => row.status === 'error')).toBe(true);
    expect(cacheKeys().length).toBe(0);
    first.unmount();

    render(<CompareTable opps={opps} />);
    await waitFor(() => {
      expect(mockGetMatchExplanation).toHaveBeenCalledTimes(4);
    });
    // The second visit actually succeeds. Counting calls alone would pass even
    // if every retry failed too, which is the state this test exists to rule
    // out — a failed row must be recoverable, not permanently unavailable.
    await waitFor(() => {
      expect(lastBucketRows?.every((row) => row.status === 'ready')).toBe(true);
    });
    expect(lastBucketRows?.every((row) => row.match?.final_score === 82)).toBe(true);
  });
});

/**
 * Session cache keys, enumerated through the Storage API.
 *
 * `Object.keys(sessionStorage)` returns [] in jsdom whatever is stored, so a
 * test written that way reports "nothing was cached" for every case and its
 * negative assertions are vacuous.
 */
function cacheKeys(): string[] {
  return Array.from(
    { length: sessionStorage.length },
    (_, i) => sessionStorage.key(i) ?? '',
  );
}

describe('a 200 is not automatically a verdict', () => {
  // The response carries three things beyond the score: which id it is about,
  // whether the server counts it as a match, and which matcher produced it.
  // Reading only the score turns "not in your results" into a ranked card and
  // an echoed wrong id into a permanent, cached mislabelling.
  const excludedFor = (id: string) => explanationFor(id, {
    in_results: false,
    excluded_reason: 'cross_school_hidden',
  });

  it('keeps an excluded 200 out of the comparison entirely', async () => {
    setStorage(true, profile);
    mockGetMatchExplanation.mockImplementation(
      async (_p: unknown, id: string) => (
        id === 'b' ? excludedFor(id) : explanationFor(id)
      ),
    );

    render(<CompareTable opps={opps} />);
    await waitFor(() => {
      expect(screen.getByTestId('compare-reference-card')).toBeInTheDocument();
    });

    // One usable target is not a comparison, so nothing is compared — not
    // Bucket cards, not Differences, not the radar.
    expect(screen.getByText(
      'Fewer than 2 of these are confirmed as targets you can act on, so there is nothing to compare. The rest are listed below for reference.',
    )).toBeInTheDocument();
    expect(screen.queryByTestId('bucket-cards')).not.toBeInTheDocument();
    expect(screen.queryByTestId('radar-chart')).not.toBeInTheDocument();
    expect(screen.queryByText('Differences')).not.toBeInTheDocument();
    expect(lastBucketRows).toBeNull();

    // Its own reason, not a borrowed one: it is not closed, it is elsewhere.
    const card = screen.getByTestId('compare-reference-card');
    expect(card).toHaveTextContent('Not in your current results');
    expect(card).not.toHaveTextContent('Closed —');
    expect(card).not.toHaveTextContent('82%');

    // Nothing about the excluded one is written to the session cache: the next
    // visit must ask again rather than repeat a verdict it never displayed.
    // Waited on, because the two requests settle independently — the live
    // one's write can land after the excluded one has already rendered, and
    // asserting immediately would test the race rather than the rule.
    await waitFor(() => {
      expect(cacheKeys().some((key) => key.includes('_a_'))).toBe(true);
    });
    expect(cacheKeys().some((key) => key.includes('_b_'))).toBe(false);
    // Still exactly one call per id.
    expect(mockGetMatchExplanation).toHaveBeenCalledTimes(2);
  });

  it('compares the usable ones and sidelines only the excluded one', async () => {
    // Three live targets, one of which the server scores as outside these
    // results. The other two still compare — the exclusion is per row.
    const three = [
      ...opps,
      {
        id: 'c', title: 'Lab C', organization: 'Org C',
        ...LISTING_KIND, target_truth: { ...ACTIONABLE_TRUTH },
      },
    ] as unknown as Opportunity[];
    setStorage(true, profile);
    mockGetMatchExplanation.mockImplementation(
      async (_p: unknown, id: string) => (
        id === 'c' ? excludedFor(id) : explanationFor(id)
      ),
    );

    render(<CompareTable opps={three} />);
    await waitFor(() => expect(screen.getByTestId('bucket-cards')).toBeInTheDocument());

    // Bucket, Differences and the radar all see the same two rows.
    expect(lastBucketRows?.map((row) => row.opp.id).sort()).toEqual(['a', 'b']);
    expect(lastBucketRows?.some((row) => row.status === 'excluded')).toBe(false);
    expect(lastDifferencesRows?.map((row) => row.opp.id).sort()).toEqual(['a', 'b']);
    expect(lastRadarRows?.map((row) => row.opp.id).sort()).toEqual(['a', 'b']);
    // And the excluded one is readable, on its own terms.
    expect(screen.getByTestId('compare-reference-card')).toHaveTextContent(
      'Not in your current results',
    );
  });

  it('says both things the reference section can mean', async () => {
    // The umbrella copy covers two populations at once: not-confirmed-
    // actionable, and live-but-not-in-this-match. Claiming either one for
    // both would be false for half the cards under it.
    const { dictionaries } = await import('@/i18n/dictionaries');
    for (const locale of ['en', 'zh'] as const) {
      const body = dictionaries[locale].compare.referenceOnlyBody;
      expect(body).not.toMatch(/no longer open|已经不再开放/);
      expect(body).not.toMatch(/source reported|来源页的说法/);
    }
    expect(dictionaries.en.compare.referenceOnlyBody).toMatch(/not part of this match/);
    expect(dictionaries.zh.compare.referenceOnlyBody).toMatch(/不属于本次匹配结果/);
  });

  it('discards a response echoing a different id', async () => {
    setStorage(true, profile);
    mockGetMatchExplanation.mockImplementation(async (_p: unknown, id: string) => (
      id === 'b'
        ? explanationFor('some-other-target')
        : explanationFor(id)
    ));

    render(<CompareTable opps={opps} />);
    await waitFor(() => expect(screen.getByTestId('bucket-cards')).toBeInTheDocument());

    // Whatever that response describes, it is not this card.
    expect(lastBucketRows?.find((row) => row.opp.id === 'b')?.status).toBe('error');
    expect(lastBucketRows?.find((row) => row.opp.id === 'b')?.match).toBeNull();
    // The other row is a canonical ready control: a change that rejected every
    // response would fail here rather than pass this test for free.
    expect(lastBucketRows?.find((row) => row.opp.id === 'a')?.status).toBe('ready');
    expect(lastBucketRows?.find((row) => row.opp.id === 'a')?.match?.final_score).toBe(82);
    expect(cacheKeys().some((key) => key.includes('_b_'))).toBe(false);
    expect(mockGetMatchExplanation).toHaveBeenCalledTimes(2);
  });

  // Only the two cases that stand on their own. "Stale" needs a reference
  // generation to be stale RELATIVE TO, and this surface has none unless a
  // match cache was written — without one, `v-old` is simply an unfamiliar
  // version, which is not the same claim. Cross-generation disagreement is
  // covered where it can be stated honestly: between the rows themselves.
  it.each([
    ['a missing matcher_version', undefined],
    ['an empty matcher_version', ''],
  ])('will not take an exclusion from %s', async (_label, version) => {
    // "Not in your results" is a verdict about a universe some particular
    // matcher computed. Taken from an unnamed or superseded generation, it
    // sidelines a target on the say-so of a scorer that is not the one
    // ranking anything — so it fails closed as unavailable, not as excluded.
    setStorage(true, profile);
    mockGetMatchExplanation.mockImplementation(async (_p: unknown, id: string) => {
      if (id !== 'b') return explanationFor(id, { matcher_version: 'v-current' });
      const resp = explanationFor(id, { in_results: false }) as Record<string, unknown>;
      if (version === undefined) delete resp.matcher_version;
      else resp.matcher_version = version;
      return resp;
    });

    render(<CompareTable opps={opps} />);
    await waitFor(() => expect(screen.getByTestId('bucket-cards')).toBeInTheDocument());

    const row = lastBucketRows?.find((r) => r.opp.id === 'b');
    expect(row?.status).toBe('error');
    expect(row?.match).toBeNull();
    // Not sidelined as "not in your results" — we do not know that.
    expect(screen.queryByTestId('compare-reference-card')).not.toBeInTheDocument();
    // The other row is a canonical ready control, so a mutant that rejected
    // everything could not pass this.
    expect(lastBucketRows?.find((r) => r.opp.id === 'a')?.status).toBe('ready');
  });

  it('accepts a matching echoed id', async () => {
    setStorage(true, profile);
    answerCanonically();

    render(<CompareTable opps={opps} />);
    await waitFor(() => expect(screen.getByTestId('bucket-cards')).toBeInTheDocument());

    expect(lastBucketRows?.every((row) => row.status === 'ready')).toBe(true);
  });
});

describe('a poisoned cache entry must not strand the session', () => {
  // The cache TTL is an hour. An entry the validator rejects used to become a
  // permanent "Unavailable" for that hour — the row failed, and nothing ever
  // asked again. Rejecting it has to mean dropping it and fetching, not
  // remembering the rejection.
  function seed(id: string, data: Record<string, unknown>) {
    sessionStorage.setItem(
      `ofe_explain_target_truth_v3_${id}_${hashProfile(profile)}_ai0`,
      JSON.stringify({ savedAt: Date.now(), data }),
    );
  }

  const POISONED: [string, Record<string, unknown>][] = [
    ['a wrong echoed id', explanationFor('some-other-target')],
    ['a missing echoed id', { ...EXPLANATION }],
    ['a missing in_results', (() => {
      const r = explanationFor('b') as Record<string, unknown>;
      delete r.in_results;
      return r;
    })()],
    ['an explicit in_results:false', explanationFor('b', { in_results: false })],
    ['a missing matcher_version', (() => {
      const r = explanationFor('b') as Record<string, unknown>;
      delete r.matcher_version;
      return r;
    })()],
    ['an empty matcher_version', explanationFor('b', { matcher_version: '' })],
  ];

  it.each(POISONED)('re-fetches past %s and renders the live answer', async (_label, data) => {
    setStorage(true, profile);
    seed('b', data);
    answerCanonically({ final_score: 77 });

    render(<CompareTable opps={opps} />);
    await waitFor(() => expect(screen.getByTestId('bucket-cards')).toBeInTheDocument());

    // The poisoned row asked the server, and shows the answer it got.
    expect(mockGetMatchExplanation).toHaveBeenCalledWith(profile, 'b', { llm: false });
    const row = lastBucketRows?.find((r) => r.opp.id === 'b');
    expect(row?.status).toBe('ready');
    expect(row?.match?.final_score).toBe(77);
    // And the bad entry is gone rather than left to be re-read next render.
    expect(cacheKeys().filter((key) => key.includes('_b_')).length).toBe(1);
  });

  it('serves a complete cached verdict without asking again', async () => {
    // The control: a legitimate entry still costs zero requests. Without this,
    // "always re-fetches" would pass every test above.
    setStorage(true, profile);
    seed('a', explanationFor('a', { final_score: 63 }));
    seed('b', explanationFor('b', { final_score: 63 }));
    answerCanonically();

    render(<CompareTable opps={opps} />);
    await waitFor(() => expect(screen.getByTestId('bucket-cards')).toBeInTheDocument());

    expect(mockGetMatchExplanation).not.toHaveBeenCalled();
    expect(lastBucketRows?.every((r) => r.match?.final_score === 63)).toBe(true);
  });

  it('discards a cache split across two matcher generations and converges', async () => {
    // Both entries are individually valid; together they are two scoring
    // functions in one table. With no page-level version to arbitrate, the
    // only way out is to drop both and ask — otherwise the student sits
    // behind a cache that can never agree with itself.
    setStorage(true, profile);
    seed('a', explanationFor('a', { matcher_version: 'v1', final_score: 30 }));
    seed('b', explanationFor('b', { matcher_version: 'v2', final_score: 90 }));
    answerCanonically({ matcher_version: 'v3', final_score: 50 });

    render(<CompareTable opps={opps} />);
    await waitFor(() => expect(screen.getByTestId('bucket-cards')).toBeInTheDocument());

    // Both re-asked, both answered by the same current generation.
    expect(mockGetMatchExplanation).toHaveBeenCalledWith(profile, 'a', { llm: false });
    expect(mockGetMatchExplanation).toHaveBeenCalledWith(profile, 'b', { llm: false });
    expect(lastBucketRows?.every((r) => r.status === 'ready')).toBe(true);
    expect(lastBucketRows?.every((r) => r.match?.matcher_version === 'v3')).toBe(true);
    // Neither of the mixed generations survives in storage.
    expect(lastBucketRows?.some((r) => r.match?.final_score === 30)).toBe(false);
    expect(lastBucketRows?.some((r) => r.match?.final_score === 90)).toBe(false);
  });

  it('refuses to rank two live answers from different generations', async () => {
    // The same rule on the live path, where there is no cache to clear: the
    // table is withheld rather than mixed.
    setStorage(true, profile);
    mockGetMatchExplanation.mockImplementation(async (_p: unknown, id: string) => (
      explanationFor(id, { matcher_version: id === 'a' ? 'v1' : 'v2' })
    ));

    render(<CompareTable opps={opps} />);
    await waitFor(() => expect(screen.getByTestId('bucket-cards')).toBeInTheDocument());

    expect(lastBucketRows?.every((r) => r.status === 'error')).toBe(true);
    expect(lastBucketRows?.every((r) => r.match === null)).toBe(true);
  });
});

describe('a verdict belongs to one request, not to an id', () => {
  const OTHER_PROFILE = { ...profile, major: 'Physics' } as ProfileData;

  it('clears the previous profile\'s scores instead of showing them', async () => {
    setStorage(true, profile);
    answerCanonically();
    const view = render(<CompareTable opps={opps} />);
    await waitFor(() => expect(screen.getByTestId('bucket-cards')).toBeInTheDocument());
    expect(lastBucketRows?.[0]?.match?.final_score).toBe(82);

    // The profile changes and the new answers have not arrived yet.
    const nextPending: { id: string; resolve: (value: unknown) => void }[] = [];
    mockGetMatchExplanation.mockImplementation(
      (_p: unknown, id: string) => new Promise((resolve) => {
        nextPending.push({ id, resolve });
      }),
    );
    setStorage(true, OTHER_PROFILE);
    view.rerender(<CompareTable opps={opps} />);

    // Analysing, not the old profile's numbers under the new profile.
    await waitFor(() => {
      expect(screen.getByText('Analyzing fit…')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('bucket-cards')).not.toBeInTheDocument();

    await waitFor(() => expect(nextPending).toHaveLength(2));
    await act(async () => {
      const first = nextPending[0];
      first.resolve(explanationFor(first.id, { final_score: 41 }));
      await Promise.resolve();
    });
    // One new answer cannot combine with the other id's old-profile score.
    expect(screen.getByText('Analyzing fit…')).toBeInTheDocument();
    expect(screen.queryByTestId('bucket-cards')).not.toBeInTheDocument();

    await act(async () => {
      const second = nextPending[1];
      second.resolve(explanationFor(second.id, { final_score: 41 }));
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.getByTestId('bucket-cards')).toBeInTheDocument());
    expect(lastBucketRows?.every((row) => row.match?.final_score === 41)).toBe(true);
  });

  it('ignores a late response from the superseded request', async () => {
    setStorage(true, profile);
    // P1's calls never settle until we say so. The id is captured with each
    // resolver so the late answer is fully canonical when it lands: a response
    // missing its echo would be rejected by the id check, and the test would
    // pass without ever exercising the identity guard it is named for.
    const pending: { id: string; resolve: (value: unknown) => void }[] = [];
    mockGetMatchExplanation.mockImplementation(
      (_p: unknown, id: string) => new Promise((resolve) => { pending.push({ id, resolve }); }),
    );
    const view = render(<CompareTable opps={opps} />);
    await waitFor(() => expect(mockGetMatchExplanation).toHaveBeenCalledTimes(2));

    // Switch to P2, whose answers arrive first.
    answerCanonically({ final_score: 55 });
    setStorage(true, OTHER_PROFILE);
    view.rerender(<CompareTable opps={opps} />);
    await waitFor(() => expect(screen.getByTestId('bucket-cards')).toBeInTheDocument());
    expect(lastBucketRows?.every((row) => row.match?.final_score === 55)).toBe(true);

    // Now P1's stale answers land — each one perfectly valid on its own
    // terms. They must not overwrite P2's.
    await act(async () => {
      pending.forEach(({ id, resolve }) => resolve(explanationFor(id, { final_score: 82 })));
      await Promise.resolve();
    });
    expect(screen.getByTestId('bucket-cards')).toBeInTheDocument();
    expect(screen.queryByText('Analyzing fit…')).not.toBeInTheDocument();
    expect(lastBucketRows?.every((row) => row.match?.final_score === 55)).toBe(true);
  });

  it('re-asks when the AI mode changes rather than reusing the id\'s verdict', async () => {
    releaseScopeRef.matchAiRefine = true;
    setStorage(true, profile, true, '0');
    answerCanonically({ method: 'local' });
    const view = render(<CompareTable opps={opps} />);
    await waitFor(() => expect(screen.getByTestId('bucket-cards')).toBeInTheDocument());
    expect(mockGetMatchExplanation).toHaveBeenCalledWith(profile, 'a', { llm: false });

    answerCanonically({ method: 'llm' });
    setStorage(true, profile, true, '1');
    view.rerender(<CompareTable opps={opps} />);

    await waitFor(() => {
      expect(mockGetMatchExplanation).toHaveBeenCalledWith(profile, 'a', { llm: true });
    });
  });
});

/**
 * Record every storage key the component reads, keeping real behaviour.
 *
 * "The explain API was not called" is not enough on its own: a cached verdict
 * would render a score without any call at all. The stronger claim is that the
 * dead id is never even looked up.
 */
function spyOnStorageReads(reads: string[]) {
  // The instance, not Storage.prototype: in jsdom the explain cache's
  // `sessionStorage.getItem` does not resolve through the prototype, so a
  // prototype spy records nothing and every assertion built on it is vacuous.
  const original = window.sessionStorage.getItem.bind(window.sessionStorage);
  const spy = vi.spyOn(window.sessionStorage, 'getItem');
  spy.mockImplementation((key: string) => {
    reads.push(key);
    return original(key);
  });
  return spy;
}

describe('/compare is reachable by URL, so it fails closed on its own', () => {
  // The selection guard lives on /favorites. ?ids= is typed, bookmarked and
  // pasted into chats, so nothing about arriving here implies a live target
  // was ever ticked. Everything this page does to a row — a paid explain call,
  // a score, a bucket, a radar spoke, an Apply link — is a claim about an
  // option the student can still take.
  // Every opening-shaped field populated, and all of it poison: a card that
  // leaked any one of these would be describing terms of an offer that is not
  // on the table.
  function dead(id: string, truth: unknown): Opportunity {
    // The kind follows the reason. `faculty_not_accepting` is a statement a
    // faculty profile makes about a person; it cannot arrive on a listing, so
    // a fixture that put it there would be testing an impossible record.
    // Everything else here is a listing that went dead.
    const reason = (truth as { reason_code?: string } | null | undefined)?.reason_code;
    const kind = reason === 'faculty_not_accepting'
      ? { source_type: 'faculty_research', record_kind: 'faculty_contact' }
      : { source_type: 'campus_program', record_kind: 'listing' };
    const opp = {
      id, title: `Dead ${id}`, organization: 'Org D',
      ...kind,
      source_url: 'https://example.edu/source-page',
      url: 'https://example.edu/display-page',
      application: { application_url: 'https://example.edu/apply-here' },
      deadline: '2099-12-31',
      paid: 'yes',
      compensation_details: 'POISON $30/hr stipend',
      on_campus: true,
      opportunity_type: 'research',
      description_clean: 'POISON we are recruiting two students now',
      eligibility: { international_friendly: 'yes' },
      target_truth: truth,
    } as unknown as Opportunity;
    if (truth === undefined) {
      delete (opp as unknown as Record<string, unknown>).target_truth;
    }
    return opp;
  }

  const BAD_TRUTHS: [string, unknown, string][] = [
    ['closed', {
      ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'closed',
      accepting_state: 'not_accepting', reason_code: 'listing_closed',
      reference_only: true,
    }, 'Closed — no longer accepting applications'],
    ['reference-only', {
      ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'unknown',
      accepting_state: 'unknown', reason_code: 'reference_only',
      reference_only: true,
    }, 'Reference record — not an open listing'],
    ['inactive', {
      ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'unknown',
      accepting_state: 'unknown', reason_code: 'inactive',
    }, 'Inactive — no longer carried in the catalog'],
    ['faculty-stop', {
      ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'unknown',
      accepting_state: 'not_accepting', reason_code: 'faculty_not_accepting',
    }, 'Source profile states this faculty member is not currently accepting undergraduate students'],
    ['missing', undefined, 'Status unconfirmed — check the source'],
    ['null', null, 'Status unconfirmed — check the source'],
    ['malformed', { listing_state: 'open' }, 'Status unconfirmed — check the source'],
    [
      'self-contradicting',
      { ...ACTIONABLE_TRUTH, listing_state: 'closed' },
      'Status unconfirmed — check the source',
    ],
  ];

  it.each(BAD_TRUTHS)(
    'never scores or requests an explain for a %s target reached by URL',
    async (_label, truth, statusText) => {
      setStorage(true, profile);
      answerCanonically();
      // Watch the cache at the boundary: "no explain call" alone would still
      // pass if the row were served from a cached score instead.
      const reads: string[] = [];
      const getItem = spyOnStorageReads(reads);

      render(<CompareTable opps={[opps[0], dead('dead-1', truth)]} />);

      // Wait for the LIVE half's call, not just for the card to paint. The
      // effect body is async, so asserting on first paint would check the
      // storage log before a single read had happened — and every "never
      // read" assertion below would pass vacuously.
      await waitFor(() => expect(mockGetMatchExplanation).toHaveBeenCalled());
      expect(screen.getByTestId('compare-reference-card')).toBeInTheDocument();
      // One live target left, so there is no comparison — and we say so
      // rather than rendering a one-card "comparison".
      expect(screen.queryByTestId('bucket-cards')).not.toBeInTheDocument();
      expect(screen.queryByTestId('radar-chart')).not.toBeInTheDocument();
      expect(screen.queryByText('Differences')).not.toBeInTheDocument();
      // The paid call is never made for the dead one. It may be made for the
      // live one; what must never happen is spending on the dead id.
      const askedFor = mockGetMatchExplanation.mock.calls.map((call) => call[1]);
      expect(askedFor).not.toContain('dead-1');
      // Nor is any cached verdict for it ever looked up, under any prefix.
      expect(reads.filter((key) => key.includes('dead-1'))).toEqual([]);
      // Its own reason, in its own words — never collapsed into one label.
      expect(screen.getByTestId('compare-reference-card')).toHaveTextContent(statusText);
      // None of the poisoned opening facts reach the DOM.
      for (const poison of ['2099-12-31', 'POISON $30/hr stipend', 'POISON we are recruiting']) {
        expect(document.body).not.toHaveTextContent(poison);
      }
      getItem.mockRestore();
    },
  );

  it('reads a cached verdict only for the comparable half', async () => {
    // The positive control for the assertion above: the live id IS looked up,
    // so "no read for the dead one" reflects the gate rather than a caching
    // path that never runs at all.
    setStorage(true, profile);
    answerCanonically();
    const reads: string[] = [];
    const getItem = spyOnStorageReads(reads);

    render(<CompareTable opps={[opps[0], dead('dead-1', BAD_TRUTHS[0][1])]} />);
    await waitFor(() => expect(mockGetMatchExplanation).toHaveBeenCalled());

    expect(reads.some((key) => key.startsWith('ofe_explain_target_truth_v3_a_'))).toBe(true);
    expect(reads.filter((key) => key.includes('dead-1'))).toEqual([]);
    getItem.mockRestore();
  });

  it('shows only title, precise status and the SOURCE link on a dead target', async () => {
    setStorage(true, profile);
    answerCanonically();

    render(<CompareTable opps={[opps[0], dead('dead-1', BAD_TRUTHS[0][1])]} />);
    await waitFor(() => {
      expect(screen.getByTestId('compare-reference-card')).toBeInTheDocument();
    });
    const card = screen.getByTestId('compare-reference-card');

    expect(card).toHaveTextContent('Dead dead-1');
    expect(card).toHaveTextContent('Closed — no longer accepting applications');
    // source_url wins over url, and the application URL is never offered —
    // not even relabelled as "view source".
    const links = Array.from(card.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(links).toContain('https://example.edu/source-page');
    expect(links).not.toContain('https://example.edu/apply-here');
    expect(links).not.toContain('https://example.edu/display-page');
    // No opening facts of any kind.
    expect(card).not.toHaveTextContent('2099-12-31');
    expect(card).not.toHaveTextContent('82%');
    expect(card).not.toHaveTextContent('Great topical fit.');
    expect(card).not.toHaveTextContent('Apply');
  });

  it('keeps the same posture when there is no profile at all', () => {
    // No profile means no explain calls anyway, so the temptation is to skip
    // the check on this branch — and then the dead row still reaches
    // Differences, which is precisely a table of pay, eligibility and deadline
    // presented as things to weigh against each other.
    setStorage(false, null);

    render(<CompareTable opps={[opps[0], dead('dead-1', BAD_TRUTHS[0][1])]} />);

    expect(screen.getByTestId('compare-reference-card')).toBeInTheDocument();
    expect(screen.queryByTestId('bucket-cards')).not.toBeInTheDocument();
    expect(screen.queryByTestId('radar-chart')).not.toBeInTheDocument();
    expect(mockGetMatchExplanation).not.toHaveBeenCalled();
    // Differences renders on this branch — with the live half only. Its
    // section heading is present; the dead row's facts are not.
    expect(screen.getByText('Differences')).toBeInTheDocument();
    for (const poison of [
      '2099-12-31', 'POISON $30/hr stipend', 'POISON we are recruiting', 'Dead dead-1',
    ]) {
      if (poison === 'Dead dead-1') continue;  // the title IS allowed, on the reference card
      expect(document.body).not.toHaveTextContent(poison);
    }
    // And the reference card carries the title, so "not in the DOM" above is
    // about the facts, not about the row having vanished.
    expect(screen.getByTestId('compare-reference-card')).toHaveTextContent('Dead dead-1');
  });

  const OLD_PREFIX = 'ofe_explain_faculty_truth_ai_close_v2_';

  function seedOldPoison(id: string) {
    sessionStorage.setItem(
      `${OLD_PREFIX}${id}_${hashProfile(profile)}_ai0`,
      JSON.stringify({
        savedAt: Date.now(),
        data: {
          ...EXPLANATION,
          final_score: 99,
          explanation: 'POISONED CACHE TEXT',
          reasons_fit: ['POISONED FIT LINE'],
        },
      }),
    );
  }

  it('never reads a poisoned explain entry left by the previous cache version', async () => {
    // The realistic attack on ourselves: an open tab still holds sessionStorage
    // entries written before this surface gated on truth. Those were keyed only
    // by (id, profile, mode), so the closed target's old score and paragraph
    // are still sitting there under the previous prefix.
    setStorage(true, profile);
    seedOldPoison('dead-1');
    answerCanonically();
    const reads: string[] = [];
    const getItem = spyOnStorageReads(reads);

    render(<CompareTable opps={[opps[0], dead('dead-1', BAD_TRUTHS[0][1])]} />);
    await waitFor(() => expect(mockGetMatchExplanation).toHaveBeenCalled());
    expect(screen.getByTestId('compare-reference-card')).toBeInTheDocument();

    // Not read at all — stronger than "not displayed", which would also hold
    // if the entry were read and then discarded downstream.
    expect(getItem).toHaveBeenCalled();
    expect(reads.filter((key) => key.includes('dead-1'))).toEqual([]);
    expect(document.body).not.toHaveTextContent('POISONED CACHE TEXT');
    expect(document.body).not.toHaveTextContent('POISONED FIT LINE');
    expect(document.body).not.toHaveTextContent('99%');
    getItem.mockRestore();
  });

  it('strands the old prefix even for a live target', async () => {
    // The other half of the bump: a poisoned entry keyed to a target that IS
    // comparable must also be ignored, and the row re-fetched. Without this,
    // "never read" above could be explained entirely by the posture gate while
    // the version bump did nothing.
    setStorage(true, profile);
    seedOldPoison('a');
    answerCanonically();

    render(<CompareTable opps={opps} />);
    await waitFor(() => {
      expect(screen.getByTestId('bucket-cards')).toBeInTheDocument();
    });

    expect(mockGetMatchExplanation).toHaveBeenCalledWith(profile, 'a', { llm: false });
    expect(lastBucketRows?.find((row) => row.opp.id === 'a')?.match?.final_score).toBe(82);
    expect(document.body).not.toHaveTextContent('POISONED CACHE TEXT');
  });
});
