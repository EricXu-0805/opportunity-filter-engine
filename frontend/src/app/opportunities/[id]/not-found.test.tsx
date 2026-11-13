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

import OpportunityNotFound from './not-found';

describe('opportunity not-found page', () => {
  it('reads its body in Chinese when the visitor chose Chinese', async () => {
    cookie.lang = 'zh';
    render(await OpportunityNotFound());
    expect(screen.getByRole('heading', { name: '未找到机会' })).toBeInTheDocument();
    expect(screen.getByText('该机会可能已过期、被删除，或链接有误。试着找一个符合你档案的匹配吧。')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '浏览匹配' })).toHaveAttribute('href', '/results');
    expect(document.body.textContent).not.toMatch(/[A-Za-z]/);
  });

  it("keeps today's English body without a language cookie", async () => {
    cookie.lang = undefined;
    render(await OpportunityNotFound());
    expect(screen.getByRole('heading', { name: 'Opportunity not found' })).toBeInTheDocument();
    expect(screen.getByText(
      'This opportunity may have expired, been removed, or the link is wrong. Try finding a match that fits your profile instead.',
    )).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Browse matches' })).toHaveAttribute('href', '/results');
  });
});
