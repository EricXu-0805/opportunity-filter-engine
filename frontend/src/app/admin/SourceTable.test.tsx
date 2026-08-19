import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SourceTable } from './SourceTable';
import type { SourceRow, TFunc } from './types';

const columns = {
  source: 'Source',
  total: 'Total',
  emptyMajors: 'Empty majors',
  emptyKeywords: 'Empty keywords',
  rolling: 'Rolling',
  missingDeadline: 'Missing deadline',
  past: 'Past',
  inactive: 'Inactive',
};

const t = ((key: string) => (
  key === 'admin.bySourceCols' ? columns : key
)) as unknown as TFunc;

function renderRow(overrides: Partial<SourceRow> = {}) {
  render(
    <SourceTable
      rows={[{
        source: 'mixed-source',
        total: 20,
        listing_total: 2,
        missing_deadline: 1,
        ...overrides,
      }]}
      t={t}
    />,
  );
}

describe('SourceTable listing percentages', () => {
  it('uses listing_total on desktop and mobile and alerts on a 50% defect rate', () => {
    renderRow();

    const cells = screen.getAllByText((_, node) => (
      node?.tagName === 'SPAN' && node.textContent === '1 (50%)'
    ));
    expect(cells).toHaveLength(2);
    for (const cell of cells) {
      expect(cell).toHaveClass('text-amber-700', 'font-semibold');
    }
    expect(screen.queryByText('(5%)')).not.toBeInTheDocument();
  });

  it.each([
    ['legacy', undefined],
    ['zero-listing', 0],
  ])('shows an honest count without a percentage for a %s response', (_, listingTotal) => {
    renderRow({ listing_total: listingTotal });

    expect(screen.queryByText(/\(\d+%\)/)).not.toBeInTheDocument();
    const counts = screen.getAllByText('1');
    expect(counts).toHaveLength(2);
    for (const count of counts) {
      expect(count).toHaveClass('text-gray-700');
      expect(count).not.toHaveClass('text-amber-700');
    }
  });
});
