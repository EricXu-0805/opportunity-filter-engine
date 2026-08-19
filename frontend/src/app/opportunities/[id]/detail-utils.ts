import type { Opportunity } from '@/lib/types';
import type { TFunc } from './types';

export function formatType(t: string): string {
  return t.replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
}

/**
 * Truthful no-deadline classification. `is_rolling=true` is a blanket
 * collector default on all faculty records and most campus programs — NOT
 * scraped evidence of rolling admissions — so displays must never read it as
 * a fact on its own:
 *   - 'faculty'   — a faculty profile with no listed opening deadline; this
 *     says nothing about whether the lab is currently recruiting;
 *   - 'rolling'   — actual scraped evidence: metadata.deadline_note mentions
 *     rolling;
 *   - 'none'      — everything else: we only know no deadline was listed.
 * Shared by the detail page and the compare surfaces so the evidence gate
 * lives in exactly one place.
 */
export type NoDeadlineKind = 'faculty' | 'rolling' | 'none';

export function noDeadlineKind(
  opp: Pick<Opportunity, 'source_type' | 'metadata'>,
): NoDeadlineKind {
  if (opp.source_type === 'faculty_research') return 'faculty';
  const note = opp.metadata?.deadline_note;
  if (note && /rolling/i.test(note)) return 'rolling';
  return 'none';
}

/**
 * Whether a record's scraped faculty rank supports "Professor" framing
 * ("Email Professor" CTA, "this professor's publication record"). A rank
 * claim is EARNED by a stated professor rank ("Professor", "Assistant
 * Professor", "Prof.", …) — an unknown rank ('' / absent) gets the neutral
 * framing, and a stated non-professor rank ("Senior Lecturer", "Research
 * Scientist") must never be framed as a professor. Mirrors the backend's
 * src/evidence.is_professor_rank, including rejecting "Professional …".
 */
export function allowsProfessorFraming(facultyTitle?: string | null): boolean {
  const rank = (facultyTitle ?? '').trim();
  return /\bprof(?:essor|\.|\b)/i.test(rank);
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
