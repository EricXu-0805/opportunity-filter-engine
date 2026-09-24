import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';

const { mockFrom, mockGetSession, mockUpsert, mockVersionInsert, mockMaybeSingle, mockHistory } = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return { mockFrom: vi.fn(), mockGetSession: vi.fn(), mockUpsert: vi.fn(),
    mockVersionInsert: vi.fn(), mockMaybeSingle: vi.fn(), mockHistory: vi.fn() };
});
vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({
    auth: { getSession: mockGetSession, signInAnonymously: vi.fn(),
      onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })) },
    from: mockFrom,
  }),
}));

import { loadRenovation, listRenovationVersions, RenovationLoadError, saveRenovation } from './supabase';
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
  }, base_snapshot: {}, method: 'ai', warnings: [], updated_at: '',
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
function save(doc: Record<string, unknown> = { sections: ['a'] }, token = captureOwnerToken()) {
  return saveRenovation('opp-1', doc, {}, 'ai', [], token);
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
  mockFrom.mockReset().mockImplementation(() => {
    const chain = {
      upsert: mockUpsert,
      insert: mockVersionInsert,
      select: () => chain,
      eq: (column: string, value: unknown) => { filters.push([column, value]); return chain; },
      maybeSingle: mockMaybeSingle,
      order: () => chain,
      limit: mockHistory,
    };
    return chain;
  });
});

describe('renovation persistence capability', () => {
  it('saves working doc and history for the already-established anonymous owner', async () => {
    expect(await save()).toBe(true);
    expect(mockUpsert.mock.calls[0][0].device_id).toBe(A);
    expect(mockVersionInsert.mock.calls[0][0].device_id).toBe(A);
    expect(await loadRenovation('opp-1')).toEqual(stored);
    expect(await listRenovationVersions('opp-1')).toEqual([{ id: 'v1', doc: stored.doc, created_at: '' }]);
    expect(filters).toEqual([['device_id', A], ['opportunity_id', 'opp-1'], ['device_id', A], ['opportunity_id', 'opp-1']]);
  });

  it('does not adopt an account that resolves after the action starts', async () => {
    const pending = deferred<ReturnType<typeof session>>();
    mockGetSession.mockReturnValueOnce(pending.promise);
    const result = save();
    const rejection = expect(result).rejects.toThrow('identity');
    await waitFor(() => expect(mockGetSession).toHaveBeenCalled());
    await establish(B);
    pending.resolve(session(B));
    await rejection;
    expect(mockFrom).not.toHaveBeenCalled();
  });

  it('never starts history after a working-save response crosses an identity change', async () => {
    const pending = deferred<{ error: null }>();
    mockUpsert.mockReturnValueOnce(pending.promise);
    const result = save();
    const rejection = expect(result).rejects.toThrow('identity');
    await waitFor(() => expect(mockUpsert).toHaveBeenCalled());
    await establish(B);
    pending.resolve({ error: null });
    await rejection;
    expect(mockVersionInsert).not.toHaveBeenCalled();
  });

  it('serializes successive working-document saves and skips stale queued work', async () => {
    const pending = deferred<{ error: null }>();
    mockUpsert.mockReturnValueOnce(pending.promise);
    const owner = captureOwnerToken();
    const first = save({ version: 1 }, owner);
    const firstRejection = expect(first).rejects.toThrow('identity');
    const second = save({ version: 2 }, owner);
    const secondRejection = expect(second).rejects.toThrow('identity');
    await waitFor(() => expect(mockUpsert).toHaveBeenCalledTimes(1));
    await establish(B);
    pending.resolve({ error: null });
    await Promise.all([firstRejection, secondRejection]);
    expect(mockUpsert).toHaveBeenCalledTimes(1);
  });

  it('does not let a newer working doc overtake an earlier pending save', async () => {
    const pending = deferred<{ error: null }>();
    mockUpsert.mockReturnValueOnce(pending.promise);
    const first = save({ version: 1 });
    const second = save({ version: 2 });
    await waitFor(() => expect(mockUpsert).toHaveBeenCalledTimes(1));
    pending.resolve({ error: null });
    expect(await Promise.all([first, second])).toEqual([true, true]);
    expect(mockUpsert.mock.calls.map(([payload]) => payload.doc.version)).toEqual([1, 2]);
  });

  it.each(['working', 'history'] as const)('rejects a late %s read after identity changes', async (kind) => {
    const pending = deferred<{ data: unknown; error: null }>();
    (kind === 'working' ? mockMaybeSingle : mockHistory).mockReturnValueOnce(pending.promise);
    const result = kind === 'working' ? loadRenovation('opp-1') : listRenovationVersions('opp-1');
    const rejection = expect(result).rejects.toThrow('identity');
    await waitFor(() => expect(kind === 'working' ? mockMaybeSingle : mockHistory).toHaveBeenCalled());
    await establish(B);
    pending.resolve({ data: kind === 'working' ? stored : [stored], error: null });
    await rejection;
  });

  it('reports a working-save failure without creating a history snapshot', async () => {
    mockUpsert.mockResolvedValueOnce({ error: { message: 'offline' } });
    expect(await save()).toBe(false);
    expect(mockVersionInsert).not.toHaveBeenCalled();
  });

  it.each(['pending', 'rejected'] as const)('still confirms the working doc when best-effort history is %s', async (kind) => {
    mockVersionInsert.mockReturnValueOnce(kind === 'pending'
      ? new Promise(() => {}) : Promise.reject(new Error('history offline')));
    expect(await save()).toBe(true);
    expect(mockUpsert).toHaveBeenCalledTimes(1);
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
