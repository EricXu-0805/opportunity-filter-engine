'use client';

import { useT } from '@/i18n/client';
import type { Locale } from '@/i18n/translate';

const LABELS: Record<Locale, string> = {
  en: 'EN',
  zh: '中文',
};

export default function LanguageSwitcher() {
  const { locale, setLocale, isChanging, changeFailed } = useT();
  const other: Locale = locale === 'en' ? 'zh' : 'en';

  const pendingLabel = locale === 'zh' ? '切换中…' : 'Switching…';
  const retryLabel = locale === 'zh' ? '重试切换' : 'Retry language';
  const failedLabel = locale === 'zh' ? '无法保存语言偏好，请允许此网站使用 Cookie 后重试。' : 'Could not save the language preference. Allow cookies for this site and try again.';

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setLocale(other);
        }}
        className="inline-flex items-center justify-center h-7 px-2 rounded-full text-[11px] font-medium text-gray-500 hover:text-gray-900 hover:bg-black/[0.04] focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 transition-colors"
        aria-label={locale === 'en' ? 'Switch to Chinese' : 'Switch to English'}
        lang={isChanging || changeFailed ? locale : other}
        disabled={isChanging}
        aria-busy={isChanging || undefined}
        title={changeFailed ? failedLabel : undefined}
      >
        {isChanging ? pendingLabel : changeFailed ? retryLabel : LABELS[other]}
      </button>
      {changeFailed && <span role="alert" className="sr-only">{failedLabel}</span>}
    </>
  );
}
