import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const loadArchived = vi.hoisted(() => vi.fn<(token: unknown, archiveId: string) => Promise<Record<string, unknown> | null>>());
vi.mock('@/lib/supabase', () => ({
  loadArchivedGuestProfile: (token: unknown, archiveId: string) => loadArchived(token, archiveId),
}));

import { MergedGuestProfileNotice } from './MergedGuestProfileNotice';
import type { GuestRestoreBlocker, GuestRestoreCheck, GuestRestoreOutcome } from './use-profile-form';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner, type OwnerToken } from '@/lib/identity-owner';
import { clearMergedGuestProfile, readMergedGuestProfile, recordMergedGuestProfile } from '@/lib/merged-guest-profile';

const t = (key: string) => key;
// The archived row the merge wrote, as /auth/callback recorded it.
const ARCHIVE = '6f1c2b9e-0d4a-4c1e-9a57-3f2d8e1b7c40';
const GUEST = { name: 'Guest', major: 'Physics', grade: 'Freshman' };
let sequence = 0;

async function signIn(uid: string): Promise<OwnerToken> {
  await act(async () => { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); });
  return captureOwnerToken();
}
type Archived = Record<string, unknown>;
type Props = {
  ready: boolean;
  blocker: (owner: OwnerToken) => GuestRestoreBlocker | null;
  onRestore: (owner: OwnerToken, read: () => Promise<Archived | null>) => Promise<GuestRestoreOutcome>;
  onCheck: (archived: Archived, owner: OwnerToken) => Promise<GuestRestoreCheck>;
  onStored: (archived: Archived, owner: OwnerToken) => boolean;
};
// The rows a restore was given to save.
let restoredRows: Archived[] = [];
/** onRestore as the hook does it: the row is read with `read`, and a restore
 *  of it ends as `outcome`. */
function restoringTo(outcome: GuestRestoreOutcome | (() => Promise<GuestRestoreOutcome>)) {
  return vi.fn(async (_owner: OwnerToken, read: () => Promise<Archived | null>): Promise<GuestRestoreOutcome> => {
    let row: Archived | null;
    try { row = await read(); } catch { return 'refused'; }
    if (!row) return 'skipped';
    restoredRows.push(row);
    return typeof outcome === 'function' ? outcome() : outcome;
  });
}
function mount(owner: OwnerToken | null, overrides: Partial<Props> = {}) {
  const props: Props = {
    ready: true, blocker: vi.fn((): GuestRestoreBlocker | null => null),
    onRestore: restoringTo('restored'),
    onCheck: vi.fn(async (): Promise<GuestRestoreCheck> => 'restored'), onStored: vi.fn(() => false), ...overrides,
  };
  const view = render(<MergedGuestProfileNotice owner={owner} t={t} {...props} />);
  return {
    ...props,
    update(next: Partial<Props>) {
      Object.assign(props, next);
      view.rerender(<MergedGuestProfileNotice owner={owner} t={t} {...props} />);
    },
  };
}
const notice = () => screen.getByTestId('merged-guest-notice');
const restoreButton = () => screen.getByTestId('restore-guest-profile');
const keepButton = () => screen.getByTestId('keep-account-profile');

beforeEach(() => {
  loadArchived.mockReset().mockImplementation(async () => structuredClone(GUEST));
  restoredRows = [];
  advanceOwnerEpoch(null);
});
afterEach(() => { cleanup(); });

describe('MergedGuestProfileNotice', () => {
  it('says nothing, and reads nothing, when no merge set a guest profile aside', async () => {
    const owner = await signIn(`notice-none-${++sequence}`);
    mount(owner);
    await act(async () => { await Promise.resolve(); });
    expect(screen.queryByTestId('merged-guest-notice')).toBeNull();
    expect(loadArchived).not.toHaveBeenCalled();
  });

  it('offers the archived row the merge wrote and restores that row, read again by its id', async () => {
    const owner = await signIn(`notice-restore-${++sequence}`);
    expect(recordMergedGuestProfile(owner, ARCHIVE)).toBe(true);
    const { onRestore } = mount(owner);

    const restore = await screen.findByTestId('restore-guest-profile');
    expect(notice()).toHaveTextContent('home.mergedGuest.title');
    expect(notice()).toHaveTextContent('home.mergedGuest.body');
    expect(restore).toHaveTextContent('home.mergedGuest.restore');
    expect(loadArchived).toHaveBeenCalledWith(owner, ARCHIVE);

    fireEvent.click(restore);
    await waitFor(() => expect(notice()).toHaveTextContent('home.mergedGuest.restored'));
    expect(loadArchived).toHaveBeenCalledTimes(2);
    expect(loadArchived.mock.calls.every(([token, id]) => token === owner && id === ARCHIVE)).toBe(true);
    expect(onRestore).toHaveBeenCalledOnce();
    expect(onRestore).toHaveBeenCalledWith(owner, expect.any(Function));
    expect(restoredRows).toEqual([GUEST]);
    expect(readMergedGuestProfile(), 'not offered again once restored').toBeNull();
    expect(screen.queryByTestId('restore-guest-profile')).toBeNull();
  });

  it.each([
    ['is no longer in the account'],
    ['was followed by a later merge that archived another guest profile'],
  ])('restores nothing, says so and stops offering when the recorded row %s', async () => {
    // loadArchivedGuestProfile answers null for both: the row by its id is
    // gone, or a revision-less row newer than it exists.
    const owner = await signIn(`notice-gone-${++sequence}`);
    recordMergedGuestProfile(owner, ARCHIVE);
    loadArchived.mockResolvedValue(null);
    const { onRestore } = mount(owner);

    await waitFor(() => expect(notice()).toHaveTextContent('home.mergedGuest.gone'));
    expect(loadArchived).toHaveBeenCalledWith(owner, ARCHIVE);
    expect(screen.queryByTestId('restore-guest-profile')).toBeNull();
    expect(onRestore).not.toHaveBeenCalled();
    expect(readMergedGuestProfile(), 'the notice is removed, not read again on every visit').toBeNull();
    cleanup();
    mount(owner);
    await act(async () => { await Promise.resolve(); });
    expect(loadArchived).toHaveBeenCalledOnce();
  });

  it('restores nothing when a later merge archived another guest profile after the offer was shown', async () => {
    // Browser X merged G1 and left the offer open; G2 then signed in to the
    // same account on a phone. X must not restore G2's profile, nor G1's.
    const owner = await signIn(`notice-superseded-${++sequence}`);
    recordMergedGuestProfile(owner, ARCHIVE);
    const { onRestore } = mount(owner);
    const restore = await screen.findByTestId('restore-guest-profile');
    loadArchived.mockResolvedValue(null);

    fireEvent.click(restore);
    await waitFor(() => expect(notice()).toHaveTextContent('home.mergedGuest.gone'));
    expect(onRestore).toHaveBeenCalledOnce();
    expect(restoredRows).toEqual([]);
    expect(readMergedGuestProfile()).toBeNull();
  });

  /** Offered, and Restore clicked: the row is read again and handed over. */
  async function clickRestore(owner: OwnerToken, overrides: Partial<Props> = {}) {
    recordMergedGuestProfile(owner, ARCHIVE);
    const view = mount(owner, overrides);
    fireEvent.click(await screen.findByTestId('restore-guest-profile'));
    await waitFor(() => expect(view.onRestore).toHaveBeenCalledOnce());
    expect(view.onRestore).toHaveBeenCalledWith(owner, expect.any(Function));
    await waitFor(() => expect(restoredRows).toEqual([GUEST]));
    return view;
  }

  it('holds Restore and Keep while the restore is being saved, and says why Keep waits', async () => {
    const owner = await signIn(`notice-saving-${++sequence}`);
    let finish!: (outcome: GuestRestoreOutcome) => void;
    await clickRestore(owner, { onRestore: restoringTo(() => new Promise<GuestRestoreOutcome>((resolve) => { finish = resolve; })) });

    expect(restoreButton()).toHaveTextContent('home.mergedGuest.restoring');
    expect(restoreButton()).toBeDisabled();
    expect(keepButton(), 'a restore under way could still land after a Keep').toBeDisabled();
    expect(notice()).toHaveTextContent('home.mergedGuest.keepWaits');
    expect(keepButton()).toHaveAttribute('aria-describedby', 'merged-guest-keep-waits');
    await act(async () => { finish('restored'); });
    expect(notice()).toHaveTextContent('home.mergedGuest.restored');
    expect(readMergedGuestProfile()).toBeNull();
  });

  it.each([
    ['offline', 'home.mergedGuest.blocked.offline'],
    ['saving', 'home.mergedGuest.blocked.saving'],
    ['refreshing', 'home.mergedGuest.blocked.refreshing'],
  ] as const)('disables Restore, and says why, while the form says %s', async (reason, copy) => {
    const owner = await signIn(`notice-blocked-${++sequence}`);
    recordMergedGuestProfile(owner, ARCHIVE);
    const view = mount(owner, { blocker: vi.fn((): GuestRestoreBlocker | null => reason) });

    await waitFor(() => expect(restoreButton()).toBeDisabled());
    expect(notice()).toHaveTextContent(copy);
    expect(restoreButton()).toHaveAttribute('aria-describedby', 'merged-guest-blocked');
    fireEvent.click(restoreButton());
    expect(view.onRestore).not.toHaveBeenCalled();
    expect(keepButton(), 'nothing of a restore is pending, so Keep is safe').toBeEnabled();

    view.update({ blocker: vi.fn(() => null) });
    expect(restoreButton()).toBeEnabled();
    expect(notice()).not.toHaveTextContent(copy);
  });

  it("says why when another tab's unsent save holds Restore back, and offers it again once that save is done", async () => {
    const owner = await signIn(`notice-outbox-${++sequence}`);
    recordMergedGuestProfile(owner, ARCHIVE);
    // What the hook's blocker reads: the outbox every tab of the account
    // shares.
    let otherTabSaving = false;
    const view = mount(owner, { blocker: vi.fn((): GuestRestoreBlocker | null => (otherTabSaving ? 'saving' : null)) });
    await waitFor(() => expect(restoreButton()).toBeEnabled());

    // Another tab's write to the outbox reaches this one as a storage event.
    otherTabSaving = true;
    act(() => { window.dispatchEvent(new StorageEvent('storage')); });
    expect(restoreButton()).toBeDisabled();
    expect(notice()).toHaveTextContent('home.mergedGuest.blocked.saving');
    otherTabSaving = false;
    act(() => { window.dispatchEvent(new StorageEvent('storage')); });
    expect(restoreButton()).toBeEnabled();
    expect(notice()).not.toHaveTextContent('home.mergedGuest.blocked.saving');

    // Held back with no event to say so: the click says why instead of
    // doing nothing.
    otherTabSaving = true;
    fireEvent.click(restoreButton());
    expect(view.onRestore).not.toHaveBeenCalled();
    expect(restoreButton()).toBeDisabled();
    expect(notice()).toHaveTextContent('home.mergedGuest.blocked.saving');
  });

  it('follows the connection: going offline or online renders the reason again', async () => {
    const owner = await signIn(`notice-online-${++sequence}`);
    recordMergedGuestProfile(owner, ARCHIVE);
    let online = true;
    mount(owner, { blocker: vi.fn((): GuestRestoreBlocker | null => (online ? null : 'offline')) });
    await waitFor(() => expect(restoreButton()).toBeEnabled());

    online = false;
    act(() => { window.dispatchEvent(new Event('offline')); });
    expect(restoreButton()).toBeDisabled();
    online = true;
    act(() => { window.dispatchEvent(new Event('online')); });
    expect(restoreButton()).toBeEnabled();
  });

  it('after a conflict says the account profile changed elsewhere and offers Restore again', async () => {
    const owner = await signIn(`notice-conflict-${++sequence}`);
    const view = await clickRestore(owner, { onRestore: restoringTo('conflict') });

    await waitFor(() => expect(notice()).toHaveTextContent('home.mergedGuest.conflict'));
    expect(readMergedGuestProfile()).toBe(ARCHIVE);
    expect(keepButton()).toBeEnabled();
    // Held until the form shows the stored profile (the hook's blocker says
    // so), then offered again.
    view.update({ blocker: vi.fn((): GuestRestoreBlocker | null => 'refreshing') });
    expect(restoreButton()).toBeDisabled();
    view.update({ blocker: vi.fn(() => null), onRestore: restoringTo('restored') });
    fireEvent.click(restoreButton());
    await waitFor(() => expect(notice()).toHaveTextContent('home.mergedGuest.restored'));
    expect(readMergedGuestProfile()).toBeNull();
  });

  it.each([
    ['the save was refused', restoringTo('refused')],
    ['the archived row could not be read again', null],
  ])('says nothing was restored and leaves the offer as it was when %s', async (_, onRestore) => {
    const owner = await signIn(`notice-refused-${++sequence}`);
    recordMergedGuestProfile(owner, ARCHIVE);
    mount(owner, onRestore ? { onRestore } : {});
    const restore = await screen.findByTestId('restore-guest-profile');
    if (!onRestore) loadArchived.mockRejectedValueOnce(new Error('offline'));
    fireEvent.click(restore);

    await waitFor(() => expect(notice()).toHaveTextContent('home.mergedGuest.notRestored'));
    expect(readMergedGuestProfile()).toBe(ARCHIVE);
    expect(restoreButton()).toBeEnabled();
    expect(keepButton()).toBeEnabled();
    if (!onRestore) expect(restoredRows).toEqual([]);
  });

  it.each([
    ['restored', 'home.mergedGuest.restored'],
    ['notRestored', 'home.mergedGuest.notRestored'],
    ['changed', 'home.mergedGuest.changed'],
  ] as const)('after a save with no answer, holds Restore and Keep while it checks, then says what it found: %s', async (found, copy) => {
    const owner = await signIn(`notice-unknown-${++sequence}`);
    const stored = found === 'restored';
    let answer!: (check: GuestRestoreCheck) => void;
    const onCheck = vi.fn(() => new Promise<GuestRestoreCheck>((resolve) => { answer = resolve; }));
    await clickRestore(owner, { onRestore: restoringTo('unknown'), onCheck });

    await waitFor(() => expect(notice()).toHaveTextContent('home.mergedGuest.checking'));
    expect(onCheck).toHaveBeenCalledWith(GUEST, owner);
    expect(restoreButton()).toBeDisabled();
    expect(keepButton()).toBeDisabled();
    expect(notice()).toHaveTextContent('home.mergedGuest.keepWaits');
    // Another tab settling the offer meanwhile does not cut the check short.
    clearMergedGuestProfile(owner);
    act(() => { window.dispatchEvent(new StorageEvent('storage')); });
    expect(notice()).toHaveTextContent('home.mergedGuest.checking');
    recordMergedGuestProfile(owner, ARCHIVE);

    await act(async () => { answer(found); });
    expect(notice()).toHaveTextContent(copy);
    expect(notice()).not.toHaveTextContent('home.mergedGuest.keepWaits');
    expect(readMergedGuestProfile()).toBe(stored ? null : ARCHIVE);
    if (!stored) {
      expect(restoreButton()).toBeEnabled();
      expect(keepButton()).toBeEnabled();
    }
  });

  it('keeps holding Restore and Keep while the check cannot read, and checks again on Retry and on reconnecting', async () => {
    const owner = await signIn(`notice-unknown-offline-${++sequence}`);
    const onCheck = vi.fn(async (): Promise<GuestRestoreCheck> => { throw new Error('offline'); });
    const view = await clickRestore(owner, { onRestore: restoringTo('unknown'), onCheck });

    await waitFor(() => expect(notice()).toHaveTextContent('home.mergedGuest.checkFailed'));
    expect(restoreButton()).toBeDisabled();
    expect(keepButton()).toBeDisabled();
    // The message itself says why Keep waits.
    expect(keepButton()).toHaveAttribute('aria-describedby', 'merged-guest-status');
    fireEvent.click(screen.getByText('common.retry'));
    await waitFor(() => expect(onCheck).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(notice()).toHaveTextContent('home.mergedGuest.checkFailed'));

    onCheck.mockImplementation(async () => 'notRestored');
    act(() => { window.dispatchEvent(new Event('online')); });
    await waitFor(() => expect(notice()).toHaveTextContent('home.mergedGuest.notRestored'));
    expect(onCheck).toHaveBeenCalledTimes(3);
    expect(view.onRestore).toHaveBeenCalledOnce();
    expect(readMergedGuestProfile()).toBe(ARCHIVE);
  });

  it('says restored, and does not offer it, when the stored profile already is the guest profile', async () => {
    // A restore whose answer was lost and whose check never finished, then a
    // reload: the stored row is the restore.
    const owner = await signIn(`notice-stored-${++sequence}`);
    recordMergedGuestProfile(owner, ARCHIVE);
    const view = mount(owner, { onStored: vi.fn(() => true) });

    await waitFor(() => expect(notice()).toHaveTextContent('home.mergedGuest.restored'));
    expect(view.onStored).toHaveBeenCalledWith(GUEST, owner);
    expect(screen.queryByTestId('restore-guest-profile')).toBeNull();
    expect(screen.queryByTestId('keep-account-profile')).toBeNull();
    expect(readMergedGuestProfile()).toBeNull();
    expect(view.onRestore).not.toHaveBeenCalled();
  });

  it('stops offering in this tab once another tab restored it or kept the account profile', async () => {
    const owner = await signIn(`notice-tabs-${++sequence}`);
    recordMergedGuestProfile(owner, ARCHIVE);
    const { onRestore } = mount(owner);
    await screen.findByTestId('restore-guest-profile');

    // The other tab removes the marker; this tab hears it as a storage event.
    clearMergedGuestProfile(owner);
    act(() => { window.dispatchEvent(new StorageEvent('storage')); });
    expect(screen.queryByTestId('merged-guest-notice')).toBeNull();
    expect(onRestore).not.toHaveBeenCalled();
  });

  it('lets the student keep the account profile instead, for good', async () => {
    const owner = await signIn(`notice-keep-${++sequence}`);
    recordMergedGuestProfile(owner, ARCHIVE);
    const { onRestore } = mount(owner);

    fireEvent.click(await screen.findByTestId('keep-account-profile'));
    expect(screen.queryByTestId('merged-guest-notice')).toBeNull();
    expect(onRestore).not.toHaveBeenCalled();
    expect(readMergedGuestProfile()).toBeNull();
  });

  it('says so when the archived copy could not be read, and can read it again', async () => {
    const owner = await signIn(`notice-failed-${++sequence}`);
    recordMergedGuestProfile(owner, ARCHIVE);
    loadArchived.mockRejectedValueOnce(new Error('offline'));
    mount(owner);

    await waitFor(() => expect(notice()).toHaveTextContent('home.mergedGuest.loadFailed'));
    expect(screen.queryByTestId('restore-guest-profile')).toBeNull();
    expect(readMergedGuestProfile(), 'a failed read is not "gone"').toBe(ARCHIVE);
    fireEvent.click(screen.getByText('common.retry'));
    expect(await screen.findByTestId('restore-guest-profile')).toBeEnabled();
  });

  it('waits until the form is showing the account profile before reading anything', async () => {
    const owner = await signIn(`notice-wait-${++sequence}`);
    recordMergedGuestProfile(owner, ARCHIVE);
    mount(owner, { ready: false });
    await act(async () => { await Promise.resolve(); });
    expect(loadArchived).not.toHaveBeenCalled();
    expect(screen.queryByTestId('merged-guest-notice')).toBeNull();
  });

  it('is never shown to a different account than the one the guest profile was merged into', async () => {
    const merged = await signIn(`notice-merged-${++sequence}`);
    recordMergedGuestProfile(merged, ARCHIVE);
    const other = await signIn(`notice-other-${sequence}`);
    mount(other);
    await act(async () => { await Promise.resolve(); });
    expect(screen.queryByTestId('merged-guest-notice')).toBeNull();
    expect(loadArchived).not.toHaveBeenCalled();
  });
});
