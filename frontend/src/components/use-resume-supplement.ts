'use client';

import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import {
  captureOwnerToken, isOwnerTokenValid, isTokenOwnerStillCurrent, onLocalOwnerStateChange,
  type OwnerToken,
} from '@/lib/identity-owner';
import {
  commitProfileAction, flushPendingProfileWrite, hydrateProfile, makeProfileViewSnapshot,
  readProfileSyncEnvelopeStrict, readProfileView, RESUME_BUNDLE,
  type ProfileActionOutcome, type ProfileSaveResult, type ProfileViewSnapshot,
} from '@/lib/profile-sync';
import { resumeMasterEditBase } from '@/lib/resume-master';
import { prepareConfirmedSupplement, type SupplementDraft } from '@/lib/resume-supplement';
import type { ExperienceEntry, ProfileData } from '@/lib/types';

export interface SupplementBaseline {
  view: ProfileViewSnapshot;
  activityId: string;
  targetKey: string;
}
export type ResumeSupplementPhase = 'loading' | 'load-error' | 'not-saved' | 'ready' | 'stale'
  | 'saving' | 'recorded' | 'conflict' | 'save-error' | 'save-unknown' | 'saved' | 'retired' | 'profile-unavailable';
export interface ResumeSupplementOptions {
  enabled?: boolean;
  profileAvailable?: boolean;
  owner?: OwnerToken;
  targetKey: string;
  onAcceptedProfile?: (view: ProfileViewSnapshot, againstView: ProfileViewSnapshot) => void;
}
interface Operation {
  against: SupplementBaseline;
  entry: ExperienceEntry;
  durable: boolean | 'unknown';
  confirmed: boolean;
  outcome?: ProfileActionOutcome;
}
interface Scope {
  active: boolean;
  owner: OwnerToken;
  targetKey: string;
  load: number;
  readController: AbortController | null;
  view: ProfileViewSnapshot | null;
  operation: Operation | null;
  busy: boolean;
  phase: ResumeSupplementPhase;
}
interface State {
  owner: OwnerToken | null;
  targetKey: string;
  operationLocked: boolean;
  view: ProfileViewSnapshot | null;
  phase: ResumeSupplementPhase;
  error: string | null;
  confirmedEntryId: string | null;
}
const ownerKey = (owner: OwnerToken) => JSON.stringify([owner.uid, owner.epoch, owner.generation]);
const canonical = (value: unknown): string => JSON.stringify(value, (_key, item: unknown) =>
  !item || typeof item !== 'object' || Array.isArray(item) ? item
    : Object.fromEntries(Object.entries(item as Record<string, unknown>).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)));
const bundleKey = (profile: ProfileData): string => canonical({
  ...resumeMasterEditBase(profile), coursework: profile.coursework ?? [],
});
const rejected = (): ProfileActionOutcome => ({ durable: false, reason: 'stale-view' });

/** Receipt identity is the complete manual entry plus its particular activity
 * reference. An unrelated successful flush is never this operation's success. */
function containsOperation(profile: ProfileData | null, operation: Operation): boolean {
  if (!profile) return false;
  const entries = profile.experience_entries;
  const activities = profile.resume_master?.activities;
  if (!Array.isArray(entries) || !Array.isArray(activities)) return false;
  const matching = entries.filter(entry => entry.id === operation.entry.id);
  const activity = activities.find(item => item.id === operation.against.activityId);
  return matching.length === 1 && canonical(matching[0]) === canonical(operation.entry)
    && !!activity && activity.details.filter(ref => ref.id === operation.entry.id
      && ref.revision === operation.entry.revision).length === 1;
}

export function useResumeSupplement({ enabled = true, profileAvailable = true, owner, targetKey, onAcceptedProfile }: ResumeSupplementOptions) {
  const liveOwner = owner ?? captureOwnerToken();
  const scopeKey = ownerKey(liveOwner);
  const scopeRef = useRef<Scope | null>(null);
  const availability = useRef({ available: profileAvailable, version: 0 });
  const callbackRef = useRef(onAcceptedProfile);
  const [state, setState] = useState<State>({ owner: null, targetKey: '', operationLocked: false, view: null, phase: 'loading', error: null, confirmedEntryId: null });
  useLayoutEffect(() => { callbackRef.current = onAcceptedProfile; }, [onAcceptedProfile]);
  const current = useCallback((scope: Scope) => scope.active && scopeRef.current === scope
    && isOwnerTokenValid(scope.owner, scope.owner.uid), []);
  const publish = useCallback((scope: Scope, phase: ResumeSupplementPhase, error: string | null = null,
    confirmedEntryId: string | null = null) => {
    if (current(scope)) {
      scope.phase = phase;
      setState({ owner: { ...scope.owner }, targetKey: scope.targetKey, operationLocked: !!scope.operation?.durable || (!!scope.operation && scope.busy && error === 'profile-unavailable') || phase === 'saving', view: scope.view, phase, error, confirmedEntryId });
    }
  }, [current]);

  // Availability retires use of the profile, not answers or journal identity.
  // Restoring availability requires an explicit read of the current materials.
  useLayoutEffect(() => {
    if (availability.current.available === profileAvailable) return;
    availability.current = { available: profileAvailable, version: availability.current.version + 1 };
    const scope = scopeRef.current;
    if (!scope || !current(scope)) return;
    scope.load += 1; scope.readController?.abort(); scope.readController = null;
    scope.view = null;
    publish(scope, profileAvailable ? 'stale' : 'profile-unavailable', 'profile-unavailable');
  }, [profileAvailable, current, publish]);

  const accept = useCallback(async (scope: Scope) => {
    if (!availability.current.available || !current(scope) || scope.busy) return;
    const availableVersion = availability.current.version;
    const request = ++scope.load;
    scope.readController?.abort();
    const controller = new AbortController(); scope.readController = controller;
    publish(scope, 'loading');
    try {
      const loaded = await hydrateProfile(controller.signal);
      if (!current(scope) || request !== scope.load || !availability.current.available || availability.current.version !== availableVersion) return;
      if (ownerKey(loaded.token) !== ownerKey(scope.owner) || loaded.quarantineFailed) {
        publish(scope, 'load-error', 'unavailable'); return;
      }
      if (!loaded.profile || !loaded.baseProfile || loaded.revision < 1) {
        scope.view = null; publish(scope, 'not-saved', 'profile-not-saved'); return;
      }
      const view = makeProfileViewSnapshot({ renderedProfile: loaded.profile, baseProfile: loaded.baseProfile,
        revision: loaded.revision, token: loaded.token, identityGeneration: loaded.token.epoch, source: 'hydration' });
      scope.view = view;
      if (loaded.conflictKeys.some(key => (RESUME_BUNDLE as readonly string[]).includes(key))) {
        publish(scope, 'conflict', 'bundle-conflict'); return;
      }
      // A recorded operation stays retryable after rechecking; accepting a new
      // baseline must never silently turn it into a second addition.
      if (scope.operation?.durable) {
        const op = scope.operation;
        if (containsOperation(view.baseProfile, op) && containsOperation(view.renderedProfile, op)) {
          op.confirmed = true;
          publish(scope, 'saved', null, op.entry.id);
          if (scope.targetKey === op.against.targetKey) callbackRef.current?.(view, op.against.view);
        } else publish(scope, op.durable === 'unknown' ? 'save-unknown' : 'recorded', 'pending-operation');
      } else publish(scope, 'ready');
    } catch {
      if (current(scope) && request === scope.load && availability.current.available && availability.current.version === availableVersion) publish(scope, 'load-error', 'unavailable');
    } finally { if (scope.readController === controller) scope.readController = null; }
  }, [current, publish]);

  useLayoutEffect(() => {
    const previous = scopeRef.current;
    const changedTarget = previous !== null && ownerKey(previous.owner) === scopeKey && previous.targetKey !== targetKey;
    if (previous) { previous.active = false; previous.readController?.abort(); }
    if (!enabled) { scopeRef.current = null; return; }
    const preserved = changedTarget && previous?.operation && !previous.operation.confirmed && (previous.operation.durable || previous.busy)
      ? { ...previous.operation, durable: previous.operation.durable || 'unknown' as const } : null;
    const scope: Scope = { active: true, owner: { ...liveOwner }, targetKey, load: 0, readController: null,
      view: null, operation: preserved, busy: false, phase: changedTarget ? 'stale' : 'loading' };
    scopeRef.current = scope;
    // This lifecycle reset clears private state before paint on owner changes.
    setState({ owner: { ...scope.owner }, targetKey, operationLocked: !!preserved, view: null, phase: changedTarget ? 'stale' : 'loading', error: changedTarget ? 'target-changed' : null, confirmedEntryId: null });
    const inspect = () => {
      if (!scope.active) return;
      if (!isTokenOwnerStillCurrent(scope.owner) || captureOwnerToken().generation !== scope.owner.generation) {
        scope.active = false;
        setState({ owner: { ...scope.owner }, targetKey, operationLocked: false, view: null, phase: 'retired', error: 'owner-changed', confirmedEntryId: null });
        return;
      }
      if (!availability.current.available || !current(scope) || scope.busy || !scope.view) return;
      const latest = readProfileView(scope.owner);
      if (!latest || bundleKey(latest.renderedProfile) !== bundleKey(scope.view.renderedProfile)) {
        publish(scope, 'stale', 'bundle-changed');
      }
    };
    const unsubscribe = onLocalOwnerStateChange(inspect);
    window.addEventListener('storage', inspect);
    window.addEventListener('focus', inspect);
    if (!changedTarget) void accept(scope);
    return () => { scope.active = false; scope.readController?.abort(); unsubscribe(); window.removeEventListener('storage', inspect); window.removeEventListener('focus', inspect); };
    // Tokens are plain values: a recreated prop object must not restart hydration.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, scopeKey, targetKey, accept, current, publish]);

  const finish = useCallback((scope: Scope, operation: Operation, result: ProfileSaveResult) => {
    if (!current(scope) || scope.operation !== operation) return;
    if (result.status === 'saved' || result.status === 'already-saved' || result.status === 'blocked') {
      const envelope = readProfileSyncEnvelopeStrict();
      const latest = envelope.ok ? readProfileView(scope.owner) : null;
      const noBundleConflict = envelope.ok && !envelope.value?.pending?.lockedKeys.some(key => (RESUME_BUNDLE as readonly string[]).includes(key));
      const receiptMatches = result.status === 'blocked' || containsOperation(result.profile, operation);
      if (receiptMatches && latest && noBundleConflict && latest.revision >= 1
        && (result.status === 'blocked' || latest.revision >= result.revision)
        && containsOperation(latest.baseProfile, operation) && containsOperation(latest.renderedProfile, operation)) {
        scope.view = latest;
        operation.confirmed = true;
        publish(scope, 'saved', null, operation.entry.id);
        if (current(scope) && scope.targetKey === operation.against.targetKey) callbackRef.current?.(latest, operation.against.view);
      } else publish(scope, 'stale', 'operation-not-confirmed');
    } else if (result.status === 'conflict' || result.status === 'stale-conflict') publish(scope, 'conflict', 'bundle-conflict');
    else if (result.status === 'abandoned') publish(scope, 'stale', 'owner-changed');
    else publish(scope, operation.durable === 'unknown' ? 'save-unknown' : 'recorded', result.status);
  }, [current, publish]);

  const retryRecorded = useCallback(async (): Promise<ProfileSaveResult> => {
    const scope = scopeRef.current;
    const operation = scope?.operation;
    if (!availability.current.available) return { status: 'missing', reason: 'absent' };
    if (!scope || !operation?.durable || !current(scope)) return { status: 'abandoned' };
    if (scope.busy) return { status: 'blocked' };
    const availableVersion = availability.current.version;
    scope.busy = true; publish(scope, 'saving');
    try {
      const result = await flushPendingProfileWrite(scope.owner);
      if (availability.current.available && availability.current.version === availableVersion) finish(scope, operation, result);
      return current(scope) ? result : { status: 'abandoned' };
    } catch {
      if (current(scope) && availability.current.available && availability.current.version === availableVersion) publish(scope, operation.durable === 'unknown' ? 'save-unknown' : 'recorded', 'retry-failed');
      return { status: 'error', message: 'retry-failed' };
    } finally {
      scope.busy = false;
      if (current(scope) && availability.current.version !== availableVersion) {
        publish(scope, availability.current.available ? 'stale' : 'profile-unavailable', 'profile-unavailable');
      }
    }
  }, [current, finish, publish]);

  const confirm = useCallback(async (draft: SupplementDraft, against: SupplementBaseline): Promise<ProfileActionOutcome | null> => {
    const scope = scopeRef.current;
    if (!availability.current.available || !scope || !current(scope) || scope.busy || !scope.view || !['ready', 'save-error', 'saved', 'recorded'].includes(scope.phase) || against.view !== scope.view
      || against.targetKey !== scope.targetKey || against.activityId !== draft.activityId) return rejected();
    if (scope.operation?.durable) {
      if (scope.operation.entry.id !== draft.entryId) { publish(scope, 'recorded', 'pending-operation'); return rejected(); }
      return scope.operation.outcome ?? { durable: true };
    }
    const envelope = readProfileSyncEnvelopeStrict();
    const latest = envelope.ok ? readProfileView(scope.owner) : null;
    if (!latest || latest.revision < 1 || !latest.baseProfile || !current(scope) || bundleKey(latest.renderedProfile) !== bundleKey(against.view.renderedProfile)) {
      publish(scope, 'stale', 'bundle-changed'); return rejected();
    }
    if (envelope.ok && envelope.value?.pending?.lockedKeys.some(key => (RESUME_BUNDLE as readonly string[]).includes(key))) {
      publish(scope, 'conflict', 'bundle-conflict'); return rejected();
    }
    const prepared = prepareConfirmedSupplement(against.view.renderedProfile, draft);
    if (!prepared.ok) { publish(scope, 'save-error', prepared.reason); return { durable: false, reason: 'record-failed' }; }
    const operation: Operation = { against: Object.freeze({ ...against }), entry: prepared.entry, durable: false, confirmed: false };
    const availableVersion = availability.current.version;
    scope.operation = operation; scope.busy = true; publish(scope, 'saving');
    try {
      const outcome = await commitProfileAction({ view: against.view, desiredAfter: prepared.desired,
        keys: ['experience_entries', 'resume_master'], writer: 'resume-supplement', allowCreate: false });
      operation.durable = outcome.durable; operation.outcome = outcome;
      if (!current(scope)) return rejected();
      // The RPC may have committed. Keep its receipt on the same operation,
      // but do not accept an old profile after an absence/recovery transition.
      if (!availability.current.available || availability.current.version !== availableVersion) return outcome;
      if (!outcome.durable) publish(scope, outcome.reason === 'stale-view' ? 'stale' : 'save-error', outcome.reason ?? 'record-failed');
      else if (outcome.result) finish(scope, operation, outcome.result);
      else publish(scope, 'recorded', 'pending-operation');
      return outcome;
    } catch {
      // commitProfileAction records synchronously before awaiting. An unexpected
      // rejection has an unknown durable outcome; only replay may resolve it.
      scope.operation = { ...operation, durable: 'unknown' };
      if (current(scope) && availability.current.available && availability.current.version === availableVersion) publish(scope, 'save-unknown', 'save-unknown');
      return null;
    } finally {
      scope.busy = false;
      if (current(scope) && availability.current.version !== availableVersion) {
        publish(scope, availability.current.available ? 'stale' : 'profile-unavailable', 'profile-unavailable');
      }
    }
  }, [current, finish, publish]);

  const acceptCurrent = useCallback(async () => {
    const scope = scopeRef.current;
    if (!availability.current.available || !scope || !current(scope) || scope.busy) return;
    // An explicit new round after confirmed success accepts a fresh baseline.
    if (scope.operation?.confirmed) scope.operation = null;
    await accept(scope);
  }, [accept, current]);
  const baseline = useCallback((activityId: string): SupplementBaseline | null => {
    const scope = scopeRef.current;
    return availability.current.available && scope && current(scope) && scope.view && scope.view.revision >= 1
      ? Object.freeze({ view: scope.view, activityId, targetKey: scope.targetKey }) : null;
  }, [current]);
  const visible = enabled && state.owner && ownerKey(state.owner) === scopeKey && state.targetKey === targetKey
    && isTokenOwnerStillCurrent(state.owner) && captureOwnerToken().generation === state.owner.generation;
  return { view: visible && profileAvailable ? state.view : null, acceptedView: visible && profileAvailable ? state.view : null,
    phase: visible ? !profileAvailable ? 'profile-unavailable' as ResumeSupplementPhase : state.phase : 'retired' as ResumeSupplementPhase, error: visible ? state.error : 'owner-changed',
    ownerScopeKey: scopeKey, operationLocked: !!visible && state.operationLocked, confirmedEntryId: visible && profileAvailable ? state.confirmedEntryId : null,
    acceptCurrent, baseline, confirm, retryRecorded };
}
