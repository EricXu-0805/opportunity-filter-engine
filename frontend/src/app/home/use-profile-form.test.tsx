import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { Suspense } from 'react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string) => key,
  }),
}));

const refreshSpy = vi.fn();
const pushSpy = vi.fn();
const prefetchSpy = vi.fn();
const pathnameRef = { current: '/' };
const searchRef = { current: '' };

vi.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: refreshSpy, push: pushSpy, prefetch: prefetchSpy }),
  useSearchParams: () => new URLSearchParams(searchRef.current),
  usePathname: () => pathnameRef.current,
}));

vi.mock('@/lib/api', () => ({
  getStats: () => Promise.resolve({ total: 100, last_updated_at: '2026-04-01T00:00:00Z' }),
  parseGitHubProfile: vi.fn(),
}));

vi.mock('@/lib/supabase', () => ({
  loadProfile: () => Promise.resolve(null),
  saveProfile: vi.fn(() => Promise.resolve()),
}));

import { useProfileForm } from './use-profile-form';

function TestHarness() {
  const form = useProfileForm((k) => k);
  return (
    <div>
      <span data-testid="grade">{form.profile.grade}</span>
      <span data-testid="seeking">{(form.profile.seeking_types ?? []).join(',')}</span>
    </div>
  );
}

function Wrapped() {
  return (
    <Suspense fallback={null}>
      <TestHarness />
    </Suspense>
  );
}

beforeEach(() => {
  refreshSpy.mockReset();
  pushSpy.mockReset();
  prefetchSpy.mockReset();
  searchRef.current = '';
});

describe('useProfileForm — prefill from URL', () => {
  it('does not prefill anything when no prefill_* params present', async () => {
    searchRef.current = '';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe(''));
  });

  it('prefills grade when prefill_year is a valid grade', async () => {
    searchRef.current = 'prefill_year=Junior';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe('Junior'));
  });

  it('ignores invalid prefill_year values', async () => {
    searchRef.current = 'prefill_year=PostDoc';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe(''));
  });

  it('prefills seeking_types when prefill_seeking is valid', async () => {
    searchRef.current = 'prefill_seeking=summer_program';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('seeking').textContent).toContain('summer_program'));
  });

  it('ignores invalid prefill_seeking values', async () => {
    searchRef.current = 'prefill_seeking=internship_extreme';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('seeking').textContent).toBe(''));
  });

  it('applies both prefill_year and prefill_seeking when present', async () => {
    searchRef.current = 'prefill_year=Senior&prefill_seeking=fellowship';
    render(<Wrapped />);
    await waitFor(() => expect(screen.getByTestId('grade').textContent).toBe('Senior'));
    expect(screen.getByTestId('seeking').textContent).toContain('fellowship');
  });
});
