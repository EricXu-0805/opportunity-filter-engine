import { describe, expect, it } from 'vitest';
import { DETAIL_FIELD_NAMES, readDetailFields } from './detail-fields';

function envelope(fields: Record<string, unknown>, version = 'm03-v1') {
  return { detail_fields: { version, fields } };
}

describe('readDetailFields', () => {
  it('returns null — legacy sections, not "all confirmed" — when there is nothing to read', () => {
    expect(readDetailFields(undefined)).toBeNull();
    expect(readDetailFields({})).toBeNull();
    expect(readDetailFields({ detail_fields: null })).toBeNull();
    expect(readDetailFields(envelope({}, 'm03-v0'))).toBeNull();
    expect(readDetailFields({ detail_fields: 'm03-v1' })).toBeNull();
  });

  it('reports every field, and a missing field as unknown', () => {
    const fields = readDetailFields(envelope({}))!;
    expect(Object.keys(fields)).toEqual([...DETAIL_FIELD_NAMES]);
    for (const name of DETAIL_FIELD_NAMES) {
      expect(fields[name].state).toBe('unknown');
      expect(fields[name].facets.every((f) => f.truth.state === 'unknown')).toBe(true);
    }
  });

  it('reads source, inferred and unknown facets', () => {
    const fields = readDetailFields(envelope({
      funding: {
        state: 'inferred',
        explicit: { compensation: '$5,000' },
        inferred: { paid: { value: 'stipend', basis: 'collector_default' } },
        unknown: [],
        provenance: { source_url: 'https://example.edu/p', observed_at: '2026-09-01T00:00:00' },
      },
    }))!;
    const byFacet = Object.fromEntries(fields.funding.facets.map((f) => [f.facet, f.truth]));
    expect(byFacet.compensation).toEqual({ state: 'source', value: '$5,000' });
    expect(byFacet.paid).toEqual({ state: 'inferred', value: 'stipend', basis: 'collector_default' });
    expect(fields.funding.sourceUrl).toBe('https://example.edu/p');
    expect(fields.funding.observedAt).toBe('2026-09-01');
  });

  it('keeps a stated value and our derived one side by side', () => {
    const fields = readDetailFields(envelope({
      research_content: {
        explicit: { research_areas: 'Number theory' },
        inferred: { research_areas: { value: ['number theory'], basis: 'external_enrichment' } },
      },
    }))!;
    expect(fields.research_content.facets.map((f) => f.truth.state)).toEqual(['source', 'inferred']);
  });

  it('fails closed: malformed values and unknown bases become unknown, never source', () => {
    const fields = readDetailFields(envelope({
      funding: {
        state: 'source',
        explicit: { paid: { nested: 'object' }, compensation: '   ' },
        inferred: {},
      },
      eligibility: {
        inferred: {
          majors: { value: ['CS'], basis: 'vibes' },
          class_year: 'junior',
          international_students: { value: ['yes', 3], basis: 'text_scan' },
        },
      },
    }))!;
    expect(fields.funding.state).toBe('unknown');
    expect(fields.eligibility.state).toBe('unknown');
  });

  it('recomputes the field state from its facets instead of trusting the summary', () => {
    const fields = readDetailFields(envelope({
      funding: { state: 'source', explicit: {}, inferred: {} },
    }))!;
    expect(fields.funding.state).toBe('unknown');
  });

  it('drops a non-http source url', () => {
    const fields = readDetailFields(envelope({
      school: { explicit: { institution: 'X' }, provenance: { source_url: 'javascript:alert(1)' } },
    }))!;
    expect(fields.school.sourceUrl).toBeNull();
  });
});
