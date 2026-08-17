import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Opportunity } from '@/lib/types';
import DifferencesSection from './DifferencesSection';

function opportunity(id: string): Opportunity {
  return {
    id,
    title: id,
    organization: 'Test University',
    opportunity_type: 'research',
    paid: 'unknown',
    location: '',
    on_campus: null,
    description_clean: '',
    keywords: [],
    eligibility: {
      preferred_year: [],
      majors: [],
      skills_required: [],
      international_friendly: 'unknown',
      citizenship_required: null,
    },
    application: {
      application_effort: 'unknown',
      requires_resume: 'unknown',
      contact_method: 'unknown',
    },
    metadata: { is_active: true, confidence_score: 0.9 },
  } as Opportunity;
}

describe('DifferencesSection faculty trust boundary', () => {
  it('labels a poisoned faculty deadline as unconfirmed, not a fixed opening date', () => {
    const faculty = {
      ...opportunity('faculty-contact'),
      source_type: 'faculty_research',
      deadline: '2099-12-31',
      deadline_is_estimate: false,
      is_rolling: true,
    } as Opportunity;
    const listing = {
      ...opportunity('real-listing'),
      source_type: 'campus_program',
      deadline: '2027-02-01',
      deadline_is_estimate: false,
    } as Opportunity;

    render(<DifferencesSection rows={[{ opp: faculty }, { opp: listing }]} profile={null} />);

    expect(screen.getByTestId('compare-value-deadline-faculty-contact')).toHaveTextContent(
      'Current opening and deadline not confirmed',
    );
    expect(screen.queryByText('2099-12-31')).toBeNull();
    expect(screen.getByText('2027-02-01')).toBeInTheDocument();
  });
});
