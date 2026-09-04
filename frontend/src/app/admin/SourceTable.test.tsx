import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SourceTable } from './SourceTable';
import { QUALITY_SCOPE } from './types';
import type { SourceRow, TFunc } from './types';

// The real translator resolves a path to a STRING or gives the key back; it
// never returns a dictionary subtree. A mock that handed one over made the
// header row look populated in every test while the page rendered nine blank
// cells, so this one behaves the way translate() does.
const t = ((key: string) => key) as unknown as TFunc;

const COLUMN_KEYS = [
  'source', 'total', 'emptyMajors', 'emptyKeywords', 'rolling',
  'missingDeadline', 'past', 'inactive', 'unreviewedRecordKind',
];

describe('column headers', () => {
  it('names every column through a resolvable key', () => {
    render(<SourceTable rows={[]} qualityScope={QUALITY_SCOPE} t={t} />);
    for (const key of COLUMN_KEYS) {
      expect(screen.getByText(`admin.bySourceCols.${key}`)).toBeInTheDocument();
    }
  });
});

// The scope is REQUIRED here on purpose. With a default, a case meaning
// "legacy" could pass `undefined` and be silently handed the current scope
// back — the negative would be testing the positive.
function renderRow(qualityScope: string | undefined, overrides: Partial<SourceRow> = {}) {
  render(
    <SourceTable
      rows={[{
        source: 'mixed-source',
        total: 20,
        listing_total: 2,
        missing_deadline: 1,
        ...overrides,
      }]}
      qualityScope={qualityScope}
      t={t}
    />,
  );
}

/** Every other numeric cell non-zero, so a `0` on screen can only be ours. */
const ONLY_UNREVIEWED_IS_ZERO: Partial<SourceRow> = {
  empty_majors: 4,
  empty_keywords: 5,
  rolling_deadline: 6,
  missing_deadline: 7,
  past_deadline: 8,
  flagged_inactive: 9,
  unreviewed_record_kind: 0,
};

describe('SourceTable listing percentages', () => {
  it('uses listing_total on desktop and mobile and alerts on a 50% defect rate', () => {
    renderRow(QUALITY_SCOPE);

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
    renderRow(QUALITY_SCOPE, { listing_total: listingTotal });

    expect(screen.queryByText(/\(\d+%\)/)).not.toBeInTheDocument();
    const counts = screen.getAllByText('1');
    expect(counts).toHaveLength(2);
    for (const count of counts) {
      expect(count).toHaveClass('text-gray-700');
      expect(count).not.toHaveClass('text-amber-700');
    }
  });

  it.each([
    ['a legacy response', undefined],
    ['a future scope this build does not know', 'reviewed-record-kind-v2'],
  ])('shows the count without a percentage for %s, even with listing_total present', (_, scope) => {
    // The case field-presence could never catch: the denominator is there,
    // it just counted unreviewed records as listings.
    renderRow(scope);
    expect(screen.queryByText(/\(\d+%\)/)).not.toBeInTheDocument();
    expect(screen.getAllByText('1')).toHaveLength(2);
  });
});

describe('SourceTable unreviewed record kinds', () => {
  it('shows the per-source count in both layouts under the current scope', () => {
    renderRow(QUALITY_SCOPE, { unreviewed_record_kind: 3 });
    const cells = screen.getAllByText('3');
    expect(cells).toHaveLength(2);
    for (const cell of cells) expect(cell).toHaveClass('text-indigo-700');
    expect(screen.getAllByText('admin.bySourceCols.unreviewedRecordKind')).toHaveLength(2);
  });

  it('shows an explicit zero when the backend sent one', () => {
    // Every other numeric cell is non-zero, so the two zeros on screen can
    // only be the desktop and mobile unreviewed cells.
    renderRow(QUALITY_SCOPE, ONLY_UNREVIEWED_IS_ZERO);
    expect(screen.getAllByText('0')).toHaveLength(2);
    expect(screen.queryAllByText('—')).toHaveLength(0);
  });

  it.each([
    ['a legacy response', undefined],
    ['a future scope this build does not know', 'reviewed-record-kind-v2'],
  ])('shows an em dash for %s even when the row carries a number', (_, scope) => {
    // The scope, not the field, decides. A number counted under rules this
    // build cannot see is not a number it may print — and asserting on a row
    // that DOES carry 99 is what kills removing the scope gate.
    renderRow(scope, { unreviewed_record_kind: 99 });
    expect(screen.getAllByText('—')).toHaveLength(2);
    expect(screen.queryByText('99')).not.toBeInTheDocument();
  });
});
