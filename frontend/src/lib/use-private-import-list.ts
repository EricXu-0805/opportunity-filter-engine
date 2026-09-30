'use client';

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { getAuthState, onAuthChange, type AuthState } from './supabase';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange, OwnerMismatchError, type OwnerToken } from './identity-owner';
import { deletePrivateImportTarget, getPrivateImportTarget, listPrivateImportTargets, PrivateTargetError, PRIVATE_TARGET_TIMEOUT_MS,
  type PrivateImportCursor, type PrivateImportSummary, type PrivateImportTarget, type PrivateTargetErrorCode } from './private-import-target-api';

export type PrivateImportListError = PrivateTargetErrorCode | 'owner_changed';
export type PrivateImportDetailView =
  | { status: 'closed' }
  | { status: 'loading'; id: string }
  | { status: 'error'; id: string; code: PrivateImportListError }
  | { status: 'ready'; target: PrivateImportTarget; deleting: boolean; deleteError: PrivateImportListError | null };
export type PrivateImportListView = {
  status: 'loading' | 'sign_in_required' | 'ready' | 'error';
  items: PrivateImportSummary[]; cursor: PrivateImportCursor | null;
  code: PrivateImportListError | null; more: 'idle' | 'loading' | 'error';
  detail: PrivateImportDetailView; deleted: boolean;
};
const empty = (): PrivateImportListView => ({ status: 'loading', items: [], cursor: null, code: null, more: 'idle', detail: { status: 'closed' }, deleted: false });
function ownerSnapshot(): string {
  const token = captureOwnerToken();
  return JSON.stringify([token.uid, token.epoch, token.generation, isOwnerTokenValid(token, token.uid)]);
}
function subscribeOwner(changed: () => void) {
  const stop = onLocalOwnerStateChange(changed); window.addEventListener('storage', changed);
  return () => { stop(); window.removeEventListener('storage', changed); };
}
function code(error: unknown): PrivateImportListError {
  return error instanceof PrivateTargetError ? error.code : error instanceof OwnerMismatchError ? 'owner_changed' : 'unavailable';
}
function freeze<T>(value: T): T {
  if (value && typeof value === 'object') { for (const child of Object.values(value)) freeze(child); Object.freeze(value); }
  return value;
}
async function readAuthWithDeadline(signal: AbortSignal): Promise<AuthState> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let abort: (() => void) | undefined;
  const deadline = new Promise<never>((_resolve, reject) => {
    abort = () => reject(new PrivateTargetError('aborted'));
    if (signal.aborted) { abort(); return; }
    signal.addEventListener('abort', abort, { once: true });
    timer = setTimeout(() => reject(new PrivateTargetError('timeout')), PRIVATE_TARGET_TIMEOUT_MS);
  });
  try {
    // The SDK bounds its own auth step. This UI preflight must also settle
    // even if a session read never resolves; its late result has no authority.
    return await Promise.race([getAuthState({ throwOnError: true }), deadline]);
  } finally {
    clearTimeout(timer);
    if (abort) signal.removeEventListener('abort', abort);
  }
}
type Actions = { refresh: () => Promise<void>; more: () => Promise<void>; open: (id: string) => Promise<void>;
  close: () => void; remove: (target: PrivateImportTarget) => Promise<void> };

/** Independent account list. It never uploads local records or mutates their storage. */
export function usePrivateImportList() {
  const owner = useSyncExternalStore(subscribeOwner, ownerSnapshot, () => 'server');
  const [stored, setStored] = useState<{ owner: string; view: PrivateImportListView }>({ owner, view: empty() });
  const actions = useRef<Actions | null>(null);
  useEffect(() => {
    let active = true; let epoch = 0; let detailEpoch = 0;
    let view = empty(); let token: OwnerToken | null = null; let authIdentity: string | undefined;
    let listController: AbortController | null = null; let detailController: AbortController | null = null;
    const current = () => active && ownerSnapshot() === owner;
    const publish = (next: PrivateImportListView) => { view = next; if (current()) setStored({ owner, view: next }); };
    const close = () => { detailEpoch++; detailController?.abort(); detailController = null; publish({ ...view, detail: { status: 'closed' } }); };
    const refresh = async (observedAuth?: AuthState) => {
      const attempt = ++epoch; listController?.abort(); detailEpoch++; detailController?.abort();
      const controller = new AbortController(); listController = controller; token = null;
      publish(empty());
      try {
        const auth = observedAuth ?? await readAuthWithDeadline(controller.signal);
        if (!current() || attempt !== epoch) return;
        authIdentity = JSON.stringify([auth.user?.id ?? null, auth.isAnonymous]);
        if (!auth.user || auth.isAnonymous || !auth.session?.access_token) { publish({ ...empty(), status: 'sign_in_required' }); return; }
        const origin = captureOwnerToken();
        if (origin.uid !== auth.user.id || !isOwnerTokenValid(origin, origin.uid)) throw new OwnerMismatchError();
        token = origin;
        const page = await listPrivateImportTargets({ owner: origin, signal: controller.signal });
        if (!current() || attempt !== epoch) return;
        publish({ ...empty(), status: 'ready', items: freeze(page.items), cursor: page.next_cursor });
      } catch (error) {
        if (!current() || attempt !== epoch) return;
        const reason = code(error);
        publish({ ...empty(), status: reason === 'sign_in_required' ? 'sign_in_required' : 'error', code: reason });
      }
    };
    const more = async () => {
      if (!current() || !token || view.status !== 'ready' || !view.cursor || view.more === 'loading') return;
      const attempt = epoch; const origin = token; const cursor = { ...view.cursor };
      const controller = new AbortController(); listController = controller;
      publish({ ...view, more: 'loading', code: null });
      try {
        const page = await listPrivateImportTargets({ owner: origin, cursor, signal: controller.signal });
        if (!current() || attempt !== epoch) return;
        const ids = new Set(view.items.map(item => item.id));
        if (page.items.some(item => ids.has(item.id))) throw new PrivateTargetError('invalid_receipt');
        publish({ ...view, items: freeze([...view.items, ...page.items]), cursor: page.next_cursor, more: 'idle' });
      } catch (error) { if (current() && attempt === epoch) publish({ ...view, more: 'error', code: code(error) }); }
    };
    const open = async (id: string) => {
      if (!current() || !token || view.status !== 'ready') return;
      const attempt = ++detailEpoch; const listAttempt = epoch; const origin = token;
      detailController?.abort(); const controller = new AbortController(); detailController = controller;
      publish({ ...view, detail: { status: 'loading', id }, deleted: false });
      try {
        const result = await getPrivateImportTarget(id, { owner: origin, signal: controller.signal });
        if (!current() || attempt !== detailEpoch || listAttempt !== epoch) return;
        if (!result) throw new PrivateTargetError('not_found');
        if (result.target.deleted_at !== null || !result.target.opportunity) throw new PrivateTargetError('deleted');
        publish({ ...view, detail: { status: 'ready', target: freeze(result.target), deleting: false, deleteError: null } });
      } catch (error) { if (current() && attempt === detailEpoch && listAttempt === epoch) publish({ ...view, detail: { status: 'error', id, code: code(error) } }); }
    };
    const remove = async (reviewed: PrivateImportTarget) => {
      if (!current() || !token || view.detail.status !== 'ready' || view.detail.deleting) return;
      // The exact detail shown before confirmation, never a newer revision.
      if (view.detail.target !== reviewed) { publish({ ...view, detail: { ...view.detail, deleteError: 'conflict' } }); return; }
      const attempt = ++detailEpoch; const listAttempt = epoch; const origin = token;
      detailController?.abort(); const controller = new AbortController(); detailController = controller;
      publish({ ...view, detail: { status: 'ready', target: reviewed, deleting: true, deleteError: null } });
      try {
        await deletePrivateImportTarget(reviewed.id, reviewed.revision, { owner: origin, signal: controller.signal });
        if (!current() || attempt !== detailEpoch || listAttempt !== epoch) return;
        publish({ ...view, items: view.items.filter(item => item.id !== reviewed.id), detail: { status: 'closed' }, deleted: true });
      } catch (error) {
        if (current() && attempt === detailEpoch && listAttempt === epoch) publish({ ...view, detail: { status: 'ready', target: reviewed, deleting: false, deleteError: code(error) } });
      }
    };
    const machine: Actions = { refresh: () => refresh(), more, open, close, remove };
    actions.current = machine;
    void refresh();
    const stop = onAuthChange(auth => {
      if (!current()) return;
      const identity = JSON.stringify([auth.user?.id ?? null, auth.isAnonymous]);
      if (identity !== authIdentity) { authIdentity = identity; void refresh(auth); }
    });
    return () => { active = false; epoch++; detailEpoch++; listController?.abort(); detailController?.abort(); stop(); if (actions.current === machine) actions.current = null; };
  }, [owner]);
  const refresh = useCallback(() => actions.current?.refresh() ?? Promise.resolve(), []);
  const loadMore = useCallback(() => actions.current?.more() ?? Promise.resolve(), []);
  const open = useCallback((id: string) => actions.current?.open(id) ?? Promise.resolve(), []);
  const close = useCallback(() => actions.current?.close(), []);
  const remove = useCallback((target: PrivateImportTarget) => actions.current?.remove(target) ?? Promise.resolve(), []);
  // Hide the old account on the first render, before passive cleanup runs.
  return { state: stored.owner === owner ? stored.view : empty(), refresh, loadMore, open, close, remove };
}
