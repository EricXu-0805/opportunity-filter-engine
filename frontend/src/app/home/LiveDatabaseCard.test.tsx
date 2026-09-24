import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { translate } from '@/i18n/translate';
import { LiveDatabaseCard } from './LiveDatabaseCard';
import type { DatabaseStats } from './use-database-stats';

const ready: DatabaseStats = {
  oppCount: 1234, facultyCount: 9876, lastUpdated: '2026-01-01T12:00:00Z', status: 'ready',
};
const t = (key: string, vars?: Record<string, string | number>) => translate('en', key, vars);

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('LiveDatabaseCard', () => {
  it.each([
    ['en', 'Projects & postings', 'Professor profiles', 'Latest dataset update:'],
    ['zh', '项目与岗位', '教授资料', '数据集最近更新：'],
  ] as const)('labels both populations and the dataset timestamp in %s', (locale, listing, faculty, updated) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-24T12:00:00Z'));
    render(<LiveDatabaseCard {...ready} t={(key, vars) => translate(locale, key, vars)} />);
    expect(screen.getByText(listing).parentElement).toHaveTextContent('1,234');
    expect(screen.getByText(faculty).parentElement).toHaveTextContent('9,876');
    expect(screen.queryByText('11,110')).not.toBeInTheDocument();
    expect(screen.getByText(updated, { exact: false })).toBeInTheDocument();
    expect(document.querySelector('time')).toHaveAttribute('dateTime', ready.lastUpdated);
  });

  it('keeps zero distinct from an unavailable faculty measurement', () => {
    render(<LiveDatabaseCard {...ready} oppCount={0} facultyCount={null} t={t} />);
    expect(screen.getByText('Projects & postings').parentElement).toHaveTextContent('0');
    expect(screen.getByText('Professor profiles').parentElement).toHaveTextContent('Unknown');
    expect(screen.getByText(/Professor profiles do not confirm an opening/)).toBeInTheDocument();
  });

  it.each([null, 'not-a-date'])('explicitly reports an unknown update time (%s)', (lastUpdated) => {
    render(<LiveDatabaseCard {...ready} lastUpdated={lastUpdated} t={t} />);
    expect(screen.getByText('Dataset update time unavailable')).toBeInTheDocument();
    expect(document.querySelector('time')).toBeNull();
  });

  it('shows loading without presenting unmeasured counts as zero', () => {
    render(<LiveDatabaseCard oppCount={null} facultyCount={null} lastUpdated={null} status="loading" t={t} />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading statistics');
    expect(document.querySelector('dl')).toHaveAttribute('aria-busy', 'true');
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('shows request failure instead of remaining in loading forever', () => {
    render(<LiveDatabaseCard oppCount={null} facultyCount={null} lastUpdated={null} status="error" t={t} />);
    expect(screen.getByRole('status')).toHaveTextContent('Statistics are temporarily unavailable.');
    expect(screen.getAllByText('Unknown')).toHaveLength(2);
    expect(screen.queryByText('Loading statistics…')).not.toBeInTheDocument();
  });
});
