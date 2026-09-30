import { StrictMode, useState } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Locale } from './translate';
import { STORAGE_KEYS } from '@/lib/storage-keys';

const navigation = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => navigation }));

import { LanguageProvider, useT } from './client';
import LanguageSwitcher from '@/components/LanguageSwitcher';

function Consumer() {
  const { locale, t } = useT();
  const [draft, setDraft] = useState('');
  return <><output aria-label="locale">{locale}</output><p>{t('detail.backToMatches')}</p>
    <input aria-label="unsaved draft" value={draft} onChange={event => setDraft(event.target.value)} />
    <LanguageSwitcher /></>;
}
function View({ locale }: { locale: Locale }) {
  return <LanguageProvider initialLocale={locale}><Consumer /><footer>{locale === 'zh' ? '隐私政策' : 'Privacy Policy'}</footer></LanguageProvider>;
}

beforeEach(() => {
  navigation.refresh.mockReset();
  document.cookie = `${STORAGE_KEYS.LOCALE}=; path=/; max-age=0`;
  document.documentElement.lang = '';
});

describe('language recovery shares the server-rendered locale', () => {
  it('writes the missing cookie then waits for the server instead of changing hydrating text', () => {
    localStorage.setItem(STORAGE_KEYS.LOCALE, 'zh');
    const view = render(<View locale="en" />);
    expect(navigation.refresh).toHaveBeenCalledTimes(1);
    expect(document.cookie).toContain('ofe_lang=zh');
    expect(screen.getByLabelText('locale')).toHaveTextContent('en');
    expect(screen.getByText('Privacy Policy')).toBeVisible();
    expect(document.documentElement.lang).toBe('en');
    view.rerender(<View locale="zh" />);
    expect(screen.getByLabelText('locale')).toHaveTextContent('zh');
    expect(screen.getByText('隐私政策')).toBeVisible();
    expect(document.documentElement.lang).toBe('zh');
    expect(navigation.refresh).toHaveBeenCalledTimes(1);
  });

  it.each([['en', 'zh'], ['zh', 'en']] as const)('resolves %s server / %s stored conflict once', (initial, stored) => {
    document.cookie = `ofe_lang=${initial}; path=/`;
    localStorage.setItem(STORAGE_KEYS.LOCALE, stored);
    const view = render(<StrictMode><View locale={initial} /></StrictMode>);
    expect(navigation.refresh).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('locale')).toHaveTextContent(initial);
    expect(document.cookie).toContain(`ofe_lang=${stored}`);
    view.rerender(<StrictMode><View locale={stored} /></StrictMode>);
    expect(screen.getByLabelText('locale')).toHaveTextContent(stored);
    expect(navigation.refresh).toHaveBeenCalledTimes(1);
  });

  it('does not refresh matching stored/server preferences, including a remount', () => {
    document.cookie = 'ofe_lang=zh; path=/';
    localStorage.setItem(STORAGE_KEYS.LOCALE, 'zh-CN');
    const first = render(<View locale="zh" />); first.unmount();
    render(<View locale="zh" />);
    expect(navigation.refresh).not.toHaveBeenCalled();
    expect(document.documentElement.lang).toBe('zh');
  });

  it('uses the server preference when storage is absent or unreadable', () => {
    const first = render(<View locale="zh" />); first.unmount();
    vi.spyOn(localStorage, 'getItem').mockImplementation(() => { throw new DOMException('blocked', 'SecurityError'); });
    render(<View locale="zh" />);
    expect(navigation.refresh).not.toHaveBeenCalled();
    expect(screen.getByLabelText('locale')).toHaveTextContent('zh');
  });

  it.each(['silent', 'throws'])('does not refresh-loop when cookie writes fail (%s)', mode => {
    localStorage.setItem(STORAGE_KEYS.LOCALE, 'zh');
    vi.spyOn(document, 'cookie', 'set').mockImplementation(() => {
      if (mode === 'throws') throw new DOMException('blocked', 'SecurityError');
    });
    const view = render(<StrictMode><View locale="en" /></StrictMode>);
    expect(navigation.refresh).not.toHaveBeenCalled();
    expect(screen.getByLabelText('locale')).toHaveTextContent('en');
    expect(screen.getByRole('alert')).toHaveTextContent('Allow cookies');
    expect(screen.getByRole('button', { name: 'Switch to Chinese' })).toHaveTextContent('Retry language');
    fireEvent.click(screen.getByRole('button', { name: 'Switch to Chinese' }));
    view.rerender(<StrictMode><View locale="en" /></StrictMode>);
    expect(navigation.refresh).not.toHaveBeenCalled();
    expect(document.documentElement.lang).toBe('en');
  });

  it('preserves the current unsaved form through an explicit server locale update', () => {
    const view = render(<View locale="en" />);
    fireEvent.change(screen.getByLabelText('unsaved draft'), { target: { value: 'My existing draft 王' } });
    fireEvent.click(screen.getByRole('button', { name: 'Switch to Chinese' }));
    expect(navigation.refresh).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(STORAGE_KEYS.LOCALE)).toBe('zh');
    expect(screen.getByLabelText('locale')).toHaveTextContent('en');
    view.rerender(<View locale="zh" />);
    expect(screen.getByLabelText('unsaved draft')).toHaveValue('My existing draft 王');
    expect(screen.getByText('隐私政策')).toBeVisible();
    expect(navigation.refresh).toHaveBeenCalledTimes(1);
  });

  it('can persist the cookie even when writing localStorage is blocked', () => {
    render(<View locale="en" />);
    vi.spyOn(localStorage, 'setItem').mockImplementation(() => { throw new DOMException('blocked', 'SecurityError'); });
    fireEvent.click(screen.getByRole('button', { name: 'Switch to Chinese' }));
    expect(document.cookie).toContain('ofe_lang=zh');
    expect(navigation.refresh).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows a pending switch and prevents duplicate clicks until the refresh settles', async () => {
    let settle!: () => void;
    navigation.refresh.mockImplementation(() => new Promise<void>(resolve => { settle = resolve; }));
    const view = render(<View locale="en" />);
    const button = screen.getByRole('button', { name: 'Switch to Chinese' });
    fireEvent.click(button);
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent('Switching…');
    expect(button).toHaveAttribute('lang', 'en');
    expect(button).toHaveAttribute('aria-busy', 'true');
    fireEvent.click(button);
    expect(navigation.refresh).toHaveBeenCalledTimes(1);
    await act(async () => { settle(); });
    view.rerender(<View locale="zh" />);
    expect(screen.getByRole('button', { name: 'Switch to English' })).toBeEnabled();
  });
});
