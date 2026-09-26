import { webcrypto } from 'node:crypto';
import { StrictMode } from 'react';
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useColdEmailDraftPersistence } from './use-cold-email-draft';
import { COLD_EMAIL_DRAFT_LIMITS, readColdEmailDraft, saveColdEmailDraft, type ColdEmailDraftPayload } from './cold-email-draft';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
const A = 'hook-owner-a', B = 'hook-owner-b';
let target = 0;
const originalLocks = navigator.locks;
function payload(body = 'Current exact text'): ColdEmailDraftPayload {
  return { subject: 'Subject', body, pendingEdit: '', selectedStyle: 'professional', context: { version: 1, purpose: 'first_contact' },
    sources: { profile_sig: null, target_version: null, contact_sig: null } };
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
function locks(gate?: Promise<void>) {
  let tail = Promise.resolve();
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: (_n: string, _o: unknown, fn: () => unknown) => {
    const run = tail.then(async () => { await gate; return fn(); }); tail = run.then(() => undefined, () => undefined); return run;
  } } });
}
async function drain() { await act(async () => { for (let i = 0; i < 20; i += 1) await Promise.resolve(); }); }
async function owner(id: string) { await act(async () => { advanceOwnerEpoch(id); await syncLocalIdentityOwner(id); }); }
function mount(id = `hook-target-${++target}`, strict = false) {
  const hook = renderHook(() => useColdEmailDraftPersistence(), strict ? { wrapper: StrictMode } : undefined);
  let opened!: ReturnType<typeof hook.result.current.open>;
  act(() => { opened = hook.result.current.open(id); });
  return { ...hook, id, opened };
}
async function persist(hook: ReturnType<typeof mount>, value = payload()) {
  act(() => hook.result.current.persist(value)); await drain();
}
async function flush(hook: ReturnType<typeof mount>) { let ok = false; await act(async () => { ok = await hook.result.current.flush(); }); return ok; }
async function retry(hook: ReturnType<typeof mount>) { let ok = false; await act(async () => { ok = await hook.result.current.retry(); }); return ok; }
function failWrites() {
  const real = localStorage.setItem.bind(localStorage);
  return vi.spyOn(localStorage, 'setItem').mockImplementation((key, value) => {
    if (key.includes(STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX)) throw new DOMException('full', 'QuotaExceededError'); real(key, value);
  });
}
beforeEach(async () => { locks(); localStorage.clear(); vi.stubGlobal('crypto', webcrypto); await owner(A); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); Object.defineProperty(navigator, 'locks', { configurable: true, value: originalLocks }); });

it('saves, flushes and restores an independent exact draft under StrictMode', async () => {
  const hook = mount(undefined, true); expect(hook.opened).toEqual({ draft: null, restored: false });
  await persist(hook); expect(await flush(hook)).toBe(true); expect(hook.result.current.status).toBe('saved');
  hook.unmount(); const next = mount(hook.id, true); expect(next.opened).toEqual({ draft: payload(), restored: true });
  next.opened.draft!.body = 'mutated return';
  act(() => next.result.current.detach());
  let reread!: ReturnType<typeof next.result.current.open>; act(() => { reread = next.result.current.open(hook.id); });
  expect(reread.draft).toEqual(payload());
});
it('keeps failed raw edits over SPA unmount and explicitly retries after quota recovers', async () => {
  const hook = mount(); const failure = failWrites(); await persist(hook, payload('unfinished typed text'));
  expect(hook.result.current.status).toBe('failed'); expect(await flush(hook)).toBe(false);
  hook.unmount(); failure.mockRestore(); const next = mount(hook.id);
  expect(next.opened.draft?.body).toBe('unfinished typed text'); expect(next.result.current.status).toBe('failed');
  expect(await retry(next)).toBe(true); expect(next.result.current.status).toBe('saved');
  expect(readColdEmailDraft(captureOwnerToken(), hook.id)).toMatchObject({ draft: { body: 'unfinished typed text' } });
});
it('retry uses the last successful revision rather than the initial missing revision', async () => {
  const hook = mount(); await persist(hook, payload('saved one')); const failure = failWrites();
  await persist(hook, payload('failed two')); failure.mockRestore();
  expect(await retry(hook)).toBe(true);
  expect(readColdEmailDraft(captureOwnerToken(), hook.id)).toMatchObject({ draft: { body: 'failed two' } });
});
it('retains newer edits while failed and retries their latest snapshot without automatic replay', async () => {
  const hook = mount(); const failure = failWrites(); await persist(hook, payload('failure'));
  failure.mockRestore(); await persist(hook, payload('latest answer'));
  expect(readColdEmailDraft(captureOwnerToken(), hook.id).status).toBe('missing'); expect(hook.result.current.status).toBe('failed');
  expect(await retry(hook)).toBe(true); expect(readColdEmailDraft(captureOwnerToken(), hook.id)).toMatchObject({ draft: { body: 'latest answer' } });
});
it('retry cannot overwrite another window that changed the originally observed revision', async () => {
  const hook = mount(); await persist(hook, payload('original')); const original = readColdEmailDraft(captureOwnerToken(), hook.id);
  const failure = failWrites(); await persist(hook, payload('local failed')); failure.mockRestore();
  await saveColdEmailDraft(captureOwnerToken(), hook.id, original.revision, payload('other window'));
  expect(await retry(hook)).toBe(false); expect(hook.result.current.status).toBe('conflict');
  await persist(hook, payload('local newer')); expect(await retry(hook)).toBe(false);
  expect(readColdEmailDraft(captureOwnerToken(), hook.id)).toMatchObject({ draft: { body: 'other window' } });
});
it('an unreadable initial slot cannot be overwritten after an unseen record becomes readable', async () => {
  const id = `unseen-${++target}`; await saveColdEmailDraft(captureOwnerToken(), id, null, payload('unseen existing draft'));
  const real = localStorage.getItem.bind(localStorage);
  const failure = vi.spyOn(localStorage, 'getItem').mockImplementation(key => { if (key.includes(STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX)) throw new Error('denied'); return real(key); });
  const hook = mount(id); expect(hook.result.current.status).toBe('failed'); await persist(hook, payload('typed while unreadable'));
  failure.mockRestore(); expect(await retry(hook)).toBe(false); expect(hook.result.current.status).toBe('conflict');
  expect(await retry(hook)).toBe(false); expect(readColdEmailDraft(captureOwnerToken(), id)).toMatchObject({ draft: { body: 'unseen existing draft' } });
});
it('a failed initial read can retry when a fresh authoritative read proves the slot empty', async () => {
  const real = localStorage.getItem.bind(localStorage);
  const failure = vi.spyOn(localStorage, 'getItem').mockImplementation(key => { if (key.includes(STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX)) throw new Error('denied'); return real(key); });
  const hook = mount(); await persist(hook); failure.mockRestore();
  expect(await retry(hook)).toBe(true); expect(hook.result.current.status).toBe('saved');
});
it('over-limit text stays exact in memory; compliant edits require explicit retry', async () => {
  const hook = mount(); const large = payload('x'.repeat(COLD_EMAIL_DRAFT_LIMITS.body + 1)); await persist(hook, large);
  expect(hook.result.current.issue).toBe('too_large'); hook.unmount(); const next = mount(hook.id);
  expect(next.opened.draft).toEqual(large); await persist(next, payload('now within limit'));
  expect(next.result.current.status).toBe('failed'); expect(await retry(next)).toBe(true);
});
it('an unrepresentable panel snapshot blocks retries and cannot be marked saved by an older completion', async () => {
  const gate = deferred<void>(); locks(gate.promise); const hook = mount();
  act(() => hook.result.current.persist(payload('older savable text')));
  act(() => hook.result.current.markUnsaved('too_large'));
  await act(async () => { gate.resolve(); }); await drain();
  expect(hook.result.current.status).toBe('failed'); expect(await flush(hook)).toBe(false); expect(hook.result.current.status).toBe('failed');
  expect(await retry(hook)).toBe(false);
  // A new valid snapshot may even equal the previous backup after the user
  // removes the oversized answer. The blocked marker must still be cleared.
  await persist(hook, payload('older savable text')); expect(await retry(hook)).toBe(true);
});
it('flush fails if a newer edit was queued while it waited, while preserving that newer save', async () => {
  const gate = deferred<void>(); locks(gate.promise); const hook = mount();
  act(() => hook.result.current.persist(payload('first')));
  let pending!: Promise<boolean>; act(() => { pending = hook.result.current.flush(); });
  act(() => hook.result.current.persist(payload('newer')));
  let ok = true; await act(async () => { gate.resolve(); ok = await pending; }); await drain();
  expect(ok).toBe(false); expect(await flush(hook)).toBe(true);
  expect(readColdEmailDraft(captureOwnerToken(), hook.id)).toMatchObject({ draft: { body: 'newer' } });
});
it('abandon prevents a late failed write from resurrecting unfinished text', async () => {
  const gate = deferred<void>(); locks(gate.promise); const hook = mount(); const failure = failWrites();
  act(() => hook.result.current.persist(payload('abandoned')));
  act(() => hook.result.current.abandon()); await act(async () => { gate.resolve(); }); await drain();
  failure.mockRestore(); const next = mount(hook.id); expect(next.opened).toEqual({ draft: null, restored: false });
  expect(next.result.current.status).toBe('idle');
});
it('retired late callbacks cannot remove or replace a new session with the same owner and target', async () => {
  const gate = deferred<void>(); locks(gate.promise); const hook = mount(); const failure = failWrites();
  act(() => hook.result.current.persist(payload('abandoned old session'))); act(() => hook.result.current.abandon());
  act(() => { hook.result.current.open(hook.id); hook.result.current.persist(payload('new session')); });
  await act(async () => { gate.resolve(); }); await drain();
  failure.mockRestore(); hook.unmount(); const next = mount(hook.id);
  expect(next.opened.draft?.body).toBe('new session'); expect(await retry(next)).toBe(true);
});
it('owner switch and logout block pending callbacks from populating another owner session', async () => {
  const gate = deferred<void>(); locks(gate.promise); const hook = mount();
  act(() => hook.result.current.persist(payload('private A'))); act(() => advanceOwnerEpoch(null));
  await act(async () => { gate.resolve(); }); await drain(); await owner(B);
  let opened!: ReturnType<typeof hook.result.current.open>; act(() => { opened = hook.result.current.open(hook.id); });
  expect(opened).toEqual({ draft: null, restored: false }); await persist(hook, payload('private B'));
  expect(readColdEmailDraft(captureOwnerToken(), hook.id)).toMatchObject({ draft: { body: 'private B' } });
});
it('clear removes the old payload and starts subsequent explicit edits from the tombstone revision', async () => {
  const hook = mount(); await persist(hook); let cleared = false;
  await act(async () => { cleared = await hook.result.current.clear(); }); expect(cleared).toBe(true); expect(hook.result.current.status).toBe('idle');
  expect(readColdEmailDraft(captureOwnerToken(), hook.id).status).toBe('missing');
  hook.unmount(); const next = mount(hook.id); expect(next.opened).toEqual({ draft: null, restored: false });
  await persist(next, payload('explicit new draft')); expect(await flush(next)).toBe(true);
});
it('clear never resets a newly opened target when its old deletion finishes', async () => {
  const hook = mount(); await persist(hook, payload('A target')); const gate = deferred<void>(); locks(gate.promise);
  let deletion!: Promise<boolean>; act(() => { deletion = hook.result.current.clear(); }); await drain();
  act(() => { hook.result.current.open('new-target-after-delete'); hook.result.current.persist(payload('B target')); });
  let cleared = true; await act(async () => { gate.resolve(); cleared = await deletion; }); await drain();
  expect(cleared).toBe(false); expect(hook.result.current.status).toBe('saved');
  expect(readColdEmailDraft(captureOwnerToken(), 'new-target-after-delete')).toMatchObject({ draft: { body: 'B target' } });
});
it('clear racing a new edit before its flush completes does not delete that edit', async () => {
  const gate = deferred<void>(); locks(gate.promise); const hook = mount(); act(() => hook.result.current.persist(payload('old')));
  let pending!: Promise<boolean>; act(() => { pending = hook.result.current.clear(); hook.result.current.persist(payload('new input')); });
  let ok = true; await act(async () => { gate.resolve(); ok = await pending; }); await drain();
  expect(ok).toBe(false); expect(readColdEmailDraft(captureOwnerToken(), hook.id)).toMatchObject({ draft: { body: 'new input' } });
});
it('keeps edits made during an already-started delete and requires retry from the tombstone', async () => {
  const hook = mount(); await persist(hook); const gate = deferred<void>(); locks(gate.promise);
  let deletion!: Promise<boolean>; act(() => { deletion = hook.result.current.clear(); }); await drain();
  act(() => hook.result.current.persist(payload('typed during deletion')));
  let cleared = true; await act(async () => { gate.resolve(); cleared = await deletion; }); await drain();
  expect(cleared).toBe(false); expect(hook.result.current.issue).toBe('draft_changed');
  expect(readColdEmailDraft(captureOwnerToken(), hook.id).status).toBe('missing');
  expect(await retry(hook)).toBe(true); expect(readColdEmailDraft(captureOwnerToken(), hook.id)).toMatchObject({ draft: { body: 'typed during deletion' } });
});
it('clear conflicts leave both the other window record and this editor text intact', async () => {
  const hook = mount(); await persist(hook); const base = readColdEmailDraft(captureOwnerToken(), hook.id);
  await saveColdEmailDraft(captureOwnerToken(), hook.id, base.revision, payload('other window record'));
  let cleared = true; await act(async () => { cleared = await hook.result.current.clear(); });
  expect(cleared).toBe(false); expect(hook.result.current.status).toBe('conflict');
  hook.unmount(); const next = mount(hook.id); expect(next.opened.draft).toEqual(payload());
  expect(readColdEmailDraft(captureOwnerToken(), hook.id)).toMatchObject({ draft: { body: 'other window record' } });
});
it('a late delete also clears its old target recovery cache without resetting the new target', async () => {
  const hook = mount(); await persist(hook); const gate = deferred<void>(); locks(gate.promise);
  let deletion!: Promise<boolean>; act(() => { deletion = hook.result.current.clear(); }); await drain();
  act(() => { hook.result.current.open(`other-${hook.id}`); });
  await act(async () => { gate.resolve(); await deletion; });
  let reopened!: ReturnType<typeof hook.result.current.open>; act(() => { reopened = hook.result.current.open(hook.id); });
  expect(reopened).toEqual({ draft: null, restored: false });
});
it('a completed clear retires the old editing session so a late persist cannot resurrect its payload', async () => {
  const hook = mount(); await persist(hook); await act(async () => { expect(await hook.result.current.clear()).toBe(true); });
  await persist(hook); expect(readColdEmailDraft(captureOwnerToken(), hook.id).status).toBe('missing');
  act(() => { hook.result.current.open(hook.id); }); await persist(hook, payload('new deliberate editor'));
  expect(await flush(hook)).toBe(true);
});
