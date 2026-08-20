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
  // TailorModal (rendered for real when the Tailor CTA opens it — see the
  // "Tailor CTA" describe block below) probes these on open.
  getTailorStatus: vi.fn().mockResolvedValue({ ai_available: true }),
  tailorResume: vi.fn(),
  extractResumeBullets: vi.fn(),
}));

import MatchCard from './MatchCard';
import type { MatchResult, Opportunity, MatchBucket, ProfileData } from '@/lib/types';

// Cards gate every action on the server-stamped target truth, so the default
// fixture carries the shape a live record has. Tests for a closed, reference
// or unverified record override it explicitly.
export const ACTIONABLE_TRUTH = {
  listing_state: 'open',
  reference_only: false,
  actionable: true,
  accepting_state: 'accepting',
  reason_code: null,
  verified_at: null,
  expires_at: null,
} as const;

function makeOpp(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: 'opp-1',
    title: 'Test Opportunity',
    organization: 'UIUC CS',
    target_truth: { ...ACTIONABLE_TRUTH },
    source_type: 'campus_program',
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

const PROFILE: ProfileData = {
  institution: 'UIUC',
  home_school: 'uiuc',
  college: 'Grainger College of Engineering',
  major: 'Computer Science',
  grade: 'Sophomore',
  is_international: false,
  research_interests: 'machine learning',
  skills: [{ name: 'Python', level: 'experienced' }],
};

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

  it('labels a faculty city as affiliation rather than an opening location', () => {
    render(
      <MatchCard
        match={makeMatch({ source_type: 'faculty_research', location: 'Urbana, IL' })}
        onDraftEmail={() => {}}
      />,
    );
    expect(screen.getByText('card.facultyAffiliationLocation')).toBeInTheDocument();
    expect(screen.queryByText('Urbana, IL')).toBeNull();
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

    it('estimated past deadline renders the est marker, never "Deadline passed"', () => {
      // NSF projected dates: a confident red "passed" assertion on an
      // estimated date would be an overclaim.
      render(
        <MatchCard
          match={makeMatch({ deadline: '2020-01-01', deadline_is_estimate: true })}
          onDraftEmail={() => {}}
        />,
      );
      expect(screen.getByText('2020-01-01 · badges.estimated')).toBeInTheDocument();
      expect(screen.queryByText('badges.deadlinePassed')).toBeNull();
    });

    it('estimated near deadline renders the est marker, never a countdown', () => {
      const soon = new Date(Date.now() + 5 * 86400000).toISOString().slice(0, 10);
      render(
        <MatchCard
          match={makeMatch({ deadline: soon, deadline_is_estimate: true })}
          onDraftEmail={() => {}}
        />,
      );
      expect(screen.getByText(`${soon} · badges.estimated`)).toBeInTheDocument();
      expect(screen.queryByText(/^badges\.dueInDays:\d+$/)).toBeNull();
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

  describe('per-card save failure/retry (favSaveError / trackSaveError)', () => {
    it('renders no error UI when favSaveError/trackSaveError are unset', () => {
      render(
        <MatchCard
          match={makeMatch()}
          onDraftEmail={() => {}}
          onToggleFavorite={() => {}}
          onTrackInteraction={() => {}}
        />,
      );
      expect(screen.queryByRole('alert')).toBeNull();
    });

    it('renders a visible favSaveError with a Retry that calls onRetryFavSave with THIS card\'s opportunity id', () => {
      const onRetryFavSave = vi.fn();
      render(
        <MatchCard
          match={makeMatch({ id: 'opp-xyz' })}
          onDraftEmail={() => {}}
          onToggleFavorite={() => {}}
          favSaveError
          onRetryFavSave={onRetryFavSave}
        />,
      );
      expect(screen.getByText('results.favSaveError')).toBeInTheDocument();
      fireEvent.click(screen.getByText('common.retry'));
      expect(onRetryFavSave).toHaveBeenCalledWith('opp-xyz');
    });

    it('renders a visible trackSaveError with a Retry that calls onRetryTrackSave with THIS card\'s opportunity id', () => {
      const onRetryTrackSave = vi.fn();
      render(
        <MatchCard
          match={makeMatch({ id: 'opp-xyz' })}
          onDraftEmail={() => {}}
          onTrackInteraction={() => {}}
          trackSaveError
          onRetryTrackSave={onRetryTrackSave}
        />,
      );
      expect(screen.getByText('results.trackSaveError')).toBeInTheDocument();
      fireEvent.click(screen.getByText('common.retry'));
      expect(onRetryTrackSave).toHaveBeenCalledWith('opp-xyz');
    });

    it('favSaveError and trackSaveError render independently — one does not imply or hide the other', () => {
      render(
        <MatchCard
          match={makeMatch()}
          onDraftEmail={() => {}}
          onToggleFavorite={() => {}}
          onTrackInteraction={() => {}}
          favSaveError
          trackSaveError
        />,
      );
      expect(screen.getByText('results.favSaveError')).toBeInTheDocument();
      expect(screen.getByText('results.trackSaveError')).toBeInTheDocument();
    });
  });

  describe('Tailor CTA — fail-closed on ownerReady (C1-R2B)', () => {
    it('ownerReady=false (including the unspecified default) disables the Tailor CTA and never opens the modal', () => {
      const { rerender } = render(
        <MatchCard match={makeMatch()} profile={PROFILE} onDraftEmail={() => {}} />,
      );
      let tailorBtn = screen.getByText('card.tailorResume').closest('button')!;
      expect(tailorBtn).toBeDisabled();
      fireEvent.click(tailorBtn);
      expect(screen.queryByText('tailor.title')).toBeNull(); // never opened

      rerender(
        <MatchCard match={makeMatch()} profile={PROFILE} onDraftEmail={() => {}} ownerReady={false} />,
      );
      tailorBtn = screen.getByText('card.tailorResume').closest('button')!;
      expect(tailorBtn).toBeDisabled();
      fireEvent.click(tailorBtn);
      expect(screen.queryByText('tailor.title')).toBeNull();
    });

    it('ownerReady=true enables the Tailor CTA, and a real click actually opens the modal', async () => {
      render(
        <MatchCard match={makeMatch()} profile={PROFILE} onDraftEmail={() => {}} ownerReady />,
      );
      const tailorBtn = screen.getByText('card.tailorResume').closest('button')!;
      expect(tailorBtn).not.toBeDisabled();
      fireEvent.click(tailorBtn);
      // TailorModal is loaded via next/dynamic({ssr:false}) — its content
      // resolves asynchronously even in this test environment, so a real
      // click's effect is only observable through an async query. A
      // synchronous getByText/queryByText here would pass even against an
      // onClick that does nothing at all (or opens a different modal) —
      // findByText is what actually proves the click opened THIS modal.
      expect(await screen.findByText('tailor.title')).toBeInTheDocument();
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

  describe('MVP release surface', () => {
    it('keeps Tailor while hiding Renovate and the Roadmap preparation plan', () => {
      render(<MatchCard match={makeMatch()} profile={PROFILE} onDraftEmail={() => {}} />);
      expect(screen.getByText('card.tailorResume')).toBeInTheDocument();
      expect(screen.queryByText('card.renovateResume')).not.toBeInTheDocument();

      fireEvent.click(screen.getByText('card.showDetails'));
      expect(screen.queryByText('Show preparation plan')).not.toBeInTheDocument();
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

    it('faculty record shows "Draft Email" + secondary "Faculty Page", never "Apply Now"', () => {
      // application_url on a faculty record is the prof's directory page, not
      // an apply form — surfacing it as "Apply Now" dead-ends, so we don't.
      const match = makeMatch({
        source_type: 'faculty_research',
        url: 'https://faculty.example/real-profile',
        faculty_title: 'Professor',
        application: {
          application_effort: 'medium',
          requires_resume: 'no',
          contact_method: 'email',
          application_url: 'https://fake.example/apply',
        },
      });
      render(<MatchCard match={match} onDraftEmail={() => {}} />);
      expect(screen.queryByText('card.applyNow')).toBeNull();
      expect(screen.getByText('card.facultyContactUnconfirmed')).toBeInTheDocument();
      expect(screen.queryByText('badges.paid')).toBeNull();
      expect(screen.queryByText('card.emailProfessor')).toBeNull();
      expect(screen.getByText('card.draftEmail')).toBeInTheDocument();
      const facultyLink = screen.getByText('card.viewFacultyPage').closest('a');
      expect(facultyLink!.getAttribute('href')).toBe('https://faculty.example/real-profile');
      expect(screen.queryByRole('link', { name: 'card.applyNow' })).toBeNull();
    });

    it('faculty "Draft Email" button triggers onDraftEmail', () => {
      const handler = vi.fn();
      const match = makeMatch({
        id: 'fac-1',
        source_type: 'faculty_research',
        faculty_title: 'Professor',
        application: {
          application_effort: 'low',
          requires_resume: 'no',
          contact_method: 'email',
          application_url: 'https://faculty.example/prof',
        },
      });
      render(<MatchCard match={match} onDraftEmail={handler} />);
      fireEvent.click(screen.getByText('card.draftEmail'));
      expect(handler).toHaveBeenCalledWith('fac-1');
    });

    it('shows an explicit undergraduate stop and removes the outreach draft action', () => {
      const handler = vi.fn();
      const match = makeMatch({
        source_type: 'faculty_research',
        faculty_availability_status: 'not_accepting_undergraduates',
        url: 'https://faculty.example/source',
      });
      render(<MatchCard match={match} onDraftEmail={handler} />);

      expect(screen.getByText('card.facultyNotAcceptingUndergraduates')).toBeInTheDocument();
      expect(screen.queryByText('card.facultyContactUnconfirmed')).toBeNull();
      expect(screen.queryByText('card.draftEmail')).toBeNull();
      expect(handler).not.toHaveBeenCalled();
      expect(screen.getByText('card.viewFacultyPage')).toBeInTheDocument();
    });

    it('shows research inactivity precisely without inferring that outreach is forbidden', () => {
      const handler = vi.fn();
      const match = makeMatch({
        source_type: 'faculty_research',
        faculty_availability_status: 'research_inactive',
      });
      render(<MatchCard match={match} onDraftEmail={handler} />);

      expect(screen.getByText('card.facultyResearchInactive')).toBeInTheDocument();
      fireEvent.click(screen.getByText('card.draftEmail'));
      expect(handler).toHaveBeenCalledWith('opp-1');
    });

    it('faculty record with a non-professor rank gets "Draft Email", not "Email Professor"', () => {
      // faculty_title is the scraped rank — "Senior Lecturer" must not be
      // framed as a professor on the CTA.
      const match = makeMatch({
        source_type: 'faculty_research',
        faculty_title: 'Senior Lecturer',
      });
      render(<MatchCard match={match} onDraftEmail={() => {}} />);
      expect(screen.queryByText('card.emailProfessor')).toBeNull();
      expect(screen.getByText('card.draftEmail')).toBeInTheDocument();
    });

    it('faculty record with a professor-like rank still gets "Draft Email"', () => {
      const match = makeMatch({
        source_type: 'faculty_research',
        faculty_title: 'Assistant Professor',
      });
      render(<MatchCard match={match} onDraftEmail={() => {}} />);
      expect(screen.queryByText('card.emailProfessor')).toBeNull();
      expect(screen.getByText('card.draftEmail')).toBeInTheDocument();
    });

    it('fails closed for a poisoned faculty profile with no verified email or opening facts', () => {
      const today = new Date().toISOString().slice(0, 10);
      const match = makeMatch({
        source_type: 'faculty_research',
        faculty_title: 'Professor',
        deadline: '2099-12-31',
        posted_date: today,
        paid: 'yes',
        eligibility: {
          ...makeOpp().eligibility,
          international_friendly: 'yes',
          citizenship_required: false,
          skills_required: ['FAKE_REQUIRED_SKILL'],
        },
        application: {
          application_effort: 'unknown',
          requires_resume: 'unknown',
          contact_method: '',
        },
      });
      render(<MatchCard match={match} isNew onDraftEmail={() => {}} />);

      expect(screen.queryByText('card.emailProfessor')).toBeNull();
      expect(screen.getByText('card.draftEmail')).toBeInTheDocument();
      expect(screen.queryByText('results.newMatchBadge')).toBeNull();
      expect(screen.queryByText('badges.new')).toBeNull();
      expect(screen.queryByText('2099-12-31')).toBeNull();
      expect(screen.queryByText('badges.intlOk')).toBeNull();
      // No eligibility badge at all now, not even the degraded "verify" one.
      // Who may apply is a term of an application, and a directory row is not
      // one — "verify your international eligibility" on a faculty contact
      // still implies there is something to be eligible for.
      expect(screen.queryByText('badges.intlVerify')).toBeNull();
      fireEvent.click(screen.getByText('card.showDetails'));
      expect(screen.queryByText('FAKE_REQUIRED_SKILL')).toBeNull();
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

describe('MatchCard target-truth postures', () => {
  const HISTORICAL = {
    listing_state: 'closed',
    reference_only: true,
    actionable: false,
    accepting_state: 'not_accepting',
    reason_code: 'listing_closed',
    verified_at: null,
    expires_at: null,
  } as const;

  const POSTURES: [string, unknown][] = [
    ['historical', HISTORICAL],
    ['unknown (missing)', undefined],
    ['unknown (null)', null],
    ['unknown (malformed)', { listing_state: 'open' }],
    ['unknown (self-contradicting)', { ...HISTORICAL, actionable: true }],
    // The live side of the canonical table. Both of these claim `actionable`
    // and pass every "obviously contradictory" check, which is exactly why
    // they used to unlock the full CTA set: Apply, Draft Email, Tailor.
    ['unknown (open but not accepting-stated)', {
      ...ACTIONABLE_TRUTH, listing_state: 'open', accepting_state: 'unknown',
    }],
    ['unknown (unstamped yet claiming to accept)', {
      ...ACTIONABLE_TRUTH, listing_state: 'unknown', accepting_state: 'accepting',
    }],
  ];

  function renderWith(truth: unknown, onDraftEmail = () => {}) {
    const overrides: Record<string, unknown> = {
      source_type: 'campus_program',
      url: 'https://example.edu/source',
      application: {
        application_effort: 'low',
        requires_resume: 'yes',
        contact_method: 'email',
        application_url: 'https://example.edu/apply',
      },
    };
    if (truth === undefined) overrides.target_truth = undefined;
    else overrides.target_truth = truth;
    const opp = makeOpp(overrides as never);
    if (truth === undefined) delete (opp as unknown as Record<string, unknown>).target_truth;
    return render(
      <MatchCard
        match={{ ...makeMatch(), opportunity: opp }}
        profile={PROFILE}
        onDraftEmail={onDraftEmail}
        ownerReady
      />,
    );
  }

  it.each(POSTURES)('offers no action controls for a %s target', (_label, truth) => {
    renderWith(truth);
    // Absent from the accessibility tree, not merely styled away: a disabled
    // or visually-hidden control is still announced and still focusable.
    for (const label of ['card.applyNow', 'card.draftEmail', 'card.tailorResume']) {
      expect(screen.queryByText(label)).toBeNull();
      expect(screen.queryByRole('button', { name: label })).toBeNull();
      expect(screen.queryByRole('link', { name: label })).toBeNull();
    }
  });

  it.each(POSTURES)('never links the apply URL for a %s target', (_label, truth) => {
    const { container } = renderWith(truth);
    const hrefs = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(hrefs.some((href) => href?.includes('/apply'))).toBe(false);
  });

  it.each(POSTURES)('still lets the user read the source of a %s target', (_label, truth) => {
    const { container } = renderWith(truth);
    const hrefs = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(hrefs).toContain('https://example.edu/source');
  });

  describe('being actionable is not the same as being a confirmed listing', () => {
    // Every offer term populated and poisonous. The record is live — the
    // server vouches for it — but we have never confirmed it IS a listing, so
    // there is no application whose terms these could be.
    const OFFER_POISON = {
      paid: 'yes',
      compensation_details: 'POISON $32/hr',
      duration: 'POISON 12 weeks',
      opportunity_type: 'POISON_TYPE',
      deadline: '2099-12-31',
      deadline_is_estimate: false,
      posted_date: '2099-01-01',
      eligibility: {
        international_friendly: 'yes',
        preferred_year: [], majors: [],
        skills_required: ['POISON_REQUIRED_SKILL'],
        citizenship_required: null,
      },
      application: {
        application_effort: 'low',
        requires_resume: 'yes',
        requires_recommendation: 'yes',
        contact_method: 'email',
      },
      url: 'https://example.edu/source',
    };

    function renderKind(sourceType: string | undefined) {
      const overrides: Record<string, unknown> = {
        ...OFFER_POISON,
        source_type: sourceType,
        target_truth: { ...ACTIONABLE_TRUTH },
      };
      const opp = makeOpp(overrides as never);
      if (sourceType === undefined) {
        delete (opp as unknown as Record<string, unknown>).source_type;
      }
      return render(
        <MatchCard
          match={{ ...makeMatch(), opportunity: opp }}
          profile={PROFILE}
          onDraftEmail={() => {}}
          ownerReady
        />,
      );
    }

    const OFFER_TEXT = [
      'POISON $32/hr', 'POISON 12 weeks', 'POISON_TYPE', '2099-12-31',
      'badges.dueInDays', 'badges.new', 'results.newMatchBadge',
      'badges.intlOk', 'badges.paid',
    ];

    it('shows no offer terms for a live record of unreviewed kind', () => {
      renderKind(undefined);

      for (const text of OFFER_TEXT) {
        expect(screen.queryByText(text)).toBeNull();
      }
      // It says what it does not know, instead of borrowing the record's own
      // unreviewed type claim.
      expect(screen.getByText('card.recordTypeUnconfirmed')).toBeInTheDocument();
      fireEvent.click(screen.getByText('card.showDetails'));
      expect(screen.queryByText('POISON_REQUIRED_SKILL')).toBeNull();
    });

    it('shows no listing terms for a live faculty profile', () => {
      renderKind('faculty_research');

      for (const text of OFFER_TEXT) {
        expect(screen.queryByText(text)).toBeNull();
      }
      expect(screen.getByText('card.facultyContactUnconfirmed')).toBeInTheDocument();
      expect(screen.queryByText('card.recordTypeUnconfirmed')).toBeNull();
    });

    it('keeps every listing term for a confirmed listing', () => {
      // The control. Without it, hiding everything unconditionally would pass
      // both tests above.
      renderKind('campus_program');

      expect(screen.getByText('POISON_TYPE')).toBeInTheDocument();
      expect(screen.getByText('POISON $32/hr')).toBeInTheDocument();
      expect(screen.getByText('POISON 12 weeks')).toBeInTheDocument();
      expect(screen.getByText('badges.intlOk')).toBeInTheDocument();
      expect(screen.queryByText('card.recordTypeUnconfirmed')).toBeNull();
      fireEvent.click(screen.getByText('card.showDetails'));
      expect(screen.getByText('POISON_REQUIRED_SKILL')).toBeInTheDocument();
    });
  });

  describe('a listing whose kind is known but which is no longer current', () => {
    // Every offer term populated and poisonous. Unlike the unreviewed-kind
    // block above, there is no doubt about what this record IS: it is a
    // campus_program, a listing, and the poison below is a faithful copy of
    // what a listing carries. The only thing that changed is that the server
    // stopped calling it actionable — which is the whole of the claim these
    // terms make.
    const OFFER_POISON = {
      source_type: 'campus_program',
      school: 'ucb',
      audience: 'open',
      paid: 'yes',
      compensation_details: 'POISON $32/hr',
      duration: 'POISON 12 weeks',
      opportunity_type: 'POISON_TYPE',
      deadline: '2099-12-31',
      deadline_is_estimate: false,
      // Yesterday, not a date in 2099. A future posted_date does satisfy
      // isNewPosting today — `Date.now() - future` is negative, which is
      // trivially under the fourteen-day window — but only by accident of
      // sign, and nothing pinned it. Any future hardening against posted
      // dates in the future would flip it to false and quietly retire the
      // "New" half of these assertions without failing anything.
      posted_date: new Date(Date.now() - 86400000).toISOString().slice(0, 10),
      description_clean: 'POISON apply by Friday, stipend paid monthly',
      eligibility: {
        international_friendly: 'yes',
        preferred_year: [], majors: [],
        skills_required: ['POISON_REQUIRED_SKILL'],
        citizenship_required: null,
      },
      application: {
        application_effort: 'low',
        requires_resume: 'yes',
        requires_recommendation: 'yes',
        contact_method: 'email',
        application_url: 'https://example.edu/apply',
      },
      url: 'https://example.edu/source',
    };

    // The full set, named one by one rather than sampled: "New" and the
    // posted-date "new" badge, the type, who may apply, whether it pays, the
    // date and both of its urgency phrasings, the money, the duration, both
    // application requirements, the audience chip, and the description the
    // card has never republished (pinned so it stays that way).
    const OFFER_TEXT = [
      'POISON_TYPE', 'POISON $32/hr', 'POISON 12 weeks',
      '2099-12-31', 'badges.dueInDays', 'badges.deadlinePassed',
      'badges.estimated',
      'badges.new', 'results.newMatchBadge',
      'badges.intlOk', 'badges.paid',
      'card.resumeRequired', 'card.recLetterNeeded',
      'card.scope.openWithHost:UC Berkeley',
      'POISON apply by Friday, stipend paid monthly',
    ];

    // Every non-actionable shape a KNOWN listing can arrive in, paired with
    // the one sentence it is allowed to say. Four rows, four sentences: a
    // closed posting, a reference record, a deactivated row and a truth we
    // could not read are four different facts about a student's options.
    const DEAD: Array<[string, unknown, string]> = [
      ['closed', {
        listing_state: 'closed', reference_only: false, actionable: false,
        accepting_state: 'not_accepting', reason_code: 'listing_closed',
        verified_at: null, expires_at: null,
      }, 'compare.status.closed'],
      ['reference-only', {
        listing_state: 'unknown', reference_only: true, actionable: false,
        accepting_state: 'unknown', reason_code: 'reference_only',
        verified_at: null, expires_at: null,
      }, 'compare.status.reference'],
      ['inactive', {
        listing_state: 'unknown', reference_only: false, actionable: false,
        accepting_state: 'unknown', reason_code: 'inactive',
        verified_at: null, expires_at: null,
      }, 'compare.status.inactive'],
      // Not a reason the backend emits — a truth this build cannot parse.
      // "we could not confirm this" is not "the source says it ended".
      ['unreadable truth', { listing_state: 'open' }, 'compare.status.unverified'],
    ];

    function renderDead(truth: unknown) {
      return render(
        <MatchCard
          match={{
            ...makeMatch(),
            opportunity: makeOpp({ ...OFFER_POISON, target_truth: truth } as never),
          }}
          profile={PROFILE}
          onDraftEmail={() => {}}
          onTrackInteraction={() => {}}
          isNew
          ownerReady
        />,
      );
    }

    it.each(DEAD)('shows no offer term for a %s listing', (_label, truth) => {
      renderDead(truth);
      for (const text of OFFER_TEXT) {
        expect(screen.queryByText(text)).toBeNull();
      }
      fireEvent.click(screen.getByText('card.showDetails'));
      expect(screen.queryByText('POISON_REQUIRED_SKILL')).toBeNull();
    });

    it.each(DEAD)('offers no action on a %s listing', (_label, truth) => {
      renderDead(truth);
      for (const label of ['card.applyNow', 'card.draftEmail', 'card.tailorResume']) {
        expect(screen.queryByText(label)).toBeNull();
        expect(screen.queryByRole('button', { name: label })).toBeNull();
        expect(screen.queryByRole('link', { name: label })).toBeNull();
      }
    });

    it.each(DEAD)('says exactly why for a %s listing', (_label, truth, key) => {
      renderDead(truth);
      expect(screen.getByText(key)).toBeInTheDocument();
      // Only its own sentence. Before this the card said nothing at all here,
      // and the temptation is to reach for "closed" for all four.
      const others = DEAD.map(([, , k]) => k).filter((k) => k !== key);
      for (const other of others) {
        expect(screen.queryByText(other)).toBeNull();
      }
    });

    it.each(DEAD)('keeps identity, score and the source link for a %s listing', (_label, truth) => {
      const { container } = renderDead(truth);
      expect(screen.getByText('Test Opportunity')).toBeInTheDocument();
      expect(screen.getByText('UIUC CS')).toBeInTheDocument();
      // The match score is a statement about fit, not about availability.
      expect(screen.getByText('results.tabs.highPriority')).toBeInTheDocument();
      // The user's own tracking survives — it is their record of their own
      // process, and it outlives the target.
      expect(screen.getByText('results.statusMenu.trigger')).toBeInTheDocument();
      const hrefs = Array.from(container.querySelectorAll('a'))
        .map((a) => a.getAttribute('href'));
      expect(hrefs).toContain('https://example.edu/source');
      expect(hrefs.some((href) => href?.includes('/apply'))).toBe(false);
    });

    it('keeps every one of those terms while the same listing IS current', () => {
      // The control. Hiding all of it unconditionally would pass all four
      // cases above, and would also be a product that shows nothing.
      render(
        <MatchCard
          match={{
            ...makeMatch(),
            opportunity: makeOpp({
              ...OFFER_POISON, target_truth: { ...ACTIONABLE_TRUTH },
            } as never),
          }}
          profile={PROFILE}
          onDraftEmail={() => {}}
          onTrackInteraction={() => {}}
          isNew
          ownerReady
        />,
      );
      expect(screen.getByText('POISON_TYPE')).toBeInTheDocument();
      expect(screen.getByText('POISON $32/hr')).toBeInTheDocument();
      expect(screen.getByText('POISON 12 weeks')).toBeInTheDocument();
      expect(screen.getByText('badges.intlOk')).toBeInTheDocument();
      expect(screen.getByText('results.newMatchBadge')).toBeInTheDocument();
      // The OTHER "new": `results.newMatchBadge` comes from the isNew prop,
      // this one from posted_date. They sit behind two separate gates in the
      // card, so pinning one proves nothing about the other.
      expect(screen.getByText('badges.new')).toBeInTheDocument();
      expect(screen.getByText('card.resumeRequired')).toBeInTheDocument();
      expect(screen.getByText('card.recLetterNeeded')).toBeInTheDocument();
      expect(screen.getByText('card.scope.openWithHost:UC Berkeley')).toBeInTheDocument();
      expect(screen.getByText('card.applyNow')).toBeInTheDocument();
      // And no reason badge, because there is nothing to explain.
      for (const [, , key] of DEAD) {
        expect(screen.queryByText(key)).toBeNull();
      }
      fireEvent.click(screen.getByText('card.showDetails'));
      expect(screen.getByText('POISON_REQUIRED_SKILL')).toBeInTheDocument();
    });

    // The urgency band is a coloured stripe, not text, so none of the
    // queryByText assertions above can see it. It is also the loudest claim on
    // the card: a red rail reads as "act now" from across a page of results.
    const BANDS: Array<[string, string, string]> = [
      ['urgent', new Date(Date.now() + 3 * 86400000).toISOString().slice(0, 10), 'before:bg-red-400'],
      ['soon', new Date(Date.now() + 20 * 86400000).toISOString().slice(0, 10), 'before:bg-amber-400'],
      ['passed', '2000-01-01', 'before:bg-gray-300'],
    ];

    function renderBand(deadline: string, truth: unknown) {
      const { container } = render(
        <MatchCard
          match={{
            ...makeMatch(),
            opportunity: makeOpp({
              ...OFFER_POISON, deadline, target_truth: truth,
            } as never),
          }}
          profile={PROFILE}
          onDraftEmail={() => {}}
          ownerReady
        />,
      );
      return container.querySelector('div.relative')!;
    }

    it.each(BANDS)('draws the %s urgency band while the listing is current', (_label, deadline, cls) => {
      expect(renderBand(deadline, { ...ACTIONABLE_TRUTH }).className).toContain(cls);
    });

    it.each(BANDS)('drops the %s urgency band once the listing is closed', (_label, deadline, cls) => {
      const card = renderBand(deadline, DEAD[0][1]);
      expect(card.className).not.toContain(cls);
      // And not some other band instead — no band at all.
      for (const [, , other] of BANDS) {
        expect(card.className).not.toContain(other);
      }
    });
  });

  it('keeps every control for an actionable target', () => {
    renderWith({
      listing_state: 'open',
      reference_only: false,
      actionable: true,
      accepting_state: 'accepting',
      reason_code: null,
      verified_at: null,
      expires_at: null,
    });
    expect(screen.getByText('card.applyNow')).toBeInTheDocument();
    expect(screen.getByText('card.draftEmail')).toBeInTheDocument();
    expect(screen.getByText('card.tailorResume')).toBeInTheDocument();
  });
});
