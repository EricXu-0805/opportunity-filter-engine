import { afterEach, describe, expect, it } from 'vitest';
import {
  addCustomImport,
  findExistingImport,
  readCustomImports,
  removeCustomImport,
} from './custom-imports';
import type { ImportedOpportunity } from './api';

function makeOpp(overrides: Partial<ImportedOpportunity> = {}): ImportedOpportunity {
  return {
    source: 'url_parser',
    source_url: 'https://example.com/job',
    title: 'Sample Internship',
    description_raw: 'desc',
    url: 'https://example.com/job',
    organization: 'Acme Corp',
    extra_fields: { llm_enriched: true },
    ...overrides,
  };
}

afterEach(() => {
  localStorage.clear();
});

describe('addCustomImport', () => {
  it('appends a new entry with a generated id and timestamp', () => {
    const entry = addCustomImport(makeOpp());
    expect(entry.id).toMatch(/^custom-\d+-[a-z0-9]+$/);
    expect(entry.imported_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(readCustomImports()).toHaveLength(1);
    expect(readCustomImports()[0].opportunity.title).toBe('Sample Internship');
  });

  it('returns the existing entry when source_url matches (no duplicate write)', () => {
    const first = addCustomImport(makeOpp());
    const second = addCustomImport(makeOpp({ description_raw: 'different desc' }));
    expect(second.id).toBe(first.id);
    expect(readCustomImports()).toHaveLength(1);
    expect(readCustomImports()[0].opportunity.description_raw).toBe('desc');
  });

  it('prepends new entries so most recent is first', () => {
    addCustomImport(makeOpp({ source_url: 'https://example.com/a', title: 'A' }));
    addCustomImport(makeOpp({ source_url: 'https://example.com/b', title: 'B' }));
    const list = readCustomImports();
    expect(list.map((e) => e.opportunity.title)).toEqual(['B', 'A']);
  });

  it('deduplicates by title + organization when no source_url present', () => {
    const oppA = makeOpp({ source_url: '', url: '', title: 'Pasted Posting', organization: 'BigCo' });
    const oppB = makeOpp({ source_url: '', url: '', title: 'Pasted Posting', organization: 'BigCo', description_raw: 'updated' });
    const first = addCustomImport(oppA);
    const second = addCustomImport(oppB);
    expect(second.id).toBe(first.id);
    expect(readCustomImports()).toHaveLength(1);
  });

  it('does NOT deduplicate empty-URL entries with different title/org', () => {
    addCustomImport(makeOpp({ source_url: '', url: '', title: 'A', organization: 'X' }));
    addCustomImport(makeOpp({ source_url: '', url: '', title: 'B', organization: 'X' }));
    expect(readCustomImports()).toHaveLength(2);
  });
});

describe('removeCustomImport', () => {
  it('removes the entry with the matching id', () => {
    const a = addCustomImport(makeOpp({ source_url: 'https://a.example/x', title: 'A' }));
    addCustomImport(makeOpp({ source_url: 'https://b.example/x', title: 'B' }));
    removeCustomImport(a.id);
    const list = readCustomImports();
    expect(list).toHaveLength(1);
    expect(list[0].opportunity.title).toBe('B');
  });

  it('removes the storage key entirely when last entry is removed', () => {
    const a = addCustomImport(makeOpp());
    removeCustomImport(a.id);
    expect(localStorage.getItem('ofe_custom_imports')).toBeNull();
  });

  it('is a no-op for unknown id', () => {
    addCustomImport(makeOpp());
    removeCustomImport('custom-doesnotexist');
    expect(readCustomImports()).toHaveLength(1);
  });
});

describe('findExistingImport', () => {
  it('returns null for empty storage', () => {
    expect(findExistingImport(makeOpp())).toBeNull();
  });

  it('matches on source_url ignoring other fields', () => {
    const entry = addCustomImport(makeOpp());
    const lookup = findExistingImport(
      makeOpp({ title: 'Different Title', organization: 'Different Org' }),
    );
    expect(lookup?.id).toBe(entry.id);
  });
});
