import { dictionaries, DEFAULT_LOCALE, LOCALES } from './dictionaries';
import type { Locale, Dictionary } from './dictionaries';

export { LOCALES, DEFAULT_LOCALE };
export type { Locale };

type Path = string;

type DeepValue = string | DeepObj;
interface DeepObj { [key: string]: DeepValue }

export function resolvePath(dict: DeepObj, path: Path): string | undefined {
  const parts = path.split('.');
  let cur: DeepValue = dict;
  for (const part of parts) {
    if (typeof cur !== 'object' || cur === null || !(part in cur)) return undefined;
    cur = (cur as DeepObj)[part];
  }
  return typeof cur === 'string' ? cur : undefined;
}

export function interpolate(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key) => {
    const v = vars[key];
    return v === undefined || v === null ? match : String(v);
  });
}

export function translate(
  locale: Locale,
  path: Path,
  vars?: Record<string, string | number>,
): string {
  const dict = dictionaries[locale] ?? dictionaries[DEFAULT_LOCALE];
  const resolved = resolvePath(dict as DeepObj, path);
  if (resolved === undefined) {
    const fallback = resolvePath(dictionaries[DEFAULT_LOCALE] as DeepObj, path);
    if (fallback === undefined) return path;
    return vars ? interpolate(fallback, vars) : fallback;
  }
  return vars ? interpolate(resolved, vars) : resolved;
}

export function isLocale(v: unknown): v is Locale {
  return typeof v === 'string' && (LOCALES as readonly string[]).includes(v);
}

export function normalizeLocale(v: string | undefined | null): Locale {
  if (!v) return DEFAULT_LOCALE;
  const lower = v.toLowerCase();
  if (lower.startsWith('zh')) return 'zh';
  if (lower.startsWith('en')) return 'en';
  return isLocale(v) ? (v as Locale) : DEFAULT_LOCALE;
}

export type { Dictionary };
