import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string, vars?: Record<string, string | number>) => {
      if (vars && 'count' in vars) return `${key}:${vars.count}`;
      if (vars && 'host' in vars) return `${key}:${vars.host}`;
      return key;
    },
  }),
}));

vi.mock('@/lib/api', () => ({
  getGapAnalysis: vi.fn(),
  getResponsivenessSignals: vi.fn().mockResolvedValue({}),
}));

import MatchCard from './MatchCard';
import type { MatchResult, Opportunity, MatchBucket, ProfileData } from '@/lib/types';

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

  describe('AI reason + recent work on the card face', () => {
    it('renders the ai_reason lead line when present', () => {
      render(
        <MatchCard
          match={makeMatch({}, { ai_reason: 'Their sparse-attention work matches your LLM interest.' })}
          onDraftEmail={() => {}}
        />,
      );
      expect(
        screen.getByText('Their sparse-attention work matches your LLM interest.'),
      ).toBeInTheDocument();
    });

    it('renders nothing extra when ai_reason is absent', () => {
      render(<MatchCard match={makeMatch()} onDraftEmail={() => {}} />);
      expect(screen.queryByText(/card.recentWork/)).toBeNull();
    });

    it('renders the first recent-work title with year when attribution is verified', () => {
      render(
        <MatchCard
          match={makeMatch({
            recent_works: [
              { title: 'Segmenting Tumors with Vision Transformers', year: 2025 },
              { title: 'Second Paper', year: 2024 },
            ],
            publication_attribution_status: 'verified_author_id',
          })}
          onDraftEmail={() => {}}
        />,
      );
      expect(
        screen.getByText(/Segmenting Tumors with Vision Transformers \(2025\)/),
      ).toBeInTheDocument();
      expect(screen.queryByText(/Second Paper/)).toBeNull();
    });

    it('hides works entirely unless attribution is explicitly verified (fail closed)', () => {
      const works = [{ title: 'A Borderline Paper', year: 2025 }];
      // name_match, absent (legacy), and junk statuses must all fail closed:
      // no paper line, no label — the work simply does not render.
      for (const status of ['name_match', undefined, 'trust_me'] as const) {
        const { unmount } = render(
          <MatchCard
            match={makeMatch({
              recent_works: works,
              publication_attribution_status: status as never,
            })}
            onDraftEmail={() => {}}
          />,
        );
        expect(screen.queryByText(/A Borderline Paper/)).toBeNull();
        expect(screen.queryByText(/card.recentWork/)).toBeNull();
        unmount();
      }
      render(
        <MatchCard
          match={makeMatch({
            recent_works: works,
            publication_attribution_status: 'verified_author_id',
          })}
          onDraftEmail={() => {}}
        />,
      );
      expect(screen.getByText(/A Borderline Paper \(2025\)/)).toBeInTheDocument();
    });
  });

  describe('international-friendly badge', () => {
    it('renders badges.intlOk key (green) for yes', () => {
      const match = makeMatch({ eligibility: { ...makeOpp().eligibility, international_friendly: 'yes' } });
      render(<MatchCard match={match} onDraftEmail={() => {}} />);
      expect(screen.getByText('badges.intlOk')).toBeInTheDocument();
    });

    it('renders badges.intlUsOnly key (red) for no', () => {
      const match = makeMatch({ eligibility: { ...makeOpp().eligibility, international_friendly: 'no' } });
      render(<MatchCard match={match} onDraftEmail={() => {}} />);
      expect(screen.getByText('badges.intlUsOnly')).toBeInTheDocument();
    });

    it('renders badges.intlVerify key (orange) when status is anything else', () => {
      const match = makeMatch({ eligibility: { ...makeOpp().eligibility, international_friendly: 'unknown' } });
      render(<MatchCard match={match} onDraftEmail={() => {}} />);
      expect(screen.getByText('badges.intlVerify')).toBeInTheDocument();
    });
  });

  describe('paid badge', () => {
    it('renders badges.paid key (green) for yes', () => {
      render(<MatchCard match={makeMatch({ paid: 'yes' })} onDraftEmail={() => {}} />);
      expect(screen.getByText('badges.paid')).toBeInTheDocument();
    });

    it('renders badges.stipend key (blue) for stipend', () => {
      render(<MatchCard match={makeMatch({ paid: 'stipend' })} onDraftEmail={() => {}} />);
      expect(screen.getByText('badges.stipend')).toBeInTheDocument();
    });

    it('renders badges.unpaid key (gray) for no', () => {
      render(<MatchCard match={makeMatch({ paid: 'no' })} onDraftEmail={() => {}} />);
      expect(screen.getByText('badges.unpaid')).toBeInTheDocument();
    });

    // R70-D: previously 'unknown' fell through to the misleading "Unpaid"
    // label. Now it routes to badges.notDisclosed so uiuc_faculty records
    // (which are simply missing compensation info, not explicitly unpaid)
    // render with accurate copy.
    it('renders badges.notDisclosed key (gray) for unknown', () => {
      render(<MatchCard match={makeMatch({ paid: 'unknown' })} onDraftEmail={() => {}} />);
      expect(screen.getByText('badges.notDisclosed')).toBeInTheDocument();
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

  describe('match feedback thumbs (Phase 9.6)', () => {
    it('renders no feedback UI when onFeedback is not provided', () => {
      render(<MatchCard match={makeMatch()} onDraftEmail={() => {}} />);
      expect(screen.queryByLabelText('card.feedback.up')).toBeNull();
      expect(screen.queryByLabelText('card.feedback.down')).toBeNull();
    });

    it('renders both thumbs with the prompt when onFeedback is provided', () => {
      render(<MatchCard match={makeMatch()} onDraftEmail={() => {}} onFeedback={() => {}} />);
      expect(screen.getByText('card.feedback.prompt')).toBeInTheDocument();
      expect(screen.getByLabelText('card.feedback.up')).toBeInTheDocument();
      expect(screen.getByLabelText('card.feedback.down')).toBeInTheDocument();
    });

    it('calls onFeedback with (id, "up", {bucket, finalScore}) on thumbs-up', () => {
      const handler = vi.fn();
      render(
        <MatchCard
          match={makeMatch({ id: 'opp-fb' }, { bucket: 'good_match', final_score: 72 })}
          onDraftEmail={() => {}}
          onFeedback={handler}
        />,
      );
      fireEvent.click(screen.getByLabelText('card.feedback.up'));
      expect(handler).toHaveBeenCalledWith('opp-fb', 'up', { bucket: 'good_match', finalScore: 72 });
    });

    it('calls onFeedback with (id, "down", ...) on thumbs-down', () => {
      const handler = vi.fn();
      render(
        <MatchCard match={makeMatch({ id: 'opp-fb' })} onDraftEmail={() => {}} onFeedback={handler} />,
      );
      fireEvent.click(screen.getByLabelText('card.feedback.down'));
      expect(handler).toHaveBeenCalledWith('opp-fb', 'down', { bucket: 'high_priority', finalScore: 85 });
    });

    it('tapping the active thumb again clears the verdict (passes null)', () => {
      const handler = vi.fn();
      render(
        <MatchCard
          match={makeMatch({ id: 'opp-fb' })}
          onDraftEmail={() => {}}
          onFeedback={handler}
          feedbackVerdict="up"
        />,
      );
      fireEvent.click(screen.getByLabelText('card.feedback.up'));
      expect(handler).toHaveBeenCalledWith('opp-fb', null, { bucket: 'high_priority', finalScore: 85 });
    });

    it('switching thumbs replaces the verdict instead of clearing it', () => {
      const handler = vi.fn();
      render(
        <MatchCard
          match={makeMatch({ id: 'opp-fb' })}
          onDraftEmail={() => {}}
          onFeedback={handler}
          feedbackVerdict="up"
        />,
      );
      fireEvent.click(screen.getByLabelText('card.feedback.down'));
      expect(handler).toHaveBeenCalledWith('opp-fb', 'down', { bucket: 'high_priority', finalScore: 85 });
    });

    it('reflects the current verdict via aria-pressed', () => {
      render(
        <MatchCard
          match={makeMatch()}
          onDraftEmail={() => {}}
          onFeedback={() => {}}
          feedbackVerdict="down"
        />,
      );
      expect(screen.getByLabelText('card.feedback.up')).toHaveAttribute('aria-pressed', 'false');
      expect(screen.getByLabelText('card.feedback.down')).toHaveAttribute('aria-pressed', 'true');
    });
  });

  describe('draft email action', () => {
    it('calls onDraftEmail with the opportunity id when clicked', () => {
      const handler = vi.fn();
      render(<MatchCard match={makeMatch({ id: 'opp-abc' })} onDraftEmail={handler} />);
      fireEvent.click(screen.getByText('card.draftEmail'));
      expect(handler).toHaveBeenCalledWith('opp-abc');
    });
  });

  describe('apply / view links', () => {
    it('shows Apply Now link with application_url when present', () => {
      const match = makeMatch({}, undefined);
      match.opportunity.application = { ...match.opportunity.application, application_url: 'https://apply.example' };
      render(<MatchCard match={match} onDraftEmail={() => {}} />);
      const link = screen.getByText('card.applyNow').closest('a');
      expect(link).not.toBeNull();
      expect(link!.getAttribute('href')).toBe('https://apply.example');
      expect(link!.getAttribute('target')).toBe('_blank');
    });

    it('falls back to View Details (opp.url) when no application_url', () => {
      const match = makeMatch({ url: 'https://opp.example' });
      render(<MatchCard match={match} onDraftEmail={() => {}} />);
      // R70-F: link CTA → card.viewDetails key; expand toggle → card.showDetails key.
      const link = screen.getByText('card.viewDetails').closest('a');
      expect(link).not.toBeNull();
      expect(link!.getAttribute('href')).toBe('https://opp.example');
    });

    it('faculty record shows "Email Professor" + secondary "Faculty Page", never "Apply Now"', () => {
      // application_url on a faculty record is the prof's directory page, not
      // an apply form — surfacing it as "Apply Now" dead-ends, so we don't.
      const match = makeMatch({
        source_type: 'faculty_research',
        url: 'https://faculty.example/prof',
        application: {
          application_effort: 'medium',
          requires_resume: 'no',
          contact_method: 'email',
          application_url: 'https://faculty.example/prof',
        },
      });
      render(<MatchCard match={match} onDraftEmail={() => {}} />);
      expect(screen.queryByText('card.applyNow')).toBeNull();
      expect(screen.getByText('card.emailProfessor')).toBeInTheDocument();
      const facultyLink = screen.getByText('card.viewFacultyPage').closest('a');
      expect(facultyLink!.getAttribute('href')).toBe('https://faculty.example/prof');
    });

    it('faculty "Email Professor" button triggers onDraftEmail', () => {
      const handler = vi.fn();
      const match = makeMatch({
        id: 'fac-1',
        source_type: 'faculty_research',
        application: {
          application_effort: 'low',
          requires_resume: 'no',
          contact_method: 'email',
          application_url: 'https://faculty.example/prof',
        },
      });
      render(<MatchCard match={match} onDraftEmail={handler} />);
      fireEvent.click(screen.getByText('card.emailProfessor'));
      expect(handler).toHaveBeenCalledWith('fac-1');
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

  // PR #187 Phase 1: host+audience chip. Home-campus records (the majority)
  // must stay chipless; only open / unknown / foreign-campus records get one.
  describe('discovery-scope chip', () => {
    const SCOPE_KEYS = /^card\.scope\./;

    function makeProfile(homeSchool?: string): ProfileData {
      return {
        institution: 'UIUC',
        home_school: homeSchool,
        college: 'Grainger College of Engineering',
        major: 'Computer Science',
        grade: 'Freshman',
        is_international: false,
        research_interests: 'ml',
        skills: [],
      };
    }

    it('renders NO chip for a home-campus record', () => {
      render(
        <MatchCard
          match={makeMatch({ school: 'uiuc', audience: 'campus' })}
          profile={makeProfile('uiuc')}
          onDraftEmail={() => {}}
        />,
      );
      expect(screen.queryByText(SCOPE_KEYS)).toBeNull();
    });

    it('renders NO chip when the record has no scope metadata (pre-#189 cache)', () => {
      render(<MatchCard match={makeMatch()} onDraftEmail={() => {}} />);
      expect(screen.queryByText(SCOPE_KEYS)).toBeNull();
    });

    it('renders the hostless open chip for a national open record', () => {
      render(
        <MatchCard
          match={makeMatch({ school: null, audience: 'open' })}
          onDraftEmail={() => {}}
        />,
      );
      expect(screen.getByText('card.scope.open')).toBeInTheDocument();
    });

    it('renders host · open for a foreign open record', () => {
      render(
        <MatchCard
          match={makeMatch({ school: 'ucb', audience: 'open' })}
          profile={makeProfile('uiuc')}
          onDraftEmail={() => {}}
        />,
      );
      expect(screen.getByText('card.scope.openWithHost:UC Berkeley')).toBeInTheDocument();
    });

    it('renders host · unconfirmed for an unknown-audience record', () => {
      render(
        <MatchCard
          match={makeMatch({ school: 'ucb', audience: 'unknown' })}
          onDraftEmail={() => {}}
        />,
      );
      expect(screen.getByText('card.scope.unknownWithHost:UC Berkeley')).toBeInTheDocument();
    });

    it('renders students-only for a foreign campus-only record after a school switch', () => {
      render(
        <MatchCard
          match={makeMatch({ school: 'uiuc', audience: 'campus' })}
          profile={makeProfile('ucb')}
          onDraftEmail={() => {}}
        />,
      );
      expect(screen.getByText('card.scope.campusOnly:UIUC')).toBeInTheDocument();
    });

    it('defaults the home school to uiuc when the profile predates the switcher', () => {
      render(
        <MatchCard
          match={makeMatch({ school: 'uiuc', audience: 'campus' })}
          profile={makeProfile(undefined)}
          onDraftEmail={() => {}}
        />,
      );
      expect(screen.queryByText(SCOPE_KEYS)).toBeNull();
    });
  });
});
