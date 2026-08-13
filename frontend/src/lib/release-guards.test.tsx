import { describe, expect, it, vi } from 'vitest';

const { notFound } = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error('NEXT_NOT_FOUND');
  }),
}));

vi.mock('next/navigation', () => ({ notFound }));

import ComparePage from '@/app/compare/page';
import FellowshipsReleaseGuard from '@/app/fellowships/layout';
import RoadmapReleaseGuard from '@/app/roadmap/layout';

// These three guards returned 404 for the whole MVP route freeze. The features
// are accepted now, so the assertion inverts — but the guard stays in the
// source and keeps its test, because what it protects against is a route
// remaining reachable after a switch closes again. A guard nobody exercises is
// how a closed feature quietly stays open.
describe('accepted route guards let their route render', () => {
  it('renders Fellowships instead of calling notFound', () => {
    expect(() =>
      FellowshipsReleaseGuard({ children: <div>rendered</div> }),
    ).not.toThrow();
    expect(notFound).not.toHaveBeenCalled();
  });

  it('renders Roadmap instead of calling notFound', () => {
    expect(() =>
      RoadmapReleaseGuard({ children: <div>rendered</div> }),
    ).not.toThrow();
  });

  it('resolves Compare rather than refusing before it reads its ids', async () => {
    await expect(
      ComparePage({ searchParams: Promise.resolve({ ids: '' }) }),
    ).resolves.toBeDefined();
  });
});
