import actualResolved from './__fixtures__/private-resolved-target-api.json';
import actualApi from './__fixtures__/private-import-target-api.json';
import { createHash } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('./supabase', () => ({ getAuthState: vi.fn() }));
import { getAuthState } from './supabase';
import { advanceOwnerEpoch, captureOwnerToken, OwnerMismatchError } from './identity-owner';
import { OWNER, OTHER, setupOwner, deferred, owner as setOwner } from './application-material.test-utils';
import { deletePrivateImportTarget, getPrivateImportTarget, getResolvedPrivateImportTarget, listPrivateImportTargets, resolvePrivateImportTrackerTargets, savePrivateImportTarget, PRIVATE_TARGET_TIMEOUT_MS } from './private-import-target-api';
import type { ImportedOpportunity } from './api';
const id = 'private-import:cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const auth = vi.mocked(getAuthState); const fetchMock = vi.fn<typeof fetch>();
const state = (uid = OWNER, isAnonymous = false) => ({ user: { id: uid }, session: { user: { id: uid }, access_token: 'test-only-token' }, isAnonymous, email: null }) as Awaited<ReturnType<typeof getAuthState>>;
const opp = (): ImportedOpportunity => ({ source: 'text_parser', source_url: '', url: '', title: 'Research 中文', description_raw: 'Start\n' + 'Long original content. '.repeat(230) + '\nGPA < 3.0; scores > 80. END', extra_fields: { description_source: 'pasted_text', ai_input_scope: 'source_excerpt', llm_enriched: true, suggested_skills: ['SQL'] } });
const stamp = '2026-09-28T23:00:00.000001Z';
function target(revision = 1, opportunity: ImportedOpportunity | null = opp(), changes: Record<string, unknown> = {}) {
  const key = { id, owner_id: OWNER, revision };
  return { ...key, opportunity, import_source: opportunity ? { version: 1, description_source: 'pasted_text', ai_input_scope: 'source_excerpt', llm_enriched: true } : null,
    created_at: stamp, updated_at: stamp, deleted_at: opportunity ? null : stamp, target_scope: 'private_import', verification: 'unverified',
    target_version: 'pit1:' + createHash('sha256').update(JSON.stringify(key)).digest('hex'), ...changes };
}
const json = (data: unknown, status = 200, headers = {}) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', ...headers } });
const one = (value = target(), replayed = false) => json({ version: 1, target: value, replayed });
const options = () => ({ owner: captureOwnerToken() });
beforeEach(async () => { await setupOwner(); auth.mockReset().mockResolvedValue(state()); fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });
it('roundtrips full source and explicit unverified scope with owner, CAS, no-store, and no redirect', async () => {
  const input = opp(); fetchMock.mockResolvedValue(one());
  expect((await savePrivateImportTarget(id, input, 0, options())).target.opportunity).toEqual(input);
  const [url, init] = fetchMock.mock.calls[0]; expect(String(url)).toContain(encodeURIComponent(id));
  expect(init).toMatchObject({ method: 'PUT', cache: 'no-store', redirect: 'error' });
  expect(JSON.parse(init!.body as string)).toEqual({ expected_owner_id: OWNER, expected_revision: 0, opportunity: input });
  expect(new Headers(init!.headers).get('Authorization')).toBe('Bearer test-only-token');
});
it('keeps the original intent snapshot while auth waits and allows exact replay receipt', async () => {
  const gate = deferred<Awaited<ReturnType<typeof getAuthState>>>(); auth.mockReturnValue(gate.promise);
  const input = opp(); const original = structuredClone(input); const opts = options();
  const pending = savePrivateImportTarget(id, input, 1, opts); input.description_raw = 'different'; opts.owner.uid = OTHER;
  fetchMock.mockResolvedValue(one(target(2, original), true)); gate.resolve(state());
  expect((await pending).replayed).toBe(true); expect(JSON.parse(fetchMock.mock.calls[0][1]!.body as string).opportunity).toEqual(original);
});
it('requires current nonanonymous owner before HTTP and rejects a different session owner', async () => {
  for (const value of [state(OWNER, true), { ...state(), session: null }]) {
    auth.mockResolvedValueOnce(value); await expect(getPrivateImportTarget(id, options())).rejects.toMatchObject({ code: 'sign_in_required' });
  }
  auth.mockResolvedValueOnce(state(OTHER)); await expect(getPrivateImportTarget(id, options())).rejects.toBeInstanceOf(OwnerMismatchError);
  expect(fetchMock).not.toHaveBeenCalled();
});
it('retires pending authentication on account change without dispatching later', async () => {
  const gate = deferred<Awaited<ReturnType<typeof getAuthState>>>(); auth.mockReturnValue(gate.promise);
  const pending = getPrivateImportTarget(id, options()); const check = expect(pending).rejects.toBeInstanceOf(OwnerMismatchError);
  advanceOwnerEpoch(OTHER); await check; gate.resolve(state()); await Promise.resolve(); expect(fetchMock).not.toHaveBeenCalled();
});
it('rejects a response arriving for an abandoned owner', async () => {
  const gate = deferred<Response>(); fetchMock.mockReturnValue(gate.promise);
  const pending = getPrivateImportTarget(id, options()); const check = expect(pending).rejects.toBeInstanceOf(OwnerMismatchError);
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce()); advanceOwnerEpoch(OTHER); await check; gate.resolve(one());
});
it('returns null only for the recognized 404 and preserves deletion tombstone', async () => {
  fetchMock.mockResolvedValueOnce(json({ detail: { code: 'private_target_not_found' } }, 404)); expect(await getPrivateImportTarget(id, options())).toBeNull();
  fetchMock.mockResolvedValueOnce(one(target(2, null))); expect((await getPrivateImportTarget(id, options()))?.target.deleted_at).toBe(stamp);
  fetchMock.mockResolvedValueOnce(json({ detail: { code: 'private_target_not_found' } }, 500)); await expect(getPrivateImportTarget(id, options())).rejects.toMatchObject({ code: 'unavailable' });
});
it('refuses wrong owner/id/version, public scope, fabricated authority, and stale mutation receipts', async () => {
  for (const change of [{ owner_id: OTHER }, { id: 'public-id' }, { target_scope: 'public' }, { verification: 'verified' }, { target_version: 'pit1:' + '0'.repeat(64) }, { revision: 4 }]) {
    fetchMock.mockResolvedValueOnce(one(target(1, opp(), change))); await expect(getPrivateImportTarget(id, options())).rejects.toMatchObject({ code: 'invalid_receipt' });
  }
  fetchMock.mockResolvedValueOnce(one(target(2))); await expect(savePrivateImportTarget(id, opp(), 0, options())).rejects.toMatchObject({ code: 'invalid_receipt' });
  fetchMock.mockResolvedValueOnce(one(target(1, { ...opp(), description_raw: 'changed upstream' }))); await expect(savePrivateImportTarget(id, opp(), 0, options())).rejects.toMatchObject({ code: 'invalid_receipt' });
});
it('accepts only exact versioned deletion without recreating or retrying', async () => {
  fetchMock.mockResolvedValueOnce(one(target(2, null))); expect((await deletePrivateImportTarget(id, 1, options())).target.opportunity).toBeNull();
  expect(JSON.parse(fetchMock.mock.calls[0][1]!.body as string)).toEqual({ expected_owner_id: OWNER, expected_revision: 1 });
  fetchMock.mockRejectedValueOnce(new Error('private transport details')); await expect(deletePrivateImportTarget(id, 1, options())).rejects.toMatchObject({ code: 'unavailable' }); expect(fetchMock).toHaveBeenCalledTimes(2);
});
function summary() { const value = target(); const { opportunity: unused, import_source: unusedScope, ...rest } = value; void unused; void unusedScope;
  return { ...rest, title: 'Research 中文', organization: null, source_url: '', url: '', source: 'text_parser' }; }
it('lists bounded summaries only, with exact cursor and no source text', async () => {
  const value = summary(); const cursor = { updated_at: stamp, id };
  fetchMock.mockResolvedValueOnce(json({ version: 1, items: [value], next_cursor: cursor }));
  expect((await listPrivateImportTargets({ ...options(), limit: 1 })).items).toEqual([value]);
  fetchMock.mockResolvedValueOnce(json({ version: 1, items: [], next_cursor: null })); await listPrivateImportTargets({ ...options(), cursor });
  expect(String(fetchMock.mock.calls[1][0])).toContain('before_id=private-import%3A');
  for (const items of [[{ ...value, opportunity: opp() }], [value, value]]) {
    fetchMock.mockResolvedValueOnce(json({ version: 1, items, next_cursor: null })); await expect(listPrivateImportTargets(options())).rejects.toMatchObject({ code: 'invalid_receipt' });
  }
});
it('rejects bad input before authentication, including NUL, bad JSON and excess metadata', async () => {
  for (const value of [{ ...opp(), description_raw: 'NUL\u0000' }, { ...opp(), extra_fields: { x: NaN } }, { ...opp(), extra_fields: { x: 'x'.repeat(256 * 1024) } }, { ...opp(), source: 'official' }]) {
    await expect(savePrivateImportTarget(id, value, 0, options())).rejects.toBeTruthy();
  }
  await expect(getPrivateImportTarget('../public-id', options())).rejects.toMatchObject({ code: 'invalid_input' });
  expect(auth).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
});
it('bounds error bodies and never exposes server/source text', async () => {
  fetchMock.mockResolvedValueOnce(new Response('PRIVATE secret'.repeat(1000), { status: 500 }));
  await expect(getPrivateImportTarget(id, options())).rejects.not.toThrow('PRIVATE');
  fetchMock.mockResolvedValueOnce(new Response('{}', { headers: { 'Content-Type': 'application/json', 'Content-Length': '999999999' } }));
  await expect(getPrivateImportTarget(id, options())).rejects.toMatchObject({ code: 'invalid_receipt' });
});
it('timeout covers authentication and cannot dispatch a late resolved attempt', async () => {
  vi.useFakeTimers(); const gate = deferred<Awaited<ReturnType<typeof getAuthState>>>(); auth.mockReturnValue(gate.promise);
  const pending = savePrivateImportTarget(id, opp(), 0, options()); const check = expect(pending).rejects.toMatchObject({ code: 'timeout' });
  await vi.advanceTimersByTimeAsync(PRIVATE_TARGET_TIMEOUT_MS); await check; gate.resolve(state()); await Promise.resolve(); expect(fetchMock).not.toHaveBeenCalled();
});
it('cancelled requests do not dispatch, and known conflicts require user review', async () => {
  const controller = new AbortController(); controller.abort();
  await expect(getPrivateImportTarget(id, { ...options(), signal: controller.signal })).rejects.toMatchObject({ code: 'aborted' });
  expect(fetchMock).not.toHaveBeenCalled();
  fetchMock.mockResolvedValueOnce(json({ detail: { code: 'private_target_conflict', message: 'secret ignored' } }, 409));
  await expect(savePrivateImportTarget(id, opp(), 1, options())).rejects.toMatchObject({ code: 'conflict' }); expect(fetchMock).toHaveBeenCalledOnce();
});

it('binds source labels to retained raw metadata without inventing AI coverage', async () => {
  for (const change of [
    { description_source: 'page_text', ai_input_scope: 'source_excerpt', llm_enriched: true },
    { description_source: 'pasted_text', ai_input_scope: 'unknown', llm_enriched: false },
    null,
  ]) {
    fetchMock.mockResolvedValueOnce(one(target(1, opp(), { import_source: change && { version: 1, ...change } })));
    await expect(getPrivateImportTarget(id, options())).rejects.toMatchObject({ code: 'invalid_receipt' });
  }
  const unlabeled = { ...opp(), extra_fields: {} };
  fetchMock.mockResolvedValueOnce(one(target(1, unlabeled)));
  await expect(getPrivateImportTarget(id, options())).rejects.toMatchObject({ code: 'invalid_receipt' });
  fetchMock.mockResolvedValueOnce(one(target(1, unlabeled, { import_source: null })));
  expect((await getPrivateImportTarget(id, options()))?.target.import_source).toBeNull();
  const unsupported: ImportedOpportunity = { ...opp(), extra_fields: { description_source: 'pasted_text', ai_input_scope: 'full_source', llm_enriched: true } };
  const labels = { version: 1, description_source: 'pasted_text', ai_input_scope: 'unknown', llm_enriched: true };
  fetchMock.mockResolvedValueOnce(one(target(1, unsupported, { import_source: labels })));
  expect((await getPrivateImportTarget(id, options()))?.target.import_source).toEqual(labels);
});

it('consumes actual FastAPI receipts captured with synthetic GoTrue and PostgREST', async () => {
  const uid = actualApi.create.target.owner_id;
  const targetId = actualApi.create.target.id;
  await setOwner(uid); auth.mockResolvedValue(state(uid));
  fetchMock.mockResolvedValueOnce(json(actualApi.create));
  expect(await savePrivateImportTarget(targetId, actualApi.create.target.opportunity as ImportedOpportunity, 0, options())).toEqual(actualApi.create);
  fetchMock.mockResolvedValueOnce(json(actualApi.read));
  expect(await getPrivateImportTarget(targetId, options())).toEqual(actualApi.read);
  fetchMock.mockResolvedValueOnce(json(actualApi.list));
  expect(await listPrivateImportTargets(options())).toEqual(actualApi.list);
  fetchMock.mockResolvedValueOnce(json(actualApi.delete));
  expect(await deletePrivateImportTarget(targetId, 1, options())).toEqual(actualApi.delete);
});

it('applies the source field limits to list summaries as well as full records', async () => {
  for (const change of [{ title: 'x'.repeat(1001) }, { source_url: 'x'.repeat(8193) },
    { organization: 'x'.repeat(2001) }, { title: 'NUL\u0000' }]) {
    fetchMock.mockResolvedValueOnce(json({ version: 1, items: [{ ...summary(), ...change }], next_cursor: null }));
    await expect(listPrivateImportTargets(options())).rejects.toMatchObject({ code: 'invalid_receipt' });
  }
});


function resolved() {
  const raw = target(); const detail = { title: raw.opportunity!.title, organization: null, description_raw: raw.opportunity!.description_raw,
    source_url: null, url: null, location: null, deadline: null, posted_date: null, import_source: raw.import_source };
  return { version: 1, id, owner_id: OWNER, revision: 1, target_scope: 'private_import', verification: 'unverified', target_version: raw.target_version,
    detail, tracker: { id, title: detail.title, organization: null, source_url: null, url: null, target_scope: 'private_import',
      verification: 'unverified', target_version: raw.target_version }, capabilities: { read: true, tracker_identity: true, writes: false } };
}
it('reads an owner-bound private display receipt without granting writing authority', async () => {
  const value = resolved(); fetchMock.mockResolvedValueOnce(json(value));
  expect(await getResolvedPrivateImportTarget(id, { ...options(), expectedVersion: value.target_version })).toEqual(value);
  expect(String(fetchMock.mock.calls[0][0])).toContain('/resolved?');
  expect(String(fetchMock.mock.calls[0][0])).toContain('expected_target_version=pit1%3A');
});
it('rejects forged private display scope, version, links, fields, and action capabilities', async () => {
  for (const change of [{ owner_id: OTHER }, { target_version: 'pit1:' + '0'.repeat(64) },
    { capabilities: { read: true, tracker_identity: true, writes: true } },
    { detail: { ...resolved().detail, source_url: 'javascript:alert(1)' } },
    { tracker: { ...resolved().tracker, title: 'wrong target title' } },
    { detail: { ...resolved().detail, recipient: 'fabricated@example.test' } }]) {
    fetchMock.mockResolvedValueOnce(json({ ...resolved(), ...change }));
    await expect(getResolvedPrivateImportTarget(id, options())).rejects.toMatchObject({ code: 'invalid_receipt' });
  }
  fetchMock.mockResolvedValueOnce(json({ detail: { code: 'private_target_changed' } }, 409));
  await expect(getResolvedPrivateImportTarget(id, options())).rejects.toMatchObject({ code: 'changed' });
});

it('consumes the actual FastAPI resolved fixture without inventing public fields', async () => {
  await setOwner(actualResolved.owner_id); auth.mockResolvedValue(state(actualResolved.owner_id));
  fetchMock.mockResolvedValueOnce(json(actualResolved));
  expect(await getResolvedPrivateImportTarget(actualResolved.id, options())).toEqual(actualResolved);
});

describe('batch Tracker resolution', () => {
  const other = 'private-import:dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  const version = (revision: number, target = id) => 'pit1:' + createHash('sha256').update(JSON.stringify({ id: target, owner_id: OWNER, revision })).digest('hex');
  const tracker = (changes: Record<string, unknown> = {}) => ({ id, title: 'Research 中文', organization: null, source_url: 'https://lab.example.edu/join', url: null,
    target_scope: 'private_import', verification: 'unverified', target_version: version(2), ...changes });
  const batch = (items: unknown[]) => json({ version: 1, items });
  const resolved = (changes: Record<string, unknown> = {}, trackerChanges: Record<string, unknown> = {}) => ({ id, status: 'resolved', revision: 2, tracker: tracker(trackerChanges), ...changes });

  it('posts the owner and ids once and keeps per-item deleted/missing results in request order', async () => {
    fetchMock.mockResolvedValueOnce(batch([resolved(), { id: other, status: 'not_found' }]));
    expect(await resolvePrivateImportTrackerTargets([id, other], options())).toEqual([{ id, status: 'resolved', tracker: tracker() }, { id: other, status: 'not_found' }]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/private-import-targets\/resolved$/);
    expect(init).toMatchObject({ method: 'POST', cache: 'no-store', redirect: 'error' });
    expect(JSON.parse(init!.body as string)).toEqual({ expected_owner_id: OWNER, ids: [id, other] });
  });

  it.each([
    ['empty', []], ['duplicate', [id, id]], ['public id', ['public-1']],
    ['over the limit', Array.from({ length: 101 }, (_, n) => `private-import:cccccccc-cccc-4ccc-8ccc-${String(n).padStart(12, '0')}`)],
  ])('refuses %s input before any request', async (_label, ids) => {
    await expect(resolvePrivateImportTrackerTargets(ids as string[], options())).rejects.toMatchObject({ code: 'invalid_input' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ['reordered items', () => [{ id: other, status: 'not_found' }, resolved()]],
    ['missing item', () => [resolved()]],
    ['forged version', () => [resolved({}, { target_version: version(3) }), { id: other, status: 'deleted' }]],
    ['unrecomputable revision', () => [resolved({ revision: 0 }), { id: other, status: 'deleted' }]],
    ['unsafe link', () => [resolved({}, { url: 'javascript:alert(1)' }), { id: other, status: 'deleted' }]],
    ['extra authority', () => [resolved({}, { target_truth: { actionable: true } }), { id: other, status: 'deleted' }]],
    ['public scope', () => [resolved({}, { target_scope: 'public' }), { id: other, status: 'deleted' }]],
    ['blank title', () => [resolved({}, { title: ' ' }), { id: other, status: 'deleted' }]],
    ['unknown status', () => [resolved(), { id: other, status: 'archived' }]],
    ['detail smuggled into a status item', () => [resolved(), { id: other, status: 'deleted', tracker: tracker() }]],
  ])('rejects a receipt with %s', async (_label, items) => {
    fetchMock.mockResolvedValueOnce(batch(items()));
    await expect(resolvePrivateImportTrackerTargets([id, other], options())).rejects.toMatchObject({ code: 'invalid_receipt' });
  });

  it('reports a refused batch as unavailable, never as missing targets', async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: 'Too many requests' }, 429));
    await expect(resolvePrivateImportTrackerTargets([id], options())).rejects.toMatchObject({ code: 'unavailable' });
  });

  it('refuses a session that resolves to another account', async () => {
    auth.mockResolvedValueOnce(state(OTHER));
    await expect(resolvePrivateImportTrackerTargets([id], options())).rejects.toBeInstanceOf(OwnerMismatchError);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
