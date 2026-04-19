import { cookies, headers } from 'next/headers';
import { normalizeLocale, translate, DEFAULT_LOCALE } from './translate';
import type { Locale } from './translate';

export const LOCALE_COOKIE = 'ofe_lang';

export function getServerLocale(): Locale {
  try {
    const fromCookie = cookies().get(LOCALE_COOKIE)?.value;
    if (fromCookie) return normalizeLocale(fromCookie);
  } catch {
    /* outside request context */
  }
  try {
    const accept = headers().get('accept-language');
    if (accept) {
      const first = accept.split(',')[0]?.trim();
      if (first) return normalizeLocale(first);
    }
  } catch {
    /* outside request context */
  }
  return DEFAULT_LOCALE;
}

export function tServer(path: string, vars?: Record<string, string | number>): string {
  return translate(getServerLocale(), path, vars);
}
