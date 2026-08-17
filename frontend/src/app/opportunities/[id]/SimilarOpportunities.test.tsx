import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { SimilarOpportunity } from '@/lib/api-server';
import { SimilarOpportunities } from './SimilarOpportunities';

const t = (key: string) => key;

describe('SimilarOpportunities faculty trust boundary', () => {
  it('does not render poisoned faculty pay as an opening fact', () => {
    const faculty = {
      id: 'faculty-ada',
      title: 'Ada profile',
      organization: 'Test University',
      opportunity_type: 'research',
      source_type: 'faculty_research',
      paid: 'yes',
      _similarity: 0.9,
    } as SimilarOpportunity;

    render(<SimilarOpportunities similar={[faculty]} t={t} />);

    expect(screen.getByText('Ada profile')).toBeInTheDocument();
    expect(screen.queryByText('badges.paid')).toBeNull();
  });
});
