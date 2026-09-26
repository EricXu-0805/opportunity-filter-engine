import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { translate, type Locale } from '@/i18n/translate';
import type { ContactEvent } from '@/lib/contact-ledger';

const mocks = vi.hoisted(() => ({ getContactEvents: vi.fn(), locale: 'en' as 'en' | 'zh' }));
vi.mock('@/lib/supabase', () => ({ getContactEvents: (...args: unknown[]) => mocks.getContactEvents(...args) }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ locale: mocks.locale, t: (key: string, vars?: Record<string, string | number>) => translate(mocks.locale, key, vars) }) }));
import ContactHistory from './ContactHistory';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from '@/lib/identity-owner';

const props = { opportunityId: 'opp-A', refreshKey: '2026-09-25T12:00:00Z' };
const cursor = { confirmedAt: '2026-09-25T11:00:00Z', id: 'event-A' };
function event(overrides: Partial<ContactEvent> = {}): ContactEvent {
  return { id: 'event-A', deviceId: 'owner-A', opportunityId: 'opp-A', recipient: 'professor@example.edu', subject: 'Research question',
    body: 'Hello Professor,\nMy question about your project.', actualSentAt: '2026-09-24T15:00:00Z', confirmedAt: '2026-09-25T11:00:00Z',
    materialRefs: [{ kind: 'profile', version: 'profile-v1' }], confirmationSource: 'user_reported', ...overrides };
}
function page(events: ContactEvent[], nextCursor: typeof cursor | null = null) { return { events, nextCursor, hasMore: nextCursor !== null }; }
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: Error) => void; const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; }
async function owner(uid: string) { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); }
const label = (key: string, locale: Locale = 'en') => translate(locale, `detail.tracker.contactHistory.${key}`);
beforeEach(async () => { localStorage.clear(); await owner('owner-A'); mocks.getContactEvents.mockReset(); mocks.locale = 'en'; });

describe('ContactHistory — truthful saved snapshots', () => {
  it('shows loading without claiming empty history or using the interaction update as a contact date', async () => {
    mocks.getContactEvents.mockReturnValue(new Promise(() => {}));
    const { container } = render(<ContactHistory {...props} />);
    expect(screen.getByRole('status')).toHaveTextContent(label('loading'));
    expect(screen.queryByText(label('empty'))).not.toBeInTheDocument();
    expect(container.querySelector('time')).toBeNull();
    await waitFor(() => expect(mocks.getContactEvents).toHaveBeenCalledWith('opp-A'));
  });

  it('distinguishes an authoritative empty ledger from absence of prior contacts', async () => {
    mocks.getContactEvents.mockResolvedValue(page([]));
    render(<ContactHistory {...props} />);
    expect(await screen.findByText(label('empty'))).toHaveTextContent('Earlier contacts may not have a snapshot');
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
    expect(screen.queryByText(label('error'))).not.toBeInTheDocument();
  });

  it('shows each message snapshot with separate user-reported and server confirmation dates', async () => {
    mocks.getContactEvents.mockResolvedValue(page([event()]));
    const { container } = render(<ContactHistory {...props} />);
    await screen.findByText('Research question');
    const details = container.querySelector('details')!;
    expect(details).not.toHaveAttribute('open');
    expect(within(details).getByText('professor@example.edu', { exact: false })).toBeInTheDocument();
    expect(within(details).getByText(label('sentAt'))).toBeInTheDocument();
    expect(within(details).getByText(label('confirmedAt'))).toBeInTheDocument();
    expect(Array.from(details.querySelectorAll('time')).map(el => el.dateTime)).toEqual(['2026-09-24T15:00:00Z', '2026-09-25T11:00:00Z']);
    expect(details).toHaveTextContent('My question about your project.');
    expect(screen.getByText(label('hint'))).toHaveTextContent('have not been verified');
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('does not infer a missing sent time from the confirmed or updated time', async () => {
    mocks.getContactEvents.mockResolvedValue(page([event({ actualSentAt: null })]));
    const { container } = render(<ContactHistory {...props} />);
    await screen.findByText(label('sentUnknown'));
    expect(container.querySelectorAll('time')).toHaveLength(1);
    expect(container.querySelector('time')).toHaveAttribute('dateTime', '2026-09-25T11:00:00Z');
  });

  it('renders hostile message, subject and recipient as plain text without executable markup', async () => {
    const text = '<img src=x onerror="alert(1)">\n[click](javascript:alert(1))';
    mocks.getContactEvents.mockResolvedValue(page([event({ subject: '<script>secret()</script>', recipient: '<svg onload=alert(1)>', body: text })]));
    const { container } = render(<ContactHistory {...props} />);
    await screen.findByText('<script>secret()</script>');
    expect(container.textContent).toContain(text);
    expect(container.querySelector('script,img,svg,a')).toBeNull();
    expect(container.querySelector('dd.whitespace-pre-wrap')?.closest('dl')).toHaveClass('[overflow-wrap:anywhere]', { exact: false });
  });

  it('labels material references as source versions and does not claim files were attached', async () => {
    mocks.getContactEvents.mockResolvedValue(page([event({ materialRefs: [
      { kind: 'profile', version: 'profile-v1' }, { kind: 'target', version: 'target-v1' },
      { kind: 'contact_context', version: 'context-v1' }, { kind: 'resume', version: 'resume-v1' },
    ] })]));
    render(<ContactHistory {...props} />);
    await screen.findByText('Research question');
    const sources = screen.getByTestId('contact-event-sources');
    expect(sources).not.toHaveAttribute('open');
    fireEvent.click(within(sources).getByText(label('materials')));
    expect(sources).toHaveAttribute('open');
    expect(screen.getByText(label('materialsHint'))).toHaveTextContent('these references do not contain the attached files');
    for (const version of ['profile-v1', 'target-v1', 'context-v1', 'resume-v1']) expect(screen.getByText(version)).toBeInTheDocument();
  });

  it('shows absent material references and a missing subject explicitly', async () => {
    mocks.getContactEvents.mockResolvedValue(page([event({ subject: '', materialRefs: [] })]));
    render(<ContactHistory {...props} />);
    await screen.findByText(label('noSubject'));
    fireEvent.click(within(screen.getByTestId('contact-event-sources')).getByText(label('materials')));
    expect(screen.getByText(label('noMaterials'))).toBeInTheDocument();
  });

  it('renders the Chinese copy without falling back to English', async () => {
    mocks.locale = 'zh'; mocks.getContactEvents.mockResolvedValue(page([event()]));
    render(<ContactHistory {...props} />);
    await screen.findByText('邮件记录');
    await screen.findByText('你填写的发送时间');
    expect(screen.getByText('确认保存时间')).toBeInTheDocument();
    expect(screen.getByText('根据你的确认保存，尚未核实实际发送或送达。')).toBeInTheDocument();
  });

  it('uses a safe error and offers retry, never mislabeling failure as empty', async () => {
    mocks.getContactEvents.mockRejectedValueOnce(new Error('private database error')).mockResolvedValueOnce(page([event()]));
    render(<ContactHistory {...props} />);
    expect(await screen.findByRole('alert')).toHaveTextContent(label('error'));
    expect(screen.queryByText('private database error')).not.toBeInTheDocument();
    expect(screen.queryByText(label('empty'))).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: label('retry') }));
    await screen.findByText('Research question');
    expect(mocks.getContactEvents).toHaveBeenCalledTimes(2);
  });
});

describe('ContactHistory — pagination and private read scopes', () => {
  it('loads older records using the cursor and honestly labels incomplete history', async () => {
    mocks.getContactEvents.mockResolvedValueOnce(page([event()], cursor)).mockResolvedValueOnce(page([event({ id: 'event-B', subject: 'Older email' })]));
    render(<ContactHistory {...props} />);
    await screen.findByText('Records shown: 1. More records are available.');
    fireEvent.click(screen.getByRole('button', { name: label('loadMore') }));
    await screen.findByText('Older email');
    expect(mocks.getContactEvents).toHaveBeenLastCalledWith('opp-A', { cursor });
    expect(screen.getByText('Saved records: 2')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: label('loadMore') })).not.toBeInTheDocument();
  });

  it('prevents repeated load-more requests while a page is pending', async () => {
    const pending = deferred<ReturnType<typeof page>>();
    mocks.getContactEvents.mockResolvedValueOnce(page([event()], cursor)).mockReturnValueOnce(pending.promise);
    render(<ContactHistory {...props} />);
    const button = await screen.findByRole('button', { name: label('loadMore') });
    fireEvent.click(button); fireEvent.click(button);
    expect(button).toBeDisabled();
    expect(mocks.getContactEvents).toHaveBeenCalledTimes(2);
    await act(async () => { pending.resolve(page([])); });
    expect(screen.queryByRole('button', { name: label('loadingMore') })).not.toBeInTheDocument();
  });

  it('preserves current rows when a later page fails and retries the same cursor', async () => {
    mocks.getContactEvents.mockResolvedValueOnce(page([event()], cursor)).mockRejectedValueOnce(new Error('hidden')).mockResolvedValueOnce(page([event({ id: 'event-B', subject: 'Recovered older email' })]));
    render(<ContactHistory {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: label('loadMore') }));
    expect(await screen.findByRole('alert')).toHaveTextContent(label('moreError'));
    expect(screen.getByText('Research question')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: label('retryMore') }));
    await screen.findByText('Recovered older email');
    expect(mocks.getContactEvents.mock.calls.slice(1)).toEqual([['opp-A', { cursor }], ['opp-A', { cursor }]]);
  });

  it('does not repeat an event already rendered by an earlier page', async () => {
    mocks.getContactEvents.mockResolvedValueOnce(page([event()], cursor)).mockResolvedValueOnce(page([event(), event({ id: 'event-B', subject: 'Second' })]));
    render(<ContactHistory {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: label('loadMore') }));
    await screen.findByText('Second');
    expect(screen.getAllByText('Research question')).toHaveLength(1);
    expect(screen.getByText('Saved records: 2')).toBeInTheDocument();
  });

  it('refreshes from page one after a new contact confirmation changes the parent timestamp', async () => {
    mocks.getContactEvents.mockResolvedValueOnce(page([event()], cursor)).mockResolvedValueOnce(page([event({ id: 'event-B', subject: 'New confirmation' }), event()]));
    const { rerender } = render(<ContactHistory {...props} />);
    await screen.findByText('Research question');
    rerender(<ContactHistory {...props} refreshKey="2026-09-25T13:00:00Z" />);
    expect(screen.queryByText('Research question')).not.toBeInTheDocument();
    await screen.findByText('New confirmation');
    expect(mocks.getContactEvents.mock.calls).toEqual([['opp-A'], ['opp-A']]);
  });

  it('retracts the previous opportunity history immediately while the new read waits', async () => {
    mocks.getContactEvents.mockResolvedValueOnce(page([event()])).mockReturnValueOnce(new Promise(() => {}));
    const { rerender } = render(<ContactHistory {...props} />);
    await screen.findByText('Research question');
    rerender(<ContactHistory {...props} opportunityId="opp-B" />);
    expect(screen.queryByText('Research question')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(label('loading'));
  });

  it('ignores a late initial result for another opportunity', async () => {
    const pending = deferred<ReturnType<typeof page>>();
    mocks.getContactEvents.mockReturnValueOnce(pending.promise).mockResolvedValueOnce(page([]));
    const { rerender } = render(<ContactHistory {...props} />);
    await waitFor(() => expect(mocks.getContactEvents).toHaveBeenCalledTimes(1));
    rerender(<ContactHistory {...props} opportunityId="opp-B" />);
    await screen.findByText(label('empty'));
    await act(async () => { pending.resolve(page([event()])); });
    expect(screen.queryByText('Research question')).not.toBeInTheDocument();
  });

  it('retires an old page request after the parent refreshes the same opportunity', async () => {
    const pending = deferred<ReturnType<typeof page>>();
    mocks.getContactEvents.mockResolvedValueOnce(page([event()], cursor)).mockReturnValueOnce(pending.promise).mockResolvedValueOnce(page([event({ id: 'event-new', subject: 'Latest' })]));
    const { rerender } = render(<ContactHistory {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: label('loadMore') }));
    rerender(<ContactHistory {...props} refreshKey="new-confirmation" />);
    await screen.findByText('Latest');
    await act(async () => { pending.resolve(page([event({ id: 'event-old', subject: 'Retired page' })])); });
    expect(screen.queryByText('Retired page')).not.toBeInTheDocument();
    expect(screen.getByText('Saved records: 1')).toBeInTheDocument();
  });

  it('does not carry an old page error into a different opportunity', async () => {
    const pending = deferred<ReturnType<typeof page>>();
    mocks.getContactEvents.mockResolvedValueOnce(page([event()], cursor)).mockReturnValueOnce(pending.promise).mockResolvedValueOnce(page([]));
    const { rerender } = render(<ContactHistory {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: label('loadMore') }));
    rerender(<ContactHistory {...props} opportunityId="opp-B" />);
    await screen.findByText(label('empty'));
    await act(async () => { pending.reject(new Error('late private page failure')); });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: label('retryMore') })).not.toBeInTheDocument();
  });

  it('owner change retracts completed private history before the parent remounts', async () => {
    mocks.getContactEvents.mockResolvedValueOnce(page([event()])).mockReturnValue(new Promise(() => {}));
    render(<ContactHistory {...props} />);
    await screen.findByText('Research question');
    await act(async () => { await owner('owner-B'); });
    expect(screen.queryByText('Research question')).not.toBeInTheDocument();
    expect(screen.queryByText('professor@example.edu', { exact: false })).not.toBeInTheDocument();
  });

  it('ignores an old-owner page even after returning to the same uid in a newer generation', async () => {
    const pending = deferred<ReturnType<typeof page>>();
    mocks.getContactEvents.mockResolvedValueOnce(page([event()], cursor)).mockReturnValueOnce(pending.promise).mockResolvedValue(page([]));
    render(<ContactHistory {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: label('loadMore') }));
    await act(async () => { await owner('owner-B'); });
    await act(async () => { await owner('owner-A'); });
    await screen.findByText(label('empty'));
    await act(async () => { pending.resolve(page([event({ subject: 'Stale owner email' })])); });
    expect(screen.queryByText('Stale owner email')).not.toBeInTheDocument();
  });

  it('does not query a private ledger before identity becomes ready', async () => {
    await act(async () => { advanceOwnerEpoch(null); });
    render(<ContactHistory {...props} />);
    await screen.findByRole('alert');
    expect(mocks.getContactEvents).not.toHaveBeenCalled();
  });

  it('observes late read rejection after unmount without showing a stale error', async () => {
    const pending = deferred<ReturnType<typeof page>>();
    mocks.getContactEvents.mockReturnValue(pending.promise);
    const { unmount } = render(<ContactHistory {...props} />);
    await waitFor(() => expect(mocks.getContactEvents).toHaveBeenCalledTimes(1));
    unmount();
    await act(async () => { pending.reject(new Error('late private read failure')); });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
