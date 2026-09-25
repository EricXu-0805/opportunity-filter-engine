'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange, type OwnerToken } from './identity-owner';
import { PROFILE_REFRESH_DEADLINE_MS, type ProfileActionReceipt, type ProfileRefreshState } from './use-profile-refresh';
import type { ProfileData } from './types';

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
  timer: ReturnType<typeof setTimeout> | null;
}

/** Queue data, never a generator closure. Only a committed render that actually
 * displays the checked candidate can consume the intent. This is one bounded
 * pre-action read; it cannot guarantee the server will not change afterwards. */
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
    if (!current.isOpen || !current.profileAvailable || !current.profile || !before
      || (!check && current.readiness === 'blocked') || !isOwnerTokenValid(token, token.uid)) {
      setError('unavailable'); return;
    }
    let copied: I;
    try { copied = structuredClone(intent); } catch { setError('unavailable'); return; }
    const record: Pending<I> = { intent: copied, owner: token, scopeKey: current.scopeKey,
      editRevision: current.editRevision, before, receipt: null, checking: !!check,
      legacy: !check, matched: false, timer: null };
    pending.current = record;
    setBusy(true);
    setError(null); setVersion((value) => value + 1);
    // Failure bound only: elapsed time never counts as a successful read or a
    // committed profile. Cancellation retires this intent, not a shared read.
    record.timer = setTimeout(() => finish(record, 'unavailable'), PROFILE_REFRESH_DEADLINE_MS);
    if (!check) return;
    void Promise.resolve().then(() => pending.current === record ? check() : null).then((receipt) => {
      if (pending.current !== record) return;
      if (!receipt || !receipt.profile || !isOwnerTokenValid(receipt.owner, receipt.owner.uid)
        || receipt.owner.uid !== record.owner.uid || receipt.owner.epoch !== record.owner.epoch
        || receipt.owner.generation !== record.owner.generation) { finish(record, 'unavailable'); return; }
      record.receipt = receipt;
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
    if (!isOwnerTokenValid(record.owner, record.owner.uid) || options.scopeKey !== record.scopeKey
      || options.editRevision !== record.editRevision) { finish(record, 'changed'); return; }
    if (!options.profileAvailable || !options.profile) finish(record, 'unavailable');
  }, [options.isOpen, options.profileAvailable, options.profile, options.scopeKey, options.editRevision, owner, finish]);

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
    if (rendered !== expected) {
      // Old props may still be committed when hydrate resolves. Only wait for
      // that known old render; a third document is a superseding source.
      if (record.matched || rendered !== record.before) finish(record, 'changed');
      return;
    }
    record.matched = true;
    if (current.readiness === 'blocked') { finish(record, 'unavailable'); return; }
    if (current.readiness === 'waiting') return;
    finish(record, null); // Retire before executing; StrictMode cannot repeat it.
    current.execute(record.intent);
  }, [version, options.profile, options.readiness, options.scopeKey, options.editRevision, options.profileAvailable, options.isOpen, owner, finish]);

  useEffect(() => () => {
    const record = pending.current;
    if (record?.timer) clearTimeout(record.timer);
    pending.current = null;
  }, []);

  return { request, busy, cancel, error };
}
