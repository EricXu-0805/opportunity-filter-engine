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
import { confirmContactEvent, getContactEvents, OwnerMismatchError } from './supabase';
import { ContactEventError, ContactHistoryLoadError, type ContactEventInput } from './contact-ledger';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
const A = 'contact-owner-A', B = 'contact-owner-B', O = 'opp-1';
const session = (uid: string) => ({ data: { session: { user: { id: uid, is_anonymous: true } } } });
const input = (): ContactEventInput => ({ id: 'd501e1bf-3e60-89f2-9a09-18e9402a91c0', recipient: 'prof@example.edu',
  subject: ' My exact subject ', body: 'Hello,\r\n\nExact draft  ', materialRefs: [{ kind: 'profile', version: 'v1' }], actualSentAt: null });
const event = () => ({ event_id: input().id, device_id: A, opportunity_id: O, recipient: input().recipient,
  subject: input().subject, body: input().body, materials: input().materialRefs, actual_sent_at: input().actualSentAt,
  confirmed_at: '2026-09-25T12:00:00.123456+00:00', confirmation_source: 'user_reported' });
const interaction = () => ({ device_id: A, opportunity_id: O, interaction_type: 'replied', notes: 'Do not overwrite', remind_at: '2026-10-01',
  last_contacted_at: '2026-09-25T12:00:00.123456+00:00', updated_at: '2026-09-25T12:00:00.123456+00:00' });
const receipt = () => ({ data: { event: event(), interaction: interaction(), replayed: false }, error: null });
async function owner(uid: string) { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
beforeEach(async () => {
  localStorage.clear(); await owner(A);
  api.session.mockReset().mockResolvedValue(session(A));
  api.rpc.mockReset().mockResolvedValue(receipt());
  api.limit.mockReset().mockResolvedValue({ data: [event()], error: null });
  const query = { eq: api.eq, order: api.order, or: api.or, limit: api.limit };
  api.eq.mockReset().mockReturnValue(query); api.order.mockReset().mockReturnValue(query); api.or.mockReset().mockReturnValue(query);
  api.select.mockReset().mockReturnValue(query); api.from.mockReset().mockReturnValue({ select: api.select });
});
describe('exact immutable contact confirmation', () => {
  it('submits the exact snapshot and returns the preserved advanced tracker state', async () => {
    const result = await confirmContactEvent(O, input(), captureOwnerToken());
    expect(result.interaction).toEqual({ type: 'replied', notes: 'Do not overwrite', remind_at: interaction().remind_at,
      last_contacted_at: interaction().last_contacted_at, updated_at: interaction().updated_at });
    expect(result.event).toMatchObject({ ...input(), deviceId: A, opportunityId: O, confirmationSource: 'user_reported' });
    expect(api.rpc).toHaveBeenCalledExactlyOnceWith('confirm_contact_event', {
      p_expected_device_id: A, p_event_id: input().id, p_opportunity_id: O, p_recipient: input().recipient,
      p_subject: input().subject, p_body: input().body, p_materials: input().materialRefs, p_actual_sent_at: null,
    });
  });
  it('reuses an explicit stable ID for an uncertain retry', async () => {
    api.rpc.mockResolvedValueOnce({ data: null, error: { message: 'connection lost' } }).mockResolvedValueOnce({ ...receipt(), data: { ...receipt().data, replayed: true } });
    await expect(confirmContactEvent(O, input(), captureOwnerToken())).rejects.toMatchObject({ code: 'unavailable' });
    expect((await confirmContactEvent(O, input(), captureOwnerToken())).replayed).toBe(true);
    expect(api.rpc.mock.calls.map(call => call[1].p_event_id)).toEqual([input().id, input().id]);
    expect(api.from).not.toHaveBeenCalled();
  });
  it('an exact replay can preserve a summary the user has removed', async () => {
    api.rpc.mockResolvedValue({ ...receipt(), data: { ...receipt().data, interaction: null, replayed: true } });
    expect((await confirmContactEvent(O, input(), captureOwnerToken())).interaction).toBeNull();
  });
  it('replay preserves nullable legacy summary dates and absence of a reminder', async () => {
    api.rpc.mockResolvedValue({ ...receipt(), data: { ...receipt().data, replayed: true,
      interaction: { ...interaction(), remind_at: null, last_contacted_at: null, updated_at: null } } });
    expect((await confirmContactEvent(O, input(), captureOwnerToken())).interaction).toMatchObject({
      type: 'replied', remind_at: undefined, last_contacted_at: undefined, updated_at: undefined,
    });
  });
  it('distinguishes owner retirement and server validation from uncertain transport', async () => {
    api.rpc.mockResolvedValueOnce({ data: null, error: { code: '42501', message: 'identity_changed' } });
    await expect(confirmContactEvent(O, input(), captureOwnerToken())).rejects.toBeInstanceOf(OwnerMismatchError);
    api.rpc.mockResolvedValueOnce({ data: null, error: { code: '22023', message: 'invalid_contact_event' } });
    await expect(confirmContactEvent(O, input(), captureOwnerToken())).rejects.toMatchObject({ code: 'invalid_input' });
    api.rpc.mockResolvedValueOnce({ data: null, error: { code: 'P0002', message: 'private_target_unavailable' } });
    await expect(confirmContactEvent(O, input(), captureOwnerToken())).rejects.toMatchObject({ code: 'target_unavailable' });
    api.rpc.mockResolvedValueOnce({ data: null, error: { code: 'P0002', message: 'private detail' } });
    await expect(confirmContactEvent(O, input(), captureOwnerToken())).rejects.toMatchObject({ code: 'unavailable' });
  });
  it('only the documented conflict is distinguishable; errors never leak server text or call legacy RPC', async () => {
    api.rpc.mockResolvedValueOnce({ data: null, error: { code: '23505', message: 'contact_event_conflict' } });
    await expect(confirmContactEvent(O, input(), captureOwnerToken())).rejects.toMatchObject({ code: 'conflict' });
    api.rpc.mockResolvedValueOnce({ data: null, error: { code: '23505', message: 'private database details' } });
    await expect(confirmContactEvent(O, input(), captureOwnerToken())).rejects.toEqual(new ContactEventError('unavailable'));
    expect(api.rpc.mock.calls.every(call => call[0] === 'confirm_contact_event')).toBe(true);
  });
  it('copies input and token before queue/auth awaits', async () => {
    const held = deferred<ReturnType<typeof session>>(); api.session.mockReturnValue(held.promise);
    const draft = input(); const token = captureOwnerToken(); const save = confirmContactEvent(O, draft, token);
    draft.subject = 'mutated'; draft.materialRefs[0].version = 'mutated'; token.uid = B;
    held.resolve(session(A)); await save;
    expect(api.rpc.mock.calls[0][1]).toMatchObject({ p_subject: input().subject, p_materials: input().materialRefs, p_expected_device_id: A });
  });
  it.each([
    { event: { ...event(), device_id: B } }, { event: { ...event(), opportunity_id: 'other' } },
    { event: { ...event(), event_id: '11111111-1111-8111-8111-111111111111' } },
    { event: { ...event(), body: 'changed' } }, { event: { ...event(), recipient: 'changed@example.edu' } },
    { event: { ...event(), materials: [] } }, { event: { ...event(), actual_sent_at: '2026-09-24T00:00:00Z' } },
    { event: { ...event(), confirmed_at: 'invalid' } }, { interaction: null },
    { interaction: { ...interaction(), interaction_type: 'unknown' } },
    { interaction: { ...interaction(), device_id: B } }, { interaction: { ...interaction(), opportunity_id: 'wrong' } },
    { interaction: { ...interaction(), remind_at: '2026-02-30' } },
    { interaction: { ...interaction(), updated_at: null } }, { replayed: 'true' },
  ])('rejects a successful but invalid receipt %#', patch => {
    api.rpc.mockResolvedValue({ data: { ...receipt().data, ...patch }, error: null });
    return expect(confirmContactEvent(O, input(), captureOwnerToken())).rejects.toMatchObject({ code: 'invalid_receipt' });
  });
  it('accepts an offset-equivalent actual send timestamp', async () => {
    const value = { ...input(), actualSentAt: '2026-09-25T05:00:00.123456-05:00' };
    api.rpc.mockResolvedValue({ ...receipt(), data: { ...receipt().data, event: { ...event(), actual_sent_at: '2026-09-25T10:00:00.123456Z' } } });
    expect((await confirmContactEvent(O, value, captureOwnerToken())).event.actualSentAt).toBe('2026-09-25T10:00:00.123456Z');
  });
  it('does not dispatch a stale-owner token or bad input', async () => {
    const token = captureOwnerToken(); await owner(B);
    await expect(confirmContactEvent(O, input(), token)).rejects.toBeInstanceOf(OwnerMismatchError);
    await owner(A);
    await expect(confirmContactEvent(O, { ...input(), body: '' }, captureOwnerToken())).rejects.toMatchObject({ code: 'invalid_input' });
    expect(api.rpc).not.toHaveBeenCalled();
  });
});
describe('owner-bound paginated contact history', () => {
  it('loads only the owner/target, preserving exact snapshots and ordering', async () => {
    const result = await getContactEvents(O);
    expect(result.events).toHaveLength(1); expect(result).toMatchObject({ nextCursor: null, hasMore: false });
    expect(api.from).toHaveBeenCalledWith('contact_events');
    expect(api.eq.mock.calls).toEqual([['device_id', A], ['opportunity_id', O]]);
    expect(api.order.mock.calls).toEqual([['confirmed_at', { ascending: false }], ['event_id', { ascending: false }]]);
    expect(api.limit).toHaveBeenCalledWith(21);
  });
  it('only a successful empty array proves empty history', async () => {
    api.limit.mockResolvedValue({ data: [], error: null });
    expect(await getContactEvents(O)).toEqual({ events: [], hasMore: false, nextCursor: null });
  });
  it('uses the last displayed event as a microsecond cursor and loads older tied IDs', async () => {
    const older = { ...event(), event_id: '11111111-1111-8111-8111-111111111111' };
    api.limit.mockResolvedValue({ data: [event(), older], error: null });
    const page = await getContactEvents(O, { limit: 1 });
    expect(page.events).toHaveLength(1); expect(page.hasMore).toBe(true);
    expect(page.nextCursor).toEqual({ confirmedAt: event().confirmed_at, id: event().event_id });
    api.limit.mockResolvedValue({ data: [older], error: null });
    await getContactEvents(O, { cursor: page.nextCursor!, limit: 1 });
    expect(api.or).toHaveBeenCalledWith(`confirmed_at.lt.${event().confirmed_at},and(confirmed_at.eq.${event().confirmed_at},event_id.lt.${event().event_id})`);
  });
  it.each([null, {}, [event(), event()], [{ ...event(), device_id: B }], [{ ...event(), opportunity_id: 'other' }], [{ ...event(), body: '' }], [{ ...event(), confirmed_at: 'invalid' }]])('rejects malformed/unrelated successful rows %#', async data => {
    api.limit.mockResolvedValue({ data, error: null });
    await expect(getContactEvents(O)).rejects.toBeInstanceOf(ContactHistoryLoadError);
  });
  it('rejects out-of-order results rather than skipping them on the next page', async () => {
    api.limit.mockResolvedValue({ data: [{ ...event(), confirmed_at: '2026-09-25T12:00:00.123455Z' }, event()], error: null });
    await expect(getContactEvents(O)).rejects.toBeInstanceOf(ContactHistoryLoadError);
  });
  it('rejects an item that is not older than the requested cursor', async () => {
    await expect(getContactEvents(O, { cursor: { id: event().event_id, confirmedAt: event().confirmed_at } })).rejects.toBeInstanceOf(ContactHistoryLoadError);
  });
  it.each([0, -1, 101, 1.5, Number.NaN])('rejects invalid limits before reading %s', async limit => {
    await expect(getContactEvents(O, { limit })).rejects.toBeInstanceOf(ContactHistoryLoadError);
    expect(api.from).not.toHaveBeenCalled();
  });
  it('keeps failed transport/schema/permission errors distinct from empty and safe', async () => {
    api.limit.mockResolvedValueOnce({ data: [], error: { message: 'permission denied private body' } });
    await expect(getContactEvents(O)).rejects.toEqual(new ContactHistoryLoadError());
    api.limit.mockRejectedValueOnce(new Error('private details'));
    await expect(getContactEvents(O)).rejects.toEqual(new ContactHistoryLoadError());
  });
});
describe.each(['read', 'write'] as const)('contact ledger %s retirement', operation => {
  const start = () => operation === 'read' ? getContactEvents(O) : confirmContactEvent(O, input(), captureOwnerToken());
  it('does not dispatch after owner changes during auth', async () => {
    const held = deferred<ReturnType<typeof session>>(); api.session.mockReturnValue(held.promise);
    const running = start(); const assertion = expect(running).rejects.toBeInstanceOf(OwnerMismatchError);
    await waitFor(() => expect(api.session).toHaveBeenCalled());
    await owner(B); held.resolve(session(B)); await assertion;
    expect(api.from).not.toHaveBeenCalled(); expect(api.rpc).not.toHaveBeenCalled();
  });
  it.each(['owner', 'generation'] as const)('rejects late results after %s change', async change => {
    const held = deferred<unknown>(); const fn = operation === 'read' ? api.limit : api.rpc; fn.mockReturnValue(held.promise);
    const running = start(); const assertion = expect(running).rejects.toBeInstanceOf(OwnerMismatchError);
    await waitFor(() => expect(fn).toHaveBeenCalled());
    if (change === 'owner') await owner(B);
    else {
      const before = captureOwnerToken(); const marker = JSON.parse(localStorage.getItem('ofe_local_identity_owner')!);
      localStorage.setItem('ofe_local_identity_owner', JSON.stringify({ ...marker, generation: marker.generation + 1, phase: 'switching' }));
      await syncLocalIdentityOwner(A); expect(captureOwnerToken().generation).not.toBe(before.generation);
    }
    held.resolve(operation === 'read' ? { data: [event()], error: null } : receipt()); await assertion;
  });
});
