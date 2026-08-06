import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  addCustomImport,
  findExistingImport,
  readCustomImports,
  removeCustomImport,
} from './custom-imports';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner, type OwnerToken } from './identity-owner';
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

// custom-imports.ts's writes now go through writeLocalStorageJSON's
// origin-token discipline — every test needs local-owner readiness
// established (and a fresh token captured under it) before writing.
let token: OwnerToken;
beforeEach(async () => {
  advanceOwnerEpoch('custom-imports-test-uid');
  await syncLocalIdentityOwner('custom-imports-test-uid');
  token = captureOwnerToken();
});

afterEach(() => {
  localStorage.clear();
});

describe('addCustomImport', () => {
  it('appends a new entry with a generated id and timestamp', () => {
    // Non-null: `token` is a freshly established valid identity throughout
    // this describe block — addCustomImport's null return is exercised by
    // its own dedicated stale-token tests below.
    const entry = addCustomImport(makeOpp(), token)!;
    expect(entry.id).toMatch(/^custom-\d+-[a-z0-9]+$/);
    expect(entry.imported_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(readCustomImports()).toHaveLength(1);
    expect(readCustomImports()[0].opportunity.title).toBe('Sample Internship');
  });

  it('returns the existing entry when source_url matches (no duplicate write)', () => {
    const first = addCustomImport(makeOpp(), token)!;
    const second = addCustomImport(makeOpp({ description_raw: 'different desc' }), token)!;
    expect(second.id).toBe(first.id);
    expect(readCustomImports()).toHaveLength(1);
    expect(readCustomImports()[0].opportunity.description_raw).toBe('desc');
  });

  it('prepends new entries so most recent is first', () => {
    addCustomImport(makeOpp({ source_url: 'https://example.com/a', title: 'A' }), token);
    addCustomImport(makeOpp({ source_url: 'https://example.com/b', title: 'B' }), token);
    const list = readCustomImports();
    expect(list.map((e) => e.opportunity.title)).toEqual(['B', 'A']);
  });

  it('deduplicates by title + organization when no source_url present', () => {
    const oppA = makeOpp({ source_url: '', url: '', title: 'Pasted Posting', organization: 'BigCo' });
    const oppB = makeOpp({ source_url: '', url: '', title: 'Pasted Posting', organization: 'BigCo', description_raw: 'updated' });
    const first = addCustomImport(oppA, token)!;
    const second = addCustomImport(oppB, token)!;
    expect(second.id).toBe(first.id);
    expect(readCustomImports()).toHaveLength(1);
  });

  it('does NOT deduplicate empty-URL entries with different title/org', () => {
    addCustomImport(makeOpp({ source_url: '', url: '', title: 'A', organization: 'X' }), token);
    addCustomImport(makeOpp({ source_url: '', url: '', title: 'B', organization: 'X' }), token);
    expect(readCustomImports()).toHaveLength(2);
  });

  it('a STALE token (captured under a different owner) is silently rejected — the import is never written', async () => {
    const staleToken = token;
    advanceOwnerEpoch('custom-imports-other-uid');
    await syncLocalIdentityOwner('custom-imports-other-uid');
    const entry = addCustomImport(makeOpp(), staleToken);
    // Rejected before any read/write — nothing was persisted, and nothing
    // (not even a synthesized entry) is handed back to the stale caller.
    expect(entry).toBeNull();
    expect(readCustomImports()).toHaveLength(0);
  });

  it('a STALE token must not even READ the current owner\'s list — a dup match must not leak the current owner\'s entry back to the stale caller', async () => {
    const staleToken = token;
    advanceOwnerEpoch('custom-imports-leak-uid');
    await syncLocalIdentityOwner('custom-imports-leak-uid');
    const currentToken = captureOwnerToken();
    const shared = makeOpp({ source_url: 'https://shared.example/x', title: 'Shared' });
    // The CURRENT owner already saved an opportunity that would look like
    // a "duplicate" of what the stale caller is about to submit.
    const currentEntry = addCustomImport(shared, currentToken);
    // A fix that only gates the final WRITE (but still performs the read +
    // dedup check) would find the current owner's entry as a "duplicate"
    // and return it — leaking their real entry id/timestamp to a caller
    // acting on a since-replaced identity.
    const result = addCustomImport(shared, staleToken);
    expect(result).toBeNull();
    expect(readCustomImports()).toEqual([currentEntry]);
  });

  it('a VALID token whose write still fails (quota exceeded) returns null, not the entry it failed to persist', () => {
    const original = window.localStorage;
    const store = new Map<string, string>();
    for (let i = 0; i < original.length; i += 1) {
      const k = original.key(i)!;
      store.set(k, original.getItem(k)!);
    }
    Object.defineProperty(window, 'localStorage', {
      value: {
        get length() { return store.size; },
        key: (i: number) => [...store.keys()][i] ?? null,
        getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
        setItem: () => { throw new Error('QuotaExceededError'); },
        removeItem: (k: string) => { store.delete(k); },
        clear: () => store.clear(),
      },
      configurable: true,
    });
    try {
      const result = addCustomImport(makeOpp(), token);
      expect(result).toBeNull();
      expect(store.has('ofe_custom_imports')).toBe(false);
    } finally {
      Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
    }
  });
});

describe('removeCustomImport', () => {
  it('removes the entry with the matching id', () => {
    const a = addCustomImport(makeOpp({ source_url: 'https://a.example/x', title: 'A' }), token)!;
    addCustomImport(makeOpp({ source_url: 'https://b.example/x', title: 'B' }), token);
    removeCustomImport(a.id, token);
    const list = readCustomImports();
    expect(list).toHaveLength(1);
    expect(list[0].opportunity.title).toBe('B');
  });

  it('removes the storage key entirely when last entry is removed', () => {
    const a = addCustomImport(makeOpp(), token)!;
    removeCustomImport(a.id, token);
    expect(localStorage.getItem('ofe_custom_imports')).toBeNull();
  });

  it('is a no-op for unknown id, but still reports the token as current', () => {
    addCustomImport(makeOpp(), token)!;
    expect(removeCustomImport('custom-doesnotexist', token)).toBe(true);
    expect(readCustomImports()).toHaveLength(1);
  });

  it('a STALE token cannot remove the CURRENT owner\'s own entry — reports false so the caller can retry', async () => {
    const a = addCustomImport(makeOpp(), token)!;
    const staleToken = token;
    advanceOwnerEpoch('custom-imports-remove-other-uid');
    await syncLocalIdentityOwner('custom-imports-remove-other-uid');
    // The current owner writes their own entry under the same list shape.
    addCustomImport(makeOpp({ source_url: 'https://current.example/x', title: 'Current' }), captureOwnerToken());
    expect(removeCustomImport(a.id, staleToken)).toBe(false); // stale — must not touch the CURRENT owner's list
    expect(readCustomImports().map((e) => e.opportunity.title)).toEqual(['Current']);
  });

  it('a VALID token whose write still fails (quota/private-mode) returns false, and the old list is preserved', () => {
    // Two entries so the removal still needs a setItem (writing the
    // filtered list), not a bare removeItem (removing the last one) —
    // that's the path where a throwing setItem is actually exercised.
    const a = addCustomImport(makeOpp({ source_url: 'https://a.example/x', title: 'A' }), token)!;
    addCustomImport(makeOpp({ source_url: 'https://b.example/x', title: 'Keeper' }), token);
    const original = window.localStorage;
    // EVERY key, not just the list — the ownership marker lives here too, and a
    // facade that drops it makes the browser look unclaimed, which refuses the
    // write for a reason that has nothing to do with the quota under test.
    const store = new Map<string, string>();
    for (let i = 0; i < original.length; i += 1) {
      const k = original.key(i)!;
      store.set(k, original.getItem(k)!);
    }
    Object.defineProperty(window, 'localStorage', {
      value: {
        get length() { return store.size; },
        key: (i: number) => [...store.keys()][i] ?? null,
        getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
        setItem: () => { throw new Error('QuotaExceededError'); },
        removeItem: (k: string) => { store.delete(k); },
        clear: () => store.clear(),
      },
      configurable: true,
    });
    try {
      expect(removeCustomImport(a.id, token)).toBe(false);
      expect(readCustomImports()).toHaveLength(2);
      expect(readCustomImports().map((e) => e.opportunity.title)).toEqual(['Keeper', 'A']);
    } finally {
      Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
    }
  });
});

describe('findExistingImport', () => {
  it('returns null for empty storage', () => {
    expect(findExistingImport(makeOpp())).toBeNull();
  });

  it('matches on source_url ignoring other fields', () => {
    const entry = addCustomImport(makeOpp(), token)!;
    const lookup = findExistingImport(
      makeOpp({ title: 'Different Title', organization: 'Different Org' }),
    );
    expect(lookup?.id).toBe(entry.id);
  });
});
