import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import TrackerAttachmentExport from './TrackerAttachmentExport';
const mocks = vi.hoisted(() => ({ run: vi.fn(), save: vi.fn(), uid: 'one', listener: null as (() => void) | null }));
vi.mock('@/lib/tracker-attachment-export', () => ({ exportTrackerAttachments: mocks.run, AttachmentExportLimitError: class extends Error {} }));
vi.mock('@/lib/browser-download', () => ({ downloadBlob: mocks.save }));
vi.mock('@/lib/identity-owner', () => ({
  captureOwnerToken: () => ({ uid: mocks.uid }),
  isOwnerTokenValid: (token: { uid: string }, uid: string) => uid === mocks.uid && token.uid === uid,
  onLocalOwnerStateChange: (cb: () => void) => { mocks.listener = cb; return () => {}; },
}));
vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key }) }));
const button = (name: string) => screen.getByRole('button', { name: 'account.attachmentExport.' + name });
const file = { filename: 'tracker-attachments.zip', blob: new Blob(['synthetic']), count: 2 };
beforeEach(() => { mocks.uid = 'one'; mocks.run.mockReset(); mocks.save.mockReset(); mocks.listener = null; });
it('reports only an entire verified ZIP and provides a fresh retry after failure', async () => {
  mocks.run.mockRejectedValueOnce(new Error('private details')).mockResolvedValueOnce(file);
  render(<TrackerAttachmentExport uid="one" />);
  fireEvent.click(button('start'));
  await waitFor(() => expect(button('retry')).toBeEnabled());
  expect(mocks.save).not.toHaveBeenCalled();
  expect(screen.queryByText('private details')).toBeNull();
  fireEvent.click(button('retry'));
  await waitFor(() => expect(mocks.save).toHaveBeenCalledExactlyOnceWith(file));
  expect(screen.getByRole('status')).toHaveTextContent('account.attachmentExport.complete');
});
it('suppresses old bytes and feedback after a switch or an explicit cancellation', async () => {
  let finish!: (file: unknown) => void;
  mocks.run.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const view = render(<TrackerAttachmentExport key="one" uid="one" />);
  fireEvent.click(button('start'));
  const firstSignal = mocks.run.mock.calls[0][2];
  act(() => { mocks.uid = 'two'; mocks.listener?.(); });
  view.rerender(<TrackerAttachmentExport key="two" uid="two" />);
  await act(async () => finish(file));
  expect(firstSignal.aborted).toBe(true);
  fireEvent.click(button('start'));
  fireEvent.click(button('cancel'));
  await act(async () => finish(file));
  expect(mocks.save).not.toHaveBeenCalled();
  expect(screen.getByRole('status')).toBeEmptyDOMElement();
});

it('requests one explicit download per volume and never reports a failed final verification as complete', async () => {
  const verify = vi.fn().mockRejectedValue(new Error('changed while waiting'));
  const volume = { ...file, number: 1, total: 2, confirmBeforeDownload: vi.fn().mockResolvedValue(undefined) };
  mocks.run.mockImplementation(async (_uid, _token, _signal, _progress, offer) => {
    await offer(volume);
    return { ...file, filename: 'complete.sha256', parts: 2, confirmBeforeDownload: verify };
  });
  render(<TrackerAttachmentExport uid="one" />);
  fireEvent.click(button('start'));
  await waitFor(() => expect(button('part')).toBeEnabled());
  expect(mocks.save).not.toHaveBeenCalled();
  fireEvent.click(button('part'));
  await waitFor(() => expect(button('receipt')).toBeEnabled());
  expect(mocks.save).toHaveBeenCalledTimes(1);
  fireEvent.click(button('receipt'));
  await waitFor(() => expect(button('retry')).toBeEnabled());
  expect(mocks.save).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('status')).toHaveTextContent('account.attachmentExport.failed');
});
