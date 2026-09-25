import { describe, expect, it, vi } from 'vitest';
import { RenovationSaveQueue, type RenovationQueueState } from './renovation-save-queue';
import type { RenovationPayload, RenovationSaveResult, StoredRenovation } from './supabase';
const payload = (text: string): RenovationPayload => ({ doc: { text }, base_snapshot: { original: 'unchanged' }, method: null, warnings: [] });
const current = (revision: number, text = 'remote'): StoredRenovation => ({ ...payload(text), revision, owner_id: 'owner', opportunity_id: 'opp', updated_at: '2026-09-25T00:00:00Z' });
const deferred = () => { let resolve!: (r: RenovationSaveResult) => void; const promise = new Promise<RenovationSaveResult>(r => { resolve = r; }); return { resolve, promise }; };
const tick = async () => { await Promise.resolve(); await Promise.resolve(); };
describe('renovation save queue', () => {
  it('serializes edits and uses confirmed revision for the latest pending snapshot', async () => {
    const first = deferred(); const commit = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue({ status: 'saved', current: current(6, 'third') });
    const states: RenovationQueueState[] = []; const queue = new RenovationSaveQueue(4, commit, s => states.push(s));
    queue.enqueue(payload('first')); queue.enqueue(payload('second')); queue.enqueue(payload('third'));
    expect(commit).toHaveBeenCalledTimes(1); expect(states.at(-1)?.status).toBe('saving');
    first.resolve({ status: 'saved', current: current(5, 'first') }); await tick();
    expect(commit.mock.calls).toEqual([[payload('first'), 4], [payload('third'), 5]]);
    expect(states.filter(s => s.status === 'saved')).toHaveLength(1);
  });
  it('retries the uncertain operation before submitting newer edits', async () => {
    const commit = vi.fn().mockResolvedValueOnce({ status: 'unknown' }).mockResolvedValueOnce({ status: 'unchanged', current: current(3, 'first') }).mockResolvedValueOnce({ status: 'saved', current: current(4, 'newer') });
    const queue = new RenovationSaveQueue(2, commit, vi.fn()); queue.enqueue(payload('first')); await tick();
    queue.enqueue(payload('newer')); expect(commit).toHaveBeenCalledOnce(); queue.retry(); await tick(); await tick();
    expect(commit.mock.calls).toEqual([[payload('first'), 2], [payload('first'), 2], [payload('newer'), 3]]);
  });
  it('keeps edits on conflict and requires explicit replacement before another write', async () => {
    const commit = vi.fn().mockResolvedValueOnce({ status: 'conflict', current: current(9) }).mockResolvedValue({ status: 'saved', current: current(10) });
    const queue = new RenovationSaveQueue(2, commit, vi.fn()); queue.enqueue(payload('local')); await tick(); queue.enqueue(payload('new local')); queue.retry();
    expect(commit).toHaveBeenCalledOnce(); queue.resolveConflict(payload('chosen local')); await tick();
    expect(commit.mock.calls[1]).toEqual([payload('chosen local'), 9]);
  });
  it('adopting the remote copy drops pending writes without saving', async () => {
    const commit = vi.fn().mockResolvedValue({ status: 'conflict', current: current(9) });
    const queue = new RenovationSaveQueue(2, commit, vi.fn()); queue.enqueue(payload('local')); await tick(); queue.enqueue(payload('pending'));
    queue.resolveConflict(); expect(commit).toHaveBeenCalledOnce();
  });
  it('never resurrects missing material by retrying at revision zero', async () => {
    const commit = vi.fn().mockResolvedValue({ status: 'missing' }); const queue = new RenovationSaveQueue(2, commit, vi.fn());
    queue.enqueue(payload('deleted')); await tick(); queue.retry(); queue.enqueue(payload('newer')); queue.resolveConflict(payload('newer')); expect(commit).toHaveBeenCalledOnce();
  });
  it('snapshots queued input before later mutation', async () => {
    const first = deferred(); const commit = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue({ status: 'saved', current: current(3) });
    const queue = new RenovationSaveQueue(1, commit, vi.fn()); queue.enqueue(payload('first')); const next = payload('second'); queue.enqueue(next); next.doc.text = 'mutated';
    first.resolve({ status: 'saved', current: current(2) }); await tick(); expect(commit.mock.calls[1][0].doc.text).toBe('second');
  });
  it('retirement prevents late UI updates and queued owner writes', async () => {
    const first = deferred(); const commit = vi.fn().mockReturnValue(first.promise); const notify = vi.fn(); const queue = new RenovationSaveQueue(1, commit, notify);
    queue.enqueue(payload('first')); queue.enqueue(payload('pending')); queue.retire(); first.resolve({ status: 'saved', current: current(2) }); await tick(); queue.retry();
    expect(commit).toHaveBeenCalledOnce(); expect(notify).toHaveBeenCalledTimes(1);
  });
});
