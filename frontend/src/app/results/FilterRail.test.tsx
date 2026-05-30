/* @vitest-environment jsdom */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { FilterRail } from './FilterRail';
import { DEFAULT_FILTERS, type Filters, type SortKey, type TFunc } from './types';

const t: TFunc = (key, vars) => {
  if (vars && 'count' in vars) return `${key}:${vars.count}`;
  return key;
};

function renderRail(overrides: {
  filters?: Filters;
  sortBy?: SortKey;
  activeFilterCount?: number;
  showDismissed?: boolean;
  dismissedCount?: number;
} = {}) {
  const onFiltersChange = vi.fn();
  const onSortByChange = vi.fn();
  const onShowDismissedChange = vi.fn();
  render(
    <FilterRail
      filters={overrides.filters ?? DEFAULT_FILTERS}
      onFiltersChange={onFiltersChange}
      sortBy={overrides.sortBy ?? 'score'}
      onSortByChange={onSortByChange}
      showDismissed={overrides.showDismissed ?? false}
      onShowDismissedChange={onShowDismissedChange}
      dismissedCount={overrides.dismissedCount ?? 0}
      activeFilterCount={overrides.activeFilterCount ?? 0}
      t={t}
    />,
  );
  return { onFiltersChange, onSortByChange, onShowDismissedChange };
}

describe('FilterRail (R69-B mobile collapse)', () => {
  it('renders the mobile toggle button with aria-expanded=false by default', () => {
    renderRail();
    const toggle = screen.getByRole('button', { name: 'results.filtersMobileExpandAria' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveAttribute('aria-controls', 'filter-rail-chips');
  });

  it('keeps the chips container in the DOM but hidden on mobile by default (hidden class)', () => {
    renderRail();
    const chipsContainer = document.getElementById('filter-rail-chips');
    expect(chipsContainer).toBeTruthy();
    // Mobile-collapsed: chips container carries `hidden`, only sm:flex
    // restores visibility on desktop viewports.
    expect(chipsContainer?.className).toContain('hidden');
    expect(chipsContainer?.className).toContain('sm:flex');
  });

  it('toggles aria-expanded and swaps hidden→flex when the user clicks the toggle', () => {
    renderRail();
    const toggle = screen.getByRole('button', { name: 'results.filtersMobileExpandAria' });
    fireEvent.click(toggle);
    // After clicking, the aria-label flips to the collapse variant
    // because the button's accessible name re-renders with the new
    // aria-expanded state.
    const collapseToggle = screen.getByRole('button', { name: 'results.filtersMobileCollapseAria' });
    expect(collapseToggle).toHaveAttribute('aria-expanded', 'true');
    const chipsContainer = document.getElementById('filter-rail-chips');
    expect(chipsContainer?.className).toContain('flex');
    expect(chipsContainer?.className).not.toContain('hidden sm:flex');
  });

  it('does not show the active-filter badge when activeFilterCount is 0', () => {
    renderRail({ activeFilterCount: 0 });
    // The badge would render the literal count; with 0, nothing renders.
    expect(screen.queryByText('0')).toBeNull();
  });

  it('shows the active-filter badge with the current count', () => {
    renderRail({ activeFilterCount: 3 });
    // Badge text is the bare number.
    const badges = screen.getAllByText('3');
    expect(badges.length).toBeGreaterThan(0);
  });

  it('renders the mobile Clear button only when activeFilterCount > 0', () => {
    const { onFiltersChange: noClear } = renderRail({ activeFilterCount: 0 });
    expect(screen.queryByText('results.clearNFilter:0')).toBeNull();
    expect(noClear).not.toHaveBeenCalled();
  });

  it('mobile Clear button resets filters to DEFAULT_FILTERS', () => {
    const { onFiltersChange } = renderRail({
      filters: { ...DEFAULT_FILTERS, paid: 'yes', minScore: 60 },
      activeFilterCount: 2,
    });
    // The mobile toggle row renders one Clear ("Clear N filters"), and
    // the desktop chip row renders an identical sibling Clear that's
    // hidden via `hidden sm:inline-flex`. Both wire to the same handler;
    // clicking either should reset filters.
    const clearButtons = screen.getAllByText('results.clearNFilters:2');
    expect(clearButtons.length).toBeGreaterThan(0);
    fireEvent.click(clearButtons[0]);
    expect(onFiltersChange).toHaveBeenCalledWith(DEFAULT_FILTERS);
  });

  it('singular vs plural Clear copy switches at count > 1', () => {
    renderRail({ activeFilterCount: 1 });
    expect(screen.getAllByText('results.clearNFilter:1').length).toBeGreaterThan(0);
    expect(screen.queryByText('results.clearNFilters:1')).toBeNull();
  });

  it('renders the Show-dismissed button when dismissedCount > 0', () => {
    renderRail({ dismissedCount: 5, showDismissed: false });
    const btn = screen.getByText('results.showDismissedLabel:5');
    expect(btn).toBeTruthy();
  });

  it('hides the Show-dismissed button when dismissedCount is 0', () => {
    renderRail({ dismissedCount: 0 });
    expect(screen.queryByText(/showDismissedLabel/)).toBeNull();
    expect(screen.queryByText(/hideDismissedLabel/)).toBeNull();
  });

  it('all filter selects + min-score render inside the chips container', () => {
    renderRail();
    const chips = document.getElementById('filter-rail-chips');
    expect(chips).toBeTruthy();
    // 6 dropdowns + minScore. We can't easily count comboboxes by role
    // because MinScoreFilter renders a button, but the chips container
    // must hold at least 6 <select> elements.
    const selects = within(chips!).getAllByRole('combobox');
    expect(selects.length).toBe(6);
  });
});
