import { describe, expect, it } from 'vitest';
import { parseResearchContext } from './research-context';
import { researchFixture } from './research-context.test-utils';

describe('strict research context', () => {
  it('copies complete source text and preserves saved status without a clock-dependent upgrade', () => {
    const value = researchFixture(); value.snapshot!.works[0].abstract = '完整原文\n' + '🧪'.repeat(100);
    const out = parseResearchContext(value)!;
    expect(out).toEqual(value); expect(out).not.toBe(value); expect(out.snapshot!.works).not.toBe(value.snapshot!.works);
    value.status = 'stale'; expect(parseResearchContext(value)?.status).toBe('stale');
    expect(parseResearchContext({ version: 1, status: 'unavailable', snapshot: null })).not.toBeNull();
  });
  it.each([
    (v: ReturnType<typeof researchFixture>) => { (v as unknown as Record<string, unknown>).extra = true; },
    (v: ReturnType<typeof researchFixture>) => { v.snapshot!.author_id = 'https://openalex.org/A9999999999'; },
    (v: ReturnType<typeof researchFixture>) => { v.snapshot!.author_id = 'https://openalex.org/A5317838346'; },
    (v: ReturnType<typeof researchFixture>) => { v.snapshot!.author_id = 'A1'; },
    (v: ReturnType<typeof researchFixture>) => { v.snapshot!.snapshot_version = 'rs1:fake'; },
    (v: ReturnType<typeof researchFixture>) => { v.snapshot!.record_source_url = 'https://name:secret@example.edu'; },
    (v: ReturnType<typeof researchFixture>) => { v.snapshot!.record_source_url = 'javascript:alert(1)'; },
    (v: ReturnType<typeof researchFixture>) => { v.snapshot!.checked_at = '2026-02-30T12:00:00Z'; },
    (v: ReturnType<typeof researchFixture>) => { v.snapshot!.gate_version = 2; },
    (v: ReturnType<typeof researchFixture>) => { v.snapshot!.works[0].title = 'x'.repeat(1001); },
    (v: ReturnType<typeof researchFixture>) => { v.snapshot!.works[0].abstract = '🧪'.repeat(12001); },
    (v: ReturnType<typeof researchFixture>) => { v.snapshot!.works[0].abstract_status = 'missing'; },
    (v: ReturnType<typeof researchFixture>) => { v.snapshot!.works[0].source_url = 'https://attacker.example'; },
    (v: ReturnType<typeof researchFixture>) => { v.snapshot!.works[0].publication_date = '2024-01-01'; },
    (v: ReturnType<typeof researchFixture>) => { v.snapshot!.works.push({ ...v.snapshot!.works[0] }); },
    (v: ReturnType<typeof researchFixture>) => { v.status = 'unavailable'; },
  ])('rejects malformed or conflicting source shape %#', change => {
    const value = researchFixture(); change(value); expect(parseResearchContext(value)).toBeNull();
  });
  it('preserves same-title distinct IDs and explicit absent abstracts', () => {
    const value = researchFixture(); const first = value.snapshot!.works[0];
    first.abstract_status = 'too_long'; first.abstract = null;
    value.snapshot!.works.push({ ...first, work_id: 'https://openalex.org/W2', source_url: 'https://openalex.org/W2', doi: null });
    expect(parseResearchContext(value)).toEqual(value);
  });
});
