import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AuthState } from './supabase';
import type { PrivateImportTarget, PrivateImportSummary, PrivateImportPage, PrivateImportReceipt } from './private-import-target-api';
const api = vi.hoisted(() => ({ auth: vi.fn(), authChange: vi.fn(), list: vi.fn(), get: vi.fn(), remove: vi.fn() }));
vi.mock('./supabase', () => ({ getAuthState: api.auth, onAuthChange: api.authChange }));
vi.mock('./private-import-target-api', () => ({ listPrivateImportTargets: api.list, getPrivateImportTarget: api.get, deletePrivateImportTarget: api.remove, PRIVATE_TARGET_TIMEOUT_MS: 30000,
  PrivateTargetError: class extends Error { constructor(readonly code: string) { super(code); } } }));
import { usePrivateImportList } from './use-private-import-list';
import { PrivateTargetError } from './private-import-target-api';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from './identity-owner';
const OWNER = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'; const OTHER = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
let authEvent: (state: AuthState) => void;
function auth(uid = OWNER): AuthState { return { user: { id: uid }, session: { access_token: 'test-only', user: { id: uid } }, isAnonymous: false, email: null } as AuthState; }
function target(id = 'one', revision = 1, owner = OWNER): PrivateImportTarget {
  return { id, revision, owner_id: owner, created_at: '2026-09-28T12:00:00Z', updated_at: '2026-09-28T12:00:00Z', deleted_at: null,
    target_scope: 'private_import', verification: 'unverified', target_version: `pit1:${revision}`, import_source: null,
    opportunity: { source: 'text_parser', source_url: '', url: '', title: id, description_raw: 'Complete source END', extra_fields: {} } };
}
function summary(id = 'one', owner = OWNER): PrivateImportSummary {
  const { opportunity: _opportunity, import_source: _source, ...base } = target(id, 1, owner);
  return { ...base, deleted_at: null, title: id, organization: null, source_url: '', url: '', source: 'text_parser' };
}
function page(ids = ['one'], more = false, owner = OWNER): PrivateImportPage {
  const items = ids.map(id => summary(id, owner)); return { version: 1, items, next_cursor: more ? { id: ids.at(-1)!, updated_at: items.at(-1)!.updated_at } : null };
}
function receipt(id = 'one', revision = 1): PrivateImportReceipt { return { version: 1, target: target(id, revision), replayed: false }; }
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: unknown) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
beforeEach(async () => {
  localStorage.clear(); advanceOwnerEpoch(OWNER); await syncLocalIdentityOwner(OWNER);
  api.auth.mockReset().mockResolvedValue(auth()); api.authChange.mockReset().mockImplementation(callback => { authEvent = callback; return vi.fn(); });
  api.list.mockReset().mockResolvedValue(page()); api.get.mockReset().mockResolvedValue(receipt()); api.remove.mockReset().mockResolvedValue({});
});

afterEach(() => { vi.useRealTimers(); });

describe('account import list lifecycle', () => {
  it('loads summaries only and never opens details or uploads records automatically', async () => {
    const { result } = renderHook(usePrivateImportList);
    expect(result.current.state.status).toBe('loading');
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
    expect(result.current.state.items[0].id).toBe('one');
    expect(api.get).not.toHaveBeenCalled(); expect(api.remove).not.toHaveBeenCalled();
    expect(api.list.mock.calls[0][0].owner.uid).toBe(OWNER);
  });
  it('keeps signed-out/anonymous separate from a successful empty list', async () => {
    api.auth.mockResolvedValue({ ...auth(), isAnonymous: true });
    const { result } = renderHook(usePrivateImportList);
    await waitFor(() => expect(result.current.state.status).toBe('sign_in_required'));
    expect(api.list).not.toHaveBeenCalled();
  });
  it('shows initial failure as unavailable and permits a fresh read', async () => {
    api.list.mockRejectedValueOnce(new PrivateTargetError('unavailable')).mockResolvedValueOnce(page([]));
    const { result } = renderHook(usePrivateImportList);
    await waitFor(() => expect(result.current.state.status).toBe('error'));
    expect(result.current.state.code).toBe('unavailable');
    await act(async () => { await result.current.refresh(); });
    expect(result.current.state.status).toBe('ready'); expect(result.current.state.items).toEqual([]);
  });
  it('keeps the first page on a later-page error, retries the same cursor and appends once', async () => {
    api.list.mockResolvedValueOnce(page(['one'], true)).mockRejectedValueOnce(new PrivateTargetError('timeout')).mockResolvedValueOnce(page(['two']));
    const { result } = renderHook(usePrivateImportList);
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
    const cursor = result.current.state.cursor;
    await act(async () => { await result.current.loadMore(); });
    expect(result.current.state.status).toBe('ready'); expect(result.current.state.more).toBe('error');
    expect(result.current.state.items.map(i => i.id)).toEqual(['one']); expect(result.current.state.cursor).toEqual(cursor);
    await act(async () => { await result.current.loadMore(); });
    expect(result.current.state.items.map(i => i.id)).toEqual(['one', 'two']); expect(result.current.state.cursor).toBeNull();
    expect(api.list.mock.calls[2][0].cursor).toEqual(cursor);
  });
  it('does not duplicate records when a later page repeats an earlier id', async () => {
    api.list.mockResolvedValueOnce(page(['one'], true)).mockResolvedValueOnce(page(['one']));
    const { result } = renderHook(usePrivateImportList); await waitFor(() => expect(result.current.state.status).toBe('ready'));
    await act(async () => { await result.current.loadMore(); });
    expect(result.current.state.more).toBe('error'); expect(result.current.state.code).toBe('invalid_receipt');
    expect(result.current.state.items).toHaveLength(1);
  });
  it('aborts old-owner reads and never shows their late records under the new owner', async () => {
    const first = deferred<PrivateImportPage>(); api.list.mockReturnValueOnce(first.promise).mockResolvedValueOnce(page(['new-account'], false, OTHER));
    const { result } = renderHook(usePrivateImportList); await waitFor(() => expect(api.list).toHaveBeenCalledTimes(1));
    const signal = api.list.mock.calls[0][0].signal as AbortSignal;
    api.auth.mockResolvedValue(auth(OTHER));
    await act(async () => { advanceOwnerEpoch(OTHER); await syncLocalIdentityOwner(OTHER); });
    expect(signal.aborted).toBe(true);
    await waitFor(() => expect(result.current.state.items[0]?.id).toBe('new-account'));
    await act(async () => { first.resolve(page(['old-secret'])); });
    expect(result.current.state.items.map(i => i.id)).toEqual(['new-account']);
  });
  it('drops old details immediately on a signed-out auth event even before owner confirmation moves', async () => {
    const { result } = renderHook(usePrivateImportList); await waitFor(() => expect(result.current.state.status).toBe('ready'));
    await act(async () => { await result.current.open('one'); });
    expect(result.current.state.detail.status).toBe('ready');
    act(() => authEvent({ session: null, user: null, isAnonymous: false, email: null }));
    expect(result.current.state.items).toEqual([]); expect(result.current.state.detail.status).toBe('closed');
    await waitFor(() => expect(result.current.state.status).toBe('sign_in_required'));
  });
  it('retires an earlier detail stream when another record opens', async () => {
    const first = deferred<PrivateImportReceipt>(); api.get.mockReturnValueOnce(first.promise).mockResolvedValueOnce(receipt('two'));
    const { result } = renderHook(usePrivateImportList); await waitFor(() => expect(result.current.state.status).toBe('ready'));
    let pending!: Promise<void>; act(() => { pending = result.current.open('one'); });
    const signal = api.get.mock.calls[0][1].signal as AbortSignal;
    await act(async () => { await result.current.open('two'); });
    expect(signal.aborted).toBe(true);
    await act(async () => { first.resolve(receipt('one')); await pending; });
    const detail = result.current.state.detail; expect(detail.status).toBe('ready');
    if (detail.status === 'ready') expect(detail.target.id).toBe('two');
  });
  it('cancels detail on close and does not reopen it from a late response', async () => {
    const first = deferred<PrivateImportReceipt>(); api.get.mockReturnValueOnce(first.promise);
    const { result } = renderHook(usePrivateImportList); await waitFor(() => expect(result.current.state.status).toBe('ready'));
    let pending!: Promise<void>; act(() => { pending = result.current.open('one'); });
    act(() => result.current.close());
    expect(api.get.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => { first.resolve(receipt()); await pending; });
    expect(result.current.state.detail.status).toBe('closed');
  });
  it('deletes only the explicitly reviewed revision, blocks duplicate calls and leaves local data unchanged', async () => {
    localStorage.setItem('ofe_custom_imports', 'browser-sentinel');
    const pending = deferred<PrivateImportReceipt>(); api.remove.mockReturnValueOnce(pending.promise);
    const { result } = renderHook(usePrivateImportList); await waitFor(() => expect(result.current.state.status).toBe('ready'));
    await act(async () => { await result.current.open('one'); });
    const detail = result.current.state.detail; if (detail.status !== 'ready') throw new Error('not ready');
    let removal!: Promise<void>; act(() => { removal = result.current.remove(detail.target); });
    await act(async () => { await result.current.remove(detail.target); });
    expect(api.remove).toHaveBeenCalledTimes(1); expect(api.remove.mock.calls[0][1]).toBe(1);
    await act(async () => { pending.resolve(receipt()); await removal; });
    expect(result.current.state.items).toEqual([]); expect(result.current.state.deleted).toBe(true);
    expect(localStorage.getItem('ofe_custom_imports')).toBe('browser-sentinel');
  });
  it('refuses a confirmation from old detail after a newer version has been loaded', async () => {
    api.get.mockResolvedValueOnce(receipt()).mockResolvedValueOnce(receipt('one', 2));
    const { result } = renderHook(usePrivateImportList); await waitFor(() => expect(result.current.state.status).toBe('ready'));
    await act(async () => { await result.current.open('one'); });
    const old = result.current.state.detail; if (old.status !== 'ready') throw new Error('not ready');
    await act(async () => { await result.current.open('one'); await result.current.remove(old.target); });
    expect(api.remove).not.toHaveBeenCalled();
    expect(result.current.state.detail).toMatchObject({ status: 'ready', deleteError: 'conflict', target: { revision: 2 } });
  });
  it('preserves the reviewed details after delete conflict and never retries automatically', async () => {
    api.remove.mockRejectedValueOnce(new PrivateTargetError('conflict'));
    const { result } = renderHook(usePrivateImportList); await waitFor(() => expect(result.current.state.status).toBe('ready'));
    await act(async () => { await result.current.open('one'); });
    const old = result.current.state.detail; if (old.status !== 'ready') throw new Error('not ready');
    await act(async () => { await result.current.remove(old.target); });
    expect(result.current.state.detail).toMatchObject({ status: 'ready', target: old.target, deleting: false, deleteError: 'conflict' });
    expect(api.remove).toHaveBeenCalledTimes(1); expect(result.current.state.items).toHaveLength(1);
  });
});


it('times out a hung auth preflight, keeps retry available and ignores the late auth after recovery', async () => {
  vi.useFakeTimers(); const old = deferred<AuthState>(); api.auth.mockReturnValueOnce(old.promise).mockResolvedValueOnce(auth());
  const { result } = renderHook(usePrivateImportList);
  expect(result.current.state.status).toBe('loading'); expect(api.list).not.toHaveBeenCalled();
  await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
  expect(result.current.state.status).toBe('error'); expect(result.current.state.code).toBe('timeout');
  expect(vi.getTimerCount()).toBe(0); expect(api.list).not.toHaveBeenCalled();
  await act(async () => { await result.current.refresh(); });
  expect(result.current.state.status).toBe('ready'); expect(api.list).toHaveBeenCalledOnce();
  await act(async () => { old.resolve(auth(OTHER)); });
  expect(result.current.state.items.map(item => item.id)).toEqual(['one']); expect(api.list).toHaveBeenCalledOnce();
});
it('cancels a hung auth preflight on unmount and clears its deadline', async () => {
  vi.useFakeTimers(); const old = deferred<AuthState>(); api.auth.mockReturnValueOnce(old.promise);
  const { unmount } = renderHook(usePrivateImportList); expect(vi.getTimerCount()).toBe(1);
  unmount(); await act(async () => { await Promise.resolve(); });
  expect(vi.getTimerCount()).toBe(0);
  await act(async () => { old.resolve(auth()); });
  expect(api.list).not.toHaveBeenCalled();
});
