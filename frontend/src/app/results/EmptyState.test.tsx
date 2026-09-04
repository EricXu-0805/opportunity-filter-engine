/* @vitest-environment jsdom */
// The empty page is the one place the product speaks about the student's WHOLE
// match set rather than about the rows in front of it — so its claim has to
// come from evidence that survives the filters, not from the empty array those
// filters produced.
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EmptyState } from './EmptyState';
import { noMatchCarriesADeadline } from './types';
import type { TFunc } from './types';

const t = ((key: string) => key) as unknown as TFunc;

function renderEmpty(props: Partial<React.ComponentProps<typeof EmptyState>> = {}) {
  return render(
    <EmptyState
      hasFilters
      tab="all"
      onClearFilters={() => {}}
      onShowRolling={() => {}}
      t={t}
      {...props}
    />,
  );
}

describe('the empty page only claims what it can show', () => {
  it('says no match carries a deadline only when that is established', () => {
    renderEmpty({ deadlineFilterFoundNothing: true });
    expect(screen.getByText('results.empty.noDeadlines')).toBeInTheDocument();
  });

  it('falls back to the filters explanation when deadlines do exist', () => {
    renderEmpty({ deadlineFilterFoundNothing: false });
    expect(screen.queryByText('results.empty.noDeadlines')).toBeNull();
  });
});

describe('the deadline claim is decided by evidence that survives the filters', () => {
  it('is false while any match in the universe carries a deadline', () => {
    // A student picks the one deadline chip that renders, sees 151 real summer
    // programs, then clicks Starred. The intersection is empty, and the page
    // used to read the claim off that empty array — so it printed "None of
    // your matches have a set deadline" about 151 matches they were looking at
    // one click earlier.
    expect(noMatchCarriesADeadline('passed', { '7': 0, '14': 0, '30': 0, passed: 151 })).toBe(false);
    expect(noMatchCarriesADeadline('30', { '7': 3, '14': 0, '30': 0, passed: 0 })).toBe(false);
  });

  it('is true only when the whole universe carries none', () => {
    expect(noMatchCarriesADeadline('passed', { '7': 0, '14': 0, '30': 0, passed: 0 })).toBe(true);
    expect(noMatchCarriesADeadline('passed', undefined)).toBe(true);
  });

  it('never fires without a dated filter', () => {
    expect(noMatchCarriesADeadline('', { passed: 0 })).toBe(false);
    expect(noMatchCarriesADeadline('rolling', { passed: 0 })).toBe(false);
  });
});
