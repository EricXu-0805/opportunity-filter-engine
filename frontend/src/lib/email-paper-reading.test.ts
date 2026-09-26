import { describe, expect, it } from 'vitest';
import type { Opportunity, EmailContactContext } from './types';
import { emailPaperKey, emailPaperOptions, isEmailPaperReadingCurrent } from './email-paper-reading';
const paper = { title: 'Grounded Models 研究 🧪', year: 2025 };
const target = (works: unknown = [paper], status: unknown = 'verified_author_id') => ({ id: 'target-a', metadata: { recent_works: works, publication_attribution_status: status } } as Opportunity);
const context: EmailContactContext = { version: 1, purpose: 'first_contact', paper_reading: { ...paper, level: 'abstract', confirmed: true } };

describe('verified paper reading options', () => {
  it('uses exact current metadata, deduplicates only identical title/year and keeps distinct editions', () => {
    expect(emailPaperOptions(target([paper, { ...paper }, { ...paper, year: 2024 }, { title: paper.title, year: null }]))).toEqual([paper, { ...paper, year: 2024 }, { title: paper.title }]);
    expect(emailPaperKey({ title: 'Paper' })).toBe(emailPaperKey({ title: 'Paper', year: null }));
  });
  it.each([undefined, null, 'name_match', 'pending', true, 'verified_author_id_typo'])('does not expose unverified paper options (%j)', status => {
    const opportunity = target(); opportunity.metadata!.publication_attribution_status = status as never;
    expect(emailPaperOptions(opportunity)).toEqual([]);
    expect(isEmailPaperReadingCurrent(context, opportunity)).toBe(false);
  });
  it.each([null, {}, 'paper'])('rejects malformed publication lists (%j)', works => {
    expect(emailPaperOptions(target(works))).toEqual([]);
  });
  it.each([
    null, {}, { title: '' }, { title: ' padded ' }, { title: 'x'.repeat(501) }, { title: 'Line\nbreak' },
    { title: 'NUL\0' }, { title: 'Lone\ud800' }, { title: 'Year', year: true }, { title: 'Year', year: '2025' },
    { title: 'Year', year: 2025.5 }, { title: 'Year', year: 999 }, { title: 'Year', year: 2101 },
  ])('excludes malformed paper %# without repairing or fabricating it', work => {
    expect(emailPaperOptions(target([work]))).toEqual([]);
  });
  it('does not accept a list projection or a formerly verified title', () => {
    const projection = { id: 'target-a', recent_works: [paper], publication_attribution_status: 'verified_author_id' } as unknown as Opportunity;
    expect(isEmailPaperReadingCurrent(context, projection)).toBe(false);
    expect(isEmailPaperReadingCurrent(context, target([{ ...paper, year: 2024 }]))).toBe(false);
    expect(isEmailPaperReadingCurrent(context, target())).toBe(true);
  });
  it('permits skipping without a target or any publication evidence', () => {
    expect(isEmailPaperReadingCurrent({ version: 1, purpose: 'first_contact' }, null)).toBe(true);
  });
});

import { researchFixture } from './research-context.test-utils';

describe('snapshot-bound paper reading', () => {
  it('requires work ID and version, preserving same-title distinct works', () => {
    const research = researchFixture(); const first = research.snapshot!.works[0];
    research.snapshot!.works.push({ ...first, work_id: 'https://openalex.org/W2' });
    const opp = { ...target(), research_context: research };
    const options = emailPaperOptions(opp);
    expect(options).toHaveLength(2); expect(emailPaperKey(options[0])).not.toBe(emailPaperKey(options[1]));
    expect(isEmailPaperReadingCurrent(context, opp)).toBe(false);
    const bound: EmailContactContext = { ...context, paper_reading: { ...options[1], level: 'abstract', confirmed: true } };
    expect(isEmailPaperReadingCurrent(bound, opp)).toBe(true);
    research.snapshot!.snapshot_version = 'rs1:' + 'b'.repeat(64);
    expect(isEmailPaperReadingCurrent(bound, opp)).toBe(false);
  });
  it('never revives legacy titles through stale, malformed, or raw snapshots', () => {
    const research = researchFixture(); research.status = 'stale';
    expect(emailPaperOptions({ ...target(), research_context: research })).toEqual([]);
    expect(emailPaperOptions({ ...target(), research_context: { ...research, snapshot: null } })).toEqual([]);
    const raw = target(); (raw.metadata as unknown as Record<string, unknown>).research_snapshot = null;
    expect(emailPaperOptions(raw)).toEqual([]);
  });
  it('keeps the explicit legacy compatibility when no new source exists', () => {
    expect(emailPaperOptions({ ...target(), research_context: { version: 1, status: 'unavailable', snapshot: null } })).toEqual([paper]);
  });
});
