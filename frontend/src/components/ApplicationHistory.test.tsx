import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { translate, type Locale } from '@/i18n/translate';
import type { ApplicationEvent } from '@/lib/application-ledger';

const mocks = vi.hoisted(() => ({ getApplicationEvents: vi.fn(), locale: 'en' as 'en' | 'zh' }));
vi.mock('@/lib/supabase', () => ({ getApplicationEvents: (...args: unknown[]) => mocks.getApplicationEvents(...args) }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ locale: mocks.locale, t: (key: string, vars?: Record<string, string | number>) => translate(mocks.locale, key, vars) }) }));
import ApplicationHistory from './ApplicationHistory';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from '@/lib/identity-owner';

const props = { opportunityId: 'opp-A', refreshKey: '2026-09-25T12:00:00Z' };
const cursor = { confirmedAt: '2026-09-25T11:00:00Z', id: 'event-A' };
function event(overrides: Partial<ApplicationEvent> = {}): ApplicationEvent {
  return { id: 'event-A', deviceId: 'owner-A', opportunityId: 'opp-A', channel: 'web_form', destination: 'Research program portal',
    notes: 'My submitted application.\nResearch experience included.', submittedAt: '2026-09-24T15:00:00Z', confirmedAt: '2026-09-25T11:00:00Z',
    resultNote: 'Awaiting response', nextStep: 'Check the portal next week', confirmationSource: 'user_reported', ...overrides };
}
function page(events: ApplicationEvent[], nextCursor: typeof cursor | null = null) { return { events, nextCursor, hasMore: nextCursor !== null }; }
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: Error) => void; const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; }
async function owner(uid: string) { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); }
const label = (key: string, locale: Locale = 'en') => translate(locale, `applicationRecord.history.${key}`);
beforeEach(async () => { localStorage.clear(); await owner('owner-A'); mocks.getApplicationEvents.mockReset(); mocks.locale = 'en'; });

describe('ApplicationHistory — truthful saved snapshots', () => {
  it('shows loading without claiming empty history or using the interaction update as a submission date', async () => {
    mocks.getApplicationEvents.mockReturnValue(new Promise(() => {}));
    const { container } = render(<ApplicationHistory {...props} />);
    expect(screen.getByRole('status')).toHaveTextContent(label('loading'));
    expect(screen.queryByText(label('empty'))).not.toBeInTheDocument();
    expect(container.querySelector('time')).toBeNull();
    await waitFor(() => expect(mocks.getApplicationEvents).toHaveBeenCalledWith('opp-A'));
  });

  it('distinguishes an authoritative empty ledger from absence of prior applications', async () => {
    mocks.getApplicationEvents.mockResolvedValue(page([]));
    render(<ApplicationHistory {...props} />);
    expect(await screen.findByText(label('empty'))).toHaveTextContent('Earlier submissions may not have a record');
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
    expect(screen.queryByText(label('error'))).not.toBeInTheDocument();
  });

  it('shows each application record with separate user-reported and server confirmation dates', async () => {
    mocks.getApplicationEvents.mockResolvedValue(page([event()]));
    const { container } = render(<ApplicationHistory {...props} />);
    await screen.findByText('Research program portal');
    const details = container.querySelector('details')!;
    expect(details).not.toHaveAttribute('open');
    expect(within(details).getByText(label('channels.web_form'))).toBeInTheDocument();
    expect(within(details).getByText(label('submittedAt'))).toBeInTheDocument();
    expect(within(details).getByText(label('confirmedAt'))).toBeInTheDocument();
    expect(Array.from(details.querySelectorAll('time')).map(el => el.dateTime)).toEqual(['2026-09-24T15:00:00Z', '2026-09-25T11:00:00Z']);
    expect(details).toHaveTextContent('Research experience included.');
    expect(screen.getByText(label('hint'))).toHaveTextContent('have not been verified');
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('does not infer a missing submission time from the confirmed or updated time', async () => {
    mocks.getApplicationEvents.mockResolvedValue(page([event({ submittedAt: null })]));
    const { container } = render(<ApplicationHistory {...props} />);
    await screen.findByText(label('submittedUnknown'));
    expect(container.querySelectorAll('time')).toHaveLength(1);
    expect(container.querySelector('time')).toHaveAttribute('dateTime', '2026-09-25T11:00:00Z');
  });

  it('renders hostile destination and notes as plain text without executable markup', async () => {
    const text = '<img src=x onerror="alert(1)">\n[click](javascript:alert(1))';
    mocks.getApplicationEvents.mockResolvedValue(page([event({ destination: '<script>secret()</script>', notes: text, resultNote: '<svg onload=alert(1)>', nextStep: 'javascript:alert(1)' })]));
    const { container } = render(<ApplicationHistory {...props} />);
    await screen.findByText('<script>secret()</script>');
    expect(container.textContent).toContain(text);
    expect(container.querySelector('script,img,svg,a')).toBeNull();
    expect(container.querySelector('dd.whitespace-pre-wrap')?.closest('dl')).toHaveClass('[overflow-wrap:anywhere]', { exact: false });
  });

  it('keeps the record ID in optional details and shows the reported result without claiming verification', async () => {
    mocks.getApplicationEvents.mockResolvedValue(page([event()]));
    render(<ApplicationHistory {...props} />);
    await screen.findByText('Research program portal');
    const details = screen.getByTestId('application-event-details');
    expect(details).not.toHaveAttribute('open');
    fireEvent.click(within(details).getByText(label('recordDetails')));
    expect(details).toHaveAttribute('open');
    expect(within(details).getByText('event-A')).toBeInTheDocument();
    expect(screen.getByText(label('resultNote'))).toBeInTheDocument();
    expect(screen.getByText('Awaiting response')).toBeInTheDocument();
    expect(screen.getByText('Check the portal next week')).toBeInTheDocument();
  });

  it('does not invent notes, results or next steps when none were provided', async () => {
    mocks.getApplicationEvents.mockResolvedValue(page([event({ notes: null, resultNote: null, nextStep: null, channel: 'other' })]));
    render(<ApplicationHistory {...props} />);
    await screen.findByText(label('channels.other'));
    for (const field of ['notes', 'resultNote', 'nextStep']) expect(screen.queryByText(label(field))).not.toBeInTheDocument();
  });

  it('renders the Chinese copy without falling back to English', async () => {
    mocks.locale = 'zh'; mocks.getApplicationEvents.mockResolvedValue(page([event({ channel: 'email' })]));
    render(<ApplicationHistory {...props} />);
    await screen.findByText('申请记录');
    await screen.findByText('你填写的提交时间');
    expect(screen.getByText('确认保存时间')).toBeInTheDocument();
    expect(screen.getByText('根据你的自述保存，尚未核实提交情况或结果。')).toBeInTheDocument();
    expect(screen.getByText('邮件')).toBeInTheDocument();
  });

  it('uses a safe error and offers retry, never mislabeling failure as empty', async () => {
    mocks.getApplicationEvents.mockRejectedValueOnce(new Error('private database error')).mockResolvedValueOnce(page([event()]));
    render(<ApplicationHistory {...props} />);
    expect(await screen.findByRole('alert')).toHaveTextContent(label('error'));
    expect(screen.queryByText('private database error')).not.toBeInTheDocument();
    expect(screen.queryByText(label('empty'))).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: label('retry') }));
    await screen.findByText('Research program portal');
    expect(mocks.getApplicationEvents).toHaveBeenCalledTimes(2);
  });
});

describe('ApplicationHistory — pagination and private read scopes', () => {
  it('loads older records using the cursor and honestly labels incomplete history', async () => {
    mocks.getApplicationEvents.mockResolvedValueOnce(page([event()], cursor)).mockResolvedValueOnce(page([event({ id: 'event-B', destination: 'Older application' })]));
    render(<ApplicationHistory {...props} />);
    await screen.findByText('Records shown: 1. More records are available.');
    fireEvent.click(screen.getByRole('button', { name: label('loadMore') }));
    await screen.findByText('Older application');
    expect(mocks.getApplicationEvents).toHaveBeenLastCalledWith('opp-A', { cursor });
    expect(screen.getByText('Saved records: 2')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: label('loadMore') })).not.toBeInTheDocument();
  });

  it('prevents repeated load-more requests while a page is pending', async () => {
    const pending = deferred<ReturnType<typeof page>>();
    mocks.getApplicationEvents.mockResolvedValueOnce(page([event()], cursor)).mockReturnValueOnce(pending.promise);
    render(<ApplicationHistory {...props} />);
    const button = await screen.findByRole('button', { name: label('loadMore') });
    fireEvent.click(button); fireEvent.click(button);
    expect(button).toBeDisabled();
    expect(mocks.getApplicationEvents).toHaveBeenCalledTimes(2);
    await act(async () => { pending.resolve(page([])); });
    expect(screen.queryByRole('button', { name: label('loadingMore') })).not.toBeInTheDocument();
  });

  it('preserves current rows when a later page fails and retries the same cursor', async () => {
    mocks.getApplicationEvents.mockResolvedValueOnce(page([event()], cursor)).mockRejectedValueOnce(new Error('hidden')).mockResolvedValueOnce(page([event({ id: 'event-B', destination: 'Recovered older application' })]));
    render(<ApplicationHistory {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: label('loadMore') }));
    expect(await screen.findByRole('alert')).toHaveTextContent(label('moreError'));
    expect(screen.getByText('Research program portal')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: label('retryMore') }));
    await screen.findByText('Recovered older application');
    expect(mocks.getApplicationEvents.mock.calls.slice(1)).toEqual([['opp-A', { cursor }], ['opp-A', { cursor }]]);
  });

  it('does not repeat an event already rendered by an earlier page', async () => {
    mocks.getApplicationEvents.mockResolvedValueOnce(page([event()], cursor)).mockResolvedValueOnce(page([event(), event({ id: 'event-B', destination: 'Second' })]));
    render(<ApplicationHistory {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: label('loadMore') }));
    await screen.findByText('Second');
    expect(screen.getAllByText('Research program portal')).toHaveLength(1);
    expect(screen.getByText('Saved records: 2')).toBeInTheDocument();
  });

  it('refreshes from page one after a new application confirmation without unmounting the open record', async () => {
    const refreshed = deferred<ReturnType<typeof page>>();
    mocks.getApplicationEvents.mockResolvedValueOnce(page([event()], cursor)).mockReturnValueOnce(refreshed.promise);
    const { rerender } = render(<ApplicationHistory {...props} />);
    const record = (await screen.findByText('Research program portal')).closest('details')!;
    record.open = true;
    rerender(<ApplicationHistory {...props} refreshKey="2026-09-25T13:00:00Z" />);
    // Material uploads live inside this record; unmounting it would abort them silently.
    expect(record.isConnected).toBe(true);
    expect(screen.getByRole('status')).toHaveTextContent(label('loading'));
    expect(screen.getByRole('button', { name: label('loadMore') })).toBeDisabled();
    await act(async () => { refreshed.resolve(page([event({ id: 'event-B', destination: 'New confirmation' }), event()])); });
    expect(screen.getByText('New confirmation')).toBeInTheDocument();
    expect(record.isConnected).toBe(true); expect(record.open).toBe(true);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(mocks.getApplicationEvents.mock.calls).toEqual([['opp-A'], ['opp-A']]);
  });

  it('keeps an older-page record mounted when the refreshed page one does not include it', async () => {
    const refreshed = deferred<ReturnType<typeof page>>();
    const older = { confirmedAt: '2026-09-20T11:00:00Z', id: 'event-B' };
    mocks.getApplicationEvents.mockResolvedValueOnce(page([event()], cursor))
      .mockResolvedValueOnce(page([event({ id: 'event-B', destination: 'Older portal', confirmedAt: older.confirmedAt })], older))
      .mockReturnValueOnce(refreshed.promise);
    const { rerender } = render(<ApplicationHistory {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: label('loadMore') }));
    const record = (await screen.findByText('Older portal')).closest('details')!;
    record.open = true;
    rerender(<ApplicationHistory {...props} refreshKey="2026-09-25T13:00:00Z" />);
    await act(async () => { refreshed.resolve(page([event({ id: 'event-N', destination: 'New confirmation', confirmedAt: '2026-09-25T13:00:00Z' }), event()], cursor)); });
    // Its material upload lives inside this record; page one alone would unmount and abort it.
    expect(record.isConnected).toBe(true); expect(record.open).toBe(true);
    expect(Array.from(document.querySelectorAll('[data-testid="application-history"] ol > li > details > summary > span:nth-child(2)')).map(span => span.textContent))
      .toEqual(['New confirmation', 'Research program portal', 'Older portal']);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('keeps the loaded records beside the error when the refreshed read fails, then retries', async () => {
    const refreshed = deferred<ReturnType<typeof page>>();
    mocks.getApplicationEvents.mockResolvedValueOnce(page([event()])).mockReturnValueOnce(refreshed.promise)
      .mockResolvedValueOnce(page([event({ id: 'event-N', destination: 'New confirmation' }), event()]));
    const { rerender } = render(<ApplicationHistory {...props} />);
    const record = (await screen.findByText('Research program portal')).closest('details')!;
    record.open = true;
    rerender(<ApplicationHistory {...props} refreshKey="2026-09-25T13:00:00Z" />);
    await act(async () => { refreshed.reject(new Error('offline')); });
    expect(screen.getByRole('alert')).toHaveTextContent(label('error'));
    expect(screen.queryByText('offline')).not.toBeInTheDocument();
    expect(record.isConnected).toBe(true); expect(record.open).toBe(true);
    expect(screen.queryByText(label('empty'))).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: label('retry') }));
    await screen.findByText('New confirmation');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(record.isConnected).toBe(true);
  });

  it('shows the error, not an empty history, when a refresh of an empty history fails', async () => {
    const refreshed = deferred<ReturnType<typeof page>>();
    mocks.getApplicationEvents.mockResolvedValueOnce(page([])).mockReturnValueOnce(refreshed.promise);
    const { rerender } = render(<ApplicationHistory {...props} />);
    await screen.findByText(label('empty'));
    rerender(<ApplicationHistory {...props} refreshKey="2026-09-25T13:00:00Z" />);
    await act(async () => { refreshed.reject(new Error('offline')); });
    expect(screen.getByRole('alert')).toHaveTextContent(label('error'));
    expect(screen.queryByText(label('empty'))).not.toBeInTheDocument();
  });

  it('retracts the previous opportunity history immediately while the new read waits', async () => {
    mocks.getApplicationEvents.mockResolvedValueOnce(page([event()])).mockReturnValueOnce(new Promise(() => {}));
    const { rerender } = render(<ApplicationHistory {...props} />);
    await screen.findByText('Research program portal');
    rerender(<ApplicationHistory {...props} opportunityId="opp-B" />);
    expect(screen.queryByText('Research program portal')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(label('loading'));
  });

  it.each(['resolves', 'rejects'] as const)('ignores a late initial read for another opportunity that %s', async outcome => {
    const pending = deferred<ReturnType<typeof page>>();
    mocks.getApplicationEvents.mockReturnValueOnce(pending.promise).mockResolvedValueOnce(page([]));
    const { rerender } = render(<ApplicationHistory {...props} />);
    await waitFor(() => expect(mocks.getApplicationEvents).toHaveBeenCalledTimes(1));
    rerender(<ApplicationHistory {...props} opportunityId="opp-B" />);
    await screen.findByText(label('empty'));
    await act(async () => { if (outcome === 'resolves') pending.resolve(page([event()])); else pending.reject(new Error('late failure')); });
    expect(screen.queryByText('Research program portal')).not.toBeInTheDocument();
    expect(screen.getByText(label('empty'))).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('retires an old page request after the parent refreshes the same opportunity', async () => {
    const pending = deferred<ReturnType<typeof page>>();
    mocks.getApplicationEvents.mockResolvedValueOnce(page([event()], cursor)).mockReturnValueOnce(pending.promise).mockResolvedValueOnce(page([event({ id: 'event-new', destination: 'Latest' })]));
    const { rerender } = render(<ApplicationHistory {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: label('loadMore') }));
    rerender(<ApplicationHistory {...props} refreshKey="new-confirmation" />);
    await screen.findByText('Latest');
    await act(async () => { pending.resolve(page([event({ id: 'event-old', destination: 'Retired page' })])); });
    expect(screen.queryByText('Retired page')).not.toBeInTheDocument();
    expect(screen.getByText('Saved records: 1')).toBeInTheDocument();
  });

  it('does not carry an old page error into a different opportunity', async () => {
    const pending = deferred<ReturnType<typeof page>>();
    mocks.getApplicationEvents.mockResolvedValueOnce(page([event()], cursor)).mockReturnValueOnce(pending.promise).mockResolvedValueOnce(page([]));
    const { rerender } = render(<ApplicationHistory {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: label('loadMore') }));
    rerender(<ApplicationHistory {...props} opportunityId="opp-B" />);
    await screen.findByText(label('empty'));
    await act(async () => { pending.reject(new Error('late private page failure')); });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: label('retryMore') })).not.toBeInTheDocument();
  });

  it('owner change retracts completed private history before the parent remounts', async () => {
    mocks.getApplicationEvents.mockResolvedValueOnce(page([event()])).mockReturnValue(new Promise(() => {}));
    render(<ApplicationHistory {...props} />);
    await screen.findByText('Research program portal');
    await act(async () => { await owner('owner-B'); });
    expect(screen.queryByText('Research program portal')).not.toBeInTheDocument();
    expect(screen.queryByText('Research program portal', { exact: false })).not.toBeInTheDocument();
  });

  it('ignores an old-owner page even after returning to the same uid in a newer generation', async () => {
    const pending = deferred<ReturnType<typeof page>>();
    mocks.getApplicationEvents.mockResolvedValueOnce(page([event()], cursor)).mockReturnValueOnce(pending.promise).mockResolvedValue(page([]));
    render(<ApplicationHistory {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: label('loadMore') }));
    await act(async () => { await owner('owner-B'); });
    await act(async () => { await owner('owner-A'); });
    await screen.findByText(label('empty'));
    await act(async () => { pending.resolve(page([event({ destination: 'Stale owner application' })])); });
    expect(screen.queryByText('Stale owner application')).not.toBeInTheDocument();
  });

  it('does not query a private ledger before identity becomes ready', async () => {
    await act(async () => { advanceOwnerEpoch(null); });
    render(<ApplicationHistory {...props} />);
    await screen.findByRole('alert');
    expect(mocks.getApplicationEvents).not.toHaveBeenCalled();
  });

  it('observes late read rejection after unmount without showing a stale error', async () => {
    const pending = deferred<ReturnType<typeof page>>();
    mocks.getApplicationEvents.mockReturnValue(pending.promise);
    const { unmount } = render(<ApplicationHistory {...props} />);
    await waitFor(() => expect(mocks.getApplicationEvents).toHaveBeenCalledTimes(1));
    unmount();
    await act(async () => { pending.reject(new Error('late private read failure')); });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
