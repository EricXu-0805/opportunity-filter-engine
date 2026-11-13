import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { STORAGE_KEYS } from '@/lib/storage-keys';

const cookie = vi.hoisted(() => ({ lang: undefined as string | undefined }));
vi.mock('next/headers', () => ({
  cookies: async () => ({
    get: (name: string) => (
      name === STORAGE_KEYS.LOCALE && cookie.lang ? { value: cookie.lang } : undefined
    ),
  }),
}));

import NotFound from './not-found';

describe('global not-found page', () => {
  it('reads its body in Chinese when the visitor chose Chinese', async () => {
    cookie.lang = 'zh';
    render(await NotFound());
    expect(screen.getByText('这个页面不存在。')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '返回首页' })).toHaveAttribute('href', '/');
    expect(document.body.textContent).not.toMatch(/[A-Za-z]/);
  });

  it("keeps today's English body without a language cookie", async () => {
    cookie.lang = undefined;
    render(await NotFound());
    expect(screen.getByText("This page doesn't exist.")).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to Home' })).toHaveAttribute('href', '/');
  });
});
