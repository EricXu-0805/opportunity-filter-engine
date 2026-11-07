import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LanguageProvider } from '@/i18n/client';
import type { Locale } from '@/i18n/translate';

vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import ErrorPage from './error';

const API_ERROR = Object.assign(new Error('API 503: Service Unavailable'), { digest: 'd1' });
const PAGE_ERROR = new Error('boom');

function show(locale: Locale, error: Error & { digest?: string }) {
  return render(
    <LanguageProvider initialLocale={locale}>
      <ErrorPage error={error} reset={() => {}} />
    </LanguageProvider>,
  );
}

/** Page text without the raw error message and digest, which stay as thrown. */
function pageWords(container: HTMLElement) {
  const copy = container.cloneNode(true) as HTMLElement;
  copy.querySelectorAll('pre, code').forEach((node) => node.remove());
  return copy.textContent ?? '';
}

describe('error page', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('reads all eight sentences in Chinese when the visitor chose Chinese', () => {
    let { container } = show('zh', API_ERROR);
    expect(screen.getByRole('heading', { name: '没能连上匹配服务。它可能正在唤醒 —— 请过几秒再试。' })).toBeInTheDocument();
    expect(screen.getByText('d1').parentElement?.textContent).toBe('错误编号： d1 — 反馈问题时请附上这个编号。');
    expect(screen.getByText('技术详情')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '返回首页' })).toHaveAttribute('href', '/');
    expect(pageWords(container)).not.toMatch(/[A-Za-z]/);
    cleanup();

    ({ container } = show('zh', PAGE_ERROR));
    expect(screen.getByRole('heading', { name: '这个页面出了点问题。' })).toBeInTheDocument();
    expect(screen.getByText('可以重试；如果问题仍然存在，请刷新页面。')).toBeInTheDocument();
    expect(pageWords(container)).not.toMatch(/[A-Za-z]/);
  });

  it("keeps today's English sentences", () => {
    show('en', API_ERROR);
    expect(screen.getByRole('heading', {
      name: "We couldn't reach the matching service. It may be waking up — please try again in a few seconds.",
    })).toBeInTheDocument();
    expect(screen.getByText('d1').parentElement?.textContent).toBe('Reference ID: d1 — include this if you report the issue.');
    expect(screen.getByText('Technical details')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back home' })).toHaveAttribute('href', '/');
    cleanup();

    show('en', PAGE_ERROR);
    expect(screen.getByRole('heading', { name: 'Something went wrong on this page.' })).toBeInTheDocument();
    expect(screen.getByText('You can retry, or reload the page if the problem persists.')).toBeInTheDocument();
  });
});
