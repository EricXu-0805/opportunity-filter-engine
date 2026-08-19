import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { Opportunity, ProfileData } from '@/lib/types';

vi.mock('@/components/ResponsivenessBadge', () => ({
  default: () => <span>unaccepted-professor-signal</span>,
}));

import { OpportunityHeader } from './OpportunityHeader';

const OPP = {
  id: 'opp-1',
  title: 'Research Opportunity',
  organization: 'Example Lab',
  opportunity_type: 'Research',
  metadata: { is_active: true, confidence_score: 0.9 },
} as Opportunity;

const PROFILE = {
  institution: 'Example University',
  major: 'Computer Science',
  grade: 'Junior',
  research_interests: 'machine learning',
  skills: [{ name: 'Python', level: 'experienced' }],
} as ProfileData;

const noop = () => {};
const t = (key: string) => key;

function renderHeader(overrides: Partial<React.ComponentProps<typeof OpportunityHeader>> = {}) {
  return render(
    <OpportunityHeader
      opp={OPP}
      profile={PROFILE}
      isFavorited={false}
      favoriteDisabled={false}
      favoriteBusy={false}
      shareCopied={false}
      onStar={noop}
      onOpenEmailModal={noop}
      onOpenTailorModal={noop}
      tailorDisabled={false}
      onOpenRenovationModal={undefined}
      onShare={noop}
      t={t}
      {...overrides}
    />,
  );
}

describe('OpportunityHeader MVP release surface', () => {
  it('keeps Tailor while hiding Professor Signals', () => {
    renderHeader();

    expect(screen.getByText('card.tailorResume')).toBeInTheDocument();
    expect(screen.queryByText('unaccepted-professor-signal')).not.toBeInTheDocument();
  });

  it('labels a faculty directory record as a contact, not a confirmed opening', () => {
    renderHeader({
      opp: {
        ...OPP,
        source_type: 'faculty_research',
        url: 'https://faculty.example.edu/real-profile',
        paid: 'yes',
        on_campus: true,
        remote_option: 'yes',
        deadline: '2020-01-01',
        deadline_is_estimate: false,
        eligibility: {
          international_friendly: 'yes',
          citizenship_required: false,
          preferred_year: [],
          majors: [],
          skills_required: [],
        },
        application: {
          application_effort: 'unknown',
          requires_resume: 'unknown',
          contact_method: 'email',
          application_url: 'https://fake.example.edu/apply',
        },
      },
    });
    expect(screen.getByText('card.facultyContactUnconfirmed')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'detail.viewFacultyProfile' })).toHaveAttribute(
      'href',
      'https://faculty.example.edu/real-profile',
    );
    expect(screen.queryByRole('link', { name: 'detail.apply' })).not.toBeInTheDocument();
    expect(screen.queryByText('badges.paid')).not.toBeInTheDocument();
    expect(screen.queryByText('badges.onCampus')).not.toBeInTheDocument();
    expect(screen.queryByText('badges.remoteOk')).not.toBeInTheDocument();
    expect(screen.queryByText('badges.internationalFriendly')).not.toBeInTheDocument();
    expect(screen.queryByText('badges.pastDeadline')).not.toBeInTheDocument();
    expect(screen.queryByText('2020-01-01')).not.toBeInTheDocument();
  });

  it('renders an undergraduate stop state and hides Draft Email', () => {
    renderHeader({
      opp: {
        ...OPP,
        source_type: 'faculty_research',
        faculty_availability_status: 'not_accepting_undergraduates',
        url: 'https://faculty.example.edu/profile',
      },
    });

    expect(screen.getByText('card.facultyNotAcceptingUndergraduates')).toBeInTheDocument();
    expect(screen.queryByText('card.facultyContactUnconfirmed')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'detail.draftEmail' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'detail.viewFacultyProfile' })).toBeInTheDocument();
  });

  it('renders research inactivity as a warning without disabling an inquiry', () => {
    renderHeader({
      opp: {
        ...OPP,
        source_type: 'faculty_research',
        faculty_availability_status: 'research_inactive',
      },
    });
    expect(screen.getByText('card.facultyResearchInactive')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'detail.draftEmail' })).toBeInTheDocument();
  });

  it('shows Renovate only when the parent supplies its handler', () => {
    // This leaf does not read the release flag. OpportunityDetail owns the
    // public gate; this preserves dormant implementation coverage without
    // making the MVP surface reachable.
    renderHeader();
    expect(screen.queryByText('card.renovateResume')).not.toBeInTheDocument();

    renderHeader({ onOpenRenovationModal: noop });
    expect(screen.getByText('card.renovateResume')).toBeInTheDocument();
  });
});

describe('OpportunityHeader favorite control — disabled vs busy', () => {
  it('is enabled and not busy in the normal (idle) state', () => {
    renderHeader({ favoriteDisabled: false, favoriteBusy: false });
    const star = screen.getByRole('button', { name: 'detail.favoriteAdd' });
    expect(star).not.toBeDisabled();
    expect(star).toHaveAttribute('aria-busy', 'false');
  });

  it('is disabled and busy while hydration/save is actually in flight', () => {
    renderHeader({ favoriteDisabled: true, favoriteBusy: true });
    const star = screen.getByRole('button', { name: 'detail.favoriteAdd' });
    expect(star).toBeDisabled();
    expect(star).toHaveAttribute('aria-busy', 'true');
  });

  it('is disabled but NOT busy after a hydration failure — an error is not "busy", and Retry (elsewhere) is the only recovery path', () => {
    renderHeader({ favoriteDisabled: true, favoriteBusy: false });
    const star = screen.getByRole('button', { name: 'detail.favoriteAdd' });
    expect(star).toBeDisabled();
    expect(star).toHaveAttribute('aria-busy', 'false');
  });
});
