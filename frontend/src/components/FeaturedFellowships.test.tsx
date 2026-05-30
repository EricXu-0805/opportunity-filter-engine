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

// Always 90 days into the future relative to the test run, so the R49
// past-deadline filter never accidentally hides these fixtures.
const FUTURE_DEADLINE_ISO = (() => {
  const d = new Date();
  d.setDate(d.getDate() + 90);
  return d.toISOString().split('T')[0];
})();

const FAR_FUTURE_DEADLINE_ISO = (() => {
  const d = new Date();
  d.setDate(d.getDate() + 365);
  return d.toISOString().split('T')[0];
})();

const PAST_DEADLINE_ISO = (() => {
  const d = new Date();
  d.setDate(d.getDate() - 7);
  return d.toISOString().split('T')[0];
})();

const makeOpp = (overrides: Partial<Opportunity> = {}): Opportunity => ({
  id: 'opp-1',
  title: 'SURF Summer Program',
  organization: 'Beckman Institute',
  opportunity_type: 'summer_program',
  paid: 'yes',
  location: 'Urbana, IL',
  on_campus: true,
  deadline: FUTURE_DEADLINE_ISO,
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

  it('requests a larger pool on mount so the frontend filter has room to work', async () => {
    mockGetFeatured.mockResolvedValue({ opportunities: [makeOpp()], total: 1 });
    render(<FeaturedFellowships />);
    await waitFor(() => expect(mockGetFeatured).toHaveBeenCalledWith(12));
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
      opportunities: [makeOpp({ deadline: FAR_FUTURE_DEADLINE_ISO })],
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

  it('filters past-deadline opportunities out of the previewed cards (R49)', async () => {
    mockGetFeatured.mockResolvedValue({
      opportunities: [
        makeOpp({ id: 'past-1', title: 'Stale Alpha', deadline: PAST_DEADLINE_ISO }),
        makeOpp({ id: 'future-1', title: 'Fresh Bravo', deadline: FUTURE_DEADLINE_ISO }),
        makeOpp({ id: 'past-2', title: 'Stale Charlie', deadline: PAST_DEADLINE_ISO }),
      ],
      total: 3,
    });
    render(<FeaturedFellowships />);
    await waitFor(() => expect(screen.getByText('Fresh Bravo')).toBeInTheDocument());
    expect(screen.queryByText('Stale Alpha')).toBeNull();
    expect(screen.queryByText('Stale Charlie')).toBeNull();
  });

  it('renders nothing when every returned opportunity is past-deadline (R49)', async () => {
    mockGetFeatured.mockResolvedValue({
      opportunities: [
        makeOpp({ id: 'past-1', title: 'Stale 1', deadline: PAST_DEADLINE_ISO }),
        makeOpp({ id: 'past-2', title: 'Stale 2', deadline: PAST_DEADLINE_ISO }),
      ],
      total: 2,
    });
    const { container } = render(<FeaturedFellowships />);
    await waitFor(() =>
      expect(container.querySelector('[data-testid="featured-fellowships"]')).toBeNull(),
    );
  });

  it('orders surviving cards by urgency, soonest deadline first (R49)', async () => {
    mockGetFeatured.mockResolvedValue({
      opportunities: [
        makeOpp({ id: 'far', title: 'Faraway', deadline: FAR_FUTURE_DEADLINE_ISO }),
        makeOpp({ id: 'soon', title: 'Soon', deadline: FUTURE_DEADLINE_ISO }),
      ],
      total: 2,
    });
    render(<FeaturedFellowships />);
    await waitFor(() => expect(screen.getByText('Soon')).toBeInTheDocument());

    const titles = screen
      .getAllByRole('heading', { level: 3 })
      .map((el) => el.textContent ?? '');
    expect(titles).toEqual(['Soon', 'Faraway']);
  });

  it('places undated (rolling) opportunities after dated ones in the ranking (R49)', async () => {
    mockGetFeatured.mockResolvedValue({
      opportunities: [
        makeOpp({ id: 'rolling', title: 'Rolling Admit', deadline: undefined }),
        makeOpp({ id: 'soon', title: 'Soon', deadline: FUTURE_DEADLINE_ISO }),
      ],
      total: 2,
    });
    render(<FeaturedFellowships />);
    await waitFor(() => expect(screen.getByText('Soon')).toBeInTheDocument());

    const titles = screen
      .getAllByRole('heading', { level: 3 })
      .map((el) => el.textContent ?? '');
    expect(titles).toEqual(['Soon', 'Rolling Admit']);
  });
});
