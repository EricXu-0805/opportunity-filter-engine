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
  it('shows the professor signal now that professorSignals is accepted', () => {
    renderHeader();

    expect(screen.getByText('card.tailorResume')).toBeInTheDocument();
    expect(screen.getByText('unaccepted-professor-signal')).toBeInTheDocument();
  });

  it('shows Renovate only when the parent supplies its handler', () => {
    // resumeRenovate is accepted, but this component does not read the flag —
    // OpportunityDetail does, and expresses the decision by passing (or not
    // passing) onOpenRenovationModal. Keeping that split tested means the flag
    // has exactly one reader per surface.
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
