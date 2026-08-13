/* @vitest-environment jsdom */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { FilterRail } from './FilterRail';
import { sourceLabel } from './types';
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
  sourceOptions?: Array<[string, string]>;
  scopeOptions?: Array<[string, string]>;
  includeCrossSchool?: boolean;
} = {}) {
  const onFiltersChange = vi.fn();
  const onSortByChange = vi.fn();
  const onShowDismissedChange = vi.fn();
  const onIncludeCrossSchoolChange = vi.fn();
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
      sourceOptions={overrides.sourceOptions ?? [['', 'All sources'], ['uiuc_faculty', 'UIUC Faculty']]}
      scopeOptions={overrides.scopeOptions ?? []}
      includeCrossSchool={overrides.includeCrossSchool ?? false}
      crossSchoolDisabled={false}
      crossSchoolFailed={false}
      onCrossSchoolRetry={() => {}}
      onIncludeCrossSchoolChange={onIncludeCrossSchoolChange}
      t={t}
    />,
  );
  return { onFiltersChange, onSortByChange, onShowDismissedChange, onIncludeCrossSchoolChange };
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

describe('FilterRail — discovery-scope facet', () => {
  const SCOPE_OPTIONS: Array<[string, string]> = [
    ['', 'results.filters.scopeAll'],
    ['campus', 'results.filters.scopeMySchool'],
    ['open', 'results.filters.scopeOpen'],
  ];

  it('hides the scope select when scopeOptions is empty (no scope metadata)', () => {
    renderRail({ scopeOptions: [] });
    expect(screen.queryByText('results.filters.scopeAll')).toBeNull();
  });

  it('renders the scope select when options are provided', () => {
    renderRail({ scopeOptions: SCOPE_OPTIONS });
    expect(screen.getByText('results.filters.scopeAll')).toBeInTheDocument();
    expect(screen.getByText('results.filters.scopeMySchool')).toBeInTheDocument();
    expect(screen.getByText('results.filters.scopeOpen')).toBeInTheDocument();
    const chips = document.getElementById('filter-rail-chips');
    expect(within(chips!).getAllByRole('combobox').length).toBe(7);
  });

  it('selecting a scope updates filters.scope', () => {
    const { onFiltersChange } = renderRail({ scopeOptions: SCOPE_OPTIONS });
    const chips = document.getElementById('filter-rail-chips');
    const scopeSelect = within(chips!)
      .getAllByRole('combobox')
      .find((el) => within(el).queryByText('results.filters.scopeMySchool'));
    expect(scopeSelect).toBeTruthy();
    fireEvent.change(scopeSelect!, { target: { value: 'campus' } });
    expect(onFiltersChange).toHaveBeenCalledWith({ ...DEFAULT_FILTERS, scope: 'campus' });
  });
});

describe('FilterRail — cross-school toggle', () => {
  it('offers the cross-school toggle now that the facet is accepted', () => {
    renderRail();
    expect(screen.getByRole('button', { name: /crossSchool$/ })).toBeInTheDocument();
  });
});

describe('sourceLabel (derived source filter)', () => {
  const t = (k: string) => k;
  it('uses the i18n key for a known source', () => {
    expect(sourceLabel('uiuc_faculty', t)).toBe('results.filters.sourceUiucFaculty');
  });
  it('uses i18n keys for the UC Berkeley sources', () => {
    expect(sourceLabel('ucb_urap', t)).toBe('results.filters.sourceUcbUrap');
    expect(sourceLabel('ucb_urap_projects', t)).toBe('results.filters.sourceUcbUrapProjects');
    expect(sourceLabel('ucb_eecs_faculty', t)).toBe('results.filters.sourceUcbEecsFaculty');
    expect(sourceLabel('ucb_stat_faculty', t)).toBe('results.filters.sourceUcbStatFaculty');
    expect(sourceLabel('ucb_chem_faculty', t)).toBe('results.filters.sourceUcbChemFaculty');
    expect(sourceLabel('ucb_cee_faculty', t)).toBe('results.filters.sourceUcbCeeFaculty');
  });
  it('uses i18n keys for the UC Berkeley campus opportunity-graph sources', () => {
    // These three emit buckets must map to real labels — not the humanized
    // fallback ("Ucb Research Programs"), which reads as a bug in the UI.
    expect(sourceLabel('ucb_research_programs', t)).toBe(
      'results.filters.sourceUcbResearchPrograms',
    );
    expect(sourceLabel('ucb_external_research', t)).toBe(
      'results.filters.sourceUcbExternalResearch',
    );
    expect(sourceLabel('ucb_labs', t)).toBe('results.filters.sourceUcbLabs');
  });
  it('uses i18n keys for the campus-graph schools (Princeton)', () => {
    // The Top-50 rollout reuses the same three emit buckets per school; each
    // must resolve to a real label, not the humanized fallback.
    expect(sourceLabel('princeton_research_programs', t)).toBe(
      'results.filters.sourcePrincetonResearchPrograms',
    );
    expect(sourceLabel('princeton_external_research', t)).toBe(
      'results.filters.sourcePrincetonExternalResearch',
    );
    expect(sourceLabel('princeton_labs', t)).toBe('results.filters.sourcePrincetonLabs');
    expect(sourceLabel('umich_research_programs', t)).toBe(
      'results.filters.sourceUmichResearchPrograms',
    );
    expect(sourceLabel('umich_external_research', t)).toBe(
      'results.filters.sourceUmichExternalResearch',
    );
    expect(sourceLabel('umich_labs', t)).toBe('results.filters.sourceUmichLabs');
    expect(sourceLabel('umich_faculty', t)).toBe('results.filters.sourceUmichFaculty');
  });
  it('every UC Berkeley faculty source maps to a label (no humanized fallback)', () => {
    // Mirrors the ucb_*_faculty collectors wired in refresh_all
    // (deactivate_stale_faculty.FACULTY_SOURCES). Each MUST resolve to a real
    // i18n key — never the "Ucb <Dept> Faculty" humanizer fallback, which reads
    // as a bug in the source filter once these collectors' records ship.
    const UCB_FACULTY_SOURCES = [
      'ucb_eecs_faculty', 'ucb_stat_faculty', 'ucb_chem_faculty', 'ucb_cee_faculty',
      'ucb_anthro_faculty', 'ucb_arch_faculty', 'ucb_astro_faculty', 'ucb_bioe_faculty',
      'ucb_cbe_faculty', 'ucb_dcrp_faculty', 'ucb_econ_faculty', 'ucb_eps_faculty',
      'ucb_espm_faculty', 'ucb_ib_faculty', 'ucb_ieor_faculty', 'ucb_larch_faculty',
      'ucb_law_faculty', 'ucb_ling_faculty', 'ucb_math_faculty', 'ucb_mcb_faculty',
      'ucb_me_faculty', 'ucb_mse_faculty', 'ucb_ne_faculty', 'ucb_nst_faculty',
      'ucb_physics_faculty', 'ucb_pmb_faculty', 'ucb_polisci_faculty',
      'ucb_psych_faculty', 'ucb_soc_faculty',
      // batch-2 departments (all 38 wired in refresh_all must be labeled)
      'ucb_education_faculty', 'ucb_english_faculty', 'ucb_geog_faculty',
      'ucb_haas_faculty', 'ucb_history_faculty', 'ucb_journalism_faculty',
      'ucb_philos_faculty', 'ucb_socwel_faculty', 'ucb_sph_faculty',
    ];
    expect(UCB_FACULTY_SOURCES).toHaveLength(38);
    for (const src of UCB_FACULTY_SOURCES) {
      // identity t returns the key when one is mapped; the humanizer would
      // return a "Ucb …" string with no 'results.filters.' prefix.
      expect(sourceLabel(src, t), src).toMatch(/^results\.filters\.sourceUcb\w+Faculty$/);
    }
  });
  it('humanizes an unknown source key (e.g. simplify_internships)', () => {
    expect(sourceLabel('simplify_internships', t)).toBe('Simplify Internships');
  });
});
