import type { ImportUrlResponse } from './api';

export interface ImportSourceInfo {
  source: 'page_text' | 'pasted_text' | 'page_excerpt' | 'unknown';
  aiInputScope: 'full_source' | 'source_excerpt' | 'unknown';
}

/** A model response alone is not evidence of complete input or correct reading. */
export function importSourceInfo(extra: Record<string, unknown> | undefined, text: string): ImportSourceInfo {
  const value = extra?.description_source;
  const source = value === 'page_text' || value === 'pasted_text' || value === 'page_excerpt' ? value : 'unknown';
  const hasText = text.trim().length > 0;
  const full = (source === 'page_text' || source === 'pasted_text') && hasText && extra?.ai_input_scope === 'full_source';
  const excerpt = source !== 'unknown' && hasText && extra?.ai_input_scope === 'source_excerpt';
  return { source, aiInputScope: full ? 'full_source' : excerpt ? 'source_excerpt' : 'unknown' };
}

export function importFailureKey(mode: 'url' | 'text', result: ImportUrlResponse): string {
  if (result.error_code === 'import_input_too_large') {
    return mode === 'url' ? 'import.errorPageTooLong' : 'import.errorTextTooLong';
  }
  if (result.error_code === 'import_source_unreadable') return 'import.errorSourceUnreadable';
  if (mode === 'url' && result.error?.toLowerCase().includes('unsafe')) return 'import.errorUnsafe';
  return mode === 'url' ? 'import.errorFetch' : 'import.errorExtract';
}
