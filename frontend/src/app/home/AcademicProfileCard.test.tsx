import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useLocale: () => 'en',
  useT: () => ({
    locale: 'en',
    t: (key: string, vars?: Record<string, string | number>) =>
      vars ? `${key}:${Object.values(vars).join(',')}` : key,
  }),
}));

import { AcademicProfileCard } from './AcademicProfileCard';
import { DEFAULT_PROFILE } from './types';
import type { ProfileData } from '@/lib/types';

const t = (key: string, vars?: Record<string, string | number>) =>
  vars ? `${key}:${Object.values(vars).join(',')}` : key;

function renderCard(overrides: Partial<ProfileData> = {}) {
  const update = vi.fn();
  render(
    <AcademicProfileCard
      profile={{ ...DEFAULT_PROFILE, ...overrides }}
      update={update}
      t={t}
    />,
  );
  return { update };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('AcademicProfileCard — school row + switcher entry', () => {
  it('shows the current school name and a Change button (default uiuc)', () => {
    renderCard();
    expect(screen.getByText('University of Illinois Urbana-Champaign')).toBeInTheDocument();
    expect(screen.getByText('home.form.changeSchool')).toBeInTheDocument();
  });

  it('treats a stored profile without home_school as UIUC (backward compat)', () => {
    renderCard({ home_school: undefined });
    expect(screen.getByText('University of Illinois Urbana-Champaign')).toBeInTheDocument();
    expect(document.querySelector('select#college')).toBeTruthy();
  });

  it('opens the switcher modal; select + confirm updates profile.home_school', () => {
    const { update } = renderCard();
    fireEvent.click(screen.getByText('home.form.changeSchool'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('university-card-ucb'));
    fireEvent.click(screen.getByText('universitySwitcher.confirm'));
    expect(update).toHaveBeenCalledWith('home_school', 'ucb');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('cancel closes the modal without updating the profile', () => {
    const { update } = renderCard();
    fireEvent.click(screen.getByText('home.form.changeSchool'));
    fireEvent.click(screen.getByText('common.cancel'));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(update).not.toHaveBeenCalled();
  });
});

describe('AcademicProfileCard — catalog vs free-text fallback', () => {
  it('uiuc keeps the cascading college/major dropdowns', async () => {
    renderCard({ home_school: 'uiuc' });
    expect(document.querySelector('select#college')).toBeTruthy();
    expect(document.querySelector('select#major')).toBeTruthy();
    expect(screen.queryByText('home.form.catalogPendingNote')).toBeNull();
    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'Grainger College of Engineering' })).toBeInTheDocument(),
    );
  });

  it('ucb renders cascading dropdowns from its catalog once loaded', async () => {
    renderCard({ home_school: 'ucb' });
    expect(document.querySelector('input#college')).toBeNull();
    expect(document.querySelector('select#college')).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'Haas School of Business' })).toBeInTheDocument(),
    );
    expect((document.querySelector('select#college') as HTMLSelectElement).disabled).toBe(false);
    // UIUC's catalog must not bleed into UCB's dropdown.
    expect(screen.queryByRole('option', { name: 'Grainger College of Engineering' })).toBeNull();
    expect(screen.queryByText('home.form.catalogPendingNote')).toBeNull();
  });

  it('a ucb college cascades to its own majors in the major dropdown', async () => {
    renderCard({ home_school: 'ucb', college: 'Haas School of Business' });
    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'Spieker Undergraduate Business Program' })).toBeInTheDocument(),
    );
    expect((document.querySelector('select#major') as HTMLSelectElement).disabled).toBe(false);
  });

  it('a school without a catalog degrades college/major to free-text inputs with a note', () => {
    renderCard({ home_school: 'future-school' });
    const college = document.querySelector('input#college') as HTMLInputElement;
    const major = document.querySelector('input#major') as HTMLInputElement;
    expect(college).toBeTruthy();
    expect(major).toBeTruthy();
    expect(document.querySelector('select#college')).toBeNull();
    expect(document.querySelector('select#major')).toBeNull();
    expect(screen.getByText('home.form.catalogPendingNote')).toBeInTheDocument();
  });

  it('free-text inputs carry the stored college/major values (no data loss)', () => {
    renderCard({ home_school: 'future-school', college: 'College of Engineering', major: 'EECS' });
    expect((document.querySelector('input#college') as HTMLInputElement).value)
      .toBe('College of Engineering');
    expect((document.querySelector('input#major') as HTMLInputElement).value).toBe('EECS');
  });

  it('typing in the free-text college field calls update without touching major', () => {
    const { update } = renderCard({ home_school: 'future-school' });
    fireEvent.change(document.querySelector('input#college')!, {
      target: { value: 'College of Chemistry' },
    });
    expect(update).toHaveBeenCalledWith('college', 'College of Chemistry');
  });
});
