'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange, type OwnerToken } from './identity-owner';
import { readWritingTarget, writingTargetKey } from './writing-target';
import { targetPosture, targetStatusReason } from './target-truth';
import type { Opportunity } from './types';

export type TargetActionReceipt = { checkId: number; owner: OwnerToken; target: Opportunity; key: string };
export type WritingTargetState = {
  status: 'checking' | 'ready' | 'missing' | 'blocked' | 'failed';
  target: Opportunity | null;
  reason: string | null;
  refresh: () => Promise<boolean>;
  checkForAction: () => Promise<TargetActionReceipt | null>;
};
export const WRITING_TARGET_DEADLINE_MS = 15_000;
export const WRITING_TARGET_INTERVAL_MS = 60_000;

type View = Pick<WritingTargetState, 'status' | 'target' | 'reason'> & { key: string | null };
type Attempt = { controller: AbortController; promise: Promise<TargetActionReceipt | null>; ready: Promise<boolean>; cancel: () => void };
type Lifecycle = { active: boolean; cancel: (() => void) | null };
const initialView = (): View => ({ status: 'checking', target: null, reason: null, key: null });
function ownerSnapshot(): string {
  const token = captureOwnerToken();
  return JSON.stringify([token.uid, token.epoch, token.generation, isOwnerTokenValid(token, token.uid)]);
}
function subscribeOwner(changed: () => void): () => void {
  const stop = onLocalOwnerStateChange(changed);
  window.addEventListener('storage', changed);
  return () => { stop(); window.removeEventListener('storage', changed); };
}
function freeze<T>(value: T): T {
  if (value && typeof value === 'object') {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}
function failure(error: unknown): { status: 'failed' | 'missing'; reason: string } {
  const value = error && typeof error === 'object' ? error as { status?: unknown; code?: unknown } : null;
  if (value?.status === 404) return { status: 'missing', reason: 'not_found' };
  if (value?.code === 'TARGET_READ_TIMEOUT') return { status: 'failed', reason: 'timeout' };
  if (value?.code === 'INVALID_TARGET_RESPONSE') return { status: 'failed', reason: 'invalid_target' };
  return { status: 'failed', reason: 'read_failed' };
}

/** One bounded full-detail read per attempt, never a continuously current server
 * guarantee. Unusable reads retain only this session's last verified public
 * target for displaying the draft; status always withdraws action authority. */
export function useWritingTarget(enabled: boolean, opportunityId: string): WritingTargetState {
  const owner = useSyncExternalStore(subscribeOwner, ownerSnapshot, () => 'server');
  const scopeKey = JSON.stringify([enabled, opportunityId, owner]);
  const [state, setState] = useState<{ scope: string; view: View }>({ scope: scopeKey, view: initialView() });
  // A render in a new open/owner/target scope cannot expose previous readiness,
  // including disable -> enable before the passive read effect has completed.
  if (state.scope !== scopeKey) setState({ scope: scopeKey, view: initialView() });
  const lifecycle = useRef<Lifecycle | null>(null);
  const runner = useRef<(() => Attempt | null) | null>(null);
  const sequence = useRef(0);
  const refresh = useCallback(() => runner.current?.()?.ready ?? Promise.resolve(false), []);
  const checkForAction = useCallback(() => runner.current?.()?.promise ?? Promise.resolve(null), []);
  useLayoutEffect(() => {
    const scope: Lifecycle = { active: true, cancel: null };
    lifecycle.current = scope;
    // Retire before child effects or late promise continuations can act on a
    // newly closed/reassigned modal. Cancellation also settles action waiters.
    return () => { scope.active = false; scope.cancel?.(); };
  }, [scopeKey]);

  useEffect(() => {
    const scope = lifecycle.current;
    if (!enabled || !scope?.active) return;
    let disposed = false;
    let attempt: Attempt | null = null;
    let nextRead: ReturnType<typeof setTimeout> | null = null;
    let view = initialView();
    const current = () => !disposed && scope.active && ownerSnapshot() === owner;
    const foreground = () => document.visibilityState === 'visible' && navigator.onLine;
    const authorized = () => {
      const token = captureOwnerToken();
      return current() && isOwnerTokenValid(token, token.uid);
    };
    const stopTimer = () => { if (nextRead !== null) clearTimeout(nextRead); nextRead = null; };
    const publish = (patch: Partial<View>) => {
      if (!current()) return;
      view = { ...view, ...patch };
      setState({ scope: scopeKey, view });
    };
    const schedule = () => {
      stopTimer();
      if (!authorized() || !foreground()) return;
      nextRead = setTimeout(() => { nextRead = null; void run(false); }, WRITING_TARGET_INTERVAL_MS);
    };
    const run = (blocking = true): Attempt | null => {
      if (!authorized() || (!blocking && !foreground())) return null;
      stopTimer();
      if (attempt) {
        if (blocking && view.status !== 'checking') publish({ status: 'checking', reason: null });
        return attempt;
      }
      const capturedOwner = captureOwnerToken();
      const checkId = ++sequence.current;
      const controller = new AbortController();
      let cancel!: () => void;
      let timeout!: ReturnType<typeof setTimeout>;
      const cancelled = new Promise<null>((resolve) => { cancel = () => { controller.abort(); resolve(null); }; });
      const record: Attempt = { controller, promise: Promise.resolve(null), ready: Promise.resolve(false), cancel };
      attempt = record;
      if (blocking || view.status !== 'ready') publish({ status: 'checking', reason: null });
      const accepts = () => current() && attempt === record && !controller.signal.aborted && isOwnerTokenValid(capturedOwner, capturedOwner.uid);
      const work = Promise.resolve().then(async (): Promise<TargetActionReceipt | null> => {
        if (!accepts()) return null;
        try {
          const received = await readWritingTarget(opportunityId, { signal: controller.signal });
          if (!accepts()) return null;
          // Do not lend the transport or a consumer a mutable alias to the
          // target that was validated and placed on the action receipt.
          const candidate = freeze(structuredClone(received));
          const key = writingTargetKey(candidate);
          if (!key || candidate.id !== opportunityId) { publish({ status: 'failed', reason: 'invalid_target' }); return null; }
          const posture = targetPosture(candidate);
          if (posture !== 'actionable') {
            publish({ status: posture === 'historical' ? 'blocked' : 'failed', reason: targetStatusReason(candidate) ?? 'status_unverified' });
            return null;
          }
          const target = view.key === key && view.target ? view.target : candidate;
          publish({ status: 'ready', target, key, reason: null });
          if (!accepts()) return null;
          return Object.freeze({ checkId, owner: Object.freeze({ ...capturedOwner }), target, key });
        } catch (error) {
          if (accepts()) publish(failure(error));
          return null;
        }
      });
      const deadline = new Promise<null>((resolve) => {
        timeout = setTimeout(() => {
          if (accepts()) publish({ status: 'failed', reason: 'timeout' });
          controller.abort(); resolve(null);
        }, WRITING_TARGET_DEADLINE_MS);
      });
      record.promise = Promise.race([work, deadline, cancelled]).finally(() => {
        clearTimeout(timeout);
        if (attempt === record) { attempt = null; if (current()) schedule(); }
      });
      record.ready = record.promise.then((receipt) => receipt !== null);
      return record;
    };
    runner.current = run;
    const recheck = () => { if (foreground()) void run(false); else stopTimer(); };
    window.addEventListener('focus', recheck);
    window.addEventListener('online', recheck);
    window.addEventListener('offline', recheck);
    document.addEventListener('visibilitychange', recheck);
    const dispose = () => {
      if (disposed) return;
      disposed = true;
      if (runner.current === run) runner.current = null;
      stopTimer(); attempt?.cancel();
      window.removeEventListener('focus', recheck);
      window.removeEventListener('online', recheck);
      window.removeEventListener('offline', recheck);
      document.removeEventListener('visibilitychange', recheck);
    };
    scope.cancel = dispose;
    if (foreground()) void run();
    return dispose;
  }, [enabled, opportunityId, owner, scopeKey]);

  const visible = enabled && state.scope === scopeKey ? state.view : initialView();
  return { status: visible.status, target: visible.target, reason: visible.reason, refresh, checkForAction };
}
