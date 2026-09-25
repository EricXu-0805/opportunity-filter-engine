'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, useTransition } from 'react';
import { useRouter } from 'next/navigation';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { translate, normalizeLocale, DEFAULT_LOCALE, LOCALES } from './translate';
import type { Locale } from './translate';

const LOCALE_COOKIE = STORAGE_KEYS.LOCALE;
const LOCALE_STORAGE = STORAGE_KEYS.LOCALE;

interface LanguageContextValue {
  locale: Locale;
  setLocale: (l: Locale) => void;
  isChanging: boolean;
  changeFailed: boolean;
  t: (path: string, vars?: Record<string, string | number>) => string;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);

function writeLocaleCookie(locale: Locale): boolean {
  try {
    const oneYear = 60 * 60 * 24 * 365;
    document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=${oneYear}; SameSite=Lax`;
    // A blocked cookie write can silently do nothing. Do not repeatedly ask
    // the server for a preference it cannot receive.
    return document.cookie.split(';').some(part => part.trim() === `${LOCALE_COOKIE}=${locale}`);
  } catch { return false; }
}

export function LanguageProvider({
  initialLocale,
  children,
}: {
  initialLocale: Locale;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [isChanging, startTransition] = useTransition();
  const [changeFailed, setChangeFailed] = useState(false);
  const recovered = useRef(false);
  // Client text and server-rendered layout text use the same locale. Updating
  // context from a mount effect can race a still-hydrating streamed boundary.
  const locale = initialLocale;

  const setLocale = useCallback((next: Locale) => {
    if (isChanging) return;
    if (!writeLocaleCookie(next)) {
      setChangeFailed(true);
      return;
    }
    try { localStorage.setItem(LOCALE_STORAGE, next); } catch { /* cookie still persists the preference */ }
    setChangeFailed(false);
    if (next !== initialLocale) startTransition(() => router.refresh());
  }, [initialLocale, isChanging, router]);

  useEffect(() => {
    document.documentElement.lang = initialLocale;
    // Reconcile old localStorage-only preferences once, including StrictMode's
    // effect replay. A successful cookie write makes the next navigation agree.
    if (recovered.current) return;
    recovered.current = true;
    try {
      const stored = localStorage.getItem(LOCALE_STORAGE);
      if (!stored) return;
      const preferred = normalizeLocale(stored);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- One-time browser preference migration performs cookie I/O and an RSC refresh; only pending/error feedback changes locally, never the rendered locale.
      if (preferred !== initialLocale) setLocale(preferred);
      else writeLocaleCookie(preferred);
    } catch { /* Restricted storage leaves the server preference authoritative. */ }
  }, [initialLocale, setLocale]);

  const t = useCallback(
    (path: string, vars?: Record<string, string | number>) => translate(locale, path, vars),
    [locale],
  );

  const value = useMemo<LanguageContextValue>(() => ({ locale, setLocale, isChanging, changeFailed, t }), [locale, setLocale, isChanging, changeFailed, t]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useT() {
  const ctx = useContext(LanguageContext);
  if (!ctx) {
    return {
      locale: DEFAULT_LOCALE,
      setLocale: () => {},
      isChanging: false,
      changeFailed: false,
      t: (path: string, vars?: Record<string, string | number>) => translate(DEFAULT_LOCALE, path, vars),
    };
  }
  return ctx;
}

export function useLocale(): Locale {
  return useT().locale;
}

export { LOCALES };
