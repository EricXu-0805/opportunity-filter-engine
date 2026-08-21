import { beforeEach, describe, expect, it, vi } from 'vitest';

const { notFound } = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error('NEXT_NOT_FOUND');
  }),
}));

vi.mock('next/navigation', () => ({ notFound }));

import ComparePage from '@/app/compare/page';
import FellowshipsReleaseGuard from '@/app/fellowships/layout';
import RoadmapReleaseGuard from '@/app/roadmap/layout';

describe('hidden MTP route guards return 404 before rendering', () => {
  beforeEach(() => {
    notFound.mockClear();
  });

  it('refuses Fellowships', () => {
    let error: unknown;
    try {
      FellowshipsReleaseGuard({ children: <div>rendered</div> });
    } catch (caught) {
      error = caught;
    }
    expect(error).toMatchObject({ message: 'NEXT_NOT_FOUND' });
    expect(notFound).toHaveBeenCalledTimes(1);
  });

  it('refuses Roadmap', () => {
    let error: unknown;
    try {
      RoadmapReleaseGuard({ children: <div>rendered</div> });
    } catch (caught) {
      error = caught;
    }
    expect(error).toMatchObject({ message: 'NEXT_NOT_FOUND' });
    expect(notFound).toHaveBeenCalledTimes(1);
  });

  it('refuses Compare before it reads its ids', async () => {
    let error: unknown;
    try {
      await ComparePage({ searchParams: Promise.resolve({ ids: '' }) });
    } catch (caught) {
      error = caught;
    }
    expect(error).toMatchObject({ message: 'NEXT_NOT_FOUND' });
    expect(notFound).toHaveBeenCalledTimes(1);
  });
});
