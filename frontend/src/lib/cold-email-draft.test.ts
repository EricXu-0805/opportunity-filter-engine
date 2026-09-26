import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { COLD_EMAIL_DRAFT_LIMITS, COLD_EMAIL_DRAFT_LOCK_TIMEOUT_MS, createColdEmailDraftWriter,
  deleteColdEmailDraft, readColdEmailDraft, saveColdEmailDraft, snapshotColdEmailDraft,
  type ColdEmailDraftPayload } from './cold-email-draft';
import { advanceOwnerEpoch, captureOwnerToken, enterLocalOnlyMode, PRIVATE_STORAGE_LOCK,
  readUserScopedEntry, syncLocalIdentityOwner, USER_SCOPED_PREFIXES, writeUserScopedRaw } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
const A = 'draft-owner-a', B = 'draft-owner-b', O = 'opportunity/α:1';
const originalLocks = navigator.locks;
function payload(body = '  Exact original text.\n第二行😀  '): ColdEmailDraftPayload {
  return { subject: ' Subject ', body, manualRecipient: ' unfinished@ ', selectedStyle: 'professional', pendingEdit: '\nMake it warmer ',
    context: { version: 1, purpose: 'first_contact' }, sources: { profile_sig: null, target_version: null, contact_sig: null } };
}
const key = (uid: string | null = A, id = O) => STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX + encodeURIComponent(JSON.stringify([uid, id]));
async function owner(uid: string) { advanceOwnerEpoch(uid); expect(await syncLocalIdentityOwner(uid)).toBe(true); }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
function installLocks() {
  let tail = Promise.resolve();
  const request = vi.fn((_name: string, _options: unknown, body: () => unknown) => {
    const run = tail.then(body); tail = run.then(() => undefined, () => undefined); return run;
  });
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request } }); return request;
}
async function save(value = payload(), expected: string | null = null) {
  const result = await saveColdEmailDraft(captureOwnerToken(), O, expected, value);
  expect(result.status).toBe('saved'); if (result.status !== 'saved') throw new Error('save failed'); return result;
}
beforeEach(async () => { installLocks(); localStorage.clear(); await owner(A); vi.stubGlobal('crypto', webcrypto); });
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); Object.defineProperty(navigator, 'locks', { configurable: true, value: originalLocks }); });

it('registers private storage and returns only a verified empty slot as missing', () => {
  expect(USER_SCOPED_PREFIXES).toContain(STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX);
  expect(readColdEmailDraft(captureOwnerToken(), O)).toEqual({ status: 'missing', revision: null });
});
it('round-trips exact whitespace, Unicode, manual text and opaque source binding', async () => {
  const value = payload(); value.sources = { profile_sig: 'a'.repeat(64), target_version: 'wt1:target', contact_sig: 'b'.repeat(64) };
  value.context.availability = { text: '  5 hours\nweekly  ', confirmed: true };
  const saved = await save(value);
  expect(readColdEmailDraft(captureOwnerToken(), O)).toEqual({ status: 'present', revision: saved.revision, draft: value });
  expect(saved.revision).toMatch(/^[0-9a-f-]{36}$/);
  const read = readColdEmailDraft(captureOwnerToken(), O);
  if (read.status === 'present') read.draft.body = 'changed in memory';
  expect(readColdEmailDraft(captureOwnerToken(), O)).toMatchObject({ draft: value });
  expect(readColdEmailDraft(captureOwnerToken(), 'other')).toEqual({ status: 'missing', revision: null });
});
it('captures caller payload and owner before a held lock', async () => {
  const gate = deferred<void>();
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_n: string, _o: unknown, fn: () => unknown) => { await gate.promise; return fn(); } } });
  const token = captureOwnerToken(); const value = payload(); const pending = saveColdEmailDraft(token, O, null, value);
  value.body = 'mutated'; value.sources.target_version = 'new target'; token.uid = B; gate.resolve();
  expect((await pending).status).toBe('saved');
  expect(readColdEmailDraft(captureOwnerToken(), O)).toMatchObject({ draft: payload() });
});
it('uses the same lock as identity transitions and allows just one same-revision writer', async () => {
  const locks = installLocks(); const token = captureOwnerToken();
  const [a, b] = await Promise.all([saveColdEmailDraft(token, O, null, payload('A')), saveColdEmailDraft(token, O, null, payload('B'))]);
  expect(a.status).toBe('saved'); expect(b.status).toBe('conflict');
  expect(locks).toHaveBeenCalledWith(PRIVATE_STORAGE_LOCK, expect.objectContaining({ mode: 'exclusive' }), expect.any(Function));
  expect(readColdEmailDraft(token, O)).toMatchObject({ draft: { body: 'A' } });
});
it('tombstones prevent old writes and old deletes from resurrecting or erasing a newer draft', async () => {
  const token = captureOwnerToken(); const first = await save();
  const deleted = await deleteColdEmailDraft(token, O, first.revision);
  expect(deleted.status).toBe('deleted'); if (deleted.status !== 'deleted') throw new Error();
  expect(readColdEmailDraft(token, O)).toEqual({ status: 'missing', revision: deleted.revision });
  expect(readUserScopedEntry(key()).status).toBe('present');
  for (const revision of [null, first.revision]) expect((await saveColdEmailDraft(token, O, revision, payload('stale'))).status).toBe('conflict');
  const current = await save(payload('deliberate new draft'), deleted.revision);
  expect((await deleteColdEmailDraft(token, O, first.revision)).status).toBe('conflict');
  expect(readColdEmailDraft(token, O)).toMatchObject({ revision: current.revision, draft: { body: 'deliberate new draft' } });
});
it('deleting a never-saved slot still leaves a barrier for a late first save', async () => {
  const token = captureOwnerToken(); expect((await deleteColdEmailDraft(token, O, null)).status).toBe('deleted');
  expect((await saveColdEmailDraft(token, O, null, payload())).status).toBe('conflict');
});
it('serializes each immediate writer edit and flush includes edits queued during a wait', async () => {
  const gate = deferred<void>();
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_n: string, _o: unknown, fn: () => unknown) => { await gate.promise; return fn(); } } });
  const writer = createColdEmailDraftWriter(captureOwnerToken(), O, null);
  const a = writer.save(payload('first')); const flush = writer.flush(); const b = writer.save(payload('last character!'));
  expect(writer.hasPending()).toBe(true); gate.resolve();
  expect((await a).status).toBe('saved'); expect((await b).status).toBe('saved'); expect((await flush)?.status).toBe('saved');
  expect(writer.hasPending()).toBe(false); expect(readColdEmailDraft(captureOwnerToken(), O)).toMatchObject({ draft: { body: 'last character!' } });
});
it('a writer permanently stops after conflict rather than silently rebasing later edits', async () => {
  const writer = createColdEmailDraftWriter(captureOwnerToken(), O, null); await save(payload('another tab'));
  const first = await writer.save(payload('old tab')); const second = await writer.save(payload('old tab later'));
  expect(first.status).toBe('conflict'); expect(second).toEqual(first); expect(await writer.flush()).toEqual(first);
  expect(readColdEmailDraft(captureOwnerToken(), O)).toMatchObject({ draft: { body: 'another tab' } });
});
it('a completed writer deletion cannot be undone by its late save callback', async () => {
  const writer = createColdEmailDraftWriter(captureOwnerToken(), O, null); await writer.save(payload());
  expect((await writer.delete()).status).toBe('deleted');
  await expect(writer.save(payload('late'))).rejects.toMatchObject({ code: 'writer_closed' });
  expect(readColdEmailDraft(captureOwnerToken(), O).status).toBe('missing');
});
it('failed list reads never become missing and never authorize an overwrite', async () => {
  const saved = await save(); const original = localStorage.getItem.bind(localStorage);
  vi.spyOn(localStorage, 'getItem').mockImplementation(name => { if (name.includes(STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX)) throw new Error('private denied'); return original(name); });
  expect(() => readColdEmailDraft(captureOwnerToken(), O)).toThrow(expect.objectContaining({ code: 'storage_unavailable' }));
  await expect(saveColdEmailDraft(captureOwnerToken(), O, saved.revision, payload('replace'))).rejects.toMatchObject({ code: 'storage_unavailable' });
});
it.each(['throw', 'noop'] as const)('reports %s writes and keeps the earlier durable draft', async mode => {
  const first = await save(payload('backup')); const original = localStorage.setItem.bind(localStorage);
  vi.spyOn(localStorage, 'setItem').mockImplementation((name, value) => {
    if (!name.includes(STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX)) return original(name, value);
    if (mode === 'throw') throw new DOMException('quota', 'QuotaExceededError');
  });
  const writer = createColdEmailDraftWriter(captureOwnerToken(), O, first.revision);
  await expect(writer.save(payload('unsaved'))).rejects.toMatchObject({ code: 'storage_unavailable' });
  await expect(writer.flush()).rejects.toMatchObject({ code: 'storage_unavailable' });
  await expect(writer.save(payload('later'))).rejects.toMatchObject({ code: 'storage_unavailable' });
  expect(writer.hasPending()).toBe(false); expect(readColdEmailDraft(captureOwnerToken(), O)).toMatchObject({ draft: { body: 'backup' } });
});
it('a failed tombstone write does not claim deletion', async () => {
  const first = await save(); vi.spyOn(localStorage, 'setItem').mockImplementation(() => { throw new Error('quota'); });
  await expect(deleteColdEmailDraft(captureOwnerToken(), O, first.revision)).rejects.toMatchObject({ code: 'storage_unavailable' });
  expect(readColdEmailDraft(captureOwnerToken(), O).status).toBe('present');
});
it('rejects corrupt, foreign, too-large and send-state envelopes instead of replacing them', async () => {
  const token = captureOwnerToken(); const first = await save(); const entry = readUserScopedEntry(key());
  if (entry.status !== 'present') throw new Error(); const valid = JSON.parse(entry.value);
  for (const raw of ['{bad', '{}', JSON.stringify({ ...valid, ownerId: B }), JSON.stringify({ ...valid, opportunityId: 'other' }),
    JSON.stringify({ ...valid, confirmedSent: true }), 'x'.repeat(COLD_EMAIL_DRAFT_LIMITS.total + 1)]) {
    expect(writeUserScopedRaw(key(), raw, token)).toBe(true);
    expect(() => readColdEmailDraft(token, O)).toThrow();
    await expect(saveColdEmailDraft(token, O, first.revision, payload())).rejects.toThrow();
    expect(readUserScopedEntry(key())).toEqual({ status: 'present', value: raw });
  }
});
it.each(['sent', 'contacted', 'verifiedRecipient', 'recipientStatus', 'fullProfile', 'resumeText'])('rejects unexpected %s payload state', key => {
  expect(() => snapshotColdEmailDraft({ ...payload(), [key]: true })).toThrow(expect.objectContaining({ code: 'invalid_draft' }));
});
it('rejects oversized text without truncation or replacing the earlier value', async () => {
  const saved = await save(); const tooLong = payload('x'.repeat(COLD_EMAIL_DRAFT_LIMITS.body + 1));
  await expect(saveColdEmailDraft(captureOwnerToken(), O, saved.revision, tooLong)).rejects.toMatchObject({ code: 'too_large' });
  expect(readColdEmailDraft(captureOwnerToken(), O)).toMatchObject({ draft: payload() });
  expect(snapshotColdEmailDraft(payload('x'.repeat(COLD_EMAIL_DRAFT_LIMITS.body))).body).toHaveLength(COLD_EMAIL_DRAFT_LIMITS.body);
});
it('rejects lossy non-JSON input and malformed binding instead of coercing it', () => {
  const cycle: Record<string, unknown> = {}; cycle.self = cycle;
  const getter = { ...payload() }; Object.defineProperty(getter, 'body', { enumerable: true, get: () => 'not a snapshot' });
  for (const value of [{ ...payload(), body: undefined }, { ...payload(), body: '\ud800' }, { ...payload(), context: cycle },
    { ...payload(), [Symbol('hidden')]: 1 }, { ...payload(), context: new Date() }, getter,
    { ...payload(), sources: { profile_sig: 'raw resume', target_version: null, contact_sig: null } },
    { ...payload(), context: { version: 1, purpose: 'referral' } }]) expect(() => snapshotColdEmailDraft(value)).toThrow();
});
it('bounds lock wait and prevents a callback from writing after timeout even if the lock ignores abort', async () => {
  vi.useFakeTimers(); const gate = deferred<void>();
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_n: string, _o: unknown, fn: () => unknown) => { await gate.promise; return fn(); } } });
  const pending = saveColdEmailDraft(captureOwnerToken(), O, null, payload());
  const checked = expect(pending).rejects.toMatchObject({ code: 'lock_timeout' });
  await vi.advanceTimersByTimeAsync(COLD_EMAIL_DRAFT_LOCK_TIMEOUT_MS); await checked; gate.resolve(); await Promise.resolve(); await Promise.resolve();
  expect(readColdEmailDraft(captureOwnerToken(), O)).toEqual({ status: 'missing', revision: null });
});
it('requires Web Locks and strong random revision IDs', async () => {
  vi.stubGlobal('crypto', {}); await expect(save()).rejects.toMatchObject({ code: 'storage_unavailable' });
  vi.stubGlobal('crypto', webcrypto); Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined });
  await expect(save()).rejects.toMatchObject({ code: 'storage_unavailable' });
});
it('drops queued writes after logout before their lock arrives', async () => {
  const gate = deferred<void>();
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_n: string, _o: unknown, fn: () => unknown) => { await gate.promise; return fn(); } } });
  const pending = saveColdEmailDraft(captureOwnerToken(), O, null, payload());
  const checked = expect(pending).rejects.toMatchObject({ code: 'owner_changed' }); advanceOwnerEpoch(null); gate.resolve(); await checked;
  expect(localStorage.getItem(key())).toBeNull();
});
describe.each(['switch', 'roundtrip', 'claim'] as const)('%s owner isolation', kind => {
  it('does not expose or overwrite the old account draft', async () => {
    const token = captureOwnerToken(); const first = await save();
    if (kind === 'claim') { advanceOwnerEpoch(B); expect(await syncLocalIdentityOwner(B, { claim: true })).toBe(true); }
    else { await owner(B); if (kind === 'roundtrip') await owner(A); }
    expect(readColdEmailDraft(captureOwnerToken(), O)).toEqual({ status: 'missing', revision: null });
    expect(() => readColdEmailDraft(token, O)).toThrow();
    await expect(saveColdEmailDraft(token, O, first.revision, payload('late old owner'))).rejects.toThrow();
  });
});
it('does not migrate a local-only draft into the first authenticated/anonymous account', async () => {
  advanceOwnerEpoch(null); localStorage.clear(); expect(enterLocalOnlyMode()).toBe(true);
  const token = captureOwnerToken(); expect((await saveColdEmailDraft(token, O, null, payload('local only'))).status).toBe('saved');
  await owner(B); expect(readColdEmailDraft(captureOwnerToken(), O)).toEqual({ status: 'missing', revision: null });
  await expect(saveColdEmailDraft(token, O, null, payload('late'))).rejects.toThrow();
});
it('independent same-owner module realms share revisions and reject stale delete/save without auth callbacks', async () => {
  vi.resetModules(); const firstIdentity = await import('./identity-owner'); const firstStore = await import('./cold-email-draft');
  firstIdentity.advanceOwnerEpoch(A); await firstIdentity.syncLocalIdentityOwner(A); const firstToken = firstIdentity.captureOwnerToken();
  const saved = await firstStore.saveColdEmailDraft(firstToken, O, null, payload('tab one')); if (saved.status !== 'saved') throw new Error();
  vi.resetModules(); const secondIdentity = await import('./identity-owner'); const secondStore = await import('./cold-email-draft');
  secondIdentity.advanceOwnerEpoch(A); await secondIdentity.syncLocalIdentityOwner(A); const secondToken = secondIdentity.captureOwnerToken();
  expect(secondStore.readColdEmailDraft(secondToken, O)).toMatchObject({ revision: saved.revision });
  const deleted = await secondStore.deleteColdEmailDraft(secondToken, O, saved.revision); expect(deleted.status).toBe('deleted');
  expect((await firstStore.saveColdEmailDraft(firstToken, O, saved.revision, payload('late tab one'))).status).toBe('conflict');
  expect((await firstStore.deleteColdEmailDraft(firstToken, O, saved.revision)).status).toBe('conflict');
});
it('late save after a requested delete cannot cancel that already authorized deletion', async () => {
  const first = await save(); const gate = deferred<void>();
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_n: string, _o: unknown, fn: () => unknown) => { await gate.promise; return fn(); } } });
  const writer = createColdEmailDraftWriter(captureOwnerToken(), O, first.revision);
  const deletion = writer.delete();
  await expect(writer.save(payload('late event'))).rejects.toMatchObject({ code: 'writer_closed' });
  gate.resolve(); expect((await deletion).status).toBe('deleted');
  expect((await writer.flush())?.status).toBe('deleted');
});
it('preserves pending incomplete panel answers independently from applied context', async () => {
  const value = payload(); value.pendingPanel = { version: 1, opportunityId: O, paperSourceKey: 'target-scoped-papers',
    fields: { purpose: 'referral', referrerName: '  pending name ', referralNote: '\nunfinished', previousMessage: '',
      sentOn: 'unfinished date', replyStatus: 'unknown', replyText: '', availability: '  perhaps ', paperKey: '', readingLevel: '' },
    confirmed: { referral: false, sent: false, availability: false, paper: false }, pending: true, expanded: true };
  const saved = await save(value); expect(readColdEmailDraft(captureOwnerToken(), O)).toEqual({ status: 'present', revision: saved.revision, draft: value });
  await expect(saveColdEmailDraft(captureOwnerToken(), O, saved.revision, { ...value,
    pendingPanel: { ...value.pendingPanel, opportunityId: 'other' } })).rejects.toMatchObject({ code: 'invalid_draft' });
  expect(readColdEmailDraft(captureOwnerToken(), O)).toMatchObject({ draft: value });
});
it('rejects invalid or over-limit panel snapshots while retaining their prior backup', async () => {
  const saved = await save(); const value = payload();
  value.pendingPanel = { version: 1, opportunityId: O, paperSourceKey: '', fields: { purpose: 'first_contact', referrerName: '',
    referralNote: '', previousMessage: 'x'.repeat(65536), sentOn: '', replyStatus: 'unknown', replyText: '', availability: '', paperKey: '', readingLevel: '' },
    confirmed: { referral: false, sent: false, availability: false, paper: false }, pending: true, expanded: true };
  await expect(saveColdEmailDraft(captureOwnerToken(), O, saved.revision, value)).rejects.toMatchObject({ code: 'invalid_draft' });
  expect(readColdEmailDraft(captureOwnerToken(), O)).toMatchObject({ draft: payload() });
});
