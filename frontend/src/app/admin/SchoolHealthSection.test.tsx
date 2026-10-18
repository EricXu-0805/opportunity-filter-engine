import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { SchoolHealthSection } from './SchoolHealthSection';
import { translate } from '@/i18n/translate';
import type { SchoolHealthRow, SchoolHealthWorkflow, SourceHealthRow, TFunc } from './types';

const t = ((key: string, vars?: Record<string, string | number>) => translate('en', key, vars)) as TFunc;

// Shaped like the committed ledger's Barnard: both sources last succeeded on
// 2026-08-29 while the shard file was rewritten on 2026-10-17.
const barnard = (overrides: Partial<SchoolHealthRow> = {}): SchoolHealthRow => ({
  school: 'barnard',
  state: 'fully_stale',
  fully_stale: true,
  fresh_shard_count: 0,
  warn_shard_count: 0,
  stale_shard_count: 2,
  failed_shard_count: 1,
  degraded_shard_count: 2,
  total_shard_count: 2,
  oldest_stale_age_days: 49.3,
  last_successful_school_activity: '2026-08-29T08:10:26.800836+00:00',
  oldest_success_at: '2026-08-29T06:09:04.593969+00:00',
  never_succeeded_shard_count: 0,
  coverage_current_count: 9,
  coverage_last_good_count: 221,
  coverage_delta: -212,
  last_publish_at: '2026-10-17T13:34:19.129097+00:00',
  ...overrides,
});

const yale: SchoolHealthRow = {
  ...barnard(),
  school: 'yale',
  state: 'fully_fresh',
  fully_stale: false,
  fresh_shard_count: 2,
  stale_shard_count: 0,
  failed_shard_count: 0,
  degraded_shard_count: 0,
  oldest_stale_age_days: null,
  last_successful_school_activity: '2026-10-15T09:00:00+00:00',
  oldest_success_at: '2026-10-14T09:00:00+00:00',
  coverage_current_count: 300,
  coverage_last_good_count: 300,
  coverage_delta: 0,
  last_publish_at: '2026-10-15T09:05:00+00:00',
};

const source = (overrides: Partial<SourceHealthRow> = {}): SourceHealthRow => ({
  school: 'barnard',
  source: 'barnard_faculty',
  last_attempt_at: '2026-10-17T13:30:52+00:00',
  last_success_at: '2026-08-29T08:10:26+00:00',
  last_publish_at: '2026-10-17T13:34:19+00:00',
  current_record_count: 0,
  last_good_record_count: 212,
  freshness: 'stale',
  status: 'suspicious_zero',
  failure_reason: 'emitted 0 records against a baseline of 212 active record(s)',
  consecutive_failures: 3,
  eligible: true,
  ...overrides,
});

function workflow(overrides: Partial<SchoolHealthWorkflow> = {}): SchoolHealthWorkflow {
  return {
    data: {
      available: true,
      schools: [yale, barnard()],
      report: {
        school_count: 2,
        fully_fresh_school_count: 1,
        partially_degraded_school_count: 0,
        fully_stale_school_count: 1,
        stale_shard_count: 2,
        failed_shard_count: 1,
        total_shard_count: 4,
        warn_days: 10,
        stale_days: 17,
      },
    },
    error: null,
    shards: {},
    shardLoading: {},
    shardErrors: {},
    onOpen: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
}

const row = (school: string) => screen.getByTestId(`school-row-${school}`);

describe('SchoolHealthSection', () => {
  it('renders nothing before the first load', () => {
    const { container } = render(
      <SchoolHealthSection health={workflow({ data: null })} t={t} />,
    );
    expect(container.innerHTML).toBe('');
  });

  it('lists each school worst first with its own verification columns', () => {
    render(<SchoolHealthSection health={workflow()} t={t} />);
    const rows = screen.getAllByTestId(/^school-row-/);
    expect(rows.map((r) => r.getAttribute('data-testid'))).toEqual([
      'school-row-barnard', 'school-row-yale',
    ]);
    const b = within(row('barnard'));
    expect(b.getByText('Fully stale')).toBeInTheDocument();
    expect(b.getByText('0 fresh · 0 warn · 2 stale of 2')).toBeInTheDocument();
    expect(within(b.getByTestId('oldest-success')).getByText('2026-08-29 06:09 UTC')).toBeInTheDocument();
    expect(within(b.getByTestId('newest-success')).getByText('2026-08-29 08:10 UTC')).toBeInTheDocument();
    expect(b.getByText('1 failed · 2 stale')).toBeInTheDocument();
    expect(within(b.getByTestId('coverage')).getByText('-212')).toBeInTheDocument();
    expect(b.getByText('9 in latest run / 221 last good')).toBeInTheDocument();
    expect(within(b.getByTestId('last-publish')).getByText('2026-10-17 13:34 UTC')).toBeInTheDocument();
    expect(screen.getByText(/2 schools: 1 fully fresh, 0 partially degraded, 1 fully stale/))
      .toBeInTheDocument();
  });

  it('never shows the publish time, or any other time, as a school success', () => {
    // A school none of whose sources ever succeeded, written to disk today.
    render(
      <SchoolHealthSection
        health={workflow({
          data: {
            available: true,
            report: null,
            schools: [barnard({
              last_successful_school_activity: null,
              oldest_success_at: null,
              never_succeeded_shard_count: 2,
            })],
          },
        })}
        t={t}
      />,
    );
    const b = within(row('barnard'));
    expect(b.getByTestId('oldest-success')).toHaveTextContent('2 source(s) never succeeded');
    expect(b.getByTestId('newest-success')).toHaveTextContent(/^never$/);
    expect(b.getByTestId('oldest-success')).not.toHaveTextContent('2026');
    expect(b.getByTestId('newest-success')).not.toHaveTextContent('2026');
    expect(b.getByTestId('last-publish')).toHaveTextContent('2026-10-17 13:34 UTC');
  });

  it('shows a dash, not a guess, for fields an older backend does not send', () => {
    render(
      <SchoolHealthSection
        health={workflow({
          data: {
            available: true,
            report: null,
            schools: [barnard({
              oldest_success_at: undefined,
              never_succeeded_shard_count: undefined,
              coverage_delta: undefined,
              coverage_current_count: undefined,
              coverage_last_good_count: undefined,
            })],
          },
        })}
        t={t}
      />,
    );
    const b = within(row('barnard'));
    expect(b.getByTestId('oldest-success')).toHaveTextContent(/^—$/);
    expect(b.getByTestId('coverage')).toHaveTextContent(/^—$/);
  });

  it('opens a school into its sources, failing ones first, with their reasons', () => {
    const onOpen = vi.fn();
    const onClose = vi.fn();
    const { rerender } = render(<SchoolHealthSection health={workflow({ onOpen, onClose })} t={t} />);
    fireEvent.click(within(row('barnard')).getByRole('button', { name: /barnard/ }));
    expect(onOpen).toHaveBeenCalledWith('barnard');

    rerender(
      <SchoolHealthSection
        health={workflow({ onOpen, onClose, shardLoading: { barnard: true } })}
        t={t}
      />,
    );
    expect(screen.getByText('Loading sources…')).toBeInTheDocument();

    rerender(
      <SchoolHealthSection
        health={workflow({
          onOpen,
          onClose,
          shards: {
            barnard: [
              source({
                source: 'campus_graph:barnard', freshness: 'fresh', status: 'success_nonzero',
                failure_reason: null, consecutive_failures: 0, current_record_count: 9,
                last_good_record_count: 9,
              }),
              source(),
            ],
          },
        })}
        t={t}
      />,
    );
    const sources = screen.getAllByTestId(/^source-row-/);
    expect(sources.map((r) => r.getAttribute('data-testid'))).toEqual([
      'source-row-barnard_faculty', 'source-row-campus_graph:barnard',
    ]);
    const broken = within(sources[0]);
    expect(broken.getByText('Stale')).toBeInTheDocument();
    expect(broken.getByText(/Suspicious zero · 3 failed in a row/)).toBeInTheDocument();
    expect(broken.getByText('2026-08-29 08:10 UTC')).toBeInTheDocument();
    expect(broken.getByText('0 / 212')).toBeInTheDocument();
    expect(broken.getByText('emitted 0 records against a baseline of 212 active record(s)'))
      .toBeInTheDocument();

    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(within(row('barnard')).getByRole('button', { name: /barnard/ }));
    expect(screen.queryByTestId('source-row-barnard_faculty')).toBeNull();
    // Closed, so the hook stops reloading it on a refresh.
    expect(onClose).toHaveBeenCalledWith('barnard');
  });

  it('says when a school\'s sources could not be loaded', () => {
    render(
      <SchoolHealthSection
        health={workflow({ shardErrors: { barnard: 'HTTP 500' } })}
        t={t}
      />,
    );
    fireEvent.click(within(row('barnard')).getByRole('button', { name: /barnard/ }));
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load sources: HTTP 500');
  });

  it('reports a failed load instead of looking empty', () => {
    render(
      <SchoolHealthSection health={workflow({ data: null, error: 'HTTP 500' })} t={t} />,
    );
    expect(screen.getByRole('alert'))
      .toHaveTextContent('Could not load per-school verification: HTTP 500');
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('says the ledger is unavailable rather than showing no schools', () => {
    render(
      <SchoolHealthSection
        health={workflow({ data: { available: false, schools: [], report: null } })}
        t={t}
      />,
    );
    expect(screen.getByText('Source health ledger not available yet.')).toBeInTheDocument();
  });

  it('has its strings in Chinese too', () => {
    for (const key of [
      'admin.schoolHealth.title',
      'admin.schoolHealth.note',
      'admin.schoolHealth.cols.oldestSuccess',
      'admin.schoolHealth.cols.lastPublish',
      'admin.schoolHealth.state.fully_stale',
      'admin.schoolHealth.sourceCols.failureReason',
    ]) {
      expect(translate('zh', key), key).not.toBe(translate('en', key));
    }
  });
});
