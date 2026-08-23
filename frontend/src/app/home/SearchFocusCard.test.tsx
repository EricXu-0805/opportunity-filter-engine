import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

import { SearchFocusCard } from './SearchFocusCard';

const t = (key: string, vars?: Record<string, string | number>) =>
  vars ? `${key}:${Object.values(vars).join(',')}` : key;

function renderCard(overrides: Partial<{ searchWeight: number; exploring: boolean }> = {}) {
  const setSearchWeight = vi.fn();
  const setExploring = vi.fn();
  render(
    <SearchFocusCard
      searchWeight={overrides.searchWeight ?? 50}
      setSearchWeight={setSearchWeight}
      exploring={overrides.exploring ?? false}
      setExploring={setExploring}
      t={t}
    />,
  );
  return { setSearchWeight, setExploring };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('SearchFocusCard — explore toggle', () => {
  it('renders the explore switch unchecked by default', () => {
    renderCard();
    const sw = screen.getByRole('switch');
    expect(sw).toHaveAttribute('aria-checked', 'false');
  });

  it('toggles exploring on click', () => {
    const { setExploring } = renderCard({ exploring: false });
    fireEvent.click(screen.getByRole('switch'));
    expect(setExploring).toHaveBeenCalledWith(true);
  });

  it('disables the focus slider while exploring (explore widens, ignores the slider)', () => {
    renderCard({ exploring: true });
    expect(screen.getByRole('slider')).toBeDisabled();
  });

  it('keeps the slider enabled when not exploring', () => {
    renderCard({ exploring: false });
    expect(screen.getByRole('slider')).not.toBeDisabled();
  });
});

// ---------------------------------------------------------------------------
// The slider may not promise that a resume changes the results
//
// It reweights the three scoring layers. The resume reaches the matcher as one
// boolean, `profile.resume_ready` (ranker.py:1152) — and for the 94.2% of the
// corpus that is a faculty contact, that boolean resolves to the same number
// for every candidate, so it shifts all scores equally and cannot reorder
// anything. Uploading a better resume changes no match.
//
// What the right-hand end actually raises is the readiness layer, whose only
// per-opportunity term is coursework overlap. So "Coursework" is both the true
// label and the actionable one: filling in courses is what makes that end do
// something, where polishing a resume is not.
//
// Measured before the rename, on production's own top 100 for a UIUC ECE
// sophomore: dragging to the right changed 12 of 100 results and never moved
// the top one; dragging left changed 35 and did.
// ---------------------------------------------------------------------------
describe('the slider names the signals it actually moves', () => {
  const dict = () => import('@/i18n/dictionaries');

  it('neither end claims the resume affects matching', async () => {
    const { dictionaries } = await dict();
    for (const locale of ['en', 'zh'] as const) {
      const form = (dictionaries as never as Record<string, { home: { form: Record<string, string> } }>)[locale].home.form;
      const copy = [
        form.searchWeightLeft, form.searchWeightRight,
        form.searchWeightInterests, form.searchWeightExperience,
        form.searchWeightBalanced,
      ].join(' ').toLowerCase();
      expect(copy).not.toContain('resume');
      expect(copy).not.toContain('简历');
    }
  });

  it('names coursework as the right-hand end in both languages', async () => {
    const { dictionaries } = await dict();
    const d = dictionaries as never as Record<string, { home: { form: Record<string, string> } }>;
    expect(d.en.home.form.searchWeightRight.toLowerCase()).toContain('coursework');
    expect(d.zh.home.form.searchWeightRight).toContain('课程');
  });
});
