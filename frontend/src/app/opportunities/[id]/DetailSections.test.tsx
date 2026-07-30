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

  it('renders title, year, and a quoted Scholar search link per verified work', () => {
    render(
      <RecentWorksSection
        opp={opp({
          recent_works: [
            { title: 'Deep Learning for Auditory Cortex Mapping', year: 2026 },
            { title: 'A Study Without a Year', year: null },
          ],
          publication_attribution_status: 'verified_author_id',
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

  it('renders nothing for unverified attribution (fail closed)', () => {
    const works = [{ title: 'A Borderline Paper', year: 2026 }];
    // Publication trust boundary: name_match, legacy-absent, and unknown
    // statuses must not present the works as this professor's publications —
    // the whole section stays hidden, no label fallback.
    for (const metadata of [
      { recent_works: works, publication_attribution_status: 'name_match' as const },
      { recent_works: works },
      { recent_works: works, publication_attribution_status: 'trust_me' as never },
    ]) {
      const { container, unmount } = render(<RecentWorksSection opp={opp(metadata)} t={tFn} />);
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });

  it('renders verified works with the publication-record note', () => {
    render(
      <RecentWorksSection
        opp={opp({
          recent_works: [{ title: 'A Verified Paper', year: 2026 }],
          publication_attribution_status: 'verified_author_id',
        })}
        t={tFn}
      />,
    );
    expect(screen.getByRole('link', { name: 'A Verified Paper' })).toBeInTheDocument();
    expect(screen.getByText('detail.recentWorksNote')).toBeInTheDocument();
  });

  it('caps the list at 5 works', () => {
    render(
      <RecentWorksSection
        opp={opp({
          recent_works: Array.from({ length: 8 }, (_, i) => ({
            title: `Paper ${i + 1}`,
            year: 2026 - i,
          })),
          publication_attribution_status: 'verified_author_id',
        })}
        t={tFn}
      />,
    );
    expect(screen.getAllByRole('link')).toHaveLength(5);
    expect(screen.queryByText('Paper 6')).not.toBeInTheDocument();
  });
});
