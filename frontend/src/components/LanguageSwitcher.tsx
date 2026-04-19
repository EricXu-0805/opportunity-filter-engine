'use client';

import { useRouter } from 'next/navigation';
import { useT } from '@/i18n/client';
import type { Locale } from '@/i18n/translate';

const LABELS: Record<Locale, string> = {
  en: 'EN',
  zh: '中文',
};

export default function LanguageSwitcher() {
  const { locale, setLocale } = useT();
  const router = useRouter();
  const other: Locale = locale === 'en' ? 'zh' : 'en';

  return (
    <button
      type="button"
      onClick={() => {
        setLocale(other);
        router.refresh();
      }}
      className="inline-flex items-center justify-center h-7 px-2 rounded-full text-[11px] font-medium text-gray-500 hover:text-gray-900 hover:bg-black/[0.04] focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 transition-colors"
      aria-label={locale === 'en' ? 'Switch to Chinese' : 'Switch to English'}
      lang={other}
    >
      {LABELS[other]}
    </button>
  );
}
