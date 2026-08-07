/*
 * Catalog loading-state tests with a controllable loadCatalog mock so the
 * async resolution order is deterministic — the real dynamic imports in
 * AcademicProfileCard.test.tsx resolve too fast (and in registration
 * order) to exercise the rapid-switching cancellation path.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useLocale: () => 'en',
  useT: () => ({ locale: 'en', t: (key: string) => key }),
}));

type Catalog = Record<string, string[]>;
const pending = new Map<string, (data: Catalog | null) => void>();

vi.mock('@/lib/catalogs', () => ({
  loadCatalog: (slug: string) =>
    new Promise<Catalog | null>((resolve) => {
      pending.set(slug, resolve);
    }),
}));

import { AcademicProfileCard } from './AcademicProfileCard';
import { DEFAULT_PROFILE } from './types';
import type { ProfileData } from '@/lib/types';

const t = (key: string) => key;

function renderCard(overrides: Partial<ProfileData> = {}) {
  const update = vi.fn();
  const view = render(
    <AcademicProfileCard
      profile={{ ...DEFAULT_PROFILE, ...overrides }}
      update={update}
      viewSnapshot={null}
      t={t}
    />,
  );
  const rerenderCard = (next: Partial<ProfileData>) =>
    view.rerender(
      <AcademicProfileCard
        profile={{ ...DEFAULT_PROFILE, ...next }}
        update={update}
        viewSnapshot={null}
        t={t}
      />,
    );
  return { update, rerenderCard };
}

const resolveCatalog = (slug: string, data: Catalog | null) =>
  act(async () => {
    pending.get(slug)!(data);
    await Promise.resolve();
  });

const collegeSelect = () => document.querySelector('select#college') as HTMLSelectElement;
const majorSelect = () => document.querySelector('select#major') as HTMLSelectElement;

beforeEach(() => pending.clear());

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('AcademicProfileCard — catalog loading state', () => {
  it('shows disabled dropdowns with a loading placeholder until the catalog resolves', async () => {
    renderCard({ home_school: 'ucb' });
    expect(collegeSelect().disabled).toBe(true);
    expect(majorSelect().disabled).toBe(true);
    expect(screen.getAllByText('home.form.catalogLoading').length).toBe(2);

    await resolveCatalog('ucb', { 'College of Chemistry': ['Chemistry'] });
    expect(collegeSelect().disabled).toBe(false);
    expect(screen.queryByText('home.form.catalogLoading')).toBeNull();
    expect(screen.getByRole('option', { name: 'College of Chemistry' })).toBeInTheDocument();
  });

  it('rapid switching: a stale catalog resolving late never paints the current school', async () => {
    const { rerenderCard } = renderCard({ home_school: 'ucb' });
    // Switch away before ucb's chunk resolves.
    rerenderCard({ home_school: 'stanford' });
    expect(collegeSelect().disabled).toBe(true);

    await resolveCatalog('stanford', { 'School of Engineering': ['Computer Science'] });
    expect(screen.getByRole('option', { name: 'School of Engineering' })).toBeInTheDocument();

    // The abandoned ucb load resolves AFTER stanford — it must be ignored.
    await resolveCatalog('ucb', { 'College of Chemistry': ['Chemistry'] });
    expect(screen.getByRole('option', { name: 'School of Engineering' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'College of Chemistry' })).toBeNull();
    expect(collegeSelect().disabled).toBe(false);
  });

  it('switching back re-requests the catalog and the form state survives', async () => {
    const ucbCatalog = { 'College of Engineering': ['Bioengineering'] };
    const { rerenderCard } = renderCard({
      home_school: 'ucb',
      college: 'College of Engineering',
      major: 'Bioengineering',
    });
    await resolveCatalog('ucb', ucbCatalog);
    expect(collegeSelect().value).toBe('College of Engineering');

    rerenderCard({ home_school: 'stanford', college: 'College of Engineering', major: 'Bioengineering' });
    await resolveCatalog('stanford', { 'School of Engineering': ['Computer Science'] });

    rerenderCard({ home_school: 'ucb', college: 'College of Engineering', major: 'Bioengineering' });
    await resolveCatalog('ucb', ucbCatalog);
    expect(collegeSelect().value).toBe('College of Engineering');
    expect(majorSelect().value).toBe('Bioengineering');
  });
});
