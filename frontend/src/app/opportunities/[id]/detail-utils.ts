import type { TFunc } from './types';

export function formatType(t: string): string {
  return t.replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
}

/**
 * Clean a `compensation_details` value for display. ~4% of scraped records
 * carry a garbled blob — raw ` | ` delimiters plus leaked, concatenated
 * metadata, e.g. "…Duration 10 weeks Compensation $7,000 Citizenship
 * Requirement No Citiz…" — where the real value is just "$7,000". Duration and
 * citizenship have their own fields, so we surface only the pay value. A clean
 * short string passes through untouched. Returns '' when nothing usable is
 * found, so the caller can fall back to the `paid` flag.
 */
export function cleanCompensation(raw?: string | null): string {
  if (!raw) return '';
  const text = raw.trim();
  const looksDirty =
    / \| /.test(text) ||
    /citizenship requirement|duration\s+\d|compensation\s+(\$|paid|stipend|unpaid)/i.test(text) ||
    text.length > 120;
  if (!looksDirty) return text;
  // 1) an explicit dollar amount wins
  const dollar = text.match(/\$\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:\/|per)\s?\w+)?/i);
  if (dollar) return dollar[0].replace(/\s+/g, ' ').trim();
  // 2) a "Compensation <qualitative value>" token
  const qual = text.match(/compensation\s+(paid(?:\s+program)?|stipend(?:\s+provided)?|funded|unpaid)/i);
  if (qual) return qual[1].replace(/\s+/g, ' ').trim().replace(/\b\w/g, (m) => m.toUpperCase());
  // 3) a bare mention
  if (/\bstipend\b/i.test(text)) return 'Stipend provided';
  if (/\bpaid\b/i.test(text)) return 'Paid';
  if (/\bunpaid\b/i.test(text)) return 'Unpaid';
  // 4) nothing usable — let the caller fall back
  return '';
}

export function friendlyLabel(v: string, t: TFunc): string {
  if (v === 'yes') return t('common.yes');
  if (v === 'no') return t('common.no');
  if (v === 'unknown') return t('common.notSpecified');
  return v;
}
