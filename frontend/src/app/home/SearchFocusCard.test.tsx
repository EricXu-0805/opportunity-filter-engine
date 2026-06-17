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
