import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import FellowshipCard from './FellowshipCard';
import type { Opportunity } from '@/lib/types';

function makeOpp(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: 'demo-1',
    title: 'Demo Summer Program',
    organization: 'UIUC Demo Lab',
    opportunity_type: 'summer_program',
    paid: 'yes',
    location: 'on_campus',
    on_campus: true,
    description_clean: '',
    keywords: [],
    deadline: '2026-03-15',
    url: 'https://example.com/program',
    eligibility: {
      international_friendly: 'yes',
      preferred_year: ['junior'],
      majors: ['CS'],
      skills_required: [],
      citizenship_required: false,
    },
    application: {
      contact_method: 'email',
      requires_resume: 'yes',
      application_effort: 'low',
    },
    metadata: { is_active: true, confidence_score: 0.8 },
    ...overrides,
  };
}

describe('FellowshipCard', () => {
  it('renders the title as an external link', () => {
    render(<FellowshipCard opp={makeOpp()} />);
    const link = screen.getByRole('link', { name: 'Demo Summer Program' });
    expect(link).toHaveAttribute('href', 'https://example.com/program');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('renders the organization line', () => {
    render(<FellowshipCard opp={makeOpp()} />);
    expect(screen.getByText('UIUC Demo Lab')).toBeInTheDocument();
  });

  it('shows Paid badge when paid=yes', () => {
    render(<FellowshipCard opp={makeOpp({ paid: 'yes' })} />);
    expect(screen.getByText('Paid')).toBeInTheDocument();
  });

  it('shows International OK badge when international_friendly=yes', () => {
    render(<FellowshipCard opp={makeOpp()} />);
    expect(screen.getByText('International OK')).toBeInTheDocument();
  });

  it('shows Summer badge for summer_program type', () => {
    render(<FellowshipCard opp={makeOpp()} />);
    expect(screen.getByText('Summer')).toBeInTheDocument();
  });

  it('renders the deadline and on-campus location', () => {
    render(<FellowshipCard opp={makeOpp()} />);
    expect(screen.getByText('2026-03-15')).toBeInTheDocument();
    expect(screen.getByText('On campus')).toBeInTheDocument();
  });

  it('uses an internal Link when opp has no http url (falls back to /opportunities/<id>)', () => {
    render(<FellowshipCard opp={makeOpp({ url: '', source_url: '' })} />);
    const link = screen.getByRole('link', { name: 'Demo Summer Program' });
    expect(link.getAttribute('href')).toBe('/opportunities/demo-1');
  });

  it('omits Paid badge when paid=no', () => {
    render(<FellowshipCard opp={makeOpp({ paid: 'no' })} />);
    expect(screen.queryByText('Paid')).not.toBeInTheDocument();
  });
});
