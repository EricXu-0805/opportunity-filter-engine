import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { Opportunity } from '@/lib/types';

import { RecentWorksSection } from './DetailSections';

function tFn(key: string) {
  return key;
}

function opp(metadata: Partial<Opportunity['metadata']>): Opportunity {
  return {
    id: 'opp-1',
    title: 'Research with Prof X',
    organization: 'UIUC',
    metadata: { is_active: true, confidence_score: 0.9, ...metadata },
  } as Opportunity;
}

describe('RecentWorksSection', () => {
  it('renders nothing when the record has no recent works', () => {
    const { container: none } = render(
      <RecentWorksSection opp={opp({})} t={tFn} />,
    );
    expect(none).toBeEmptyDOMElement();
    const { container: empty } = render(
      <RecentWorksSection opp={opp({ recent_works: [] })} t={tFn} />,
    );
    expect(empty).toBeEmptyDOMElement();
  });

  it('renders title, year, and a quoted Scholar search link per work', () => {
    render(
      <RecentWorksSection
        opp={opp({
          recent_works: [
            { title: 'Deep Learning for Auditory Cortex Mapping', year: 2026 },
            { title: 'A Study Without a Year', year: null },
          ],
        })}
        t={tFn}
      />,
    );
    expect(screen.getByText('detail.sections.recentWorks')).toBeInTheDocument();
    expect(screen.getByText('2026')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Deep Learning for Auditory Cortex Mapping' });
    expect(link).toHaveAttribute(
      'href',
      `https://scholar.google.com/scholar?q=${encodeURIComponent('"Deep Learning for Auditory Cortex Mapping"')}`,
    );
    expect(link).toHaveAttribute('target', '_blank');
    // year-less work still renders its title
    expect(screen.getByRole('link', { name: 'A Study Without a Year' })).toBeInTheDocument();
  });

  it('caps the list at 5 works', () => {
    render(
      <RecentWorksSection
        opp={opp({
          recent_works: Array.from({ length: 8 }, (_, i) => ({
            title: `Paper ${i + 1}`,
            year: 2026 - i,
          })),
        })}
        t={tFn}
      />,
    );
    expect(screen.getAllByRole('link')).toHaveLength(5);
    expect(screen.queryByText('Paper 6')).not.toBeInTheDocument();
  });
});
