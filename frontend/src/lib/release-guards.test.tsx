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

describe('dormant route guards', () => {
  it('404s Fellowships before rendering children', () => {
    expect(() =>
      FellowshipsReleaseGuard({ children: <div>should not render</div> }),
    ).toThrow('NEXT_NOT_FOUND');
  });

  it('404s Roadmap before rendering children', () => {
    expect(() =>
      RoadmapReleaseGuard({ children: <div>should not render</div> }),
    ).toThrow('NEXT_NOT_FOUND');
  });

  it('404s Compare before resolving ids or fetching data', async () => {
    await expect(
      ComparePage({ searchParams: Promise.resolve({ ids: 'one,two' }) }),
    ).rejects.toThrow('NEXT_NOT_FOUND');
  });
});
