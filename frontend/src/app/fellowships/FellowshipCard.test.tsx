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

  it('shows Fellowship badge and preserves fellowship intent in the matcher CTA', () => {
    render(<FellowshipCard opp={makeOpp({ opportunity_type: 'fellowship' })} />);
    expect(screen.getByText('Fellowship')).toBeInTheDocument();
    expect(screen.getByTestId('match-like-this')).toHaveAttribute(
      'href',
      expect.stringContaining('prefill_seeking=fellowship'),
    );
  });

  it('renders the deadline and on-campus location', () => {
    render(<FellowshipCard opp={makeOpp()} />);
    expect(screen.getByText('2026-03-15')).toBeInTheDocument();
    expect(screen.getByText('On campus')).toBeInTheDocument();
  });

  it('labels an estimated deadline so it is not presented as a confirmed date', () => {
    render(<FellowshipCard opp={makeOpp({ deadline_is_estimate: true })} />);
    expect(screen.getByText('2026-03-15')).toBeInTheDocument();
    expect(screen.getByTestId('deadline-estimate')).toHaveTextContent('estimated');
  });

  it.each([false, undefined])(
    'shows no precision caveat when deadline_is_estimate is %s',
    (deadlineIsEstimate) => {
      render(<FellowshipCard opp={makeOpp({ deadline_is_estimate: deadlineIsEstimate })} />);
      expect(screen.getByText('2026-03-15')).toBeInTheDocument();
      expect(screen.queryByTestId('deadline-estimate')).not.toBeInTheDocument();
    },
  );

  it('marks an explicitly inactive listing and removes the matcher CTA', () => {
    render(<FellowshipCard opp={makeOpp({
      metadata: { is_active: false, confidence_score: 0.8 },
    })} />);
    expect(screen.getByTestId('activity-status')).toHaveTextContent(
      'This listing is no longer active.',
    );
    expect(screen.queryByTestId('match-like-this')).not.toBeInTheDocument();
  });

  it.each([
    ['active', makeOpp()],
    ['unknown', makeOpp({ metadata: undefined as unknown as Opportunity['metadata'] })],
  ])('shows no activity badge when activity is %s', (_label, opp) => {
    render(<FellowshipCard opp={opp} />);
    expect(screen.queryByTestId('activity-status')).not.toBeInTheDocument();
    expect(screen.getByTestId('match-like-this')).toBeInTheDocument();
  });

  it('does not present unknown campus status as off campus', () => {
    render(<FellowshipCard opp={makeOpp({
      on_campus: undefined as unknown as boolean,
    })} />);
    expect(screen.queryByText('On campus')).not.toBeInTheDocument();
    expect(screen.queryByText('Off campus')).not.toBeInTheDocument();
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

  it('renders a "Find matches like this" link with the prefill query', () => {
    render(<FellowshipCard opp={makeOpp({
      opportunity_type: 'summer_program',
      eligibility: {
        international_friendly: 'yes',
        preferred_year: ['Junior'],
        majors: ['CS'],
        skills_required: [],
        citizenship_required: false,
      },
    })} />);
    const matchLink = screen.getByTestId('match-like-this');
    const href = matchLink.getAttribute('href') ?? '';
    expect(href).toContain('prefill_year=Junior');
    expect(href).toContain('prefill_seeking=summer_program');
  });

  it('falls back to "/" with no prefill params when preferred_year is invalid', () => {
    render(<FellowshipCard opp={makeOpp({
      opportunity_type: '',
      eligibility: {
        international_friendly: 'yes',
        preferred_year: ['Any'],
        majors: [],
        skills_required: [],
        citizenship_required: false,
      },
    })} />);
    const matchLink = screen.getByTestId('match-like-this');
    expect(matchLink.getAttribute('href')).toBe('/');
  });

  it('uses the first valid year when preferred_year mixes valid + invalid', () => {
    render(<FellowshipCard opp={makeOpp({
      eligibility: {
        international_friendly: 'no',
        preferred_year: ['Graduate', 'Senior', 'Junior'],
        majors: [],
        skills_required: [],
        citizenship_required: false,
      },
    })} />);
    const matchLink = screen.getByTestId('match-like-this');
    expect(matchLink.getAttribute('href')).toContain('prefill_year=Senior');
  });
});
