import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';

const { mockFrom, mockGetSession, mockUpsert, mockVersionInsert, mockMaybeSingle, mockHistory, mockRpc } = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return { mockFrom: vi.fn(), mockGetSession: vi.fn(), mockUpsert: vi.fn(),
    mockVersionInsert: vi.fn(), mockMaybeSingle: vi.fn(), mockHistory: vi.fn(), mockRpc: vi.fn() };
});
vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({
    auth: { getSession: mockGetSession, signInAnonymously: vi.fn(),
      onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })) },
    from: mockFrom, rpc: mockRpc,
  }),
}));

import { loadRenovation, listRenovationVersions, readRenovationVersion, RenovationLoadError, saveRenovation } from './supabase';
import { advanceOwnerEpoch, captureOwnerToken, isLocalOwnerReady, syncLocalIdentityOwner } from './identity-owner';

const A = 'renovation-anonymous-a';
const B = 'renovation-anonymous-b';
const session = (uid: string) => ({ data: { session: { user: { id: uid, is_anonymous: true } } } });
const stored = {
  doc: {
    sections: [{ id: 's1', heading: 'Experience', kind: 'experience', bullets: [{
      id: 'b1', base_text: 'Built a parser.', variants: [{ source: 'macro', text: 'Built a tested parser.', source_evidence: 'Built a parser.' }],
      current: 0, action: 'keep',
    }] }], method: 'ai', warnings: [],
  }, base_snapshot: {}, method: 'ai', warnings: [], updated_at: '2026-09-25T06:30:00.123456+00:00',
  owner_id: A, opportunity_id: 'opp-1', revision: 1,
};
let filters: Array<[string, unknown]>;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
async function establish(uid: string) {
  advanceOwnerEpoch(uid);
  await syncLocalIdentityOwner(uid);
  await waitFor(() => expect(isLocalOwnerReady(uid)).toBe(true));
}
function save(doc: Record<string, unknown> = stored.doc, token = captureOwnerToken(), revision = 0) {
  return saveRenovation('opp-1', doc, {}, 'ai', [], token, revision);
}
function receipt(row: unknown) {
  if (!row || typeof row !== 'object' || Array.isArray(row)) return row;
  const value = row as Record<string, unknown>;
  return { owner_id: value.owner_id, opportunity_id: value.opportunity_id, revision: value.revision, updated_at: value.updated_at,
    payload: { doc: value.doc, base_snapshot: value.base_snapshot, method: value.method, warnings: value.warnings } };
}

beforeEach(async () => {
  localStorage.clear();
  await establish(A);
  filters = [];
  mockGetSession.mockReset().mockResolvedValue(session(A));
  mockUpsert.mockReset().mockResolvedValue({ error: null });
  mockVersionInsert.mockReset().mockResolvedValue({ error: null });
  mockMaybeSingle.mockReset().mockResolvedValue({ data: stored, error: null });
  mockHistory.mockReset().mockResolvedValue({ data: [{ id: 'v1', doc: stored.doc, created_at: '' }], error: null });
  mockFrom.mockReset();
  mockRpc.mockReset().mockImplementation(async (name: string, args: Record<string, unknown>) => {
    if (name === 'read_renovation') {
      filters.push(['device_id', args.p_expected_owner], ['opportunity_id', args.p_opportunity_id]);
      const response = await mockMaybeSingle();
      return { error: response.error, data: response.data === null ? { status: 'absent' } : { status: 'found', current: receipt(response.data) } };
    }
    if (name === 'save_renovation_cas') {
      const response = await mockUpsert(args);
      return { error: response.error, data: { status: 'saved', current: { owner_id: args.p_expected_owner, opportunity_id: args.p_opportunity_id,
        revision: Number(args.p_expected_revision) + 1, payload: args.p_payload, updated_at: stored.updated_at } } };
    }
    if (name === 'list_renovation_versions') {
      filters.push(['device_id', args.p_expected_owner], ['opportunity_id', args.p_opportunity_id]);
      return mockHistory();
    }
    throw new Error('unexpected RPC');
  });
});

describe('renovation persistence capability', () => {
  it('saves and restores the complete document through owner-bound RPCs, with no direct table writes', async () => {
    expect(await save()).toEqual({ status: 'saved', current: stored });
    expect(mockRpc).toHaveBeenCalledWith('save_renovation_cas', { p_expected_owner: A, p_opportunity_id: 'opp-1', p_expected_revision: 0,
      p_payload: { doc: stored.doc, base_snapshot: {}, method: 'ai', warnings: [] } });
    expect(await loadRenovation('opp-1')).toEqual(stored);
    expect(mockFrom).not.toHaveBeenCalled(); expect(mockVersionInsert).not.toHaveBeenCalled();
  });

  it('does not adopt an account that resolves after the action starts', async () => {
    const pending = deferred<ReturnType<typeof session>>(); mockGetSession.mockReturnValueOnce(pending.promise);
    const result = save(); await waitFor(() => expect(mockGetSession).toHaveBeenCalled());
    await establish(B); pending.resolve(session(B));
    expect(await result).toEqual({ status: 'abandoned' }); expect(mockRpc).not.toHaveBeenCalled();
  });

  it('does not acknowledge a save response after the owner changes', async () => {
    const pending = deferred<{ error: null }>(); mockUpsert.mockReturnValueOnce(pending.promise);
    const result = save(); await waitFor(() => expect(mockUpsert).toHaveBeenCalled());
    await establish(B); pending.resolve({ error: null });
    expect(await result).toEqual({ status: 'abandoned' }); expect(mockVersionInsert).not.toHaveBeenCalled();
  });

  it('rejects an old capability before any later document can be dispatched', async () => {
    const oldOwner = captureOwnerToken(); await establish(B);
    expect(await save(stored.doc, oldOwner)).toEqual({ status: 'abandoned' });
    expect(mockRpc).not.toHaveBeenCalled();
  });

  it('does not invent a revision or retry a later save; the UI supplies the accepted base', async () => {
    expect((await save()).status).toBe('saved');
    const nextDoc = { ...stored.doc, extra: 'second edit' };
    expect(await save(nextDoc, captureOwnerToken(), 1)).toEqual({ status: 'saved', current: { ...stored, doc: nextDoc, revision: 2 } });
    expect(mockRpc.mock.calls.map(([, args]) => args.p_expected_revision)).toEqual([0, 1]);
  });

  it.each(['working', 'history'] as const)('rejects a late %s read after identity changes', async (kind) => {
    const pending = deferred<{ data: unknown; error: null }>();
    (kind === 'working' ? mockMaybeSingle : mockHistory).mockReturnValueOnce(pending.promise);
    const result = kind === 'working' ? loadRenovation('opp-1') : listRenovationVersions('opp-1');
    const rejection = expect(result).rejects.toThrow('identity');
    await waitFor(() => expect(kind === 'working' ? mockMaybeSingle : mockHistory).toHaveBeenCalled());
    await establish(B); pending.resolve({ data: kind === 'working' ? stored : [stored], error: null }); await rejection;
  });

  it('reports an unconfirmed save without separately starting best-effort history', async () => {
    mockUpsert.mockResolvedValueOnce({ error: { message: 'offline' } });
    expect(await save()).toEqual({ status: 'unknown' }); expect(mockVersionInsert).not.toHaveBeenCalled();
  });

  it('awaits the single atomic save receipt instead of claiming Saved early', async () => {
    const pending = deferred<{ error: null }>(); mockUpsert.mockReturnValueOnce(pending.promise);
    let settled = false; const result = save().then((value) => { settled = true; return value; });
    await waitFor(() => expect(mockUpsert).toHaveBeenCalled()); expect(settled).toBe(false);
    pending.resolve({ error: null }); expect((await result).status).toBe('saved');
    expect(mockVersionInsert).not.toHaveBeenCalled();
  });
});


describe('renovation restore outcomes', () => {
  it('returns null only for a successful absent row and does not write', async () => {
    mockMaybeSingle.mockResolvedValueOnce({ data: null, error: null });
    expect(await loadRenovation('opp-1')).toBeNull();
    expect(mockUpsert).not.toHaveBeenCalled();
    expect(mockVersionInsert).not.toHaveBeenCalled();
  });

  it.each(['backend', 'transport', 'session'] as const)('turns a %s failure into a safe typed error, not absence', async (kind) => {
    const secret = 'PRIVATE SAVED RESUME CONTENT';
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    if (kind === 'backend') mockMaybeSingle.mockResolvedValueOnce({ data: null, error: { message: secret, details: secret } });
    else if (kind === 'transport') mockMaybeSingle.mockRejectedValueOnce(new Error(secret));
    else mockGetSession.mockRejectedValueOnce(new Error(secret));
    try {
      const caught = await loadRenovation('opp-1').catch((error: unknown) => error);
      expect(caught).toBeInstanceOf(RenovationLoadError);
      expect(caught).toMatchObject({ name: 'RenovationLoadError', code: 'read_failed' });
      expect((caught as Error).message).not.toContain(secret);
      expect(caught).not.toHaveProperty('cause');
      expect(JSON.stringify(caught)).not.toContain(secret);
      expect(warn.mock.calls.flat().join(' ')).not.toContain(secret);
      expect(mockUpsert).not.toHaveBeenCalled();
    } finally { warn.mockRestore(); }
  });

  const section = stored.doc.sections[0];
  const bullet = section.bullets[0];
  it.each([
    ['missing document', undefined], ['array document', []], ['empty document', {}],
    ['missing sections', { method: 'ai', warnings: [] }],
    ['empty sections', { ...stored.doc, sections: [] }],
    ['nonobject section', { ...stored.doc, sections: ['bad'] }],
    ['missing bullets', { ...stored.doc, sections: [{ id: 's1', heading: '', kind: 'experience' }] }],
    ['bad heading', { ...stored.doc, sections: [{ ...section, heading: {} }] }],
    ['bad base text', { ...stored.doc, sections: [{ ...section, bullets: [{ ...bullet, base_text: null }] }] }],
    ['missing variants', { ...stored.doc, sections: [{ ...section, bullets: [{ ...bullet, variants: undefined }] }] }],
    ['bad variant', { ...stored.doc, sections: [{ ...section, bullets: [{ ...bullet, variants: ['bad'] }] }] }],
    ['bad variant text', { ...stored.doc, sections: [{ ...section, bullets: [{ ...bullet, variants: [{ ...bullet.variants[0], text: {} }] }] }] }],
    ['fractional current', { ...stored.doc, sections: [{ ...section, bullets: [{ ...bullet, current: 0.5 }] }] }],
    ['out-of-range current', { ...stored.doc, sections: [{ ...section, bullets: [{ ...bullet, current: 1 }] }] }],
    ['invalid base pointer', { ...stored.doc, sections: [{ ...section, bullets: [{ ...bullet, current: -2 }] }] }],
    ['duplicate section id', { ...stored.doc, sections: [section, section] }],
    ['duplicate bullet id', { ...stored.doc, sections: [{ ...section, bullets: [bullet, bullet] }] }],
    ['missing warnings', { ...stored.doc, warnings: undefined }],
    ['nonstring warning', { ...stored.doc, warnings: [{}] }],
    ['bad source signature', { ...stored.doc, resume_sig: {} }],
    ['bad profile signature', { ...stored.doc, profile_sig: {} }],
    ['bad target signature', { ...stored.doc, target_sig: {} }],
    ['bad processing', { ...stored.doc, processing: { chunks: null } }],
  ])('rejects %s without coercing an empty draft', async (_name, doc) => {
    const row = { ...stored, doc }; const before = JSON.stringify(row);
    mockMaybeSingle.mockResolvedValueOnce({ data: row, error: null });
    await expect(loadRenovation('opp-1')).rejects.toMatchObject({ code: 'invalid_saved_data' });
    expect(JSON.stringify(row)).toBe(before);
    expect(mockUpsert).not.toHaveBeenCalled();
    expect(mockVersionInsert).not.toHaveBeenCalled();
  });

  it.each([
    undefined, [], { ...stored, base_snapshot: null },
    { ...stored, base_snapshot: { sections: [{ ...section, bullets: [{ id: 'b1' }] }] } },
    { ...stored, warnings: [{}] }, { ...stored, updated_at: {} }, { ...stored, method: {} },
  ])('rejects a malformed stored row or source snapshot', async (data) => {
    mockMaybeSingle.mockResolvedValueOnce({ data, error: null });
    await expect(loadRenovation('opp-1')).rejects.toMatchObject({ code: 'invalid_saved_data' });
  });

  it('preserves a legitimate legacy document without new fingerprints or coverage', async () => {
    const row = structuredClone(stored);
    row.doc.sections[0].bullets[0].current = -1;
    row.doc.sections[0].bullets[0].variants = [];
    mockMaybeSingle.mockResolvedValueOnce({ data: row, error: null });
    expect(await loadRenovation('opp-1')).toEqual(row);
    expect(row.doc).not.toHaveProperty('resume_sig');
    expect(row.doc).not.toHaveProperty('profile_sig');
    expect(row.doc).not.toHaveProperty('processing');
  });

  it('retains current metadata and complete source snapshots without rewriting them', async () => {
    const row = { ...stored, doc: { ...stored.doc, resume_sig: 'old-source', profile_sig: 'future-format',
      processing: { input_characters: 10, ai_chunks: 0, heuristic_chunks: 1,
        chunks: [{ start: 0, end: 10, method: 'heuristic', reason: 'not_configured' }] } },
      base_snapshot: { sections: [{ id: 's1', heading: '', kind: 'experience', bullets: [{ id: 'b1', text: 'Full original.' }] }] } };
    mockMaybeSingle.mockResolvedValueOnce({ data: row, error: null });
    expect(await loadRenovation('opp-1')).toEqual(row);
  });

  it('a failed read can be retried and then recover the existing document', async () => {
    mockMaybeSingle.mockResolvedValueOnce({ data: null, error: { message: 'offline' } });
    await expect(loadRenovation('opp-1')).rejects.toBeInstanceOf(RenovationLoadError);
    expect(await loadRenovation('opp-1')).toEqual(stored);
    expect(mockMaybeSingle).toHaveBeenCalledTimes(2);
    expect(mockUpsert).not.toHaveBeenCalled();
  });

  it('prioritizes an owner change over a late rejected transport', async () => {
    let reject!: (reason: Error) => void;
    mockMaybeSingle.mockReturnValueOnce(new Promise((_resolve, fail) => { reject = fail; }));
    const pending = loadRenovation('opp-1');
    const assertion = expect(pending).rejects.toThrow('identity');
    await waitFor(() => expect(mockMaybeSingle).toHaveBeenCalled());
    await establish(B);
    reject(new Error('PRIVATE OLD OWNER CONTENT'));
    await assertion;
    expect(mockUpsert).not.toHaveBeenCalled();
  });
});

// A read that never answers used to leave the restore spinner up for good;
// the modal and the history panel already turn a rejection into Retry.
describe('renovation read deadline', () => {
  afterEach(() => { vi.useRealTimers(); });
  function settles(promise: Promise<unknown>) {
    const state = { done: false, value: undefined as unknown };
    void promise.then(value => { state.value = value; }, (error: unknown) => { state.value = error; }).finally(() => { state.done = true; });
    return state;
  }
  const reads = [
    ['read_renovation', () => loadRenovation('opp-1')],
    ['list_renovation_versions', () => listRenovationVersions('opp-1')],
    ['get_renovation_version', () => readRenovationVersion('opp-1', '00000000-0000-4000-8000-000000000001')],
  ] as const;
  it.each(reads)('a hung %s RPC rejects at 30 s and cancels the request', async (name, read) => {
    let signal: AbortSignal | undefined;
    const hung = { then() {}, abortSignal(value: AbortSignal) { signal = value; return hung; } };
    mockRpc.mockImplementation(() => hung);
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    const outcome = settles(read());
    await vi.advanceTimersByTimeAsync(29_999);
    expect(mockRpc).toHaveBeenCalledWith(name, expect.objectContaining({ p_expected_owner: A, p_opportunity_id: 'opp-1' }));
    expect(outcome.done).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(outcome.done).toBe(true);
    expect(outcome.value).toBeInstanceOf(RenovationLoadError); expect(outcome.value).toMatchObject({ code: 'read_failed' });
    expect(signal?.aborted).toBe(true);
  });

  it.each(reads)('%s: a hung session check falls inside the same deadline', async (_name, read) => {
    mockGetSession.mockReturnValue(new Promise(() => {}));
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    const outcome = settles(read());
    await vi.advanceTimersByTimeAsync(30_000);
    expect(outcome.done).toBe(true); expect(outcome.value).toMatchObject({ name: 'RenovationLoadError', code: 'read_failed' });
    expect(mockRpc).not.toHaveBeenCalled();
  });

  it('a read that answers in time leaves no deadline behind', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    const timers = vi.getTimerCount();
    expect(await loadRenovation('opp-1')).toEqual(stored);
    expect(vi.getTimerCount()).toBe(timers);
  });
});
