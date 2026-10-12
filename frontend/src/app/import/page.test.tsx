import { beforeEach, describe, expect, it, vi } from 'vitest';

const { redirect } = vi.hoisted(() => ({
  redirect: vi.fn((target: string) => { throw new Error(`NEXT_REDIRECT:${target}`); }),
}));
vi.mock('next/navigation', () => ({ redirect }));

import ImportRedirect from './page';

beforeEach(() => {
  redirect.mockClear();
});

describe('/import', () => {
  it('redirects to the Resources page with the Import tab selected', async () => {
    await expect(ImportRedirect({ searchParams: Promise.resolve({}) })).rejects.toThrow('NEXT_REDIRECT:/resources?tab=import');
    expect(redirect).toHaveBeenCalledWith('/resources?tab=import');
  });

  it('preserves the query string on the way', async () => {
    await expect(ImportRedirect({ searchParams: Promise.resolve({ utm_source: 'mail', lab: 'dry' }) }))
      .rejects.toThrow('NEXT_REDIRECT:/resources?utm_source=mail&lab=dry&tab=import');
  });
});
