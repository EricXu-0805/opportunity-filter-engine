import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { SimilarOpportunity } from '@/lib/api-server';
import { SimilarOpportunities } from './SimilarOpportunities';

const t = (key: string) => key;

const ACTIONABLE_TRUTH = {
  listing_state: 'open',
  reference_only: false,
  actionable: true,
  accepting_state: 'accepting',
  reason_code: null,
  verified_at: null,
  expires_at: null,
} as const;

function similar(overrides: Record<string, unknown>): SimilarOpportunity {
  return {
    id: 'sim-1',
    title: 'A similar record',
    organization: 'Test University',
    opportunity_type: 'research',
    paid: 'yes',
    _similarity: 0.9,
    target_truth: { ...ACTIONABLE_TRUTH },
    ...overrides,
  } as unknown as SimilarOpportunity;
}

describe('the similar rail only recommends what can be acted on', () => {
  // This rail comes from a separate endpoint that fails open to [], so its
  // rows arrive without having passed through the match universe. A card here
  // is a recommendation; recommending a dead target is the failure.

  it('shows a live confirmed listing, with its offer terms', () => {
    render(<SimilarOpportunities similar={[similar({ source_type: 'campus_program' })]} t={t} />);

    expect(screen.getByText('A similar record')).toBeInTheDocument();
    expect(screen.getByText('badges.paid')).toBeInTheDocument();
  });

  it('shows a live faculty profile without any offer terms', () => {
    render(<SimilarOpportunities similar={[similar({ source_type: 'faculty_research' })]} t={t} />);

    expect(screen.getByText('A similar record')).toBeInTheDocument();
    // Pay is a term of an application; a directory page is not one.
    expect(screen.queryByText('badges.paid')).toBeNull();
    expect(screen.getByText('card.facultyContactUnconfirmed')).toBeInTheDocument();
  });

  const NOT_RECOMMENDABLE: [string, Record<string, unknown>][] = [
    ['a closed listing', {
      source_type: 'campus_program',
      target_truth: {
        ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'closed',
        accepting_state: 'not_accepting', reason_code: 'listing_closed',
      },
    }],
    ['a faculty member who is not accepting', {
      source_type: 'faculty_research',
      target_truth: {
        ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'unknown',
        accepting_state: 'not_accepting', reason_code: 'faculty_not_accepting',
      },
    }],
    ['an unreviewed record kind', {
      source_type: undefined,
      target_truth: {
        ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'unknown',
        accepting_state: 'unknown', reason_code: 'record_kind_unverified',
      },
    }],
    ['a row with no truth at all', { source_type: 'campus_program', target_truth: undefined }],
    ['a malformed truth', {
      source_type: 'campus_program', target_truth: { listing_state: 'open' },
    }],
  ];

  it.each(NOT_RECOMMENDABLE)('does not recommend %s', (_label, overrides) => {
    const row = similar(overrides) as unknown as Record<string, unknown>;
    if (overrides.target_truth === undefined) delete row.target_truth;
    if (overrides.source_type === undefined) delete row.source_type;

    const { container } = render(
      <SimilarOpportunities similar={[row as unknown as SimilarOpportunity]} t={t} />,
    );

    expect(screen.queryByText('A similar record')).toBeNull();
    expect(screen.queryByText('badges.paid')).toBeNull();
    // The whole section disappears rather than rendering an empty heading.
    expect(container).toBeEmptyDOMElement();
  });

  it('keeps the live ones when only some rows are dead', () => {
    render(
      <SimilarOpportunities
        similar={[
          similar({ id: 'live-1', title: 'Live one', source_type: 'campus_program' }),
          similar({
            id: 'dead-1', title: 'Dead one', source_type: 'campus_program',
            target_truth: {
              ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'closed',
              accepting_state: 'not_accepting', reason_code: 'listing_closed',
            },
          }),
        ]}
        t={t}
      />,
    );

    expect(screen.getByText('Live one')).toBeInTheDocument();
    expect(screen.queryByText('Dead one')).toBeNull();
  });
});
