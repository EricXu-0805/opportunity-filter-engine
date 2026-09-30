import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ApplicationEventInput, ApplicationEvent } from '@/lib/application-ledger';
const m = vi.hoisted(() => ({ read: vi.fn(), prepare: vi.fn(), settle: vi.fn(), discard: vi.fn(), confirm: vi.fn(), get: vi.fn(),
  uid: 'owner-a', epoch: 1, listeners: new Set<() => void>() }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key, locale: 'en' }) }));
vi.mock('@/lib/identity-owner', () => ({
  captureOwnerToken: () => ({ uid: m.uid, epoch: m.epoch, generation: m.epoch }),
  isOwnerTokenValid: (token: { uid: string; epoch: number }, uid: string) => token.uid === m.uid && token.epoch === m.epoch && uid === m.uid,
  onLocalOwnerStateChange: (listener: () => void) => { m.listeners.add(listener); return () => m.listeners.delete(listener); },
}));
vi.mock('@/lib/supabase', () => ({ confirmApplicationEvent: m.confirm, getApplicationEvent: m.get }));
vi.mock('@/lib/application-attempt-storage', () => ({ readPendingApplicationAttempts: m.read, prepareApplicationAttempt: m.prepare, settleApplicationAttempt: m.settle, discardApplicationAttempt: m.discard }));
import ApplicationRecordForm from './ApplicationRecordForm';
import { ApplicationEventError } from '@/lib/application-ledger';
const input: ApplicationEventInput = { id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', channel: 'web_form', destination: 'https://example.edu/apply', submittedAt: null, notes: null, resultNote: null, nextStep: null };
const snapshot = (data: ApplicationEventInput = input, opportunityId = 'target-a'): ApplicationEvent => ({ ...data, deviceId: m.uid, opportunityId, confirmedAt: '2026-09-25T10:00:00Z', confirmationSource: 'user_reported' });
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (cause: Error) => void; const promise = new Promise<T>((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }
function open(onConfirmed = vi.fn(), opportunityId = 'target-a') {
  const view = render(<ApplicationRecordForm opportunityId={opportunityId} ownerReady onConfirmed={onConfirmed} />);
  fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.open' }));
  return { ...view, onConfirmed };
}
function fillAndAttest() {
  fireEvent.change(screen.getByLabelText('applicationRecord.destination'), { target: { value: input.destination } });
  fireEvent.click(screen.getByRole('checkbox', { name: 'applicationRecord.attestation' }));
}
async function submit() { fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.save' })); await waitFor(() => expect(m.confirm).toHaveBeenCalled()); }
beforeEach(() => {
  vi.clearAllMocks(); m.uid = 'owner-a'; m.epoch = 1; m.listeners.clear();
  m.read.mockReturnValue([]);
  m.prepare.mockImplementation(async (_owner, opportunityId, draft) => ({ status: 'ready', attempt: { opportunityId, input: { id: input.id, ...draft } }, reused: false }));
  m.settle.mockResolvedValue(true); m.discard.mockImplementation(async () => { m.read.mockReturnValue([]); return true; });
  m.confirm.mockImplementation(async (target, data) => ({ event: snapshot(data, target), interaction: { type: 'applied' }, replayed: false }));
  m.get.mockResolvedValue(snapshot());
});
describe('ApplicationRecordForm', () => {
  it('requires explicit attestation and opening or closing does not write', () => {
    open();
    expect(screen.getByRole('button', { name: 'applicationRecord.save' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.close' }));
    expect(screen.getByRole('button', { name: 'applicationRecord.open' })).toHaveFocus();
    expect(m.prepare).not.toHaveBeenCalled(); expect(m.confirm).not.toHaveBeenCalled();
  });
  it('saves exact fields after durable preparation and keeps unknown time empty', async () => {
    const { onConfirmed } = open(); fillAndAttest();
    fireEvent.change(screen.getByLabelText('applicationRecord.notes'), { target: { value: '  My note\nSecond line  ' } });
    fireEvent.change(screen.getByLabelText('applicationRecord.resultNote'), { target: { value: 'Portal displayed received' } });
    fireEvent.change(screen.getByLabelText('applicationRecord.nextStep'), { target: { value: 'Wait for interview invitation' } });
    await submit(); await screen.findByText('applicationRecord.saved');
    expect(m.confirm.mock.calls[0][1]).toEqual({ ...input, notes: '  My note\nSecond line  ', resultNote: 'Portal displayed received', nextStep: 'Wait for interview invitation' });
    expect(m.prepare.mock.invocationCallOrder[0]).toBeLessThan(m.confirm.mock.invocationCallOrder[0]);
    expect(m.settle).toHaveBeenCalledWith(expect.objectContaining({ uid: 'owner-a' }), 'target-a', expect.objectContaining({ id: input.id }));
    expect(onConfirmed).toHaveBeenCalledWith({ type: 'applied' });
  });
  it('does not generate another request from double clicks while preparation is pending', async () => {
    const hold = deferred<Awaited<ReturnType<typeof m.prepare>>>(); m.prepare.mockReturnValue(hold.promise);
    open(); fillAndAttest(); const save = screen.getByRole('button', { name: 'applicationRecord.save' });
    fireEvent.click(save); fireEvent.click(save); expect(m.prepare).toHaveBeenCalledTimes(1); expect(m.confirm).not.toHaveBeenCalled();
    await act(async () => hold.resolve({ status: 'ready', attempt: { opportunityId: 'target-a', input }, reused: false }));
    await screen.findByText('applicationRecord.saved'); expect(m.confirm).toHaveBeenCalledTimes(1);
  });
  it('retains exact snapshot after uncertain save and retries same identifier', async () => {
    m.confirm.mockRejectedValueOnce(new Error('response lost'));
    open(); fillAndAttest(); await submit(); await screen.findByText('applicationRecord.unavailable');
    expect(screen.queryByRole('textbox', { name: 'applicationRecord.destination' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.retry' }));
    await screen.findByText('applicationRecord.saved'); expect(m.confirm.mock.calls[1][1]).toEqual(m.confirm.mock.calls[0][1]); expect(m.prepare).toHaveBeenCalledTimes(1);
  });
  it('restores pending receipt after remount without silently creating a new attempt', async () => {
    m.read.mockReturnValue([{ opportunityId: 'target-a', input }]); open();
    expect(screen.getByText(input.destination)).toBeInTheDocument();
    expect(m.confirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.retry' }));
    await screen.findByText('applicationRecord.saved'); expect(m.prepare).not.toHaveBeenCalled(); expect(m.confirm.mock.calls[0][1]).toEqual(input);
  });
  it('recovers a saved event with current null summary and reports removal honestly', async () => {
    m.read.mockReturnValue([{ opportunityId: 'target-a', input }]);
    m.confirm.mockResolvedValue({ event: snapshot(), interaction: null, replayed: true });
    const { onConfirmed } = open();
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.checkSaved' }));
    await screen.findByText('applicationRecord.savedNoStatus'); expect(onConfirmed).toHaveBeenCalledWith(null); expect(m.prepare).not.toHaveBeenCalled();
  });
  it('an absent receipt stays pending and does not become a new attempt', async () => {
    m.read.mockReturnValue([{ opportunityId: 'target-a', input }]); m.get.mockResolvedValue(null); open();
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.checkSaved' }));
    await screen.findByText('applicationRecord.notFound'); expect(m.confirm).not.toHaveBeenCalled(); expect(m.settle).not.toHaveBeenCalled(); expect(screen.getByRole('button', { name: 'applicationRecord.retry' })).toBeEnabled();
  });
  it('a different payload under the pending identifier is a conflict, never settled', async () => {
    m.read.mockReturnValue([{ opportunityId: 'target-a', input }]); m.get.mockResolvedValue(snapshot({ ...input, destination: 'https://different.edu' })); open();
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.checkSaved' })); await screen.findByText('applicationRecord.conflict'); expect(m.confirm).not.toHaveBeenCalled(); expect(m.settle).not.toHaveBeenCalled();
  });
  it('storage failure blocks writes and remains a retryable error', async () => {
    m.read.mockImplementation(() => { throw new Error('unavailable'); }); open();
    expect(screen.getByText('applicationRecord.storageError')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument(); expect(m.confirm).not.toHaveBeenCalled();
    m.read.mockReturnValue([]); fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.retry' })); expect(screen.getByRole('checkbox')).toBeInTheDocument();
  });
  it('does not write when durable preparation fails', async () => {
    m.prepare.mockRejectedValue(new Error('quota exceeded')); open(); fillAndAttest(); fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.save' }));
    await screen.findByText('applicationRecord.storageError'); expect(m.confirm).not.toHaveBeenCalled();
  });
  it('another tab pending attempt is shown without sending either snapshot', async () => {
    m.prepare.mockResolvedValue({ status: 'pending_exists', attempts: [{ opportunityId: 'target-a', input: { ...input, notes: 'Other tab note' } }] });
    open(); fillAndAttest(); fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.save' }));
    await screen.findByText('Other tab note'); expect(screen.getByText('applicationRecord.pendingExists')).toBeInTheDocument(); expect(m.confirm).not.toHaveBeenCalled();
  });
  it('future local submission time fails before durable preparation', async () => {
    open(); fillAndAttest(); fireEvent.change(screen.getByLabelText(/applicationRecord.submittedAt/), { target: { value: '2999-01-01T12:00' } });
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.save' })); await screen.findByText('applicationRecord.invalid'); expect(m.prepare).not.toHaveBeenCalled(); expect(m.confirm).not.toHaveBeenCalled();
  });
  it('invalid destination reported by validator does not become an unavailable-save warning', async () => {
    m.prepare.mockRejectedValue(new ApplicationEventError('invalid_input')); open(); fillAndAttest(); fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.save' }));
    await screen.findByText('applicationRecord.invalid'); expect(m.confirm).not.toHaveBeenCalled();
  });
  it('success with failed local cleanup keeps the original pending attempt', async () => {
    m.settle.mockRejectedValueOnce(new Error('blocked removal')); const { onConfirmed } = open(); fillAndAttest(); await submit();
    await screen.findByText('applicationRecord.storageError'); expect(onConfirmed).toHaveBeenCalledWith({ type: 'applied' });
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.retry' })); await screen.findByText('applicationRecord.saved'); expect(m.confirm.mock.calls[1][1]).toEqual(m.confirm.mock.calls[0][1]);
  });
  it('only explicit another submission opens a clean form after a confirmed record', async () => {
    open(); fillAndAttest(); await submit(); await screen.findByText('applicationRecord.saved');
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.another' }));
    expect(screen.getByLabelText('applicationRecord.destination')).toHaveValue(''); expect(screen.getByRole('checkbox')).not.toBeChecked(); expect(m.confirm).toHaveBeenCalledTimes(1);
  });
  it('publishes the receipt before slow local cleanup and cannot overwrite a newer tracker update afterwards', async () => {
    const cleanup = deferred<boolean>(); m.settle.mockReturnValue(cleanup.promise);
    let current = 'contacted';
    const onConfirmed = vi.fn((record: { type: string } | null) => { current = record?.type ?? 'none'; });
    open(onConfirmed); fillAndAttest(); await submit();
    await waitFor(() => expect(m.settle).toHaveBeenCalled());
    expect(current).toBe('applied'); expect(onConfirmed).toHaveBeenCalledTimes(1);
    current = 'replied'; // a newer saved Tracker update while cleanup is pending
    await act(async () => cleanup.resolve(true));
    await screen.findByText('applicationRecord.saved');
    expect(current).toBe('replied'); expect(onConfirmed).toHaveBeenCalledTimes(1);
  });
  it('late receipt after owner change cannot show or update the new owner', async () => {
    const hold = deferred<unknown>(); m.confirm.mockReturnValue(hold.promise); const { onConfirmed } = open(); fillAndAttest(); await submit();
    act(() => { m.uid = 'owner-b'; m.epoch += 1; m.listeners.forEach(f => f()); });
    await act(async () => hold.resolve({ event: snapshot(), interaction: { type: 'applied' }, replayed: false }));
    expect(onConfirmed).not.toHaveBeenCalled(); expect(m.settle).not.toHaveBeenCalled(); expect(screen.queryByText('applicationRecord.saved')).not.toBeInTheDocument(); expect(screen.queryByText(input.destination)).not.toBeInTheDocument();
  });
  it('late receipt after target change cannot update the new target', async () => {
    const hold = deferred<unknown>(); m.confirm.mockReturnValue(hold.promise); const { onConfirmed, rerender } = open(); fillAndAttest(); await submit();
    rerender(<ApplicationRecordForm opportunityId="target-b" ownerReady onConfirmed={onConfirmed} />);
    await act(async () => hold.resolve({ event: snapshot(), interaction: { type: 'applied' }, replayed: false }));
    expect(onConfirmed).not.toHaveBeenCalled(); expect(m.settle).not.toHaveBeenCalled(); expect(screen.queryByText('applicationRecord.saved')).not.toBeInTheDocument();
  });
  it('a receipt for the current owner can finish after closing and Escape restores focus', async () => {
    const hold = deferred<unknown>(); m.confirm.mockReturnValue(hold.promise); const { onConfirmed } = open(); fillAndAttest(); await submit();
    fireEvent.keyDown(screen.getByText('applicationRecord.pendingTitle'), { key: 'Escape' });
    expect(screen.queryByText('applicationRecord.pendingTitle')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'applicationRecord.open' })).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.open' }));
    expect(screen.getByText('applicationRecord.pendingTitle')).toBeInTheDocument();
    expect(m.confirm).toHaveBeenCalledTimes(1);
    await act(async () => hold.resolve({ event: snapshot(), interaction: { type: 'applied' }, replayed: false }));
    expect(onConfirmed).toHaveBeenCalledWith({ type: 'applied' });
  });
});

it('records a private target only after attestation and preserves its exact ID for Tracker', async () => {
  const privateId = 'private-import:cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  const { onConfirmed } = open(vi.fn(), privateId);
  expect(m.confirm).not.toHaveBeenCalled();
  fillAndAttest(); await submit(); await screen.findByText('applicationRecord.saved');
  expect(m.prepare).toHaveBeenCalledWith(expect.objectContaining({ uid: 'owner-a' }), privateId, expect.objectContaining({ destination: input.destination }));
  expect(m.confirm.mock.calls[0][0]).toBe(privateId);
  expect(m.settle).toHaveBeenCalledWith(expect.objectContaining({ uid: 'owner-a' }), privateId, expect.objectContaining({ id: input.id }));
  expect(onConfirmed).toHaveBeenCalledWith({ type: 'applied' });
});

describe('a pending attempt the server refused as invalid', () => {
  it('offers an explicit owner-bound discard that returns the exact draft to editing', async () => {
    const timed = { ...input, submittedAt: '2026-09-25T15:04:00.000Z', notes: 'Kept note' };
    m.read.mockReturnValue([{ opportunityId: 'target-a', input: timed }]); m.confirm.mockRejectedValue(new ApplicationEventError('invalid_input')); open();
    expect(screen.queryByRole('button', { name: 'applicationRecord.discard' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.retry' }));
    await screen.findByText('applicationRecord.rejectedTime');
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.discard' }));
    await waitFor(() => expect(screen.getByLabelText('applicationRecord.destination')).toHaveValue(input.destination));
    expect(m.discard).toHaveBeenCalledWith(expect.objectContaining({ uid: 'owner-a', epoch: 1 }), 'target-a', input.id);
    const local = new Date(timed.submittedAt); const pad = (n: number) => String(n).padStart(2, '0');
    expect(screen.getByLabelText(/applicationRecord.submittedAt/)).toHaveValue(`${local.getFullYear()}-${pad(local.getMonth() + 1)}-${pad(local.getDate())}T${pad(local.getHours())}:${pad(local.getMinutes())}`);
    expect(screen.getByLabelText('applicationRecord.notes')).toHaveValue('Kept note');
    expect(screen.getByRole('checkbox', { name: 'applicationRecord.attestation' })).not.toBeChecked(); expect(m.confirm).toHaveBeenCalledTimes(1); expect(m.settle).not.toHaveBeenCalled();
  });
  it('a refusal without a time names no clock problem, and an uncertain failure never offers discard', async () => {
    m.read.mockReturnValue([{ opportunityId: 'target-a', input }]); m.confirm.mockRejectedValueOnce(new Error('response lost')).mockRejectedValueOnce(new ApplicationEventError('invalid_input')); open();
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.retry' })); await screen.findByText('applicationRecord.unavailable');
    expect(screen.queryByRole('button', { name: 'applicationRecord.discard' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.retry' })); await screen.findByText('applicationRecord.rejected');
    expect(screen.getByRole('button', { name: 'applicationRecord.discard' })).toBeEnabled();
  });
  it('a failed discard keeps the pending record visible and says so', async () => {
    m.read.mockReturnValue([{ opportunityId: 'target-a', input }]); m.confirm.mockRejectedValue(new ApplicationEventError('invalid_input')); m.discard.mockRejectedValue(new Error('locked')); open();
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.retry' })); await screen.findByText('applicationRecord.rejected');
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.discard' })); await screen.findByText('applicationRecord.storageError');
    expect(screen.getByText(input.destination)).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'applicationRecord.discard' })).toBeEnabled();
  });
});
describe('target re-check before an application write', () => {
  it('refuses visibly and writes nothing when the target is no longer available', async () => {
    const verifyTarget = vi.fn().mockResolvedValue(false);
    render(<ApplicationRecordForm opportunityId="target-a" ownerReady onConfirmed={vi.fn()} verifyTarget={verifyTarget} />);
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.open' })); fillAndAttest();
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.save' })); await screen.findByText('applicationRecord.targetUnavailable');
    expect(verifyTarget).toHaveBeenCalledWith(expect.objectContaining({ uid: 'owner-a', epoch: 1 }));
    expect(m.prepare).not.toHaveBeenCalled(); expect(m.confirm).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'applicationRecord.save' })).toBeEnabled();
  });
  it('shows the target as unavailable when the server refuses a deleted private target', async () => {
    m.confirm.mockRejectedValue(new ApplicationEventError('target_unavailable'));
    const { onConfirmed } = open(); fillAndAttest();
    await submit(); await screen.findByText('applicationRecord.targetUnavailable');
    expect(onConfirmed).not.toHaveBeenCalled(); expect(m.settle).not.toHaveBeenCalled();
  });
  it('a failed re-check is a refusal, and a pending retry is re-checked too', async () => {
    const verifyTarget = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(true);
    m.read.mockReturnValue([{ opportunityId: 'target-a', input }]);
    render(<ApplicationRecordForm opportunityId="target-a" ownerReady onConfirmed={vi.fn()} verifyTarget={verifyTarget} />);
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.open' }));
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.retry' })); await screen.findByText('applicationRecord.targetUnavailable'); expect(m.confirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.retry' })); await screen.findByText('applicationRecord.saved');
    expect(verifyTarget).toHaveBeenCalledTimes(2); expect(verifyTarget.mock.invocationCallOrder[1]).toBeLessThan(m.confirm.mock.invocationCallOrder[0]);
  });
  it('drops a late re-check after an owner change without writing', async () => {
    const hold = deferred<boolean>(); const verifyTarget = vi.fn().mockReturnValue(hold.promise);
    render(<ApplicationRecordForm opportunityId="target-a" ownerReady onConfirmed={vi.fn()} verifyTarget={verifyTarget} />);
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.open' })); fillAndAttest();
    fireEvent.click(screen.getByRole('button', { name: 'applicationRecord.save' })); await waitFor(() => expect(verifyTarget).toHaveBeenCalled());
    act(() => { m.uid = 'owner-b'; m.epoch += 1; m.listeners.forEach(f => f()); });
    await act(async () => hold.resolve(true));
    expect(m.prepare).not.toHaveBeenCalled(); expect(m.confirm).not.toHaveBeenCalled();
  });
});
