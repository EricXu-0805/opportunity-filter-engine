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

describe('OpportunityHeader MVP release surface', () => {
  it('keeps Tailor while hiding unaccepted Renovate and professor signals', () => {
    render(
      <OpportunityHeader
        opp={OPP}
        profile={PROFILE}
        isFavorited={false}
        shareCopied={false}
        onStar={noop}
        onOpenEmailModal={noop}
        onOpenTailorModal={noop}
        onOpenRenovationModal={undefined}
        onShare={noop}
        t={t}
      />,
    );

    expect(screen.getByText('card.tailorResume')).toBeInTheDocument();
    expect(screen.queryByText('card.renovateResume')).not.toBeInTheDocument();
    expect(screen.queryByText('unaccepted-professor-signal')).not.toBeInTheDocument();
  });
});
