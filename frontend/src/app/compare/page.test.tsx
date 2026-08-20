/* @vitest-environment jsdom */
// The whole /compare?ids= path, end to end: the server page resolves whatever
// ids the URL names, and the client table decides what may be done with them.
// Nothing in between checks anything — arriving here is not evidence that a
// selection guard ever ran, because ?ids= is typed, bookmarked and pasted.
//
// The unit tests either side of this prove each half. This proves they are
// actually joined: a URL naming one live and one closed target reaches the
// real table with both, and the closed one still costs nothing and claims
// nothing.
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const { fetchOpportunityServer, getMatchExplanation } = vi.hoisted(() => ({
  fetchOpportunityServer: vi.fn(),
  getMatchExplanation: vi.fn(),
}));

vi.mock('@/lib/api-server', () => ({ fetchOpportunityServer }));
vi.mock('@/lib/api', () => ({ getMatchExplanation }));
vi.mock('@/i18n/server', () => ({
  getServerT: async () => (key: string) => key,
}));
vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key }) }));
// Compare is dormant behind the release flag; the page 404s otherwise, and
// this file is about what it does once reopened.
vi.mock('@/lib/release-scope', () => ({ RELEASE_SCOPE: { compare: true } }));

const PROFILE = {
  major: 'CS', grade: 'Sophomore', is_international: false,
  skills: [{ name: 'Python', level: 'expert' }],
};
vi.mock('@/lib/use-local-storage-json', () => ({
  useHasLocalStorageKey: () => true,
  useLocalStorageJSON: (key: string) => (key.includes('profile') ? PROFILE : null),
}));

import ComparePage from './page';

const ACTIONABLE_TRUTH = {
  listing_state: 'open',
  reference_only: false,
  actionable: true,
  accepting_state: 'accepting',
  reason_code: null,
  verified_at: null,
  expires_at: null,
} as const;

const LIVE = {
  id: 'live-1', title: 'Live Lab RA', organization: 'Org L',
  source_type: 'campus_program',
  target_truth: { ...ACTIONABLE_TRUTH },
};

const CLOSED = {
  id: 'closed-1', title: 'Closed Program', organization: 'Org C',
  source_type: 'campus_program',
  source_url: 'https://example.edu/source-page',
  application: { application_url: 'https://example.edu/apply-here' },
  deadline: '2099-12-31',
  paid: 'yes',
  description_clean: 'POISON applications open now',
  target_truth: {
    ...ACTIONABLE_TRUTH,
    actionable: false, listing_state: 'closed', reference_only: true,
    accepting_state: 'not_accepting', reason_code: 'listing_closed',
  },
};

beforeEach(() => {
  fetchOpportunityServer.mockReset();
  getMatchExplanation.mockReset();
  window.sessionStorage.clear();
});

describe('a mixed ?ids= URL bypasses selection but not the truth', () => {
  it('resolves both, compares neither, and spends nothing on the closed one', async () => {
    fetchOpportunityServer.mockImplementation(async (id: string) => (
      id === 'live-1' ? LIVE : id === 'closed-1' ? CLOSED : null
    ));
    getMatchExplanation.mockResolvedValue({
      explanation: 'Great topical fit.', method: 'local',
      final_score: 82, bucket: 'high_priority',
      reasons_fit: [], reasons_gap: [],
      eligibility_score: 90, readiness_score: 80, upside_score: 70,
    });

    const ui = await ComparePage({
      searchParams: Promise.resolve({ ids: 'live-1,closed-1' }),
    });
    render(ui);

    // Both ids were resolved server-side — the page does not pre-filter, so
    // the client guard is genuinely what is being exercised.
    expect(fetchOpportunityServer).toHaveBeenCalledWith('live-1');
    expect(fetchOpportunityServer).toHaveBeenCalledWith('closed-1');

    await waitFor(() => {
      expect(screen.getByTestId('compare-reference-card')).toBeInTheDocument();
    });

    const askedFor = getMatchExplanation.mock.calls.map((call) => call[1]);
    expect(askedFor).not.toContain('closed-1');

    const card = screen.getByTestId('compare-reference-card');
    expect(card).toHaveTextContent('Closed Program');
    expect(card).toHaveTextContent('compare.status.closed');
    const links = Array.from(card.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(links).toContain('https://example.edu/source-page');
    expect(links).not.toContain('https://example.edu/apply-here');
    // None of the closed record's opening facts reach the page.
    expect(document.body).not.toHaveTextContent('2099-12-31');
    expect(document.body).not.toHaveTextContent('POISON applications open now');
  });

  it('says there is nothing to compare rather than comparing one', async () => {
    fetchOpportunityServer.mockImplementation(async (id: string) => (
      id === 'live-1' ? LIVE : CLOSED
    ));

    const ui = await ComparePage({
      searchParams: Promise.resolve({ ids: 'live-1,closed-1' }),
    });
    render(ui);

    await waitFor(() => {
      expect(screen.getByText('compare.notEnoughComparable')).toBeInTheDocument();
    });
  });
});
