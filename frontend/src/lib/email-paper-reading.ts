import { parseResearchContext } from './research-context';
import type { EmailContactContext, Opportunity } from './types';

export type EmailPaperOption = { title: string; year?: number; work_id?: string; snapshot_version?: string };
export type EmailPaperReading = NonNullable<EmailContactContext['paper_reading']>;
export function emailPaperKey(paper: Pick<EmailPaperReading, 'title' | 'year' | 'work_id' | 'snapshot_version'>): string {
  return JSON.stringify(paper.work_id || paper.snapshot_version
    ? [paper.title, paper.year ?? null, paper.work_id ?? null, paper.snapshot_version ?? null]
    : [paper.title, paper.year ?? null]);
}

/** Full current target metadata only. A list projection/name match is not authority. */
export function emailPaperOptions(opportunity?: Opportunity | null): EmailPaperOption[] {
  const metadata = opportunity?.metadata;
  if (opportunity && 'research_context' in opportunity) {
    const context = parseResearchContext(opportunity.research_context);
    if (!context || context.status === 'stale') return [];
    if (context.status === 'available') return context.snapshot!.works
      .filter(work => work.title === work.title.trim() && !/[\r\n\u2028\u2029]/u.test(work.title))
      .map(work => ({ title: work.title, year: work.year, work_id: work.work_id, snapshot_version: context.snapshot!.snapshot_version }));
  }
  // An unprojected stale/invalid raw snapshot must never revive legacy options.
  if (metadata && 'research_snapshot' in metadata) return [];
  if (metadata?.publication_attribution_status !== 'verified_author_id' || !Array.isArray(metadata.recent_works)) return [];
  const options = new Map<string, EmailPaperOption>();
  for (const work of metadata.recent_works) {
    if (!work || typeof work.title !== 'string' || !work.title || work.title !== work.title.trim()
      || [...work.title].length > 500 || /[\u0000\r\n\u2028\u2029]/u.test(work.title)
      || [...work.title].some(ch => { const p = ch.codePointAt(0)!; return p >= 0xd800 && p <= 0xdfff; })) continue;
    if (work.year != null && (typeof work.year !== 'number' || !Number.isInteger(work.year) || work.year < 1000 || work.year > 2100)) continue;
    const paper = { title: work.title, ...(work.year != null ? { year: work.year } : {}) };
    options.set(emailPaperKey(paper), paper);
  }
  return [...options.values()];
}

export function isEmailPaperReadingCurrent(context: EmailContactContext, opportunity?: Opportunity | null): boolean {
  return !context.paper_reading || emailPaperOptions(opportunity).some(paper => emailPaperKey(paper) === emailPaperKey(context.paper_reading!));
}
