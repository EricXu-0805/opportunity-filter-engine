import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SavedSearchHealthSection } from './SavedSearchHealthSection';
import { translate } from '@/i18n/translate';
import type { SavedSearchHealth, TFunc } from './types';

const t: TFunc = (key) => key;

const okHealth = (overrides: Partial<SavedSearchHealth> = {}): SavedSearchHealth => ({
  status: 'ok',
  searches: { total: 12, digest_opt_in: 3 },
  refresh: { last_run_at: '2026-06-10T06:00:00+00:00', never_run: 0, stale_over_48h: 0 },
  digest: { last_sent_at: '2026-06-08T12:00:00+00:00', opted_in_never_sent: 0 },
  resend_configured: true,
  generated_at: '2026-06-11T00:00:00+00:00',
  ...overrides,
});

describe('SavedSearchHealthSection', () => {
  it('renders nothing while health has not loaded', () => {
    const { container } = render(<SavedSearchHealthSection health={null} t={t} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders unconfigured as a quiet notice, not an error', () => {
    render(
      <SavedSearchHealthSection
        health={{ status: 'unconfigured', missing: ['SUPABASE_URL'] }}
        t={t}
      />,
    );
    const notice = screen.getByText('admin.savedSearch.unconfigured');
    expect(notice).toHaveClass('text-gray-400', 'italic');
    expect(screen.queryByText('admin.savedSearch.totalSearches')).toBeNull();
    expect(document.querySelector('.text-red-800')).toBeNull();
  });

  it('renders the stat tiles with the backend numbers', () => {
    render(<SavedSearchHealthSection health={okHealth()} t={t} />);
    expect(screen.getByText('admin.savedSearch.title')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('admin.savedSearch.neverRun')).toBeInTheDocument();
    expect(screen.getByText('admin.savedSearch.staleRuns')).toBeInTheDocument();
    expect(screen.getByText('admin.savedSearch.optedInNeverSent')).toBeInTheDocument();
  });

  it('paints problem counters amber and clean counters green', () => {
    const { container } = render(
      <SavedSearchHealthSection
        health={okHealth({ refresh: { last_run_at: null, never_run: 5, stale_over_48h: 0 } })}
        t={t}
      />,
    );
    expect(container.querySelectorAll('.bg-amber-50').length).toBe(1);
    expect(container.querySelectorAll('.bg-emerald-50').length).toBe(2);
  });

  it('shows the never label when timestamps are missing', () => {
    render(
      <SavedSearchHealthSection
        health={okHealth({
          refresh: { last_run_at: null, never_run: 2, stale_over_48h: 0 },
          digest: { last_sent_at: null, opted_in_never_sent: 1 },
        })}
        t={t}
      />,
    );
    expect(screen.getAllByText(/admin\.savedSearch\.never$/)).toHaveLength(2);
  });

  it('shows the resend pill green when configured, amber warning when not', () => {
    const { rerender } = render(<SavedSearchHealthSection health={okHealth()} t={t} />);
    expect(screen.getByText('admin.savedSearch.resendOk')).toBeInTheDocument();
    expect(screen.queryByText('admin.savedSearch.resendMissing')).toBeNull();

    rerender(
      <SavedSearchHealthSection health={okHealth({ resend_configured: false })} t={t} />,
    );
    expect(screen.getByText('admin.savedSearch.resendMissing')).toBeInTheDocument();
    expect(screen.queryByText('admin.savedSearch.resendOk')).toBeNull();
  });

  it('has every i18n key it uses in both en and zh dictionaries', () => {
    const keys = [
      'admin.savedSearch.title',
      'admin.savedSearch.unconfigured',
      'admin.savedSearch.totalSearches',
      'admin.savedSearch.digestOptIn',
      'admin.savedSearch.neverRun',
      'admin.savedSearch.staleRuns',
      'admin.savedSearch.optedInNeverSent',
      'admin.savedSearch.lastRefreshRun',
      'admin.savedSearch.lastDigestSent',
      'admin.savedSearch.never',
      'admin.savedSearch.resendOk',
      'admin.savedSearch.resendMissing',
    ];
    for (const key of keys) {
      // translate falls back to the key path when a dictionary entry is missing
      expect(translate('en', key), `en missing ${key}`).not.toBe(key);
      expect(translate('zh', key), `zh missing ${key}`).not.toBe(key);
    }
  });
});
