import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    locale: 'en',
    t: (key: string, vars?: Record<string, string | number>) =>
      vars ? `${key}:${Object.values(vars).join(',')}` : key,
  }),
}));

import UniversitySwitcherModal from './UniversitySwitcherModal';
import { SCHOOLS } from '@/lib/schools';

function renderModal(initialSelectedSlug = 'uiuc') {
  const onCancel = vi.fn();
  const onConfirm = vi.fn();
  render(
    <UniversitySwitcherModal
      initialSelectedSlug={initialSelectedSlug}
      onCancel={onCancel}
      onConfirm={onConfirm}
    />,
  );
  return { onCancel, onConfirm };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('UniversitySwitcherModal — rendering', () => {
  it('renders a card for every registered school', () => {
    renderModal();
    for (const school of SCHOOLS) {
      expect(screen.getByTestId(`university-card-${school.slug}`)).toBeInTheDocument();
    }
  });

  it('marks the initial school as selected (aria-pressed)', () => {
    renderModal('ucb');
    expect(screen.getByTestId('university-card-ucb')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('university-card-uiuc')).toHaveAttribute('aria-pressed', 'false');
  });

  it('shows coverage chips: counts for live schools, pending note otherwise', () => {
    renderModal();
    // Expected chip text derives from the registry (which itself derives from
    // school-stats.json at build time), so this test never goes stale as the
    // corpus grows. getAllByText because two schools can floor to the same
    // rounded count (uw and utexas both show 2,200 today).
    const uiuc = SCHOOLS.find((s) => s.slug === 'uiuc')!;
    expect(
      screen.getAllByText(
        `universitySwitcher.coverageCampus:${(
          uiuc.coverage.campusOpportunities as number
        ).toLocaleString()}`,
      ).length,
    ).toBeGreaterThanOrEqual(1);
    const ucb = SCHOOLS.find((s) => s.slug === 'ucb')!;
    expect(
      screen.getAllByText(
        `universitySwitcher.coverageCampus:${(
          ucb.coverage.campusOpportunities as number
        ).toLocaleString()}`,
      ).length,
    ).toBeGreaterThanOrEqual(1);
    // Derive the expected pending count from the registry rather than a fixed
    // "minus N live schools" — the live set grows as campus collectors ship
    // (UIUC, UCB, Princeton, …).
    const pendingCount = SCHOOLS.filter(
      (s) => s.coverage.campusOpportunities === 'pending',
    ).length;
    // queryAllByText (not getAllByText) so the assertion holds at zero — every
    // school now ships a live campus count, but the registry-derived check keeps
    // working if a future pending-coverage school is added.
    expect(screen.queryAllByText('universitySwitcher.coveragePending').length).toBe(pendingCount);
  });

  it('shows a real catalog counts line on every card, no pending-catalog note left', () => {
    renderModal();
    expect(screen.getAllByText(/universitySwitcher\.catalogSummary:/).length).toBe(SCHOOLS.length);
    expect(screen.queryByText('universitySwitcher.catalogPending')).toBeNull();
    // Counts come straight from the registry (mock t renders "key:colleges,majors").
    expect(screen.getByText('universitySwitcher.catalogSummary:12,141')).toBeInTheDocument(); // uiuc
    expect(screen.getByText('universitySwitcher.catalogSummary:7,136')).toBeInTheDocument(); // ucb
    expect(screen.getByText('universitySwitcher.catalogSummary:3,71')).toBeInTheDocument(); // stanford
  });
});

describe('UniversitySwitcherModal — search', () => {
  it('filters cards by name', () => {
    renderModal();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Berkeley' } });
    expect(screen.getByTestId('university-card-ucb')).toBeInTheDocument();
    expect(screen.queryByTestId('university-card-uiuc')).toBeNull();
  });

  it('filters by Chinese name and by location', () => {
    renderModal();
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: '斯坦福' } });
    expect(screen.getByTestId('university-card-stanford')).toBeInTheDocument();
    expect(screen.queryByTestId('university-card-ucb')).toBeNull();
    fireEvent.change(input, { target: { value: 'Ann Arbor' } });
    expect(screen.getByTestId('university-card-umich')).toBeInTheDocument();
  });

  it('shows the empty state when nothing matches', () => {
    renderModal();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hogwarts' } });
    expect(screen.getByText('universitySwitcher.noMatch:Hogwarts')).toBeInTheDocument();
  });
});

describe('UniversitySwitcherModal — select + confirm/cancel', () => {
  it('select then confirm reports the new slug', () => {
    const { onConfirm } = renderModal('uiuc');
    fireEvent.click(screen.getByTestId('university-card-ucb'));
    expect(screen.getByTestId('university-card-ucb')).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByText('universitySwitcher.confirm'));
    expect(onConfirm).toHaveBeenCalledWith('ucb');
  });

  it('confirm without changing selection reports the initial slug', () => {
    const { onConfirm } = renderModal('uiuc');
    fireEvent.click(screen.getByText('universitySwitcher.confirm'));
    expect(onConfirm).toHaveBeenCalledWith('uiuc');
  });

  it('cancel and Escape both call onCancel without confirming', () => {
    const { onCancel, onConfirm } = renderModal();
    fireEvent.click(screen.getByText('common.cancel'));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledTimes(2);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('backdrop click cancels', () => {
    const { onCancel } = renderModal();
    const dialog = screen.getByRole('dialog');
    fireEvent.click(dialog.firstElementChild as Element);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
