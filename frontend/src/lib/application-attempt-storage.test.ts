import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { prepareApplicationAttempt, readPendingApplicationAttempts, settleApplicationAttempt } from './application-attempt-storage';
import { advanceOwnerEpoch, captureOwnerToken, OwnerMismatchError, readUserScopedEntry, syncLocalIdentityOwner, writeUserScopedRaw } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
import type { ApplicationDraftInput, ApplicationEvent, ApplicationEventInput } from './application-ledger';
const A = 'application-owner-a', B = 'application-owner-b', O = 'opp-1';
const originalLocks = navigator.locks;
const key = STORAGE_KEYS.APPLICATION_ATTEMPT_PREFIX + O;
const draft = (): ApplicationDraftInput => ({ channel: 'web_form', destination: 'https://example.edu/apply', submittedAt: null,
  notes: 'Exact notes\n', resultNote: null, nextStep: null });
const receipt = (input: ApplicationEventInput): ApplicationEvent => ({ ...input, deviceId: A, opportunityId: O,
  confirmedAt: '2026-09-25T12:00:00.123456Z', confirmationSource: 'user_reported' });
async function owner(uid: string) { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
function installLocks() {
  let tail = Promise.resolve();
  const request = vi.fn((_name: string, _options: unknown, body: () => unknown) => {
    const run = tail.then(body); tail = run.then(() => undefined, () => undefined); return run;
  });
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request } });
  return request;
}
beforeEach(async () => { localStorage.clear(); await owner(A); vi.stubGlobal('crypto', webcrypto); installLocks(); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); Object.defineProperty(navigator, 'locks', { configurable: true, value: originalLocks }); });
async function prepare(value = draft()) {
  const result = await prepareApplicationAttempt(captureOwnerToken(), O, value);
  expect(result.status).toBe('ready'); if (result.status !== 'ready') throw new Error('unexpected conflict'); return result;
}
it('persists the frozen exact payload before returning a random attempt and recovers it on reread', async () => {
  const result = await prepare(); expect(result.reused).toBe(false); expect(Object.isFrozen(result.attempt.input)).toBe(true);
  expect(result.attempt.input.id).toMatch(/^[0-9a-f-]{14}4/);
  expect(readPendingApplicationAttempts(captureOwnerToken(), O)).toEqual([result.attempt]);
  expect(readUserScopedEntry(key).status).toBe('present');
});
it('serializes competing tabs and reuses the identical outstanding attempt', async () => {
  const [a, b] = await Promise.all([prepare(), prepare()]);
  expect(a.attempt.input.id).toBe(b.attempt.input.id); expect([a.reused, b.reused]).toEqual([false, true]);
});
it('never replaces a different pending snapshot', async () => {
  const first = await prepare();
  const next = await prepareApplicationAttempt(captureOwnerToken(), O, { ...draft(), notes: 'different' });
  expect(next).toEqual({ status: 'pending_exists', attempts: [first.attempt] });
  expect(readPendingApplicationAttempts(captureOwnerToken(), O)).toEqual([first.attempt]);
});
it('a real repeated submission with unspecified time gets a new UUID only after settlement', async () => {
  const first = await prepare(); expect(await settleApplicationAttempt(captureOwnerToken(), O, receipt(first.attempt.input))).toBe(true);
  expect(readPendingApplicationAttempts(captureOwnerToken(), O)).toEqual([]);
  const second = await prepare(); expect(second.attempt.input.id).not.toBe(first.attempt.input.id);
  expect(second.attempt.input.submittedAt).toBeNull();
  expect(await settleApplicationAttempt(captureOwnerToken(), O, receipt(first.attempt.input))).toBe(false);
  expect(readPendingApplicationAttempts(captureOwnerToken(), O)).toEqual([second.attempt]);
});
it('does not clear a pending attempt using altered content or a foreign receipt', async () => {
  const saved = await prepare(); const token = captureOwnerToken();
  for (const change of [{ notes: 'changed' }, { deviceId: B }, { opportunityId: 'other' }, { confirmationSource: 'provider' }, { confirmedAt: 'bad' }]) {
    await expect(settleApplicationAttempt(token, O, { ...receipt(saved.attempt.input), ...change } as ApplicationEvent)).rejects.toMatchObject({ code: 'receipt_mismatch' });
  }
  expect(readPendingApplicationAttempts(token, O)).toEqual([saved.attempt]);
});
it('treats corrupted/foreign persisted snapshots as errors rather than an empty slot', async () => {
  const token = captureOwnerToken();
  for (const raw of ['not json', '{}', JSON.stringify({ v: 1, ownerId: B, opportunityId: O, input: {} })]) {
    writeUserScopedRaw(key, raw, token);
    expect(() => readPendingApplicationAttempts(token, O)).toThrow();
    await expect(prepare()).rejects.toMatchObject({ code: 'invalid_pending' });
    expect(readUserScopedEntry(key)).toEqual({ status: 'present', value: raw });
  }
});
it('storage write exceptions and silent no-ops cannot produce ready attempts', async () => {
  const realSet = localStorage.setItem.bind(localStorage);
  const spy = vi.spyOn(localStorage, 'setItem').mockImplementation(function (this: Storage, name, value) {
    if (name.includes(STORAGE_KEYS.APPLICATION_ATTEMPT_PREFIX)) throw new Error('quota'); return realSet(name, value);
  });
  await expect(prepare()).rejects.toMatchObject({ code: 'unavailable' });
  spy.mockImplementation(function (this: Storage, name, value) { if (!name.includes(STORAGE_KEYS.APPLICATION_ATTEMPT_PREFIX)) realSet(name, value); });
  await expect(prepare()).rejects.toMatchObject({ code: 'unavailable' });
});
it('failed reads are not empty, and failed removal keeps the same retry ID', async () => {
  const saved = await prepare(); const realGet = localStorage.getItem.bind(localStorage);
  const get = vi.spyOn(localStorage, 'getItem').mockImplementation(function (this: Storage, name) {
    if (name.includes(STORAGE_KEYS.APPLICATION_ATTEMPT_PREFIX)) throw new Error('unreadable'); return realGet(name);
  });
  expect(() => readPendingApplicationAttempts(captureOwnerToken(), O)).toThrow();
  get.mockRestore(); vi.spyOn(localStorage, 'removeItem').mockImplementation(() => undefined);
  await expect(settleApplicationAttempt(captureOwnerToken(), O, receipt(saved.attempt.input))).rejects.toMatchObject({ code: 'unavailable' });
  expect(readPendingApplicationAttempts(captureOwnerToken(), O)).toEqual([saved.attempt]);
});
it('requires strong randomness and cross-tab serialization, with no weaker fallback', async () => {
  vi.stubGlobal('crypto', {}); await expect(prepare()).rejects.toMatchObject({ code: 'unavailable' });
  vi.stubGlobal('crypto', webcrypto); Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined });
  await expect(prepare()).rejects.toThrow();
  installLocks(); await syncLocalIdentityOwner(A);
  expect(readPendingApplicationAttempts(captureOwnerToken(), O)).toEqual([]);
});
it('copies draft/token before a lock wait and blocks a retired owner before writing', async () => {
  const gate = deferred<void>(); const request = vi.fn(async (_name, _options, body) => { await gate.promise; return body(); });
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request } });
  const value = draft(); const token = captureOwnerToken(); const saving = prepareApplicationAttempt(token, O, value);
  value.notes = 'mutated'; token.uid = B; gate.resolve();
  const saved = await saving; expect(saved.status).toBe('ready'); if (saved.status === 'ready') expect(saved.attempt.input.notes).toBe(draft().notes);
  const held = deferred<void>(); request.mockImplementation(async (name, _options, body) => { if (name.includes('ofe-application-attempt-v1')) await held.promise; return body(); });
  const pending = prepareApplicationAttempt(captureOwnerToken(), 'other', draft());
  const check = expect(pending).rejects.toBeInstanceOf(OwnerMismatchError); await owner(B); held.resolve(); await check;
  expect(readPendingApplicationAttempts(captureOwnerToken(), 'other')).toEqual([]);
});
describe.each(['owner', 'generation'] as const)('%s retirement', change => {
  it('does not expose the old pending snapshot or let a stale receipt remove new data', async () => {
    const saved = await prepare(); const before = captureOwnerToken();
    if (change === 'owner') await owner(B);
    else { const marker = JSON.parse(localStorage.getItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER)!);
      localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, JSON.stringify({ ...marker, generation: marker.generation + 1, phase: 'switching' })); await syncLocalIdentityOwner(A); }
    expect(() => readPendingApplicationAttempts(before, O)).toThrow(OwnerMismatchError);
    expect(readPendingApplicationAttempts(captureOwnerToken(), O)).toEqual([]);
    await expect(settleApplicationAttempt(before, O, receipt(saved.attempt.input))).rejects.toBeInstanceOf(OwnerMismatchError);
  });
});
