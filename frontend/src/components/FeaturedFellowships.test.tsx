import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string) => key,
  }),
}));

const mockGetFeatured = vi.fn();
vi.mock('@/lib/api', () => ({
  getFeaturedFellowships: (limit: number) => mockGetFeatured(limit),
}));

import FeaturedFellowships from './FeaturedFellowships';
import type { Opportunity } from '@/lib/types';

const makeOpp = (overrides: Partial<Opportunity> = {}): Opportunity => ({
  id: 'opp-1',
  title: 'SURF Summer Program',
  organization: 'Beckman Institute',
  opportunity_type: 'summer_program',
  paid: 'yes',
  location: 'Urbana, IL',
  on_campus: true,
  deadline: '2026-02-15',
  description_clean: 'desc',
  keywords: [],
  eligibility: {
    international_friendly: 'yes',
    preferred_year: ['Junior'],
    majors: ['CS'],
    skills_required: [],
    citizenship_required: false,
  },
  application: {
    application_effort: 'medium',
    requires_resume: 'yes',
    contact_method: 'email',
  },
  metadata: { is_active: true, confidence_score: 0.9 },
  ...overrides,
});

beforeEach(() => {
  mockGetFeatured.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('FeaturedFellowships', () => {
  it('shows the skeleton while loading', () => {
    mockGetFeatured.mockReturnValue(new Promise(() => {}));
    render(<FeaturedFellowships />);
    const section = screen.getByTestId('featured-fellowships');
    expect(section.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it('renders 3 cards when the API returns 3 opportunities', async () => {
    mockGetFeatured.mockResolvedValue({
      opportunities: [
        makeOpp({ id: 'a', title: 'Alpha REU' }),
        makeOpp({ id: 'b', title: 'Beta SROP' }),
        makeOpp({ id: 'c', title: 'Gamma Fellowship' }),
      ],
      total: 3,
    });
    render(<FeaturedFellowships />);
    await waitFor(() => expect(screen.getByText('Alpha REU')).toBeInTheDocument());
    expect(screen.getByText('Beta SROP')).toBeInTheDocument();
    expect(screen.getByText('Gamma Fellowship')).toBeInTheDocument();
  });

  it('caps display at 3 cards even if the API returns more', async () => {
    mockGetFeatured.mockResolvedValue({
      opportunities: Array.from({ length: 8 }, (_, i) => makeOpp({ id: String(i), title: `Opp ${i}` })),
      total: 8,
    });
    render(<FeaturedFellowships />);
    await waitFor(() => expect(screen.getByText('Opp 0')).toBeInTheDocument());
    expect(screen.queryByText('Opp 3')).toBeNull();
  });

  it('renders external URL with target=_blank rel=noopener noreferrer', async () => {
    mockGetFeatured.mockResolvedValue({
      opportunities: [makeOpp({ id: 'ext', title: 'External REU', url: 'https://example.edu/reu' })],
      total: 1,
    });
    render(<FeaturedFellowships />);
    await waitFor(() => expect(screen.getByText('External REU')).toBeInTheDocument());
    const link = screen.getByText('External REU').closest('a');
    expect(link?.getAttribute('href')).toBe('https://example.edu/reu');
    expect(link?.getAttribute('target')).toBe('_blank');
    expect(link?.getAttribute('rel')).toContain('noopener');
    expect(link?.getAttribute('rel')).toContain('noreferrer');
  });

  it('renders internal route when url is missing', async () => {
    mockGetFeatured.mockResolvedValue({
      opportunities: [makeOpp({ id: 'int-42', title: 'Internal Program', url: undefined })],
      total: 1,
    });
    render(<FeaturedFellowships />);
    await waitFor(() => expect(screen.getByText('Internal Program')).toBeInTheDocument());
    const link = screen.getByText('Internal Program').closest('a');
    expect(link?.getAttribute('href')).toBe('/opportunities/int-42');
    expect(link?.getAttribute('target')).toBeNull();
  });

  it('renders nothing when the API returns no opportunities', async () => {
    mockGetFeatured.mockResolvedValue({ opportunities: [], total: 0 });
    const { container } = render(<FeaturedFellowships />);
    await waitFor(() => expect(container.querySelector('[data-testid="featured-fellowships"]')).toBeNull());
  });

  it('renders nothing when the API fails', async () => {
    mockGetFeatured.mockRejectedValue(new Error('500'));
    const { container } = render(<FeaturedFellowships />);
    await waitFor(() => expect(container.querySelector('[data-testid="featured-fellowships"]')).toBeNull());
  });

  it('renders the browse-all CTA link to /fellowships', async () => {
    mockGetFeatured.mockResolvedValue({
      opportunities: [makeOpp()],
      total: 1,
    });
    render(<FeaturedFellowships />);
    await waitFor(() => expect(screen.getByText('home.featured.cta')).toBeInTheDocument());
    const cta = screen.getByText('home.featured.cta').closest('a');
    expect(cta?.getAttribute('href')).toBe('/fellowships');
  });

  it('requests exactly 3 opportunities on mount', async () => {
    mockGetFeatured.mockResolvedValue({ opportunities: [makeOpp()], total: 1 });
    render(<FeaturedFellowships />);
    await waitFor(() => expect(mockGetFeatured).toHaveBeenCalledWith(3));
  });

  it('renders paid and intl badges when present', async () => {
    mockGetFeatured.mockResolvedValue({
      opportunities: [
        makeOpp({ paid: 'yes', eligibility: { international_friendly: 'yes', preferred_year: [], majors: [], skills_required: [], citizenship_required: false } }),
      ],
      total: 1,
    });
    render(<FeaturedFellowships />);
    await waitFor(() => expect(screen.getByText('home.featured.paid')).toBeInTheDocument());
    expect(screen.getByText('home.featured.intl')).toBeInTheDocument();
  });

  it('omits badges when paid/intl are not yes', async () => {
    mockGetFeatured.mockResolvedValue({
      opportunities: [makeOpp({ paid: 'no', eligibility: { international_friendly: 'no', preferred_year: [], majors: [], skills_required: [], citizenship_required: false } })],
      total: 1,
    });
    render(<FeaturedFellowships />);
    await waitFor(() => expect(screen.getByText('SURF Summer Program')).toBeInTheDocument());
    expect(screen.queryByText('home.featured.paid')).toBeNull();
    expect(screen.queryByText('home.featured.intl')).toBeNull();
  });

  it('renders the deadline label and formatted date', async () => {
    mockGetFeatured.mockResolvedValue({
      opportunities: [makeOpp({ deadline: '2026-03-21' })],
      total: 1,
    });
    render(<FeaturedFellowships />);
    await waitFor(() => expect(screen.getByText(/home.featured.deadlineLabel/)).toBeInTheDocument());
  });

  it('skips the deadline line when deadline is missing', async () => {
    mockGetFeatured.mockResolvedValue({
      opportunities: [makeOpp({ deadline: undefined })],
      total: 1,
    });
    render(<FeaturedFellowships />);
    await waitFor(() => expect(screen.getByText('SURF Summer Program')).toBeInTheDocument());
    expect(screen.queryByText(/home.featured.deadlineLabel/)).toBeNull();
  });
});
