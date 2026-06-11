import { cookies, headers } from 'next/headers';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { normalizeLocale, translate, DEFAULT_LOCALE } from './translate';
import type { Locale } from './translate';

export const LOCALE_COOKIE = STORAGE_KEYS.LOCALE;

// cookies() / headers() became async in Next.js 15 and the sync form
// is removed in Next.js 16. All call sites must await.
export async function getServerLocale(): Promise<Locale> {
  try {
    const cookieStore = await cookies();
    const fromCookie = cookieStore.get(LOCALE_COOKIE)?.value;
    if (fromCookie) return normalizeLocale(fromCookie);
  } catch {
    /* outside request context */
  }
  try {
    const headerStore = await headers();
    const accept = headerStore.get('accept-language');
    if (accept) {
      const first = accept.split(',')[0]?.trim();
      if (first) return normalizeLocale(first);
    }
  } catch {
    /* outside request context */
  }
  return DEFAULT_LOCALE;
}

// Preferred entry point for server components that render multiple
// translated strings. Resolves the locale once (one cookies()+headers()
// read per render) and returns a synchronous t() bound to it. Use this
// in JSX: `const t = await getServerT(); <h1>{t('about.heroLine1')}</h1>`
export async function getServerT(): Promise<
  (path: string, vars?: Record<string, string | number>) => string
> {
  const locale = await getServerLocale();
  return (path, vars) => translate(locale, path, vars);
}

// Single-call convenience. Each invocation re-reads cookies/headers, so
// prefer getServerT() in pages that translate more than one or two strings.
export async function tServer(
  path: string,
  vars?: Record<string, string | number>,
): Promise<string> {
  const locale = await getServerLocale();
  return translate(locale, path, vars);
}
