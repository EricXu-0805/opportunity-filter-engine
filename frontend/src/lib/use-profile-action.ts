'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange, type OwnerToken } from './identity-owner';
import { PROFILE_REFRESH_DEADLINE_MS, type ProfileActionReceipt, type ProfileRefreshState } from './use-profile-refresh';
import type { Opportunity, ProfileData } from './types';
import type { WritingTargetState } from './use-writing-target';
import { writingTargetKey } from './writing-target';
import { privateEmailKey, type PrivateEmailContext } from './private-email';
import type { PrivateEmailTargetState } from './use-private-email-target';

/** In-memory structural binding only. Never persisted, logged or sent as a hash. */
export function profileActionKey(profile: ProfileData | null): string | null {
  try {
    return JSON.stringify(profile, (_key, value: unknown) => value && typeof value === 'object' && !Array.isArray(value)
      ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) : value);
  } catch { return null; }
}
function ownerKey(): string {
  const owner = captureOwnerToken();
  return JSON.stringify([owner.uid, owner.epoch, owner.generation, isOwnerTokenValid(owner, owner.uid)]);
}
function subscribeOwner(notify: () => void): () => void {
  const stop = onLocalOwnerStateChange(notify);
  window.addEventListener('storage', notify);
  return () => { stop(); window.removeEventListener('storage', notify); };
}
export type ProfileActionError = 'changed' | 'unavailable' | null;
export interface ProfileActionOptions<I> {
  isOpen: boolean;
  profile: ProfileData | null;
  profileAvailable: boolean;
  scopeKey: string;
  /** User edits only. A refreshed profile is expected to change during a check. */
  editRevision: number | string;
  refresh?: ProfileRefreshState;
  /** The exact target committed by this editor, independent of its seed card. */
  target?: Opportunity | null;
  targetRefresh?: WritingTargetState;
  privateTarget?: PrivateEmailContext | null;
  privateTargetRefresh?: PrivateEmailTargetState;
  readiness: 'ready' | 'waiting' | 'blocked';
  execute: (intent: I) => void;
}
interface Pending<I> {
  intent: I;
  owner: OwnerToken;
  scopeKey: string;
  editRevision: number | string;
  before: string;
  receipt: ProfileActionReceipt | null;
  checking: boolean;
  legacy: boolean;
  matched: boolean;
  targetBefore: string | null;
  targetId: string | null;
  targetReceipt: { key: string } | null;
  targetScope: 'public' | 'private' | null;
  targetMatched: boolean;
  timer: ReturnType<typeof setTimeout> | null;
}

type TargetOptions = Pick<ProfileActionOptions<unknown>, 'target' | 'targetRefresh' | 'privateTarget' | 'privateTargetRefresh'>;
function actionTarget(options: TargetOptions) {
  if (options.privateTargetRefresh) {
    const target = options.privateTarget;
    return { kind: 'private' as const, id: target?.id, key: privateEmailKey(target ?? null), status: options.privateTargetRefresh.status,
      invalid: !!options.target || !!options.targetRefresh,
      check: async () => {
        const receipt = await options.privateTargetRefresh!.checkForAction();
        return receipt && receipt.target.owner_id === receipt.owner.uid && privateEmailKey(receipt.target) === receipt.key
          ? { owner: receipt.owner, id: receipt.target.id, key: receipt.key } : null;
      } };
  }
  if (options.targetRefresh) return { kind: 'public' as const, id: options.target?.id, key: writingTargetKey(options.target ?? null),
    status: options.targetRefresh.status, invalid: !!options.privateTarget,
    check: async () => {
      const receipt = await options.targetRefresh!.checkForAction();
      return receipt && writingTargetKey(receipt.target) === receipt.key ? { owner: receipt.owner, id: receipt.target.id, key: receipt.key } : null;
    } };
  return null;
}

/** Queue data, never a generator closure. Only a committed render that actually
 * displays the checked profile and target can consume the intent. These are
 * bounded pre-action reads; the server can still change after they finish. */
export function useProfileAction<I>(options: ProfileActionOptions<I>): {
  request: (intent: I) => void; busy: boolean; cancel: () => void; error: ProfileActionError;
} {
  const owner = useSyncExternalStore(subscribeOwner, ownerKey, () => 'server');
  const latest = useRef(options);
  useLayoutEffect(() => { latest.current = options; });
  const pending = useRef<Pending<I> | null>(null);
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ProfileActionError>(null);
  const finish = useCallback((record: Pending<I>, nextError: ProfileActionError) => {
    if (pending.current !== record) return;
    if (record.timer) clearTimeout(record.timer);
    pending.current = null;
    setBusy(false);
    setError(nextError);
    setVersion((value) => value + 1);
  }, []);
  const cancel = useCallback(() => {
    const record = pending.current;
    if (record) finish(record, null);
    else setError(null);
  }, [finish]);

  const request = useCallback((intent: I) => {
    if (pending.current) return;
    const current = latest.current;
    const token = captureOwnerToken();
    const before = profileActionKey(current.profile);
    const check = current.refresh?.checkForAction;
    const bound = actionTarget(current);
    const targetCheck = bound?.check;
    const targetBefore = bound?.key ?? null;
    if (!current.isOpen || !current.profileAvailable || !current.profile || !before
      || (bound && (bound.invalid || !targetCheck || !bound.id || !targetBefore))
      || (current.privateTarget && !current.privateTargetRefresh)
      || (!check && !targetCheck && current.readiness === 'blocked') || !isOwnerTokenValid(token, token.uid)) {
      setError('unavailable'); return;
    }
    let copied: I;
    try { copied = structuredClone(intent); } catch { setError('unavailable'); return; }
    const record: Pending<I> = { intent: copied, owner: token, scopeKey: current.scopeKey,
      editRevision: current.editRevision, before, receipt: null, checking: !!check || !!targetCheck,
      legacy: !check, matched: false, targetBefore: targetCheck ? targetBefore : null,
      targetId: bound?.id ?? null, targetReceipt: null, targetScope: bound?.kind ?? null, targetMatched: false, timer: null };
    pending.current = record;
    setBusy(true);
    setError(null); setVersion((value) => value + 1);
    // Failure bound only: elapsed time never counts as a successful read or a
    // committed profile. Cancellation retires this intent, not a shared read.
    record.timer = setTimeout(() => finish(record, 'unavailable'), PROFILE_REFRESH_DEADLINE_MS);
    if (!check && !targetCheck) return;
    const ownerMatches = (receiptOwner: OwnerToken) => isOwnerTokenValid(receiptOwner, receiptOwner.uid)
      && receiptOwner.uid === record.owner.uid && receiptOwner.epoch === record.owner.epoch
      && receiptOwner.generation === record.owner.generation;
    // Both independent reads start together. No provider action can run until
    // both receipts have been accepted and both values are committed below.
    void Promise.all([
      Promise.resolve().then(() => pending.current === record && check ? check() : null),
      Promise.resolve().then(() => pending.current === record && targetCheck ? targetCheck() : null),
    ]).then(([receipt, targetReceipt]) => {
      if (pending.current !== record) return;
      if (check && (!receipt?.profile || !ownerMatches(receipt.owner))) { finish(record, 'unavailable'); return; }
      if (targetCheck && (!targetReceipt || !ownerMatches(targetReceipt.owner)
        || targetReceipt.id !== record.targetId || !targetReceipt.key)) { finish(record, 'unavailable'); return; }
      record.receipt = receipt;
      record.targetReceipt = targetReceipt;
      record.checking = false;
      if (record.timer) clearTimeout(record.timer);
      record.timer = setTimeout(() => finish(record, 'unavailable'), PROFILE_REFRESH_DEADLINE_MS);
      setVersion((value) => value + 1);
    }).catch(() => finish(record, 'unavailable'));
  }, [finish]);

  // A scope/edit/owner change permanently retires the intent, including a
  // change away and back before an asynchronous receipt arrives.
  useLayoutEffect(() => {
    const record = pending.current;
    if (!record) return;
    if (!options.isOpen) { finish(record, null); return; }
    const target = actionTarget({ target: options.target, targetRefresh: options.targetRefresh,
      privateTarget: options.privateTarget, privateTargetRefresh: options.privateTargetRefresh });
    if (!isOwnerTokenValid(record.owner, record.owner.uid) || options.scopeKey !== record.scopeKey
      || options.editRevision !== record.editRevision
      || (record.targetId !== null && (target?.id !== record.targetId || target?.kind !== record.targetScope))) { finish(record, 'changed'); return; }
    if (!options.profileAvailable || !options.profile) finish(record, 'unavailable');
  }, [options.isOpen, options.profileAvailable, options.profile, options.scopeKey, options.editRevision, options.target, options.targetRefresh, options.privateTarget, options.privateTargetRefresh, owner, finish]);

  useEffect(() => {
    const record = pending.current;
    if (!record || record.checking) return;
    const current = latest.current;
    if (!current.isOpen || !current.profileAvailable || !current.profile
      || !isOwnerTokenValid(record.owner, record.owner.uid)) { finish(record, 'unavailable'); return; }
    if (current.scopeKey !== record.scopeKey || current.editRevision !== record.editRevision) { finish(record, 'changed'); return; }
    const rendered = profileActionKey(current.profile);
    const expected = record.legacy ? record.before : profileActionKey(record.receipt!.profile);
    if (!rendered || !expected) { finish(record, 'unavailable'); return; }
    const profileMatches = rendered === expected;
    if (!profileMatches && (record.matched || rendered !== record.before)) { finish(record, 'changed'); return; }
    if (profileMatches) record.matched = true;
    let targetMatches = true;
    if (record.targetId !== null) {
      const bound = actionTarget(current);
      if (!bound || bound.invalid || bound.id !== record.targetId || bound.kind !== record.targetScope || !record.targetReceipt) { finish(record, 'changed'); return; }
      const renderedTarget = bound.key;
      if (!renderedTarget) { finish(record, 'unavailable'); return; }
      targetMatches = renderedTarget === record.targetReceipt.key;
      // Track each commit separately: one source may update while the other
      // still displays its old value. Once matched, reverting cancels the intent.
      if (!targetMatches && (record.targetMatched || renderedTarget !== record.targetBefore)) { finish(record, 'changed'); return; }
      if (targetMatches) record.targetMatched = true;
      if (bound.status !== 'ready' && bound.status !== 'checking') { finish(record, 'unavailable'); return; }
      if (bound.status === 'checking') return;
    }
    if (!profileMatches || !targetMatches) return;
    if (current.readiness === 'blocked') { finish(record, 'unavailable'); return; }
    if (current.readiness === 'waiting') return;
    finish(record, null); // Retire before executing; StrictMode cannot repeat it.
    current.execute(record.intent);
  }, [version, options.profile, options.readiness, options.scopeKey, options.editRevision, options.profileAvailable, options.isOpen, options.target, options.targetRefresh, options.privateTarget, options.privateTargetRefresh, owner, finish]);

  useEffect(() => () => {
    const record = pending.current;
    if (record?.timer) clearTimeout(record.timer);
    pending.current = null;
  }, []);

  return { request, busy, cancel, error };
}
