import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
const api = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return { from: vi.fn(), session: vi.fn(), rpc: vi.fn(), order: vi.fn(), eq: vi.fn(), or: vi.fn(), limit: vi.fn(), select: vi.fn() };
});
vi.mock('@supabase/supabase-js', () => ({ createClient: () => ({
  auth: { getSession: api.session, signInAnonymously: vi.fn(async () => ({ data: { session: null }, error: null })),
    onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })) }, from: api.from, rpc: api.rpc,
}) }));
import { confirmApplicationEvent, getApplicationEvents, getApplicationEvent, OwnerMismatchError } from './supabase';
import { ApplicationEventError, ApplicationHistoryLoadError, type ApplicationEventInput } from './application-ledger';
import { settleApplicationAttempt, readPendingApplicationAttempts } from './application-attempt-storage';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner, writeUserScopedRaw, removeUserScopedRaw } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
const A = 'application-owner-a', B = 'application-owner-b', O = 'opp-1';
const key = STORAGE_KEYS.APPLICATION_ATTEMPT_PREFIX + O;
const session = (uid: string) => ({ data: { session: { user: { id: uid, is_anonymous: true } } } });
const input = (): ApplicationEventInput => ({ id: 'd501e1bf-3e60-49f2-9a09-18e9402a91c0', channel: 'web_form',
  destination: 'https://example.edu/apply?source=x', submittedAt: null, notes: ' Exact notes\r\n ', resultNote: null, nextStep: 'Wait for reply' });
const event = () => ({ event_id: input().id, device_id: A, opportunity_id: O, channel: input().channel, destination: input().destination,
  actual_submitted_at: null, notes: input().notes, result_note: input().resultNote, next_step: input().nextStep,
  confirmed_at: '2026-09-25T12:00:00.123456+00:00', confirmation_source: 'user_reported' });
const interaction = () => ({ device_id: A, opportunity_id: O, interaction_type: 'applied', notes: 'Existing tracker notes', remind_at: '2026-10-01',
  last_contacted_at: null, updated_at: '2026-09-25T12:00:00.123456+00:00' });
const receipt = () => ({ data: { event: event(), interaction: interaction(), replayed: false }, error: null });
async function owner(uid: string) { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); }
function seed(value = input()) { expect(writeUserScopedRaw(key, JSON.stringify({ v: 1, ownerId: A, opportunityId: O, input: value }), captureOwnerToken())).toBe(true); }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
beforeEach(async () => {
  localStorage.clear(); await owner(A); seed();
  api.session.mockReset().mockResolvedValue(session(A)); api.rpc.mockReset().mockResolvedValue(receipt());
  api.limit.mockReset().mockResolvedValue({ data: [event()], error: null });
  const query = { eq: api.eq, order: api.order, or: api.or, limit: api.limit };
  api.eq.mockReset().mockReturnValue(query); api.order.mockReset().mockReturnValue(query); api.or.mockReset().mockReturnValue(query);
  api.select.mockReset().mockReturnValue(query); api.from.mockReset().mockReturnValue({ select: api.select });
});
describe('application event confirmation', () => {
  it('submits exact user-reported fields and never infers a contact date or material', async () => {
    const result = await confirmApplicationEvent(O, input(), captureOwnerToken());
    expect(result.event).toMatchObject({ ...input(), deviceId: A, opportunityId: O, confirmationSource: 'user_reported' });
    expect(result.interaction).toEqual({ type: 'applied', notes: interaction().notes, remind_at: interaction().remind_at,
      last_contacted_at: undefined, updated_at: interaction().updated_at });
    expect(api.rpc).toHaveBeenCalledExactlyOnceWith('confirm_application_event', {
      p_expected_device_id: A, p_event_id: input().id, p_opportunity_id: O, p_channel: input().channel,
      p_destination: input().destination, p_actual_submitted_at: null, p_notes: input().notes,
      p_result_note: input().resultNote, p_next_step: input().nextStep,
    });
    expect(readPendingApplicationAttempts(captureOwnerToken(), O)).toHaveLength(1);
  });
  it('keeps an uncertain save retryable with the same durable ID and unchanged data', async () => {
    api.rpc.mockResolvedValueOnce({ data: null, error: { message: 'lost connection' } });
    await expect(confirmApplicationEvent(O, input(), captureOwnerToken())).rejects.toMatchObject({ code: 'unavailable' });
    expect(readPendingApplicationAttempts(captureOwnerToken(), O)[0].input).toEqual(input());
    api.rpc.mockResolvedValueOnce({ ...receipt(), data: { ...receipt().data, replayed: true } });
    expect((await confirmApplicationEvent(O, input(), captureOwnerToken())).replayed).toBe(true);
    expect(api.rpc.mock.calls.map(call => call[1].p_event_id)).toEqual([input().id, input().id]);
  });
  it('replays an exact recorded event after another tab settled the local attempt', async () => {
    const saved = await confirmApplicationEvent(O, input(), captureOwnerToken());
    await settleApplicationAttempt(captureOwnerToken(), O, saved.event);
    api.rpc.mockResolvedValue({ ...receipt(), data: { ...receipt().data, replayed: true } });
    expect((await confirmApplicationEvent(O, input(), captureOwnerToken())).replayed).toBe(true);
    expect(api.eq).toHaveBeenCalledWith('event_id', input().id);
    expect(readPendingApplicationAttempts(captureOwnerToken(), O)).toEqual([]);
  });
  it('replaying an older known ID never deletes a newer pending attempt', async () => {
    const saved = await confirmApplicationEvent(O, input(), captureOwnerToken());
    await settleApplicationAttempt(captureOwnerToken(), O, saved.event);
    const newer = { ...input(), id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee' }; seed(newer);
    api.rpc.mockResolvedValue({ ...receipt(), data: { ...receipt().data, replayed: true } });
    const replay = await confirmApplicationEvent(O, input(), captureOwnerToken());
    expect(await settleApplicationAttempt(captureOwnerToken(), O, replay.event)).toBe(false);
    expect(readPendingApplicationAttempts(captureOwnerToken(), O)[0].input).toEqual(newer);
  });
  it.each(['absent', 'failed', 'different'] as const)('never creates an unprepared event when lookup is %s', async mode => {
    removeUserScopedRaw(key, captureOwnerToken());
    api.limit.mockResolvedValue(mode === 'failed' ? { data: null, error: { message: 'private database detail' } }
      : { data: mode === 'absent' ? [] : [{ ...event(), notes: 'different content' }], error: null });
    await expect(confirmApplicationEvent(O, input(), captureOwnerToken())).rejects.toBeInstanceOf(ApplicationEventError);
    expect(api.rpc).not.toHaveBeenCalled();
  });
  it('unreadable pending storage prevents even an existing-event replay RPC', async () => {
    const realGet = localStorage.getItem.bind(localStorage);
    vi.spyOn(localStorage, 'getItem').mockImplementation(name => { if (name.includes(STORAGE_KEYS.APPLICATION_ATTEMPT_PREFIX)) throw new Error('private storage error'); return realGet(name); });
    await expect(confirmApplicationEvent(O, input(), captureOwnerToken())).rejects.toEqual(new ApplicationEventError('unavailable'));
    expect(api.rpc).not.toHaveBeenCalled();
  });
  it('copies caller input and owner token before auth waits', async () => {
    const held = deferred<ReturnType<typeof session>>(); api.session.mockReturnValue(held.promise);
    const value = input(); const token = captureOwnerToken(); const saving = confirmApplicationEvent(O, value, token);
    value.notes = 'changed'; token.uid = B; held.resolve(session(A));
    await saving; expect(api.rpc.mock.calls[0][1].p_notes).toBe(input().notes);
  });
  it('accepts absent or later manually changed tracker state only on an exact replay', async () => {
    api.rpc.mockResolvedValue({ ...receipt(), data: { ...receipt().data, replayed: true, interaction: null } });
    expect((await confirmApplicationEvent(O, input(), captureOwnerToken())).interaction).toBeNull();
    api.rpc.mockResolvedValue({ ...receipt(), data: { ...receipt().data, replayed: true,
      interaction: { ...interaction(), interaction_type: 'contacted', updated_at: null } } });
    expect((await confirmApplicationEvent(O, input(), captureOwnerToken())).interaction).toMatchObject({ type: 'contacted', updated_at: undefined });
  });
  it.each([
    { event: { ...event(), device_id: B } }, { event: { ...event(), opportunity_id: 'other' } },
    { event: { ...event(), event_id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee' } },
    { event: { ...event(), destination: 'https://other.edu' } }, { event: { ...event(), channel: 'other' } },
    { event: { ...event(), notes: 'changed' } }, { event: { ...event(), result_note: 'changed' } },
    { event: { ...event(), actual_submitted_at: '2026-09-24T00:00:00Z' } }, { event: { ...event(), confirmed_at: 'bad' } },
    { interaction: null }, { replayed: 'true' }, { interaction: { ...interaction(), device_id: B } },
    { interaction: { ...interaction(), opportunity_id: 'other' } }, { interaction: { ...interaction(), interaction_type: 'contacted' } },
    { interaction: { ...interaction(), last_contacted_at: 'bad' } }, { interaction: { ...interaction(), updated_at: null } },
    { interaction: { ...interaction(), remind_at: '2026-02-30' } },
  ])('rejects malformed or mismatched successful receipt %#', async patch => {
    api.rpc.mockResolvedValue({ data: { ...receipt().data, ...patch }, error: null });
    await expect(confirmApplicationEvent(O, input(), captureOwnerToken())).rejects.toMatchObject({ code: 'invalid_receipt' });
    expect(readPendingApplicationAttempts(captureOwnerToken(), O)).toHaveLength(1);
  });
  it.each([
    ['23505', 'application_event_conflict', 'conflict'], ['22023', 'invalid_application_event', 'invalid_input'],
    ['P0002', 'private_target_unavailable', 'target_unavailable'], ['P0002', 'private detail', 'unavailable'],
    ['23505', 'private detail', 'unavailable'], ['42501', 'not authorized private detail', 'unavailable'],
  ])('maps only documented failures safely %s %s', async (code, message, expected) => {
    api.rpc.mockResolvedValue({ data: null, error: { code, message } });
    await expect(confirmApplicationEvent(O, input(), captureOwnerToken())).rejects.toMatchObject({ code: expected });
    expect(api.rpc.mock.calls.every(call => call[0] === 'confirm_application_event')).toBe(true);
  });
  it('accepts an offset-equivalent actual submission time', async () => {
    const value = { ...input(), submittedAt: '2026-09-25T07:00:00.123456-05:00' }; seed(value);
    api.rpc.mockResolvedValue({ ...receipt(), data: { ...receipt().data, event: { ...event(), actual_submitted_at: '2026-09-25T12:00:00.123456Z' } } });
    expect((await confirmApplicationEvent(O, value, captureOwnerToken())).event.submittedAt).toBe('2026-09-25T12:00:00.123456Z');
  });
});
describe('owner-bound application event reads', () => {
  it('loads only the current owner and target, in stable descending order', async () => {
    expect(await getApplicationEvents(O)).toMatchObject({ hasMore: false, nextCursor: null });
    expect(api.from).toHaveBeenCalledWith('application_events');
    expect(api.eq.mock.calls).toEqual([['device_id', A], ['opportunity_id', O]]);
    expect(api.order.mock.calls).toEqual([['confirmed_at', { ascending: false }], ['event_id', { ascending: false }]]);
    expect(api.limit).toHaveBeenCalledWith(21);
  });
  it('uses last displayed event with full microseconds as next-page boundary', async () => {
    const older = { ...event(), event_id: '11111111-1111-4111-8111-111111111111' };
    api.limit.mockResolvedValueOnce({ data: [event(), older], error: null });
    const page = await getApplicationEvents(O, { limit: 1 }); expect(page.events).toHaveLength(1); expect(page.hasMore).toBe(true);
    api.limit.mockResolvedValueOnce({ data: [older], error: null }); await getApplicationEvents(O, { cursor: page.nextCursor!, limit: 1 });
    expect(api.or).toHaveBeenCalledWith(`confirmed_at.lt.${event().confirmed_at},and(confirmed_at.eq.${event().confirmed_at},event_id.lt.${event().event_id})`);
  });
  it('only a successful empty response proves absence or empty history', async () => {
    api.limit.mockResolvedValue({ data: [], error: null });
    expect(await getApplicationEvents(O)).toEqual({ events: [], hasMore: false, nextCursor: null });
    expect(await getApplicationEvent(O, input().id)).toBeNull();
    api.limit.mockResolvedValue({ data: [], error: { message: 'private error' } });
    await expect(getApplicationEvents(O)).rejects.toEqual(new ApplicationHistoryLoadError());
    await expect(getApplicationEvent(O, input().id)).rejects.toEqual(new ApplicationHistoryLoadError());
  });
  it('looks up the exact event ID and rejects duplicate/mismatched lookup rows', async () => {
    expect((await getApplicationEvent(O, input().id))?.id).toBe(input().id);
    expect(api.eq).toHaveBeenCalledWith('event_id', input().id);
    api.limit.mockResolvedValueOnce({ data: [event(), event()], error: null });
    await expect(getApplicationEvent(O, input().id)).rejects.toBeInstanceOf(ApplicationHistoryLoadError);
    api.limit.mockResolvedValueOnce({ data: [{ ...event(), event_id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee' }], error: null });
    await expect(getApplicationEvent(O, input().id)).rejects.toBeInstanceOf(ApplicationHistoryLoadError);
  });
  it.each([null, {}, [event(), event()], [{ ...event(), device_id: B }], [{ ...event(), opportunity_id: 'other' }],
    [{ ...event(), actual_submitted_at: '2027-01-01T00:00:00Z' }], [{ ...event(), notes: '' }],
  ])('rejects malformed or foreign successful pages %#', async data => {
    api.limit.mockResolvedValue({ data, error: null }); await expect(getApplicationEvents(O)).rejects.toBeInstanceOf(ApplicationHistoryLoadError);
  });
  it('rejects page order and cursor violations rather than silently skipping them', async () => {
    api.limit.mockResolvedValueOnce({ data: [{ ...event(), confirmed_at: '2026-09-25T12:00:00.123455Z' }, event()], error: null });
    await expect(getApplicationEvents(O)).rejects.toBeInstanceOf(ApplicationHistoryLoadError);
    await expect(getApplicationEvents(O, { cursor: { id: input().id, confirmedAt: event().confirmed_at } })).rejects.toBeInstanceOf(ApplicationHistoryLoadError);
  });
  it.each([0, -1, 101, 1.5, Number.NaN])('rejects invalid page limits before reading %s', async limit => {
    await expect(getApplicationEvents(O, { limit })).rejects.toBeInstanceOf(ApplicationHistoryLoadError); expect(api.from).not.toHaveBeenCalled();
  });
});
describe.each(['read', 'lookup', 'write'] as const)('application ledger %s identity retirement', operation => {
  const start = () => operation === 'read' ? getApplicationEvents(O) : operation === 'lookup' ? getApplicationEvent(O, input().id) : confirmApplicationEvent(O, input(), captureOwnerToken());
  it('does not dispatch after identity changes during auth', async () => {
    const held = deferred<ReturnType<typeof session>>(); api.session.mockReturnValue(held.promise);
    const running = start(); const check = expect(running).rejects.toBeInstanceOf(OwnerMismatchError);
    await waitFor(() => expect(api.session).toHaveBeenCalled()); await owner(B); held.resolve(session(B)); await check;
    expect(api.from).not.toHaveBeenCalled(); expect(api.rpc).not.toHaveBeenCalled();
  });
  it.each(['owner', 'generation'] as const)('rejects late %s receipt', async change => {
    const held = deferred<unknown>(); const fn = operation === 'write' ? api.rpc : api.limit; fn.mockReturnValue(held.promise);
    const running = start(); const check = expect(running).rejects.toBeInstanceOf(OwnerMismatchError);
    await waitFor(() => expect(fn).toHaveBeenCalled());
    if (change === 'owner') await owner(B);
    else { const marker = JSON.parse(localStorage.getItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER)!);
      localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, JSON.stringify({ ...marker, generation: marker.generation + 1, phase: 'switching' })); await syncLocalIdentityOwner(A); }
    held.resolve(operation === 'write' ? receipt() : { data: [event()], error: null }); await check;
  });
});
