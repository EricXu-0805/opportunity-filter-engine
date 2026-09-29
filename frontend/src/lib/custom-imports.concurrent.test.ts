import { afterEach, describe, expect, it, vi } from 'vitest';
import { STORAGE_KEYS } from './storage-keys';
import type { ImportedOpportunity } from './api';

const KEY = STORAGE_KEYS.CUSTOM_IMPORTS;
function opportunity(title = 'A'): ImportedOpportunity {
  return { source: 'url_parser', source_url: `https://example.edu/${title}`, url: `https://example.edu/${title}`,
    title, description_raw: `Complete ${title}`, extra_fields: {} };
}
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}
async function realm(uid = 'b60-owner') {
  vi.resetModules();
  const owner = await import('./identity-owner');
  const imports = await import('./custom-imports');
  owner.advanceOwnerEpoch(uid);
  await owner.syncLocalIdentityOwner(uid);
  return { owner, imports, token: owner.captureOwnerToken() };
}
function raw(current: Awaited<ReturnType<typeof realm>>) {
  const value = current.owner.readUserScopedEntry(KEY);
  return value.status === 'present' ? value.value : null;
}
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe('coordinated custom import writes across independent module realms', () => {
  it('does not write while the shared owner-transition lock is held, then preserves both additions', async () => {
    const first = await realm();
    const second = await realm();
    const gate = deferred();
    const held = navigator.locks.request(first.owner.PRIVATE_STORAGE_LOCK, { mode: 'exclusive' }, () => gate.promise);
    const a = first.imports.addCustomImport(opportunity('A'), first.token);
    const b = second.imports.addCustomImport(opportunity('B'), second.token);
    const beforeRelease = raw(first);
    gate.resolve();
    await held;
    const results = await Promise.all([a, b]);
    expect(beforeRelease).toBeNull();
    expect(results.every((result) => result.ok)).toBe(true);
    expect(first.imports.readCustomImports().map((entry) => entry.opportunity.title).sort()).toEqual(['A', 'B']);
  });

  it('reports damaged storage without treating it as an empty store', async () => {
    const current = await realm();
    current.owner.writeUserScopedRaw(KEY, '{broken PRIVATE SOURCE', current.token);
    expect(current.imports.readCustomImportStorageState(current.token)).toEqual({ status: 'damaged', entries: [] });
    expect(await current.imports.addCustomImport(opportunity(), current.token)).toEqual({ ok: false, reason: 'storage_damaged' });
    expect(raw(current)).toBe('{broken PRIVATE SOURCE');
  });
});

async function seed(current: Awaited<ReturnType<typeof realm>>, title = 'A') {
  const result = await current.imports.addCustomImport(opportunity(title), current.token);
  if (!result.ok) throw new Error(result.reason);
  return result.entry;
}
async function hold(current: Awaited<ReturnType<typeof realm>>) {
  const gate = deferred();
  const entered = deferred();
  const promise = navigator.locks.request(current.owner.PRIVATE_STORAGE_LOCK, { mode: 'exclusive' }, () => {
    entered.resolve();
    return gate.promise;
  });
  await entered.promise;
  return { release: gate.resolve, promise };
}

describe('serialized conflicts, frozen intent and identity transitions', () => {
  it('deduplicates concurrent same-source adds after acquiring the lock', async () => {
    const a = await realm(); const b = await realm(); const barrier = await hold(a);
    const writes = [a.imports.addCustomImport(opportunity(), a.token), b.imports.addCustomImport(opportunity(), b.token)];
    expect(raw(a)).toBeNull(); barrier.release(); await barrier.promise;
    const results = await Promise.all(writes);
    expect(results[0]).toEqual(results[1]);
    expect(results.every(result => result.ok)).toBe(true);
    expect(a.imports.readCustomImports()).toHaveLength(1);
  });

  it('only the first of two reviews of the same complete entry can update it', async () => {
    const a = await realm(); const expected = await seed(a); const b = await realm(); const barrier = await hold(a);
    const first = a.imports.updateCustomImport({ ...opportunity(), description_raw: 'First review' }, expected, a.token);
    const second = b.imports.updateCustomImport({ ...opportunity(), description_raw: 'Second review' }, expected, b.token);
    barrier.release(); await barrier.promise;
    expect((await first).ok).toBe(true);
    expect(await second).toEqual({ ok: false, reason: 'changed' });
    expect(a.imports.readCustomImports()[0].opportunity.description_raw).toBe('First review');
  });

  it('preserves two independently updated entries without lost surrounding state', async () => {
    const a = await realm(); const oldA = await seed(a); const oldB = await seed(a, 'B'); const b = await realm();
    const barrier = await hold(a);
    const writes = [a.imports.updateCustomImport({ ...opportunity(), description_raw: 'A revised' }, oldA, a.token),
      b.imports.updateCustomImport({ ...opportunity('B'), description_raw: 'B revised' }, oldB, b.token)];
    barrier.release(); await barrier.promise;
    expect((await Promise.all(writes)).every(result => result.ok)).toBe(true);
    expect(a.imports.readCustomImports().map(entry => entry.opportunity.description_raw).sort()).toEqual(['A revised', 'B revised']);
  });

  it('never resurrects a deleted review target and preserves a concurrent new entry', async () => {
    const a = await realm(); const expected = await seed(a); const b = await realm(); const barrier = await hold(a);
    const deletion = b.imports.removeCustomImport(expected.id, b.token);
    const update = a.imports.updateCustomImport({ ...opportunity(), description_raw: 'Stale review' }, expected, a.token);
    const addition = b.imports.addCustomImport(opportunity('B'), b.token);
    barrier.release(); await barrier.promise;
    expect(await deletion).toEqual({ ok: true });
    expect(await update).toEqual({ ok: false, reason: 'missing' });
    expect((await addition).ok).toBe(true);
    expect(a.imports.readCustomImports().map(entry => entry.opportunity.title)).toEqual(['B']);
  });

  it('freezes candidate, complete expected entry and owner token before any waiting', async () => {
    const a = await realm(); const expected = await seed(a); const candidate = { ...opportunity(), description_raw: 'Reviewed text' };
    const passedToken = { ...a.token }; const barrier = await hold(a);
    const update = a.imports.updateCustomImport(candidate, expected, passedToken);
    candidate.description_raw = 'Unreviewed mutation'; expected.opportunity.title = 'Changed expected'; passedToken.uid = 'other';
    barrier.release(); await barrier.promise;
    expect((await update).ok).toBe(true);
    expect(a.imports.readCustomImports()[0].opportunity.description_raw).toBe('Reviewed text');
  });

  it('shares the transition lock, refusing an old queued intent after another realm switches owner', async () => {
    const a = await realm(); const b = await realm(); const barrier = await hold(a);
    b.owner.advanceOwnerEpoch('new-owner');
    const transition = b.owner.syncLocalIdentityOwner('new-owner');
    const write = a.imports.addCustomImport(opportunity('Old-owner private source'), a.token);
    barrier.release(); await barrier.promise;
    expect(await transition).toBe(true);
    expect(await write).toEqual({ ok: false, reason: 'owner_changed' });
    expect(b.imports.readCustomImports()).toEqual([]);
  });

  it('does not accept a same-uid old generation after another realm switches away and back', async () => {
    const a = await realm(); const b = await realm();
    b.owner.advanceOwnerEpoch('other'); await b.owner.syncLocalIdentityOwner('other');
    b.owner.advanceOwnerEpoch('b60-owner'); await b.owner.syncLocalIdentityOwner('b60-owner');
    const current = await seed({ ...b, token: b.owner.captureOwnerToken() }, 'Current');
    expect(await a.imports.addCustomImport(opportunity('Stale'), a.token)).toEqual({ ok: false, reason: 'owner_changed' });
    expect(b.imports.readCustomImports()).toEqual([current]);
  });
});

describe('coordination failures are explicit and never lead to a late write', () => {
  it('refuses writing and recovery when the browser has no Web Locks', async () => {
    const a = await realm(); const original = navigator.locks;
    Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined });
    try {
      expect(await a.imports.addCustomImport(opportunity(), a.token)).toEqual({ ok: false, reason: 'coordination_unavailable' });
      expect(a.imports.captureCustomImportRecovery(a.token)).toEqual({ ok: false, reason: 'coordination_unavailable' });
      expect(a.imports.readCustomImportStorageState(a.token)).toEqual({ status: 'unavailable', entries: [], reason: 'coordination_unavailable' });
    } finally { Object.defineProperty(navigator, 'locks', { configurable: true, value: original }); }
    expect(raw(a)).toBeNull();
  });

  it('reports a rejected lock request without touching the list', async () => {
    const a = await realm(); const request = vi.spyOn(navigator.locks, 'request').mockRejectedValue(new DOMException('denied', 'SecurityError'));
    expect(await a.imports.addCustomImport(opportunity(), a.token)).toEqual({ ok: false, reason: 'storage_failed' });
    request.mockRestore(); expect(raw(a)).toBeNull();
  });

  it('times out pending acquisition and cannot write after the holder finally releases', async () => {
    const a = await realm(); const barrier = await hold(a); vi.useFakeTimers();
    const write = a.imports.addCustomImport(opportunity(), a.token);
    await vi.advanceTimersByTimeAsync(a.imports.CUSTOM_IMPORT_LOCK_TIMEOUT_MS + 1);
    expect(await write).toEqual({ ok: false, reason: 'lock_timeout' });
    expect(raw(a)).toBeNull();
    // The global test lock deliberately does not implement AbortSignal. The
    // production callback must still refuse when eventually scheduled.
    barrier.release(); await barrier.promise; await Promise.resolve(); await Promise.resolve();
    expect(raw(a)).toBeNull();
  });

  it('does not time out an already acquired synchronous transaction', async () => {
    const a = await realm(); vi.useFakeTimers();
    const listener = (event: StorageEvent) => { if (event.key === KEY) vi.advanceTimersByTime(a.imports.CUSTOM_IMPORT_LOCK_TIMEOUT_MS + 1); };
    window.addEventListener('storage', listener);
    try { expect((await a.imports.addCustomImport(opportunity(), a.token)).ok).toBe(true); }
    finally { window.removeEventListener('storage', listener); }
    expect(a.imports.readCustomImports()).toHaveLength(1);
  });
});

describe('explicit damaged-data recovery uses the same owner and exact original bytes', () => {
  it('captures exact raw data, resets only after explicit invocation and permits a new save afterwards', async () => {
    const a = await realm(); const source = '{broken source 中文🙂 <tag>';
    a.owner.writeUserScopedRaw(KEY, source, a.token);
    const captured = a.imports.captureCustomImportRecovery(a.token);
    expect(captured).toEqual({ ok: true, raw: source }); expect(raw(a)).toBe(source);
    expect(await a.imports.resetCustomImports(source, a.token)).toEqual({ ok: true });
    expect(a.imports.readCustomImportStorageState(a.token)).toEqual({ status: 'ready', entries: [] });
    expect((await a.imports.addCustomImport(opportunity(), a.token)).ok).toBe(true);
  });

  it.each(['another-damaged', 'healthy', 'deleted'] as const)('refuses reset when the reviewed bytes become %s while waiting', async (mode) => {
    const a = await realm(); const b = await realm(); const source = '{broken source';
    a.owner.writeUserScopedRaw(KEY, source, a.token); const barrier = await hold(a);
    const reset = a.imports.resetCustomImports(source, a.token);
    const next = mode === 'another-damaged' ? '{changed broken' : '[]';
    if (mode === 'deleted') b.owner.removeUserScopedRaw(KEY, b.token);
    else b.owner.writeUserScopedRaw(KEY, next, b.token);
    barrier.release(); await barrier.promise;
    expect(await reset).toEqual({ ok: false, reason: 'changed' });
    expect(raw(a)).toBe(mode === 'deleted' ? null : next);
  });

  it('allows only one of two queued resets, then preserves a queued addition', async () => {
    const a = await realm(); const b = await realm(); const source = '{damaged';
    a.owner.writeUserScopedRaw(KEY, source, a.token); const barrier = await hold(a);
    const one = a.imports.resetCustomImports(source, a.token);
    const two = b.imports.resetCustomImports(source, b.token);
    const add = b.imports.addCustomImport(opportunity(), b.token);
    barrier.release(); await barrier.promise;
    expect(await one).toEqual({ ok: true }); expect(await two).toEqual({ ok: false, reason: 'changed' });
    expect((await add).ok).toBe(true); expect(a.imports.readCustomImports()).toHaveLength(1);
  });

  it('refuses a stale owner export/reset and never exposes a new owner’s raw data', async () => {
    const a = await realm(); a.owner.writeUserScopedRaw(KEY, '{old', a.token);
    const b = await realm('new-owner'); b.owner.writeUserScopedRaw(KEY, '{new private', b.token);
    expect(a.imports.captureCustomImportRecovery(a.token)).toEqual({ ok: false, reason: 'owner_changed' });
    expect(await a.imports.resetCustomImports('{old', a.token)).toEqual({ ok: false, reason: 'owner_changed' });
    expect(raw(b)).toBe('{new private');
  });

  it('never returns damaged status or permits reset for an unreadable store', async () => {
    const a = await realm(); const original = localStorage.getItem.bind(localStorage);
    const read = vi.spyOn(localStorage, 'getItem').mockImplementation(key => {
      if (key === KEY || key.endsWith(`~${KEY}`)) throw new Error('denied');
      return original(key);
    });
    expect(a.imports.readCustomImportStorageState(a.token)).toEqual({ status: 'unavailable', entries: [], reason: 'storage_failed' });
    expect(a.imports.captureCustomImportRecovery(a.token)).toEqual({ ok: false, reason: 'storage_failed' });
    expect(await a.imports.resetCustomImports('anything', a.token)).toEqual({ ok: false, reason: 'storage_failed' }); read.mockRestore();
  });

  it('shows valid neighboring entries but blocks all writes when one is damaged', async () => {
    const a = await realm(); const saved = await seed(a); a.owner.writeUserScopedRaw(KEY, JSON.stringify([saved, null]), a.token);
    expect(a.imports.readCustomImportStorageState(a.token)).toEqual({ status: 'damaged', entries: [saved] });
    expect(await a.imports.removeCustomImport(saved.id, a.token)).toEqual({ ok: false, reason: 'storage_damaged' });
    expect(await a.imports.updateCustomImport(opportunity(), saved, a.token)).toEqual({ ok: false, reason: 'storage_damaged' });
  });

  it('treats duplicate IDs as damaged and never offers recovery for a healthy list', async () => {
    const a = await realm(); const saved = await seed(a);
    expect(a.imports.captureCustomImportRecovery(a.token)).toEqual({ ok: false, reason: 'changed' });
    expect(await a.imports.resetCustomImports(raw(a)!, a.token)).toEqual({ ok: false, reason: 'changed' });
    a.owner.writeUserScopedRaw(KEY, JSON.stringify([saved, saved]), a.token);
    expect(a.imports.readCustomImportStorageState(a.token).status).toBe('damaged');
  });

  it('verifies reset contents after storage notification and never rolls back newer data', async () => {
    const a = await realm(); a.owner.writeUserScopedRaw(KEY, '{old', a.token);
    const listener = (event: StorageEvent) => { if (event.key === KEY) a.owner.writeUserScopedRaw(KEY, '{newer', a.token); };
    window.addEventListener('storage', listener);
    try { expect(await a.imports.resetCustomImports('{old', a.token)).toEqual({ ok: false, reason: 'changed' }); }
    finally { window.removeEventListener('storage', listener); }
    expect(raw(a)).toBe('{newer');
  });
});
