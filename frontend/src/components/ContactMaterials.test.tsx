import { StrictMode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { translate } from '@/i18n/translate';
import type { AuthState } from '@/lib/supabase';
import type { ContactMaterialAttempt, ContactMaterialDeletion, ContactMaterialRecord } from '@/lib/contact-material';
const mocks = vi.hoisted(() => ({
  locale: 'en' as 'en' | 'zh', auth: vi.fn(), authChange: vi.fn(), openModal: vi.fn(), events: vi.fn(), confirmContact: vi.fn(),
  list: vi.fn(), get: vi.fn(), upload: vi.fn(), download: vi.fn(), remove: vi.fn(),
  attempts: vi.fn(), deletions: vi.fn(), prepare: vi.fn(), settle: vi.fn(), settleDeletion: vi.fn(),
}));
vi.mock('@/lib/supabase', () => ({ getAuthState: mocks.auth, onAuthChange: mocks.authChange, getContactEvents: mocks.events, confirmContact: mocks.confirmContact }));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: mocks.openModal }) }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ locale: mocks.locale, t: (key: string, vars?: Record<string, string | number>) => translate(mocks.locale, key, vars) }) }));
vi.mock('@/lib/contact-material-api', () => ({ getContactMaterials: mocks.list, getContactMaterial: mocks.get,
  uploadContactMaterial: mocks.upload, downloadContactMaterial: mocks.download, deleteContactMaterial: mocks.remove }));
vi.mock('@/lib/contact-material-storage', () => ({ readPendingContactMaterialAttempts: mocks.attempts, readPendingContactMaterialDeletions: mocks.deletions,
  prepareContactMaterialAttempt: mocks.prepare, settleContactMaterialAttempt: mocks.settle, settleContactMaterialDeletion: mocks.settleDeletion }));
import ContactMaterials from './ContactMaterials';
import ContactHistory from './ContactHistory';
import { MATERIAL_AUTH_TIMEOUT_MS } from './RecordedMaterials';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
const uid = '11111111-1111-4111-8111-111111111111';
const scope = { opportunityId: 'opp-A', contactEventId: '22222222-2222-4222-8222-222222222222' };
const attempt: ContactMaterialAttempt = { scope, input: { materialId: '33333333-3333-4333-8333-333333333333', recordId: '44444444-4444-4444-8444-444444444444',
  filename: 'attached-original.pdf', mimeType: 'application/pdf', byteLength: 9, bytesSha256: 'a'.repeat(64), attested: true } };
let attempts: ContactMaterialAttempt[]; let deletions: ContactMaterialDeletion[]; let records: ContactMaterialRecord[];
let authChanged: (state: AuthState) => void;
function auth(): AuthState { return { session: { user: { id: uid } }, user: { id: uid }, isAnonymous: false, email: 'test@example.test' } as AuthState; }
function record(overrides: Partial<ContactMaterialRecord> = {}): ContactMaterialRecord {
  return { version: 1, ownerId: uid, ...scope, materialId: attempt.input.materialId, recordId: attempt.input.recordId, filename: attempt.input.filename,
    mimeType: attempt.input.mimeType, byteLength: attempt.input.byteLength, bytesSha256: attempt.input.bytesSha256, status: 'ready', stagedAt: '2026-09-25T12:00:00Z',
    archivedAt: '2026-09-25T12:01:00Z', linkedAt: '2026-09-25T12:02:00Z', deletedAt: null, confirmationSource: 'user_reported', ...overrides };
}
const removed = () => record({ status: 'deleted', filename: null, mimeType: null, byteLength: null, bytesSha256: null, deletedAt: '2026-09-25T13:00:00Z' });
const page = (items = records) => ({ items, nextCursor: null });
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (cause: Error) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
const contactKeys = new Set(['open', 'title', 'hint', 'signInHint', 'empty', 'fileLabel', 'fileHint', 'attestation', 'saved', 'recordedAt', 'another']);
const label = (key: string) => translate(mocks.locale, `${contactKeys.has(key) ? 'contactMaterials' : 'applicationRecord.materials'}.${key}`);
const button = (key: string) => screen.getByRole('button', { name: label(key) });
async function open() { fireEvent.click(button('open')); await screen.findByRole('region', { name: label('title') }); await waitFor(() => expect(mocks.list).toHaveBeenCalled()); }
function selectFile(name = 'selected.pdf') { const file = new File(['%PDF-data'], name, { type: 'application/pdf' }); fireEvent.change(screen.getByLabelText(label('fileLabel')), { target: { files: [file] } }); return file; }
function submit() { fireEvent.click(screen.getByRole('checkbox', { name: label('attestation') })); fireEvent.click(button('save')); }
beforeEach(async () => {
  vi.resetAllMocks(); localStorage.clear(); advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); mocks.locale = 'en'; attempts = []; deletions = []; records = [];
  mocks.auth.mockResolvedValue(auth()); mocks.authChange.mockImplementation(cb => { authChanged = cb; return vi.fn(); });
  mocks.list.mockImplementation(async () => page()); mocks.attempts.mockImplementation(() => attempts); mocks.deletions.mockImplementation(() => deletions);
  mocks.prepare.mockImplementation(async () => { attempts = [attempt]; return { status: 'ready', attempt, reused: false }; });
  mocks.upload.mockImplementation(async () => { records = [record()]; return { record: records[0], replayed: false }; });
  mocks.settle.mockImplementation(async () => { attempts = []; return true; }); mocks.settleDeletion.mockImplementation(async () => { deletions = []; return true; });
  mocks.get.mockResolvedValue(record()); mocks.remove.mockImplementation(async () => { records = [removed()]; return records[0]; });
});
afterEach(() => { vi.useRealTimers(); });

it.each(['en', 'zh'] as const)('shows the %s contact attachment scope and requires explicit file attestation', async locale => {
  mocks.locale = locale; render(<ContactMaterials {...scope} />); expect(mocks.auth).not.toHaveBeenCalled(); expect(mocks.list).not.toHaveBeenCalled();
  await open(); expect(screen.getByText(label('hint'))).toBeInTheDocument(); expect(button('save')).toBeDisabled();
  const selected = selectFile(); expect(button('save')).toBeDisabled(); submit(); await screen.findByText(label('saved'));
  expect(mocks.prepare).toHaveBeenCalledWith(captureOwnerToken(), scope, selected, true, expect.any(AbortSignal));
  expect(mocks.upload).toHaveBeenCalledWith(attempt, selected, expect.objectContaining({ owner: captureOwnerToken() })); expect(mocks.confirmContact).not.toHaveBeenCalled();
});
it('shows original file size and separate archive/link times, and downloads only on request', async () => {
  records = [record({ byteLength: 2048 })]; render(<ContactMaterials {...scope} />); await open();
  const row = await screen.findByTestId('contact-material-record'); expect(row).toHaveTextContent('2.0 KiB');
  expect(Array.from(row.querySelectorAll('time')).map(el => el.dateTime)).toEqual(['2026-09-25T12:01:00Z', '2026-09-25T12:02:00Z']);
  expect(row).toHaveTextContent(label('recordedAt')); expect(mocks.download).not.toHaveBeenCalled(); fireEvent.click(button('download'));
  await waitFor(() => expect(mocks.download).toHaveBeenCalledWith(scope, records[0], expect.objectContaining({ owner: captureOwnerToken() })));
});
it('recovers an unknown upload after close/reopen through a read without replaying the write', async () => {
  mocks.upload.mockRejectedValueOnce(new Error('unknown write')); render(<ContactMaterials {...scope} />); await open(); selectFile(); submit(); await screen.findByRole('alert');
  fireEvent.click(button('close')); await open(); expect(screen.getByTestId('contact-material-pending')).toHaveTextContent(attempt.input.filename);
  expect(mocks.upload).toHaveBeenCalledOnce(); fireEvent.click(button('check')); await screen.findByText(label('saved'));
  expect(mocks.upload).toHaveBeenCalledOnce(); expect(mocks.settle).toHaveBeenCalledWith(captureOwnerToken(), scope, record());
});
it('requires explicit cancellation before removing an unresolved contact upload', async () => {
  attempts = [attempt]; render(<ContactMaterials {...scope} />); await open(); fireEvent.click(button('cancelUpload'));
  expect(screen.getByRole('alertdialog')).toHaveTextContent(label('cancelUploadHint')); expect(button('keepUpload')).toHaveFocus();
  fireEvent.click(button('keepUpload')); expect(mocks.remove).not.toHaveBeenCalled(); fireEvent.click(button('cancelUpload')); fireEvent.click(button('confirmCancelUpload'));
  await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith(scope, attempt.input, expect.objectContaining({ owner: captureOwnerToken() })));
});
it('blocks downloads while another tab has unresolved deletion intent', async () => {
  records = [record()]; render(<ContactMaterials {...scope} />); await open(); await screen.findByTestId('contact-material-record');
  deletions = [{ scope, recordId: attempt.input.recordId, materialId: attempt.input.materialId }]; act(() => window.dispatchEvent(new StorageEvent('storage')));
  expect(screen.getByTestId('contact-material-delete-pending')).toHaveTextContent(label('deleteUnknown'));
  expect(screen.queryByRole('button', { name: label('download') })).not.toBeInTheDocument(); fireEvent.click(button('check'));
  await screen.findByRole('alert'); expect(mocks.settleDeletion).not.toHaveBeenCalled(); expect(mocks.remove).not.toHaveBeenCalled();
});
it('retires the previous request and file selection when the contact event changes', async () => {
  const delayed = deferred<ReturnType<typeof page>>(); mocks.list.mockReturnValueOnce(delayed.promise);
  const view = render(<ContactMaterials {...scope} />); await open(); selectFile('private-old.pdf'); const signal = mocks.list.mock.calls[0][1].signal;
  const next = { ...scope, contactEventId: '66666666-6666-4666-8666-666666666666' }; view.rerender(<ContactMaterials {...next} />);
  expect(signal.aborted).toBe(true); await act(async () => delayed.resolve(page([record()])));
  expect(screen.queryByText('private-old.pdf')).not.toBeInTheDocument(); expect(screen.queryByText(attempt.input.filename)).not.toBeInTheDocument();
  await open(); expect(mocks.list).toHaveBeenLastCalledWith(next, expect.any(Object));
});
it('cannot show or settle a late upload after logout', async () => {
  const delayed = deferred<{ record: ContactMaterialRecord; replayed: boolean }>(); mocks.upload.mockReturnValueOnce(delayed.promise);
  render(<ContactMaterials {...scope} />); await open(); selectFile(); submit(); await waitFor(() => expect(mocks.upload).toHaveBeenCalled());
  act(() => advanceOwnerEpoch(null)); await act(async () => delayed.resolve({ record: record(), replayed: false }));
  expect(screen.queryByText(label('saved'))).not.toBeInTheDocument(); expect(mocks.settle).not.toHaveBeenCalled(); expect(button('open')).toBeInTheDocument();
});
it('shows an auth read error and retries only the read before loading files', async () => {
  mocks.auth.mockRejectedValueOnce(new Error('private auth diagnostics')).mockResolvedValueOnce(auth()); render(<ContactMaterials {...scope} />); fireEvent.click(button('open'));
  expect(await screen.findByRole('alert')).toHaveTextContent(label('authError')); expect(screen.queryByRole('button', { name: label('signIn') })).not.toBeInTheDocument();
  expect(mocks.list).not.toHaveBeenCalled(); fireEvent.click(button('retry')); await screen.findByText(label('empty'));
  expect(mocks.auth).toHaveBeenCalledWith({ throwOnError: true }); expect(mocks.upload).not.toHaveBeenCalled(); expect(mocks.remove).not.toHaveBeenCalled();
});
it('bounds auth reads, ignores late success, and allows a fresh deliberate read', async () => {
  vi.useFakeTimers(); const delayed = deferred<AuthState>(); mocks.auth.mockReturnValueOnce(delayed.promise).mockResolvedValueOnce(auth());
  render(<ContactMaterials {...scope} />); fireEvent.click(button('open')); await act(async () => { await vi.advanceTimersByTimeAsync(MATERIAL_AUTH_TIMEOUT_MS); });
  expect(screen.getByRole('alert')).toHaveTextContent(label('authError')); await act(async () => delayed.resolve(auth())); expect(mocks.list).not.toHaveBeenCalled();
  await act(async () => fireEvent.click(button('retry'))); expect(screen.getByText(label('empty'))).toBeInTheDocument();
});
it('lets a new signed-out event beat a late rejected auth read in StrictMode', async () => {
  const delayed = deferred<AuthState>(); mocks.auth.mockReturnValue(delayed.promise); render(<StrictMode><ContactMaterials {...scope} /></StrictMode>); fireEvent.click(button('open'));
  act(() => authChanged({ session: null, user: null, isAnonymous: false, email: null })); await act(async () => delayed.reject(new Error('late auth failure')));
  expect(button('signIn')).toBeInTheDocument(); expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
it('ignores an auth failure after closing the disclosure', async () => {
  const delayed = deferred<AuthState>(); mocks.auth.mockReturnValueOnce(delayed.promise); render(<ContactMaterials {...scope} />); fireEvent.click(button('open')); fireEvent.click(button('close'));
  await act(async () => delayed.reject(new Error('closed'))); expect(screen.queryByRole('alert')).not.toBeInTheDocument(); expect(mocks.list).not.toHaveBeenCalled();
});
it('keeps source summaries separate from attachments and binds the selected confirmed contact event', async () => {
  const base = { deviceId: uid, opportunityId: scope.opportunityId, recipient: 'professor@example.edu', body: 'Original message', actualSentAt: null,
    confirmedAt: '2026-09-25T11:00:00Z', materialRefs: [{ kind: 'resume', version: 'resume-source-only' }], confirmationSource: 'user_reported' };
  const secondId = '66666666-6666-4666-8666-666666666666';
  mocks.events.mockResolvedValue({ events: [{ ...base, id: scope.contactEventId, subject: 'First email' }, { ...base, id: secondId, subject: 'Second email' }], nextCursor: null, hasMore: false });
  render(<ContactHistory opportunityId={scope.opportunityId} />); await screen.findByText('First email');
  expect(screen.getAllByTestId('contact-materials')).toHaveLength(2); expect(screen.getAllByTestId('contact-event-sources')).toHaveLength(2);
  expect(screen.getAllByText('resume-source-only')).toHaveLength(2); expect(mocks.list).not.toHaveBeenCalled();
  const second = screen.getByText('Second email').closest('details')!; fireEvent.click(second.querySelector('summary')!); fireEvent.click(within(second).getByText(label('open')));
  await waitFor(() => expect(mocks.list).toHaveBeenCalledWith({ opportunityId: scope.opportunityId, contactEventId: secondId }, expect.any(Object)));
  expect(mocks.list).toHaveBeenCalledOnce(); expect(mocks.confirmContact).not.toHaveBeenCalled();
});
