'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { translate, normalizeLocale, DEFAULT_LOCALE, LOCALES } from './translate';
import type { Locale } from './translate';

const LOCALE_COOKIE = STORAGE_KEYS.LOCALE;
const LOCALE_STORAGE = STORAGE_KEYS.LOCALE;

interface LanguageContextValue {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (path: string, vars?: Record<string, string | number>) => string;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);

function writeLocaleCookie(locale: Locale) {
  if (typeof document === 'undefined') return;
  const oneYear = 60 * 60 * 24 * 365;
  document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=${oneYear}; SameSite=Lax`;
}

export function LanguageProvider({
  initialLocale,
  children,
}: {
  initialLocale: Locale;
  children: React.ReactNode;
}) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      const stored = localStorage.getItem(LOCALE_STORAGE);
      if (stored) {
        const normalized = normalizeLocale(stored);
        // eslint-disable-next-line react-hooks/set-state-in-effect -- post-hydration locale upgrade: server rendered with the cookie-derived initialLocale; if the user changed locale on a page that didn't get the cookie write back, localStorage is the source of truth. useState initializer here would cause hydration mismatch.
        if (normalized !== locale) setLocaleState(normalized);
      }
    } catch { /* quota */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    writeLocaleCookie(next);
    try { localStorage.setItem(LOCALE_STORAGE, next); } catch { /* quota */ }
    if (typeof document !== 'undefined') {
      document.documentElement.lang = next;
    }
  }, []);

  const t = useCallback(
    (path: string, vars?: Record<string, string | number>) => translate(locale, path, vars),
    [locale],
  );

  const value = useMemo<LanguageContextValue>(() => ({ locale, setLocale, t }), [locale, setLocale, t]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useT() {
  const ctx = useContext(LanguageContext);
  if (!ctx) {
    return {
      locale: DEFAULT_LOCALE,
      setLocale: () => {},
      t: (path: string, vars?: Record<string, string | number>) => translate(DEFAULT_LOCALE, path, vars),
    };
  }
  return ctx;
}

export function useLocale(): Locale {
  return useT().locale;
}

export { LOCALES };
