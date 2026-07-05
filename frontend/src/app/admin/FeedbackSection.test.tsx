import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FeedbackSection } from './FeedbackSection';
import type { FeedbackInbox, TFunc } from './types';

const t: TFunc = (key) => key;

const okInbox = (overrides: Partial<FeedbackInbox> = {}): FeedbackInbox => ({
  status: 'ok',
  count: 2,
  entries: [
    {
      id: 'f1',
      created_at: '2026-07-04T10:00:00+00:00',
      message: 'The compare page is great',
      email: 'student@illinois.edu',
      props: { path: '/compare' },
    },
    {
      id: 'f2',
      created_at: '2026-07-03T09:00:00+00:00',
      message: 'Add more schools please',
      email: null,
      props: {},
    },
  ],
  match_feedback: {
    up: 10,
    down: 4,
    up_7d: 3,
    down_7d: 1,
    sample_size: 14,
    top_downvoted: [{ opportunity_id: 'opp-1', downs: 3, title: 'CV Lab' }],
  },
  ...overrides,
});

describe('FeedbackSection', () => {
  it('renders nothing while the inbox has not loaded', () => {
    const { container } = render(<FeedbackSection inbox={null} t={t} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders unconfigured as a quiet notice', () => {
    render(<FeedbackSection inbox={{ status: 'skipped', reason: 'supabase env not configured' }} t={t} />);
    expect(screen.getByText('admin.feedback.unconfigured')).toBeInTheDocument();
  });

  it('renders messages with path, email, and thumbs summary', () => {
    render(<FeedbackSection inbox={okInbox()} t={t} />);
    expect(screen.getByText('The compare page is great')).toBeInTheDocument();
    expect(screen.getByText('/compare')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'student@illinois.edu' })).toHaveAttribute(
      'href',
      'mailto:student@illinois.edu',
    );
    expect(screen.getByText('CV Lab', { exact: false })).toBeInTheDocument();
  });

  it('renders the empty state when there are no messages', () => {
    render(<FeedbackSection inbox={okInbox({ entries: [], count: 0 })} t={t} />);
    expect(screen.getByText('admin.feedback.empty')).toBeInTheDocument();
  });
});
