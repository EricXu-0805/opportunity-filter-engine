import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { SubmitRow } from './SubmitRow';

const t = ((key: string) => key) as never;

function renderRow(overrides: Partial<Parameters<typeof SubmitRow>[0]> = {}) {
  return render(
    <SubmitRow
      isValid
      shareCopied={false}
      saveStatus="idle"
      hydrationState="ready"
      isSubmitting={false}
      hasConflict={false}
      canRetrySync={false}
      onRetrySync={vi.fn()}
      onKeepMyChanges={vi.fn()}
      onUseCloudVersion={vi.fn()}
      onSubmit={vi.fn()}
      onShare={vi.fn()}
      t={t}
      {...overrides}
    />,
  );
}

describe('SubmitRow — generating matches requires a loaded profile row', () => {
  it('is enabled, with no note, once the row is ready', () => {
    renderRow();
    expect(screen.getByTestId('generate-matches')).not.toBeDisabled();
    expect(screen.queryByTestId('hydration-note')).toBeNull();
  });

  it('is disabled while the row is still loading, and says so', () => {
    renderRow({ hydrationState: 'loading' });
    expect(screen.getByTestId('generate-matches')).toBeDisabled();
    expect(screen.getByTestId('hydration-note').textContent).toBe('home.actions.profileLoading');
  });

  it('is disabled when the row could not be read, with the failure reason — not the loading one', () => {
    renderRow({ hydrationState: 'failed' });
    expect(screen.getByTestId('generate-matches')).toBeDisabled();
    expect(screen.getByTestId('hydration-note').textContent).toBe('home.actions.profileLoadFailed');
  });

  it('stays disabled for an incomplete profile even when the row is ready', () => {
    renderRow({ isValid: false });
    expect(screen.getByTestId('generate-matches')).toBeDisabled();
  });

  it.each([
    ['cloud-failed', 'home.actions.profileCloudFailed'],
    ['device-failed', 'home.actions.profileDeviceFailed'],
    ['error', 'home.actions.profileSaveFailed'],
  ] as const)(
    'shows %s with its own copy and a working retry, even on an INCOMPLETE profile',
    (status, copyKey) => {
      const onRetrySync = vi.fn();
      // isValid false is the case that used to hide the whole status area:
      // a half-landed save is exactly as true, and as retriable, on a form
      // the user has not finished filling in.
      renderRow({ saveStatus: status, onRetrySync, isValid: false, canRetrySync: true });

      expect(screen.getByText(copyKey)).toBeTruthy();
      fireEvent.click(screen.getByTestId('retry-sync'));
      expect(onRetrySync).toHaveBeenCalledTimes(1);
    },
  );

  it.each(['cloud-failed', 'device-failed', 'error'] as const)(
    'reports %s WITHOUT a retry button when there is no write left to replay',
    (status) => {
      // The affordance used to be inferred from the wording alone, so a
      // failure whose payload had already been dropped — a retry disowned by
      // an identity move, a rejected answer — still drew a button whose click
      // returned silently. Saying what happened is honest; offering a way out
      // that does nothing is not.
      renderRow({ saveStatus: status, canRetrySync: false });
      expect(screen.queryByTestId('retry-sync'),
        'no button with nothing behind it').toBeNull();
    },
  );

  it('SR-conflict-live: the answer controls belong to the QUESTION, not to the last save', () => {
    const onKeepMyChanges = vi.fn();
    const onUseCloudVersion = vi.fn();
    // A disagreement nobody has answered, while an unrelated clean save has
    // since taken the status line. The question is still open; the only way
    // out of it must still be on screen.
    renderRow({
      saveStatus: 'saved', hasConflict: true, onKeepMyChanges, onUseCloudVersion,
    });

    fireEvent.click(screen.getByTestId('conflict-keep-mine'));
    fireEvent.click(screen.getByTestId('conflict-use-cloud'));
    expect(onKeepMyChanges).toHaveBeenCalledTimes(1);
    expect(onUseCloudVersion).toHaveBeenCalledTimes(1);
    // With NO arguments. Both take an optional list of fields to answer, so
    // handing the click straight to onClick passes React's event object as
    // that list — and the blanket answer throws on `only.includes` before it
    // resolves anything. A bare `toHaveBeenCalled` cannot see this.
    expect(onKeepMyChanges.mock.calls[0],
      'the blanket answer names no fields').toEqual([]);
    expect(onUseCloudVersion.mock.calls[0]).toEqual([]);
  });

  it('SR-conflict-and-failure: an unanswered question and a failed sync are shown together', () => {
    const onKeepMyChanges = vi.fn();
    // A rejected answer: the transport failed, and the question it was about
    // is still open. Replacing the choice with a generic Retry would leave the
    // person a button that cannot unlock the key (see the coordinator's lock
    // rule) and no way back to the decision they were asked to make.
    // canRetrySync TRUE: a conflict result really does arm a retryable, so
    // this is the live case. A generic Retry still cannot unlock a conflicted
    // key — the choice is the way out, and it is the only one offered.
    renderRow({ saveStatus: 'cloud-failed', hasConflict: true, canRetrySync: true, onKeepMyChanges });

    expect(screen.getByText('home.actions.profileCloudFailed'),
      'the sync failure is still reported').toBeTruthy();
    expect(screen.queryByTestId('retry-sync'),
      'with no Retry standing in for the decision').toBeNull();
    fireEvent.click(screen.getByTestId('conflict-keep-mine'));
    expect(onKeepMyChanges, 'and the question is still answerable').toHaveBeenCalledTimes(1);
  });

  it('SR-conflict-retired: no controls once the question itself is gone', () => {
    // The complement of the two above: `hasConflict` is what draws them, so a
    // saveStatus that still says 'conflict' after the list was retired must
    // not leave buttons bound to nothing.
    renderRow({ saveStatus: 'conflict', hasConflict: false });
    expect(screen.queryByTestId('conflict-keep-mine')).toBeNull();
    expect(screen.queryByTestId('conflict-use-cloud')).toBeNull();
  });

  it('a question that was already answered elsewhere is SHOWN, with no controls behind it', () => {
    const onKeepMyChanges = vi.fn();
    const onRetrySync = vi.fn();
    renderRow({ saveStatus: 'conflict-stale', onKeepMyChanges, onRetrySync });

    // Visible, or the click reads as a button that does nothing.
    expect(screen.getByTestId('conflict-stale').textContent)
      .toContain('home.actions.profileConflictStale');
    // And no way back to a question that is gone: neither resolve control nor
    // a retry, because there is nothing behind either of them.
    expect(screen.queryByTestId('conflict-keep-mine')).toBeNull();
    expect(screen.queryByTestId('conflict-use-cloud')).toBeNull();
    expect(screen.queryByTestId('retry-sync')).toBeNull();
  });

  it('is disabled and says it is working while a submit is in flight', () => {
    renderRow({ isSubmitting: true });
    expect(screen.getByTestId('generate-matches')).toBeDisabled();
    expect(screen.getByTestId('generate-matches').textContent).toContain('home.actions.generating');
  });
});
