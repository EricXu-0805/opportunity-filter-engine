import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import * as imports from './custom-imports';
import { advanceOwnerEpoch, captureOwnerToken, readUserScopedEntry, syncLocalIdentityOwner, type OwnerToken } from './identity-owner';
import { writeLocalStorageJSON } from './use-local-storage-json';
import { STORAGE_KEYS } from './storage-keys';
import type { ImportedOpportunity } from './api';

const KEY = STORAGE_KEYS.CUSTOM_IMPORTS;
let token: OwnerToken;
let ownerSequence = 0;
function opp(overrides: Partial<ImportedOpportunity> = {}): ImportedOpportunity {
  return { source: 'url_parser', source_url: 'https://example.edu/posting', url: 'https://example.edu/posting',
    title: 'Research opportunity', organization: 'Example', description_raw: 'Old excerpt.',
    extra_fields: { description_source: 'page_excerpt', suggested_skills: ['Python'] }, ...overrides };
}
const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
function storedRaw(): string | null {
  const value = readUserScopedEntry(KEY);
  return value.status === 'present' ? value.value : null;
}
function saveExpected() {
  return copy(imports.addCustomImport(opp(), token)!);
}

beforeEach(async () => {
  advanceOwnerEpoch(`b59-update-${++ownerSequence}`);
  await syncLocalIdentityOwner(`b59-update-${ownerSequence}`);
  token = captureOwnerToken();
});
afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

describe('explicit update of an existing reviewed import', () => {
  it('replaces only the reviewed entry and preserves identity, original time and other entries', () => {
    const expected = saveExpected();
    const other = imports.addCustomImport(opp({ source_url: 'https://example.edu/other', url: 'https://example.edu/other', title: 'Other' }), token)!;
    const next = opp({ description_raw: 'Complete current source. ' + '内容🙂'.repeat(4000), extra_fields: { description_source: 'page_text', ai_input_scope: 'source_excerpt', suggested_skills: ['SQL'], receipt: { source: 'same page' } } });
    const result = imports.updateCustomImport(next, expected, token);
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.entry.id).toBe(expected.id);
    expect(result.entry.imported_at).toBe(expected.imported_at);
    expect(result.entry.updated_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(imports.readCustomImports()).toEqual([other, result.entry]);
    expect(result.entry.opportunity).toEqual(next);
    expect(expected.opportunity.description_raw).toBe('Old excerpt.');
  });

  it('refuses a same-id same-time edit anywhere in the complete expected snapshot', () => {
    const expected = saveExpected();
    const altered = copy(expected);
    altered.opportunity.extra_fields.suggested_skills = ['R'];
    writeLocalStorageJSON(KEY, [altered], token);
    const before = storedRaw();
    expect(imports.updateCustomImport(opp({ description_raw: 'Candidate' }), expected, token)).toEqual({ ok: false, reason: 'changed' });
    expect(storedRaw()).toBe(before);
  });

  it('does not confuse a paste with a URL entry having the same title and organization', () => {
    const expected = saveExpected();
    const paste = opp({ source: 'text_parser', source_url: '', url: '' });
    expect(imports.findExistingImport(paste)).toBeNull();
    expect(imports.updateCustomImport(paste, expected, token)).toEqual({ ok: false, reason: 'identity_mismatch' });
  });
});

function storageFacade(overrides: Partial<Storage>): () => void {
  const original = window.localStorage;
  const facade: Storage = {
    get length() { return original.length; }, key: (i) => original.key(i),
    getItem: (key) => original.getItem(key), setItem: (key, value) => original.setItem(key, value),
    removeItem: (key) => original.removeItem(key), clear: () => original.clear(), ...overrides,
  };
  Object.defineProperty(window, 'localStorage', { value: facade, configurable: true });
  return () => Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
}
const isImportsKey = (key: string) => key === KEY || key.endsWith(`~${KEY}`);

describe('update refuses stale or failed persistence without destroying the draft', () => {
  it.each([
    { source_url: 'https://different.edu/posting' }, { url: 'https://example.edu/other' },
    { source: 'text_parser' }, { source_url: '', url: '' },
  ])('rejects changed source identity %j', (changes) => {
    const expected = saveExpected();
    const before = storedRaw();
    expect(imports.updateCustomImport(opp(changes), expected, token)).toEqual({ ok: false, reason: 'identity_mismatch' });
    expect(storedRaw()).toBe(before);
  });

  it('allows a changed title at the same source but preserves unknown old entry fields', () => {
    const first = saveExpected();
    const expected = { ...first, legacy_note: { text: 'Keep this field' } };
    writeLocalStorageJSON(KEY, [expected], token);
    const result = imports.updateCustomImport(opp({ title: 'Revised source title' }), copy(expected), token);
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.entry).toMatchObject({ legacy_note: expected.legacy_note, id: first.id });
  });

  it('accepts equivalent full snapshots whose object keys were reordered', () => {
    const first = saveExpected();
    const expected = { opportunity: { ...first.opportunity, extra_fields: { suggested_skills: ['Python'], description_source: 'page_excerpt' as const } }, imported_at: first.imported_at, id: first.id };
    expect(imports.updateCustomImport(opp({ description_raw: 'New' }), expected, token).ok).toBe(true);
  });

  it('does not reuse an old review after the first confirmed update', () => {
    const expected = saveExpected();
    expect(imports.updateCustomImport(opp({ description_raw: 'First update' }), expected, token).ok).toBe(true);
    const before = storedRaw();
    expect(imports.updateCustomImport(opp({ description_raw: 'Old retry' }), expected, token)).toEqual({ ok: false, reason: 'changed' });
    expect(storedRaw()).toBe(before);
  });

  it('reports a deleted target as missing', () => {
    const expected = saveExpected();
    imports.removeCustomImport(expected.id, token);
    expect(imports.updateCustomImport(opp(), expected, token)).toEqual({ ok: false, reason: 'missing' });
    expect(storedRaw()).toBeNull();
  });

  it('does not read or disclose another owner’s imports under a stale token', async () => {
    const expected = saveExpected();
    advanceOwnerEpoch('b59-other-owner');
    await syncLocalIdentityOwner('b59-other-owner');
    const other = imports.addCustomImport(opp(), captureOwnerToken());
    const original = window.localStorage;
    let privateReads = 0;
    const restore = storageFacade({ getItem: (key) => { if (isImportsKey(key)) privateReads++; return original.getItem(key); } });
    try {
      expect(imports.updateCustomImport(opp(), expected, token)).toEqual({ ok: false, reason: 'owner_changed' });
      expect(privateReads).toBe(0);
    } finally { restore(); }
    expect(imports.readCustomImports()).toEqual([other]);
  });

  it.each(['throw', 'noop'] as const)('reports %s write failure without altering the stored record', (mode) => {
    const expected = saveExpected();
    const before = storedRaw();
    const original = window.localStorage;
    const restore = storageFacade({ setItem: (key, value) => {
      if (isImportsKey(key)) { if (mode === 'throw') throw new Error('QuotaExceededError'); return; }
      original.setItem(key, value);
    } });
    try { expect(imports.updateCustomImport(opp({ description_raw: 'Candidate' }), expected, token)).toEqual({ ok: false, reason: 'storage_failed' }); }
    finally { restore(); }
    expect(storedRaw()).toBe(before);
  });

  it('reports a read failure rather than treating it as a missing entry', () => {
    const expected = saveExpected();
    const original = window.localStorage;
    const restore = storageFacade({ getItem: (key) => { if (isImportsKey(key)) throw new Error('Storage denied'); return original.getItem(key); } });
    try { expect(imports.updateCustomImport(opp(), expected, token)).toEqual({ ok: false, reason: 'storage_failed' }); }
    finally { restore(); }
  });

  it('keeps an unrelated item inserted between the first and final authoritative read', () => {
    const expected = saveExpected();
    const other = { ...copy(expected), id: 'other-between-reads', opportunity: opp({ title: 'Other', source_url: 'https://example.edu/other', url: 'https://example.edu/other' }) };
    const original = window.localStorage;
    let reads = 0;
    const restore = storageFacade({ getItem: (key) => {
      if (isImportsKey(key) && ++reads === 2) original.setItem(key, JSON.stringify([other, expected]));
      return original.getItem(key);
    } });
    try { expect(imports.updateCustomImport(opp({ description_raw: 'Updated' }), expected, token).ok).toBe(true); }
    finally { restore(); }
    expect(imports.readCustomImports()[0]).toEqual(other);
    expect(imports.readCustomImports()[1].opportunity.description_raw).toBe('Updated');
  });

  it.each(['change', 'delete'] as const)('rechecks a target %s immediately before write', (mode) => {
    const expected = saveExpected();
    const otherValue = mode === 'delete' ? [] : [{ ...copy(expected), opportunity: opp({ description_raw: 'Another edit' }) }];
    const original = window.localStorage;
    let reads = 0;
    const restore = storageFacade({ getItem: (key) => {
      if (isImportsKey(key) && ++reads === 2) original.setItem(key, JSON.stringify(otherValue));
      return original.getItem(key);
    } });
    try { expect(imports.updateCustomImport(opp({ description_raw: 'Candidate' }), expected, token)).toEqual({ ok: false, reason: mode === 'delete' ? 'missing' : 'changed' }); }
    finally { restore(); }
    expect(imports.readCustomImports()).toEqual(otherValue);
  });

  it('a circular candidate fails without storage mutation', () => {
    const expected = saveExpected();
    const candidate = opp(); candidate.extra_fields.self = candidate;
    const before = storedRaw();
    expect(imports.updateCustomImport(candidate, expected, token)).toEqual({ ok: false, reason: 'storage_failed' });
    expect(storedRaw()).toBe(before);
  });

  it('same-title entries with different URLs remain distinct', () => {
    const expected = saveExpected();
    const different = opp({ source_url: 'https://example.edu/other', url: 'https://example.edu/other' });
    expect(imports.findExistingImport(different)).toBeNull();
    expect(imports.updateCustomImport(different, expected, token)).toEqual({ ok: false, reason: 'identity_mismatch' });
  });
});

describe('damaged data is display-safe and cannot be mistaken for an empty writable store', () => {
  it.each([{}, 'wrong shape', [null], [{ id: 'bad', imported_at: 'old', opportunity: { title: 5 } }]])('does not overwrite invalid stored shape %j', (bad) => {
    const expected = saveExpected();
    writeLocalStorageJSON(KEY, bad, token);
    const before = storedRaw();
    expect(imports.readCustomImports()).toEqual([]);
    expect(imports.findExistingImport(opp())).toBeNull();
    expect(imports.addCustomImport(opp({ source_url: 'https://example.edu/new' }), token)).toBeNull();
    expect(imports.removeCustomImport(expected.id, token)).toBe(false);
    expect(imports.updateCustomImport(opp(), expected, token)).toEqual({ ok: false, reason: 'storage_failed' });
    expect(storedRaw()).toBe(before);
  });

  it('shows valid old entries but blocks a write when a neighboring entry is damaged', () => {
    const expected = saveExpected();
    writeLocalStorageJSON(KEY, [expected, null], token);
    const before = storedRaw();
    expect(imports.readCustomImports()).toEqual([expected]);
    expect(imports.updateCustomImport(opp(), expected, token)).toEqual({ ok: false, reason: 'storage_failed' });
    expect(storedRaw()).toBe(before);
  });
});


describe('post-write confirmation and old browser records', () => {
  it.each(['replace', 'delete'] as const)('does not claim success after a storage listener %s', (mode) => {
    const expected = saveExpected();
    const other = { ...copy(expected), opportunity: opp({ description_raw: 'Newer listener update' }) };
    // Write into the existing owner namespace, without creating recursive events.
    const original = window.localStorage;
    const physical = Array.from({ length: original.length }, (_, i) => original.key(i)!).find(isImportsKey)!;
    const listener = (event: StorageEvent) => {
      if (event.key === KEY) original.setItem(physical, JSON.stringify(mode === 'delete' ? [] : [other]));
    };
    window.addEventListener('storage', listener);
    try {
      expect(imports.updateCustomImport(opp({ description_raw: 'Candidate' }), expected, token))
        .toEqual({ ok: false, reason: mode === 'delete' ? 'missing' : 'changed' });
    } finally { window.removeEventListener('storage', listener); }
    expect(imports.readCustomImports()).toEqual(mode === 'delete' ? [] : [other]);
  });

  it('does not discard legacy optional omissions during read or update', () => {
    const first = saveExpected();
    const legacy = copy(first);
    delete legacy.opportunity.organization;
    delete (legacy.opportunity as Partial<ImportedOpportunity>).extra_fields;
    writeLocalStorageJSON(KEY, [legacy], token);
    expect(imports.readCustomImports()).toEqual([legacy]);
    expect(imports.updateCustomImport(opp({ organization: undefined }), copy(legacy), token).ok).toBe(true);
  });

  it('accepts an explicitly reviewed paste only at the same title and organization', () => {
    const paste = opp({ source: 'text_parser', source_url: '', url: '' });
    const expected = copy(imports.addCustomImport(paste, token)!);
    expect(imports.updateCustomImport({ ...paste, description_raw: 'Full pasted text' }, expected, token).ok).toBe(true);
    const latest = copy(imports.readCustomImports()[0]);
    expect(imports.updateCustomImport({ ...paste, title: 'A different posting' }, latest, token))
      .toEqual({ ok: false, reason: 'identity_mismatch' });
  });

  it('provides a stable safe hook view without rewriting malformed bytes', () => {
    const expected = saveExpected();
    const original = window.localStorage;
    const physical = Array.from({ length: original.length }, (_, i) => original.key(i)!).find(isImportsKey)!;
    original.setItem(physical, '{broken JSON');
    const { result, rerender, unmount } = renderHook(() => imports.useCustomImports());
    expect(result.current).toEqual([]);
    const firstView = result.current;
    rerender(); expect(result.current).toBe(firstView);
    expect(imports.addCustomImport(opp(), token)).toBeNull();
    expect(imports.updateCustomImport(opp(), expected, token)).toEqual({ ok: false, reason: 'storage_failed' });
    expect(original.getItem(physical)).toBe('{broken JSON');
    unmount();
  });
});


describe('legacy URL aliases retain the same source identity', () => {
  it.each(['source_url', 'url'] as const)('accepts a legacy entry missing the redundant %s alias', (key) => {
    const expected = saveExpected();
    delete (expected.opportunity as Partial<ImportedOpportunity>)[key];
    writeLocalStorageJSON(KEY, [expected], token);
    const result = imports.updateCustomImport(opp({ description_raw: 'Complete new source.' }), expected, token);
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.entry.id).toBe(expected.id);
    expect(result.entry.imported_at).toBe(expected.imported_at);
    expect(result.entry.opportunity.description_raw).toBe('Complete new source.');
  });

  it('allows a URL-less legacy paste but never upgrades its identity to a URL source', () => {
    const saved = imports.addCustomImport(opp({ source: 'text_parser', source_url: '', url: '' }), token)!;
    const expected = copy(saved);
    delete (expected.opportunity as Partial<ImportedOpportunity>).source_url;
    delete (expected.opportunity as Partial<ImportedOpportunity>).url;
    writeLocalStorageJSON(KEY, [expected], token);
    expect(imports.updateCustomImport(opp({ source: 'text_parser' }), expected, token)).toEqual({ ok: false, reason: 'identity_mismatch' });
    const result = imports.updateCustomImport(opp({ source: 'text_parser', source_url: '', url: '', description_raw: 'New paste source.' }), expected, token);
    expect(result.ok).toBe(true);
  });
});
