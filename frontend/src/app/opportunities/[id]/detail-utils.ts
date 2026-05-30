import type { TFunc } from './types';

export function formatType(t: string): string {
  return t.replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
}

export function friendlyLabel(v: string, t: TFunc): string {
  if (v === 'yes') return t('common.yes');
  if (v === 'no') return t('common.no');
  if (v === 'unknown') return t('common.notSpecified');
  return v;
}
