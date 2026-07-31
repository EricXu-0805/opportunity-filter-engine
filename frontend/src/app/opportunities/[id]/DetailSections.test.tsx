import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { Opportunity } from '@/lib/types';

import { AtAGlanceSection, RecentWorksSection } from './DetailSections';

function tFn(key: string) {
  return key;
}

function opp(
  metadata: Partial<Opportunity['metadata']>,
  overrides: Partial<Opportunity> = {},
): Opportunity {
  return {
    id: 'opp-1',
    title: 'Research with Prof X',
    organization: 'UIUC',
    metadata: { is_active: true, confidence_score: 0.9, ...metadata },
    ...overrides,
  } as Opportunity;
}

describe('AtAGlanceSection no-deadline wording', () => {
  it('faculty records read "accepts inquiries", never "Rolling"', () => {
    // is_rolling=true is a blanket collector default on faculty records —
    // not scraped evidence of rolling admissions.
    render(
      <AtAGlanceSection
        opp={opp({}, { source_type: 'faculty_research', is_rolling: true })}
        t={tFn}
      />,
    );
    expect(screen.getByText('detail.fields.acceptsInquiries')).toBeInTheDocument();
    expect(screen.queryByText('detail.fields.rollingBasis')).not.toBeInTheDocument();
  });

  it('non-faculty records without rolling evidence read "no fixed deadline listed"', () => {
    render(
      <AtAGlanceSection
        opp={opp({}, { source_type: 'campus_program', is_rolling: true })}
        t={tFn}
      />,
    );
    expect(screen.getByText('detail.fields.noDeadlineListed')).toBeInTheDocument();
    expect(screen.queryByText('detail.fields.rollingBasis')).not.toBeInTheDocument();
  });

  it('renders rollingBasis only with scraped rolling evidence in deadline_note', () => {
    render(
      <AtAGlanceSection
        opp={opp(
          { deadline_note: 'Rolling admissions' },
          { source_type: 'campus_program', is_rolling: true },
        )}
        t={tFn}
      />,
    );
    expect(screen.getByText('detail.fields.rollingBasis')).toBeInTheDocument();
  });

  it('a listed deadline still wins over the rolling row', () => {
    render(
      <AtAGlanceSection
        opp={opp({}, { source_type: 'faculty_research', is_rolling: true, deadline: '2026-10-01' })}
        t={tFn}
      />,
    );
    expect(screen.getByText('2026-10-01')).toBeInTheDocument();
    expect(screen.queryByText('detail.fields.acceptsInquiries')).not.toBeInTheDocument();
  });
});

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
          faculty_title: 'Professor',
        })}
        t={tFn}
      />,
    );
    expect(screen.getByRole('link', { name: 'A Verified Paper' })).toBeInTheDocument();
    expect(screen.getByText('detail.recentWorksNote')).toBeInTheDocument();
  });

  it('uses the rank-neutral note for a known non-professor rank', () => {
    render(
      <RecentWorksSection
        opp={opp({
          recent_works: [{ title: 'A Verified Paper', year: 2026 }],
          publication_attribution_status: 'verified_author_id',
          faculty_title: 'Senior Lecturer',
        })}
        t={tFn}
      />,
    );
    expect(screen.getByText('detail.recentWorksNoteNeutral')).toBeInTheDocument();
    expect(screen.queryByText('detail.recentWorksNote')).not.toBeInTheDocument();
  });

  it('keeps the professor note only for stated professor ranks', () => {
    // W11: an unknown rank gets the neutral note — the professor claim is
    // earned by a stated rank, never defaulted.
    for (const faculty_title of ['Assistant Professor']) {
      const { unmount } = render(
        <RecentWorksSection
          opp={opp({
            recent_works: [{ title: 'A Verified Paper', year: 2026 }],
            publication_attribution_status: 'verified_author_id',
            faculty_title,
          })}
          t={tFn}
        />,
      );
      expect(screen.getByText('detail.recentWorksNote')).toBeInTheDocument();
      unmount();
    }
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
