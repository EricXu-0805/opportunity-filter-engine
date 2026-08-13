import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import FellowshipFilters from './FellowshipFilters';
import { DEFAULT_FELLOWSHIP_FILTERS } from './types';

vi.mock('@/i18n/client', () => ({
  useT: () => ({ t: (key: string) => key }),
}));

describe('FellowshipFilters', () => {
  it('shows only general filters backed by opportunity fields', () => {
    render(
      <FellowshipFilters
        filters={DEFAULT_FELLOWSHIP_FILTERS}
        onChange={vi.fn()}
        totalCount={20}
        filteredCount={20}
        hasConfirmedDeadlines={false}
      />,
    );

    expect(screen.getByText('fellowships.type')).toBeInTheDocument();
    expect(screen.getByText('fellowships.intl')).toBeInTheDocument();
    expect(screen.getByText('fellowships.paid')).toBeInTheDocument();
    expect(screen.getByText('fellowships.deadline')).toBeInTheDocument();
    // The UIUC-only college/year pills are gone — meaningless for a
    // multi-school catalog.
    expect(screen.queryByText('fellowships.college')).not.toBeInTheDocument();
    expect(screen.queryByText('fellowships.year')).not.toBeInTheDocument();
  });

  it('hides the upcoming pill when nothing in the set carries a confirmed date', () => {
    // It requires deadline_is_estimate === false and matched 0 of 1,406
    // records, so every click returned an empty page. Driven by the data, not
    // deleted: it returns on its own when real deadlines land.
    render(
      <FellowshipFilters
        filters={DEFAULT_FELLOWSHIP_FILTERS}
        onChange={vi.fn()}
        totalCount={20}
        filteredCount={20}
        hasConfirmedDeadlines={false}
      />,
    );

    expect(screen.getByText('fellowships.deadlineOptions.rolling')).toBeInTheDocument();
    expect(
      screen.queryByText('fellowships.deadlineOptions.upcoming'),
    ).not.toBeInTheDocument();
  });

  it('shows the upcoming pill once a confirmed date exists', () => {
    render(
      <FellowshipFilters
        filters={DEFAULT_FELLOWSHIP_FILTERS}
        onChange={vi.fn()}
        totalCount={20}
        filteredCount={20}
        hasConfirmedDeadlines
      />,
    );

    expect(screen.getByText('fellowships.deadlineOptions.upcoming')).toBeInTheDocument();
  });

  it('emits an exact type filter selection', () => {
    const onChange = vi.fn();
    render(
      <FellowshipFilters
        filters={DEFAULT_FELLOWSHIP_FILTERS}
        onChange={onChange}
        totalCount={20}
        filteredCount={20}
        hasConfirmedDeadlines={false}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'fellowships.types.fellowship' }));
    expect(onChange).toHaveBeenCalledWith({
      ...DEFAULT_FELLOWSHIP_FILTERS,
      type: 'fellowship',
    });
  });
});
