import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string, vars?: Record<string, string | number>) =>
      vars && 'count' in vars ? `${key}:${vars.count}` : key,
  }),
}));

vi.mock('@/lib/api', () => ({
  getGapAnalysis: vi.fn(),
}));

import MatchCard from './MatchCard';
import type { MatchResult, Opportunity, MatchBucket } from '@/lib/types';

function makeOpp(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: 'opp-1',
    title: 'Test Opportunity',
    organization: 'UIUC CS',
    opportunity_type: 'Research',
    paid: 'yes',
    location: 'Urbana, IL',
    on_campus: true,
    description_clean: 'A great opportunity for testing.',
    keywords: ['ml'],
    eligibility: {
      international_friendly: 'yes',
      preferred_year: ['Sophomore'],
      majors: ['CS'],
      skills_required: ['Python'],
      citizenship_required: false,
    },
    application: {
      application_effort: 'medium',
      requires_resume: 'yes',
      contact_method: 'email',
    },
    metadata: { is_active: true, confidence_score: 0.9 },
    ...overrides,
  };
}

function makeMatch(
  oppOverrides: Partial<Opportunity> = {},
  matchOverrides: Partial<MatchResult> = {},
): MatchResult {
  const opportunity = makeOpp(oppOverrides);
  return {
    opportunity_id: opportunity.id,
    eligibility_score: 0.9,
    readiness_score: 0.8,
    upside_score: 0.7,
    final_score: 85,
    bucket: 'high_priority',
    reasons_fit: [],
    reasons_gap: [],
    next_steps: [],
    opportunity,
    ...matchOverrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('MatchCard', () => {
  describe('bucket label', () => {
    const cases: Array<[MatchBucket, string]> = [
      ['high_priority', 'results.tabs.highPriority'],
      ['good_match', 'results.tabs.goodMatch'],
      ['reach', 'results.tabs.reach'],
      ['low_fit', 'results.tabs.lowFit'],
    ];
    it.each(cases)('renders %s as %s', (bucket, key) => {
      render(<MatchCard match={makeMatch({}, { bucket })} onDraftEmail={() => {}} />);
      expect(screen.getByText(key)).toBeInTheDocument();
    });
  });

  describe('international-friendly badge', () => {
    it('renders Intl OK (green) for yes', () => {
      const match = makeMatch({ eligibility: { ...makeOpp().eligibility, international_friendly: 'yes' } });
      render(<MatchCard match={match} onDraftEmail={() => {}} />);
      expect(screen.getByText('Intl OK')).toBeInTheDocument();
    });

    it('renders US Only (red) for no', () => {
      const match = makeMatch({ eligibility: { ...makeOpp().eligibility, international_friendly: 'no' } });
      render(<MatchCard match={match} onDraftEmail={() => {}} />);
      expect(screen.getByText('US Only')).toBeInTheDocument();
    });

    it('renders Verify (orange) when status is anything else', () => {
      const match = makeMatch({ eligibility: { ...makeOpp().eligibility, international_friendly: 'unknown' } });
      render(<MatchCard match={match} onDraftEmail={() => {}} />);
      expect(screen.getByText('Verify')).toBeInTheDocument();
    });
  });

  describe('paid badge', () => {
    it('renders Paid (green) for yes', () => {
      render(<MatchCard match={makeMatch({ paid: 'yes' })} onDraftEmail={() => {}} />);
      expect(screen.getByText('Paid')).toBeInTheDocument();
    });

    it('renders Stipend (blue) for stipend', () => {
      render(<MatchCard match={makeMatch({ paid: 'stipend' })} onDraftEmail={() => {}} />);
      expect(screen.getByText('Stipend')).toBeInTheDocument();
    });

    it('renders Unpaid (gray) for no', () => {
      render(<MatchCard match={makeMatch({ paid: 'no' })} onDraftEmail={() => {}} />);
      expect(screen.getByText('Unpaid')).toBeInTheDocument();
    });
  });

  describe('deadline badge', () => {
    it('renders deadlinePassed key when deadline is in the past', () => {
      render(<MatchCard match={makeMatch({ deadline: '2020-01-01' })} onDraftEmail={() => {}} />);
      expect(screen.getByText('badges.deadlinePassed')).toBeInTheDocument();
    });

    it('renders dueInDays:<n> for an urgent deadline (<= 14d)', () => {
      const soon = new Date(Date.now() + 5 * 86400000).toISOString().slice(0, 10);
      render(<MatchCard match={makeMatch({ deadline: soon })} onDraftEmail={() => {}} />);
      const node = screen.getAllByText(/^badges\.dueInDays:\d+$/);
      expect(node.length).toBeGreaterThan(0);
    });

    it('renders the raw deadline string when > 14 days out', () => {
      const far = new Date(Date.now() + 60 * 86400000).toISOString().slice(0, 10);
      render(<MatchCard match={makeMatch({ deadline: far })} onDraftEmail={() => {}} />);
      expect(screen.getByText(far)).toBeInTheDocument();
    });
  });

  describe('isNew prop (R19/R20 highlight ring + pill)', () => {
    it('renders the "New match" pill when isNew=true', () => {
      render(<MatchCard match={makeMatch()} onDraftEmail={() => {}} isNew />);
      expect(screen.getByText('results.newMatchBadge')).toBeInTheDocument();
    });

    it('omits the pill when isNew is false / undefined', () => {
      render(<MatchCard match={makeMatch()} onDraftEmail={() => {}} />);
      expect(screen.queryByText('results.newMatchBadge')).toBeNull();
    });
  });

  describe('isNewPosting (posted_date < 14d) — independent of isNew', () => {
    it('renders the badges.new pill when posted_date is recent', () => {
      const recent = new Date(Date.now() - 3 * 86400000).toISOString();
      render(<MatchCard match={makeMatch({ posted_date: recent })} onDraftEmail={() => {}} />);
      expect(screen.getByText('badges.new')).toBeInTheDocument();
    });

    it('does not render badges.new when posted_date is older than 14d', () => {
      const old = new Date(Date.now() - 30 * 86400000).toISOString();
      render(<MatchCard match={makeMatch({ posted_date: old })} onDraftEmail={() => {}} />);
      expect(screen.queryByText('badges.new')).toBeNull();
    });

    it('coexists with isNew (both pills can render at once)', () => {
      const recent = new Date(Date.now() - 3 * 86400000).toISOString();
      render(<MatchCard match={makeMatch({ posted_date: recent })} onDraftEmail={() => {}} isNew />);
      expect(screen.getByText('results.newMatchBadge')).toBeInTheDocument();
      expect(screen.getByText('badges.new')).toBeInTheDocument();
    });
  });

  describe('favorite toggle', () => {
    it('renders the star button only when onToggleFavorite is provided', () => {
      render(<MatchCard match={makeMatch()} onDraftEmail={() => {}} />);
      expect(screen.queryByLabelText(/favorite/i)).toBeNull();
    });

    it('shows "Add to favorites" label when isFavorited is false', () => {
      render(
        <MatchCard
          match={makeMatch()}
          onDraftEmail={() => {}}
          onToggleFavorite={() => {}}
          isFavorited={false}
        />,
      );
      expect(screen.getByLabelText('Add to favorites')).toBeInTheDocument();
    });

    it('shows "Remove from favorites" label when isFavorited is true', () => {
      render(
        <MatchCard
          match={makeMatch()}
          onDraftEmail={() => {}}
          onToggleFavorite={() => {}}
          isFavorited
        />,
      );
      expect(screen.getByLabelText('Remove from favorites')).toBeInTheDocument();
    });

    it('calls onToggleFavorite with the opportunity id on click', () => {
      const handler = vi.fn();
      render(
        <MatchCard match={makeMatch({ id: 'opp-xyz' })} onDraftEmail={() => {}} onToggleFavorite={handler} />,
      );
      fireEvent.click(screen.getByLabelText(/favorites/i));
      expect(handler).toHaveBeenCalledWith('opp-xyz');
    });
  });

  describe('draft email action', () => {
    it('calls onDraftEmail with the opportunity id when clicked', () => {
      const handler = vi.fn();
      render(<MatchCard match={makeMatch({ id: 'opp-abc' })} onDraftEmail={handler} />);
      fireEvent.click(screen.getByText(/Draft Email/i));
      expect(handler).toHaveBeenCalledWith('opp-abc');
    });
  });

  describe('apply / view links', () => {
    it('shows Apply Now link with application_url when present', () => {
      const match = makeMatch({}, undefined);
      match.opportunity.application = { ...match.opportunity.application, application_url: 'https://apply.example' };
      render(<MatchCard match={match} onDraftEmail={() => {}} />);
      const link = screen.getByText(/Apply Now/i).closest('a');
      expect(link).not.toBeNull();
      expect(link!.getAttribute('href')).toBe('https://apply.example');
      expect(link!.getAttribute('target')).toBe('_blank');
    });

    it('falls back to View Details (opp.url) when no application_url', () => {
      const match = makeMatch({ url: 'https://opp.example' });
      render(<MatchCard match={match} onDraftEmail={() => {}} />);
      // Case-sensitive: link reads "View Details", expand toggle reads "View details"
      const link = screen.getByText(/^View Details$/).closest('a');
      expect(link).not.toBeNull();
      expect(link!.getAttribute('href')).toBe('https://opp.example');
    });
  });

  describe('interaction tracker (R69-C menu)', () => {
    it('renders no status UI when onTrackInteraction is not provided', () => {
      render(<MatchCard match={makeMatch()} onDraftEmail={() => {}} />);
      // No trigger pill, no menu items.
      expect(screen.queryByText('results.statusMenu.trigger')).toBeNull();
      expect(screen.queryByText('detail.tracker.statusLabels.applied')).toBeNull();
    });

    it('renders the status menu trigger (collapsed by default) when onTrackInteraction is provided', () => {
      render(
        <MatchCard match={makeMatch()} onDraftEmail={() => {}} onTrackInteraction={() => {}} />,
      );
      expect(screen.getByText('results.statusMenu.trigger')).toBeInTheDocument();
      // Menu items are not rendered until the trigger is opened.
      expect(screen.queryByText('detail.tracker.statusLabels.applied')).toBeNull();
      expect(screen.queryByText('detail.tracker.statusLabels.dismissed')).toBeNull();
    });

    it('clicking the trigger reveals all 5 status options as menuitems', () => {
      render(
        <MatchCard match={makeMatch()} onDraftEmail={() => {}} onTrackInteraction={() => {}} />,
      );
      fireEvent.click(screen.getByText('results.statusMenu.trigger'));
      expect(screen.getByText('detail.tracker.statusLabels.applied')).toBeInTheDocument();
      expect(screen.getByText('detail.tracker.statusLabels.replied')).toBeInTheDocument();
      expect(screen.getByText('detail.tracker.statusLabels.interviewing')).toBeInTheDocument();
      expect(screen.getByText('detail.tracker.statusLabels.rejected')).toBeInTheDocument();
      expect(screen.getByText('detail.tracker.statusLabels.dismissed')).toBeInTheDocument();
    });

    it('trigger label reflects the current status when set, instead of the neutral "Mark status" copy', () => {
      render(
        <MatchCard
          match={makeMatch()}
          onDraftEmail={() => {}}
          onTrackInteraction={() => {}}
          interaction="applied"
        />,
      );
      // The trigger shows the active status label; the neutral
      // "Mark status" string is not present anywhere when interaction is set.
      expect(screen.queryByText('results.statusMenu.trigger')).toBeNull();
      expect(screen.getByText('detail.tracker.statusLabels.applied')).toBeInTheDocument();
    });

    it('calls onTrackInteraction with (oppId, type) when a menuitem is selected', () => {
      const handler = vi.fn();
      render(
        <MatchCard
          match={makeMatch({ id: 'opp-track' })}
          onDraftEmail={() => {}}
          onTrackInteraction={handler}
        />,
      );
      // Open the menu first; menuitems only render while open.
      fireEvent.click(screen.getByText('results.statusMenu.trigger'));
      fireEvent.click(screen.getByText('detail.tracker.statusLabels.interviewing'));
      expect(handler).toHaveBeenCalledWith('opp-track', 'interviewing');
    });
  });
});
