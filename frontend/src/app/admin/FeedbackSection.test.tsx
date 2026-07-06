import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FeedbackSection } from './FeedbackSection';
import type { FeedbackAnalysis, FeedbackInbox, TFunc } from './types';

const t: TFunc = (key, vars) =>
  vars ? `${key} ${Object.entries(vars).map(([k, v]) => `${k}=${v}`).join(' ')}` : key;

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

  const withAnalysis = (analysis: FeedbackAnalysis): FeedbackInbox => {
    const base = okInbox();
    return { ...base, match_feedback: { ...base.match_feedback!, analysis } };
  };

  it('renders the insufficient-sample notice under 50 votes', () => {
    render(
      <FeedbackSection inbox={withAnalysis({ insufficient: true, needed: 50, sample_n: 14 })} t={t} />,
    );
    expect(screen.getByText('admin.feedback.analysisTitle')).toBeInTheDocument();
    expect(screen.getByText('admin.feedback.analysisInsufficient n=14 needed=50')).toBeInTheDocument();
    expect(screen.queryByText('admin.feedback.analysisByBucket')).not.toBeInTheDocument();
  });

  it('renders breakdown rows and the degraded replay line at >= 50 votes', () => {
    render(
      <FeedbackSection
        inbox={withAnalysis({
          sample_n: 60,
          up_rate: 0.65,
          by_bucket: [{ key: 'high_priority', n: 40, up_rate: 0.9 }],
          by_score_band: [{ key: '80-100', n: 40, up_rate: 0.9 }, { key: '40-60', n: 20, up_rate: 0.2 }],
          by_school: [{ key: 'uiuc', n: 55, up_rate: 0.7 }],
          by_position: [],
          replay: {
            mode: 'score_band_agreement',
            current_agreement: 0.82,
            best_candidate: null,
            delta: null,
            sample_n: 60,
            note: 'component scores not stored',
          },
        })}
        t={t}
      />,
    );
    expect(screen.getByText('admin.feedback.analysisUpRate rate=65 n=60')).toBeInTheDocument();
    expect(screen.getByText('high_priority')).toBeInTheDocument();
    expect(screen.getByText('80-100')).toBeInTheDocument();
    expect(screen.getByText('uiuc')).toBeInTheDocument();
    // empty position breakdown renders nothing
    expect(screen.queryByText('admin.feedback.analysisByPosition')).not.toBeInTheDocument();
    expect(screen.getByText(/analysisAgreement value=82%/)).toBeInTheDocument();
    expect(screen.getByText('component scores not stored')).toBeInTheDocument();
    // degraded mode never shows a weight candidate
    expect(screen.queryByText(/analysisReplayBest/)).not.toBeInTheDocument();
  });

  it('renders the best weight candidate in replay mode', () => {
    render(
      <FeedbackSection
        inbox={withAnalysis({
          sample_n: 80,
          up_rate: 0.5,
          replay: {
            mode: 'weight_replay',
            current_agreement: 0.7,
            best_candidate: { eligibility: 0.4286, readiness: 0.3333, upside: 0.2381 },
            delta: 0.05,
            sample_n: 80,
            note: 'offline replay only — weights are never auto-applied',
          },
        })}
        t={t}
      />,
    );
    expect(
      screen.getByText(/analysisReplayBest weights=0\.4286\/0\.3333\/0\.2381 delta=\+5%/),
    ).toBeInTheDocument();
  });
});
