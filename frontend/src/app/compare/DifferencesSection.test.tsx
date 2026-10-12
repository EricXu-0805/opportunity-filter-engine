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

describe('DifferencesSection source notes', () => {
  const configured = {
    ...opportunity('configured'),
    source_type: 'campus_program',
    is_rolling: true,
    deadline_note_attribution: 'inferred',
    metadata: { is_active: true, confidence_score: 0.9, deadline_note: 'Rolling; SURF cycles' },
    eligibility: {
      ...opportunity('configured').eligibility,
      majors: ['Biology'], preferred_year: ['junior'],
    },
    majors_attribution: 'inferred', majors_basis: 'configured',
    preferred_year_attribution: 'inferred', preferred_year_basis: 'configured',
  } as unknown as Opportunity;
  const banked = {
    ...opportunity('banked'),
    source_type: 'campus_program',
    eligibility: { ...opportunity('banked').eligibility, majors: ['Chemistry'], preferred_year: ['senior'] },
    majors_attribution: 'inferred', preferred_year_attribution: 'inferred',
  } as unknown as Opportunity;
  const stated = {
    ...opportunity('stated'),
    source_type: 'campus_program',
    eligibility: { ...opportunity('stated').eligibility, majors: ['Physics'], preferred_year: ['sophomore'] },
  } as unknown as Opportunity;

  it('says whose a major list, class-year list and "Rolling" are when the page does not state them', () => {
    render(<DifferencesSection rows={[{ opp: configured }, { opp: banked }, { opp: stated }]} profile={null} />);

    expect(screen.getByTestId('compare-source-note-majors-configured')).toHaveTextContent(
      'From our listing’s major list, not confirmed on the program page.',
    );
    expect(screen.getByTestId('compare-source-note-preferredYear-configured')).toHaveTextContent(
      'From our listing’s class-year list, not confirmed on the program page.',
    );
    expect(screen.getByTestId('compare-source-note-deadline-configured')).toHaveTextContent(
      'From our listing’s deadline note, not confirmed on the program page.',
    );
    expect(screen.getByTestId('compare-source-note-majors-banked')).toHaveTextContent(
      'Matched from the program’s research areas',
    );
    expect(screen.queryByTestId('compare-source-note-majors-stated')).toBeNull();
    expect(screen.queryByTestId('compare-source-note-preferredYear-stated')).toBeNull();
  });
});
