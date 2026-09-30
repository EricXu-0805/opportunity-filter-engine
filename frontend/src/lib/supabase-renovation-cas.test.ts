import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
const { mockFrom, mockGetSession, mockRpc } = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return { mockFrom: vi.fn(), mockGetSession: vi.fn(), mockRpc: vi.fn() };
});
vi.mock('@supabase/supabase-js', () => ({ createClient: () => ({
  auth: { getSession: mockGetSession, signInAnonymously: vi.fn(), onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })) },
  from: mockFrom, rpc: mockRpc,
}) }));
import { loadRenovation, listRenovationVersions, readRenovationVersion, RenovationLoadError, RenovationSaveError, saveRenovation, type RenovationPayload } from './supabase';
import { advanceOwnerEpoch, captureOwnerToken, isLocalOwnerReady, syncLocalIdentityOwner } from './identity-owner';
const A = 'renovation-a'; const B = 'renovation-b'; const OPP = 'opp-1';
const TIME = '2026-09-25T06:30:00.123456+00:00';
const ID = '00000000-0000-4000-8000-000000000002'; const OLD_ID = '00000000-0000-4000-8000-000000000001';
const session = (uid: string) => ({ data: { session: { user: { id: uid, is_anonymous: true } } } });
function payload(): RenovationPayload {
  return { doc: { sections: [{ id: 's1', heading: '经历', kind: 'experience', bullets: [{ id: 'b1', base_text: 'Built a parser. 中文 🧑🏽‍🔬',
    variants: [{ source: 'macro', text: 'Built a tested parser.', source_evidence: 'Built a parser.' }], current: 0, action: 'keep' }] }], method: 'ai', warnings: [] },
    base_snapshot: {}, method: 'ai', warnings: [] };
}
function current(p = payload(), revision = 1) { return { owner_id: A, opportunity_id: OPP, revision, payload: p, updated_at: TIME }; }
function flat(p = payload(), revision = 1) { return { owner_id: A, opportunity_id: OPP, revision, ...p, updated_at: TIME }; }
function summary(id = ID, created_at = TIME) { return { id, created_at, revision: 1, snapshot_kind: 'complete', source_revision: null, source_updated_at: null }; }
function result(data: unknown) { return { data, error: null }; }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
async function establish(uid: string) { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); await waitFor(() => expect(isLocalOwnerReady(uid)).toBe(true)); }
function save(p = payload(), revision = 0, token = captureOwnerToken()) { return saveRenovation(OPP, p.doc, p.base_snapshot, p.method, p.warnings, token, revision); }
beforeEach(async () => {
  localStorage.clear(); await establish(A); mockGetSession.mockReset().mockResolvedValue(session(A)); mockFrom.mockReset();
  mockRpc.mockReset().mockImplementation((name: string, args: Record<string, unknown>) => {
    if (name === 'read_renovation') return Promise.resolve(result({ status: 'found', current: current() }));
    if (name === 'save_renovation_cas') return Promise.resolve(result({ status: 'saved', current: current(args.p_payload as RenovationPayload, Number(args.p_expected_revision) + 1) }));
    if (name === 'list_renovation_versions') return Promise.resolve(result({ items: [summary()], next_cursor: null }));
    if (name === 'get_renovation_version') return Promise.resolve(result({ status: 'found', version: { ...summary(), owner_id: A, opportunity_id: OPP, payload: payload() } }));
    throw new Error('unexpected RPC');
  });
});

describe('renovation CAS receipts and input snapshot', () => {
  it('copies the complete payload and capability before awaits, preserving long text and extensions', async () => {
    const p = payload(); p.doc.resume_sig = 'short-old'; p.doc.profile_sig = 'future-format'; p.doc.target_sig = 'unknown';
    p.doc.extension = { keep: ['tail', '文'.repeat(5000)], flag: false }; p.base_snapshot.extra = { original: 'Unchanged source.' };
    const before = structuredClone(p); const token = captureOwnerToken();
    const gate = deferred<ReturnType<typeof session>>(); mockGetSession.mockReturnValueOnce(gate.promise);
    const saving = save(p, 0, token);
    p.doc.sections = []; p.base_snapshot.extra = { original: 'MUTATED' }; p.warnings.push('MUTATED'); token.uid = B;
    gate.resolve(session(A));
    expect(await saving).toEqual({ status: 'saved', current: flat(before) });
    expect(mockRpc.mock.calls[0][1].p_payload).toEqual(before); expect(mockFrom).not.toHaveBeenCalled();
  });
  it.each([3, 4])('accepts exact unchanged at expected or immediate next revision %s', async revision => {
    mockRpc.mockResolvedValueOnce(result({ status: 'unchanged', current: current(payload(), revision) }));
    expect(await save(payload(), 3)).toEqual({ status: 'unchanged', current: flat(payload(), revision) });
  });
  it('accepts JSONB object key order without changing source or content', async () => {
    const p = payload(); const reordered = { warnings: p.warnings, method: p.method, base_snapshot: p.base_snapshot,
      doc: { warnings: p.doc.warnings, method: p.doc.method, sections: p.doc.sections } };
    mockRpc.mockResolvedValueOnce(result({ status: 'saved', current: current(reordered) })); expect((await save()).status).toBe('saved');
  });
  it('returns remote conflicts without adopting revision or automatically rewriting', async () => {
    const remote = payload(); remote.doc.extra = 'another tab';
    mockRpc.mockResolvedValueOnce(result({ status: 'conflict', current: current(remote, 7) }));
    expect(await save()).toEqual({ status: 'conflict', current: flat(remote, 7) }); expect(mockRpc).toHaveBeenCalledTimes(1);
  });
  it('returns missing only from its explicit envelope', async () => {
    mockRpc.mockResolvedValueOnce(result({ status: 'missing' })); expect(await save(payload(), 3)).toEqual({ status: 'missing' });
  });
  it.each([
    ['owner', { ...current(), owner_id: B }], ['target', { ...current(), opportunity_id: 'other' }],
    ['zero revision', { ...current(), revision: 0 }], ['unsafe revision', { ...current(), revision: Number.MAX_SAFE_INTEGER + 1 }],
    ['jumped revision', { ...current(), revision: 4 }], ['timestamp', { ...current(), updated_at: 'not a time' }],
    ['document', current({ ...payload(), doc: { ...payload().doc, extra: 'not sent' } })],
    ['base source', current({ ...payload(), base_snapshot: { injected: true } })],
    ['method', current({ ...payload(), method: 'fallback' })], ['warnings', current({ ...payload(), warnings: ['not sent'] })],
    ['extra payload key', current({ ...payload(), private: 'unexpected' } as RenovationPayload)], ['extra envelope key', { ...current(), private: 'unexpected' }],
  ])('never reports Saved for mismatched %s', async (_name, receipt) => {
    mockRpc.mockResolvedValueOnce(result({ status: 'saved', current: receipt })); expect(await save()).toEqual({ status: 'unknown' });
  });
  it.each([null, {}, [], { status: 'saved' }, { status: 'missing', current: current() }, { status: 'failed' }, { status: ['saved'], current: current() }, { status: 'unchanged', current: current(payload(), 8) }])('rejects malformed or ambiguous envelopes', async data => {
    mockRpc.mockResolvedValueOnce(result(data)); expect(await save()).toEqual({ status: 'unknown' });
  });
  it.each(['RPC error', 'rejection'] as const)('keeps %s unconfirmed with no hidden retry or sensitive logging', async kind => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    if (kind === 'RPC error') mockRpc.mockResolvedValueOnce({ data: null, error: { message: 'PRIVATE RESUME' } }); else mockRpc.mockRejectedValueOnce(new Error('PRIVATE RESUME'));
    try { expect(await save()).toEqual({ status: 'unknown' }); expect(mockRpc).toHaveBeenCalledTimes(1); expect(warn).not.toHaveBeenCalled(); } finally { warn.mockRestore(); }
  });
  it('retires a same-uid different epoch and never treats lack of identity as absence', async () => {
    const gate = deferred<ReturnType<typeof result>>(); mockRpc.mockReturnValueOnce(gate.promise);
    const pending = save(); await waitFor(() => expect(mockRpc).toHaveBeenCalled()); advanceOwnerEpoch(null); await establish(A);
    gate.resolve(result({ status: 'saved', current: current() })); expect(await pending).toEqual({ status: 'abandoned' });
    advanceOwnerEpoch(null); expect(await save()).toEqual({ status: 'unavailable' });
    await expect(loadRenovation(OPP)).rejects.toThrow('ownership');
  });
  it.each([-1, 0.5, Number.MAX_SAFE_INTEGER + 1])('rejects invalid expected revision %s before auth/RPC', async revision => {
    await expect(save(payload(), revision)).rejects.toMatchObject({ code: 'invalid_revision' }); expect(mockGetSession).not.toHaveBeenCalled(); expect(mockRpc).not.toHaveBeenCalled();
  });
  it('rejects invalid documents, unsafe JSON and oversize UTF-8 without touching the caller input', async () => {
    for (const extra of [NaN, '\u0000', '\ud800', '文'.repeat(710000)]) {
      const p = payload(); p.doc.extra = extra; await expect(save(p)).rejects.toBeInstanceOf(RenovationSaveError); expect(p.doc.extra).toBe(extra);
    }
    await expect(save({ ...payload(), doc: {} })).rejects.toBeInstanceOf(RenovationSaveError);
    expect(mockRpc).not.toHaveBeenCalled();
  });
});

describe('history and safe read semantics', () => {
  it('distinguishes confirmed absence from null or failed RPC responses', async () => {
    mockRpc.mockResolvedValueOnce(result({ status: 'absent' })); expect(await loadRenovation(OPP)).toBeNull();
    mockRpc.mockResolvedValueOnce(result(null)); await expect(loadRenovation(OPP)).rejects.toMatchObject({ code: 'invalid_saved_data' });
  });
  it.each(['working', 'history', 'version'] as const)('exposes safe typed %s read failures, not empty data', async kind => {
    const call = () => kind === 'working' ? loadRenovation(OPP) : kind === 'history' ? listRenovationVersions(OPP) : readRenovationVersion(OPP, ID);
    mockRpc.mockResolvedValueOnce({ data: null, error: { message: 'PRIVATE RESUME', details: 'PRIVATE RESUME', code: '42501' } });
    const error = await call().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(RenovationLoadError); expect(error).toMatchObject({ code: 'read_failed' });
    expect((error as Error).message).not.toContain('PRIVATE'); expect(error).not.toHaveProperty('cause'); expect(await call()).not.toBeNull();
  });
  it('preserves missing old history sources as null and complete snapshots in full', async () => {
    const legacy = { ...summary(), snapshot_kind: 'legacy_doc', revision: null, payload: { doc: payload().doc, base_snapshot: null, method: null, warnings: null }, owner_id: A, opportunity_id: OPP };
    mockRpc.mockResolvedValueOnce(result({ status: 'found', version: legacy })); expect(await readRenovationVersion(OPP, ID)).toEqual(legacy);
    expect(mockRpc).toHaveBeenCalledWith('get_renovation_version', { p_expected_owner: A, p_opportunity_id: OPP, p_version_id: ID });
    expect(await readRenovationVersion(OPP, ID)).toMatchObject({ payload: payload(), snapshot_kind: 'complete' });
  });
  it('retains imported complete history source metadata without inventing a current revision', async () => {
    const imported = { ...summary(), revision: null, source_revision: 7, source_updated_at: TIME, payload: payload(), owner_id: A, opportunity_id: OPP };
    mockRpc.mockResolvedValueOnce(result({ status: 'found', version: imported })); expect(await readRenovationVersion(OPP, ID)).toEqual(imported);
  });
  it('pages metadata using exact microseconds, with UUID for timestamp ties', async () => {
    const first = summary(); const second = summary(OLD_ID, '2026-09-25T06:30:00.123455+00:00'); const cursor = { id: second.id, created_at: second.created_at };
    mockRpc.mockResolvedValueOnce(result({ items: [first, second], next_cursor: cursor }));
    expect(await listRenovationVersions(OPP, 2)).toEqual({ items: [first, second], next_cursor: cursor });
    mockRpc.mockResolvedValueOnce(result({ items: [], next_cursor: null }));
    expect(await listRenovationVersions(OPP, 2, captureOwnerToken(), cursor)).toEqual({ items: [], next_cursor: null });
    expect(mockRpc.mock.calls[1]).toEqual(['list_renovation_versions', { p_expected_owner: A, p_opportunity_id: OPP, p_limit: 2, p_before_created_at: cursor.created_at, p_before_id: cursor.id }]);
    mockRpc.mockResolvedValueOnce(result({ items: [summary(), summary(OLD_ID)], next_cursor: null }));
    expect((await listRenovationVersions(OPP)).items).toHaveLength(2);
  });
  it.each([
    { items: [summary(), summary()], next_cursor: null }, { items: [summary(OLD_ID), summary(ID)], next_cursor: null },
    { items: [summary(OLD_ID, '2026-09-25T06:30:00.123455+00:00'), summary()], next_cursor: null },
    { items: [summary()], next_cursor: { id: OLD_ID, created_at: TIME } }, { items: [], next_cursor: { id: ID, created_at: TIME } },
    { items: [{ ...summary(), snapshot_kind: 'future' }], next_cursor: null },
    { items: [{ ...summary(), snapshot_kind: ['complete'] }], next_cursor: null }, { items: [{ ...summary(), revision: -1 }], next_cursor: null },
    { items: [{ ...summary(), doc: payload().doc }], next_cursor: null },
  ])('rejects malformed history pages without dropping entries or returning empty', async data => {
    mockRpc.mockResolvedValueOnce(result(data)); await expect(listRenovationVersions(OPP)).rejects.toMatchObject({ code: 'invalid_saved_data' });
  });
  it('rejects repeated-page rows and invalid requests before RPC', async () => {
    mockRpc.mockResolvedValueOnce(result({ items: [summary()], next_cursor: null }));
    await expect(listRenovationVersions(OPP, 20, captureOwnerToken(), { id: ID, created_at: TIME })).rejects.toMatchObject({ code: 'invalid_saved_data' });
    const calls = mockRpc.mock.calls.length;
    await expect(listRenovationVersions(OPP, 51)).rejects.toBeInstanceOf(RenovationLoadError);
    await expect(readRenovationVersion(OPP, 'not-a-uuid')).rejects.toBeInstanceOf(RenovationLoadError); expect(mockRpc).toHaveBeenCalledTimes(calls);
  });
  it.each([{ owner_id: B }, { opportunity_id: 'other' }, { id: OLD_ID }, { payload: { ...payload(), base_snapshot: null } }, { snapshot_kind: 'legacy_doc', payload: payload() }])('rejects mismatched selected version data', async change => {
    mockRpc.mockResolvedValueOnce(result({ status: 'found', version: { ...summary(), owner_id: A, opportunity_id: OPP, payload: payload(), ...change } }));
    await expect(readRenovationVersion(OPP, ID)).rejects.toMatchObject({ code: 'invalid_saved_data' });
  });
  it('drops a late version body when the owner changes while RPC is pending', async () => {
    const gate = deferred<ReturnType<typeof result>>(); mockRpc.mockReturnValueOnce(gate.promise);
    const pending = readRenovationVersion(OPP, ID); const rejection = expect(pending).rejects.toThrow('identity');
    await waitFor(() => expect(mockRpc).toHaveBeenCalled()); await establish(B); gate.resolve(result({ status: 'absent' })); await rejection;
  });
});
