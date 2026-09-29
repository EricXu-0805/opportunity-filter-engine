import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { addCustomImport, findExistingImport, readCustomImports, removeCustomImport, } from './custom-imports';
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
    it('appends a new entry with a generated id and timestamp', async () => {
        // Unwrap only confirmed success; rejected writes are checked separately.
        const entry = successfulImport(await addCustomImport(makeOpp(), token));
        expect(entry.id).toMatch(/^custom-\d+-[a-z0-9]+$/);
        expect(entry.imported_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
        expect(readCustomImports()).toHaveLength(1);
        expect(readCustomImports()[0].opportunity.title).toBe('Sample Internship');
    });
    it('returns the existing entry when source_url matches (no duplicate write)', async () => {
        const first = successfulImport(await addCustomImport(makeOpp(), token));
        const second = successfulImport(await addCustomImport(makeOpp({ description_raw: 'different desc' }), token));
        expect(second.id).toBe(first.id);
        expect(readCustomImports()).toHaveLength(1);
        expect(readCustomImports()[0].opportunity.description_raw).toBe('desc');
    });
    it('prepends new entries so most recent is first', async () => {
        await addCustomImport(makeOpp({ source_url: 'https://example.com/a', title: 'A' }), token);
        await addCustomImport(makeOpp({ source_url: 'https://example.com/b', title: 'B' }), token);
        const list = readCustomImports();
        expect(list.map((e) => e.opportunity.title)).toEqual(['B', 'A']);
    });
    it('deduplicates by title + organization when no source_url present', async () => {
        const oppA = makeOpp({ source_url: '', url: '', title: 'Pasted Posting', organization: 'BigCo' });
        const oppB = makeOpp({ source_url: '', url: '', title: 'Pasted Posting', organization: 'BigCo', description_raw: 'updated' });
        const first = successfulImport(await addCustomImport(oppA, token));
        const second = successfulImport(await addCustomImport(oppB, token));
        expect(second.id).toBe(first.id);
        expect(readCustomImports()).toHaveLength(1);
    });
    it('does NOT deduplicate empty-URL entries with different title/org', async () => {
        await addCustomImport(makeOpp({ source_url: '', url: '', title: 'A', organization: 'X' }), token);
        await addCustomImport(makeOpp({ source_url: '', url: '', title: 'B', organization: 'X' }), token);
        expect(readCustomImports()).toHaveLength(2);
    });
    it('a STALE token (captured under a different owner) is explicitly rejected — the import is never written', async () => {
        const staleToken = token;
        advanceOwnerEpoch('custom-imports-other-uid');
        await syncLocalIdentityOwner('custom-imports-other-uid');
        const entry = await addCustomImport(makeOpp(), staleToken);
        // Rejected before any read/write — nothing was persisted, and nothing
        // (not even a synthesized entry) is handed back to the stale caller.
        expect(entry).toEqual({ ok: false, reason: 'owner_changed' });
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
        const currentEntry = await addCustomImport(shared, currentToken);
        // A fix that only gates the final WRITE (but still performs the read +
        // dedup check) would find the current owner's entry as a "duplicate"
        // and return it — leaking their real entry id/timestamp to a caller
        // acting on a since-replaced identity.
        const result = await addCustomImport(shared, staleToken);
        expect(result).toEqual({ ok: false, reason: 'owner_changed' });
        expect(readCustomImports()).toEqual([successfulImport(currentEntry)]);
    });
    it('a VALID token whose write still fails (quota exceeded) returns storage_failed without a saved entry', async () => {
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
            const result = await addCustomImport(makeOpp(), token);
            expect(result).toEqual({ ok: false, reason: 'storage_failed' });
            expect(store.has('ofe_custom_imports')).toBe(false);
        }
        finally {
            Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
        }
    });
});
describe('removeCustomImport', () => {
    it('removes the entry with the matching id', async () => {
        const a = successfulImport(await addCustomImport(makeOpp({ source_url: 'https://a.example/x', title: 'A' }), token));
        await addCustomImport(makeOpp({ source_url: 'https://b.example/x', title: 'B' }), token);
        await removeCustomImport(a.id, token);
        const list = readCustomImports();
        expect(list).toHaveLength(1);
        expect(list[0].opportunity.title).toBe('B');
    });
    it('removes the storage key entirely when last entry is removed', async () => {
        const a = successfulImport(await addCustomImport(makeOpp(), token));
        await removeCustomImport(a.id, token);
        expect(localStorage.getItem('ofe_custom_imports')).toBeNull();
    });
    it('is a no-op for unknown id, but still reports the token as current', async () => {
        successfulImport(await addCustomImport(makeOpp(), token));
        expect(await removeCustomImport('custom-doesnotexist', token)).toEqual({ ok: true });
        expect(readCustomImports()).toHaveLength(1);
    });
    it('a STALE token cannot remove the CURRENT owner\'s own entry — reports owner_changed without touching the current list', async () => {
        const a = successfulImport(await addCustomImport(makeOpp(), token));
        const staleToken = token;
        advanceOwnerEpoch('custom-imports-remove-other-uid');
        await syncLocalIdentityOwner('custom-imports-remove-other-uid');
        // The current owner writes their own entry under the same list shape.
        await addCustomImport(makeOpp({ source_url: 'https://current.example/x', title: 'Current' }), captureOwnerToken());
        expect(await removeCustomImport(a.id, staleToken)).toEqual({ ok: false, reason: 'owner_changed' }); // stale — must not touch the CURRENT owner's list
        expect(readCustomImports().map((e) => e.opportunity.title)).toEqual(['Current']);
    });
    it('a VALID token whose write still fails (quota/private-mode) returns storage_failed and preserves the old list', async () => {
        // Two entries so the removal still needs a setItem (writing the
        // filtered list), not a bare removeItem (removing the last one) —
        // that's the path where a throwing setItem is actually exercised.
        const a = successfulImport(await addCustomImport(makeOpp({ source_url: 'https://a.example/x', title: 'A' }), token));
        await addCustomImport(makeOpp({ source_url: 'https://b.example/x', title: 'Keeper' }), token);
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
            expect(await removeCustomImport(a.id, token)).toEqual({ ok: false, reason: 'storage_failed' });
            expect(readCustomImports()).toHaveLength(2);
            expect(readCustomImports().map((e) => e.opportunity.title)).toEqual(['Keeper', 'A']);
        }
        finally {
            Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
        }
    });
});
describe('findExistingImport', () => {
    it('returns null for empty storage', () => {
        expect(findExistingImport(makeOpp())).toBeNull();
    });
    it('matches on source_url ignoring other fields', async () => {
        const entry = successfulImport(await addCustomImport(makeOpp(), token));
        const lookup = findExistingImport(makeOpp({ title: 'Different Title', organization: 'Different Org' }));
        expect(lookup?.id).toBe(entry.id);
    });
});

function successfulImport(result: import("./custom-imports").CustomImportUpdateResult) {
  if (!result.ok) throw new Error(result.reason);
  return result.entry;
}
