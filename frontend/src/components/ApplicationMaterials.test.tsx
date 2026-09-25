import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { translate } from '@/i18n/translate';
import type { AuthState } from '@/lib/supabase';
import { ApplicationMaterialError, type ApplicationMaterialAttempt, type ApplicationMaterialDeletion, type ApplicationMaterialRecord } from '@/lib/application-material';

const mocks = vi.hoisted(() => ({
  locale: 'en' as 'en' | 'zh', getAuthState: vi.fn(), onAuthChange: vi.fn(), openModal: vi.fn(),
  getApplicationMaterials: vi.fn(), getApplicationMaterial: vi.fn(), uploadApplicationMaterial: vi.fn(), downloadApplicationMaterial: vi.fn(), deleteApplicationMaterial: vi.fn(),
  readAttempts: vi.fn(), readDeletions: vi.fn(), prepare: vi.fn(), settle: vi.fn(), settleDeletion: vi.fn(),
}));
vi.mock('@/lib/supabase', () => ({ getAuthState: mocks.getAuthState, onAuthChange: mocks.onAuthChange }));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: mocks.openModal }) }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ locale: mocks.locale, t: (key: string, vars?: Record<string, string | number>) => translate(mocks.locale, key, vars) }) }));
vi.mock('@/lib/application-material-api', () => ({
  getApplicationMaterials: mocks.getApplicationMaterials, getApplicationMaterial: mocks.getApplicationMaterial,
  uploadApplicationMaterial: mocks.uploadApplicationMaterial, downloadApplicationMaterial: mocks.downloadApplicationMaterial, deleteApplicationMaterial: mocks.deleteApplicationMaterial,
}));
vi.mock('@/lib/application-material-storage', () => ({
  readPendingApplicationMaterialAttempts: mocks.readAttempts, readPendingApplicationMaterialDeletions: mocks.readDeletions,
  prepareApplicationMaterialAttempt: mocks.prepare, settleApplicationMaterialAttempt: mocks.settle, settleApplicationMaterialDeletion: mocks.settleDeletion,
}));
import ApplicationMaterials from './ApplicationMaterials';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';

const uid = '11111111-1111-4111-8111-111111111111';
const scope = { opportunityId: 'opp-A', applicationEventId: '22222222-2222-4222-8222-222222222222' };
const attempt: ApplicationMaterialAttempt = { scope, input: { materialId: '33333333-3333-4333-8333-333333333333', recordId: '44444444-4444-4444-8444-444444444444',
  filename: 'submitted-original.pdf', mimeType: 'application/pdf', byteLength: 9, bytesSha256: 'a'.repeat(64), attested: true } };
let attempts: ApplicationMaterialAttempt[]; let deletions: ApplicationMaterialDeletion[]; let records: ApplicationMaterialRecord[];
let authChanged: (state: AuthState) => void;
function auth(id = uid, anonymous = false): AuthState { return { session: { user: { id } }, user: { id }, isAnonymous: anonymous, email: 'test@example.test' } as AuthState; }
function record(overrides: Partial<ApplicationMaterialRecord> = {}): ApplicationMaterialRecord {
  return { version: 1, ownerId: uid, ...scope, materialId: attempt.input.materialId, recordId: attempt.input.recordId, filename: attempt.input.filename, mimeType: attempt.input.mimeType, byteLength: attempt.input.byteLength, bytesSha256: attempt.input.bytesSha256, status: 'ready', stagedAt: '2026-09-25T12:00:00Z', archivedAt: '2026-09-25T12:01:00Z', linkedAt: '2026-09-25T12:02:00Z', deletedAt: null, confirmationSource: 'user_reported', ...overrides };
}
function removed(): ApplicationMaterialRecord { return record({ status: 'deleted', filename: null, mimeType: null, byteLength: null, bytesSha256: null, deletedAt: '2026-09-25T13:00:00Z' }); }
const marker = (): ApplicationMaterialDeletion => ({ scope, materialId: attempt.input.materialId, recordId: attempt.input.recordId });
const page = (items = records, nextCursor: { linkedAt: string; recordId: string } | null = null) => ({ items, nextCursor });
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (cause: Error) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
const label = (key: string) => translate(mocks.locale, `applicationRecord.materials.${key}`);
const button = (key: string) => screen.getByRole('button', { name: label(key) });
async function owner(id = uid) { advanceOwnerEpoch(id); await syncLocalIdentityOwner(id); }
async function open() { fireEvent.click(button('open')); await screen.findByRole('region', { name: label('title') }); await waitFor(() => expect(mocks.getApplicationMaterials).toHaveBeenCalled()); }
function selectFile(name = 'selected.pdf') { const file = new File(['%PDF-data'], name, { type: 'application/pdf' }); fireEvent.change(screen.getByLabelText(label('fileLabel')), { target: { files: [file] } }); return file; }
function submit() { fireEvent.click(screen.getByRole('checkbox', { name: label('attestation') })); fireEvent.click(button('save')); }
async function showRecord() { records = [record()]; render(<ApplicationMaterials {...scope} />); await open(); await screen.findByRole('button', { name: label('download') }); }

beforeEach(async () => {
  vi.resetAllMocks(); localStorage.clear(); await owner(); mocks.locale = 'en'; attempts = []; deletions = []; records = [];
  mocks.getAuthState.mockResolvedValue(auth()); mocks.onAuthChange.mockImplementation(cb => { authChanged = cb; return vi.fn(); });
  mocks.getApplicationMaterials.mockImplementation(async () => page());
  mocks.readAttempts.mockImplementation(() => attempts); mocks.readDeletions.mockImplementation(() => deletions);
  mocks.prepare.mockImplementation(async () => { const reused = attempts.length > 0; attempts = [attempt]; return { status: 'ready', attempt, reused }; });
  mocks.uploadApplicationMaterial.mockImplementation(async () => { records = [record()]; return { record: records[0], replayed: false }; });
  mocks.settle.mockImplementation(async () => { attempts = []; return true; });
  mocks.settleDeletion.mockImplementation(async () => { deletions = []; return true; });
  mocks.getApplicationMaterial.mockResolvedValue(record());
  mocks.deleteApplicationMaterial.mockImplementation(async () => { records = [removed()]; return records[0]; });
});

describe('ApplicationMaterials — explicit account and file choice', () => {
  it('does not read auth, files or pending state until its own disclosure opens', () => {
    render(<ApplicationMaterials {...scope} />);
    expect(button('open')).toHaveAttribute('aria-expanded', 'false');
    expect(mocks.getAuthState).not.toHaveBeenCalled(); expect(mocks.getApplicationMaterials).not.toHaveBeenCalled(); expect(mocks.readAttempts).not.toHaveBeenCalled();
  });
  it.each(['anonymous', 'signedOut'] as const)('offers a working sign-in entry for %s without file API calls', async kind => {
    mocks.getAuthState.mockResolvedValue(kind === 'anonymous' ? auth(uid, true) : { session: null, user: null, isAnonymous: false, email: null });
    render(<ApplicationMaterials {...scope} />); fireEvent.click(button('open'));
    fireEvent.click(await screen.findByRole('button', { name: label('signIn') }));
    expect(mocks.openModal).toHaveBeenCalledWith({ phase: 'signin' }); expect(mocks.getApplicationMaterials).not.toHaveBeenCalled();
    expect(screen.queryByLabelText(label('fileLabel'))).not.toBeInTheDocument();
  });
  it('does not let late initial auth overwrite a newer signed-out notification', async () => {
    const initial = deferred<AuthState>(); mocks.getAuthState.mockReturnValue(initial.promise);
    render(<ApplicationMaterials {...scope} />); fireEvent.click(button('open'));
    act(() => authChanged({ session: null, user: null, isAnonymous: false, email: null }));
    await act(async () => initial.resolve(auth()));
    expect(button('signIn')).toBeInTheDocument(); expect(mocks.getApplicationMaterials).not.toHaveBeenCalled();
  });
  it('requires the formal account to match the current local owner', async () => {
    mocks.getAuthState.mockResolvedValue(auth('other-user')); render(<ApplicationMaterials {...scope} />); fireEvent.click(button('open'));
    await screen.findByText(label('ownerUnavailable')); expect(mocks.getApplicationMaterials).not.toHaveBeenCalled();
  });
  it('distinguishes loading, failed reads and an authoritative empty list', async () => {
    const reading = deferred<ReturnType<typeof page>>(); mocks.getApplicationMaterials.mockReturnValueOnce(reading.promise).mockResolvedValueOnce(page([]));
    render(<ApplicationMaterials {...scope} />); await open(); expect(screen.getByText(label('loading'))).toBeInTheDocument();
    expect(screen.queryByText(label('empty'))).not.toBeInTheDocument();
    await act(async () => reading.reject(new Error('private server detail')));
    expect(screen.getByRole('alert')).toHaveTextContent(label('loadError')); expect(screen.queryByText(label('empty'))).not.toBeInTheDocument();
    expect(screen.queryByText('private server detail')).not.toBeInTheDocument(); fireEvent.click(button('retry')); await screen.findByText(label('empty'));
  });
  it('requires an explicitly selected PDF and attestation, then passes that File and the frozen attempt', async () => {
    render(<ApplicationMaterials {...scope} />); await open(); expect(button('save')).toBeDisabled();
    expect(screen.getByLabelText(label('fileLabel'))).toHaveValue('');
    const file = selectFile(); expect(button('save')).toBeDisabled(); submit();
    await screen.findByText(label('saved')); expect(mocks.prepare).toHaveBeenCalledWith(captureOwnerToken(), scope, file, true, expect.any(AbortSignal));
    expect(mocks.uploadApplicationMaterial).toHaveBeenCalledWith(attempt, file, expect.objectContaining({ owner: captureOwnerToken() }));
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument(); expect(button('another')).toBeInTheDocument();
  });
  it('renders archive and association times independently without presenting either as application submission time', async () => {
    await showRecord(); const row = screen.getByTestId('application-material-record');
    expect(within(row).getByText(label('archivedAt'))).toBeInTheDocument(); expect(within(row).getByText(label('recordedAt'))).toBeInTheDocument();
    expect(Array.from(row.querySelectorAll('time')).map(node => node.dateTime)).toEqual(['2026-09-25T12:01:00Z', '2026-09-25T12:02:00Z']);
    expect(row).not.toHaveTextContent(translate('en', 'applicationRecord.submittedAt'));
  });
  it.each([[2048, '2.0 KiB'], [1572864, '1.5 MiB']] as const)('shows the archived original file size %s without exposing it on a tombstone', async (byteLength, text) => {
    records = [record({ byteLength }), { ...removed(), recordId: '55555555-5555-4555-8555-555555555555' }];
    render(<ApplicationMaterials {...scope} />); await open(); await screen.findByText(text);
    expect(screen.getAllByTestId('application-material-size')).toHaveLength(1);
    expect(within(screen.getAllByTestId('application-material-record')[1]).queryByTestId('application-material-size')).not.toBeInTheDocument();
  });
  it('resets the attestation when a different file is selected and starts a separate record only after another action', async () => {
    render(<ApplicationMaterials {...scope} />); await open(); selectFile(); fireEvent.click(screen.getByRole('checkbox')); selectFile('second.pdf'); expect(button('save')).toBeDisabled();
    submit(); await screen.findByText(label('saved')); fireEvent.click(button('another'));
    expect(button('save')).toBeDisabled(); expect(screen.getByRole('checkbox')).not.toBeChecked(); expect(mocks.uploadApplicationMaterial).toHaveBeenCalledTimes(1);
  });
  it.each([['invalid_pdf', 'invalidFile'], ['file_too_large', 'tooLarge'], ['storage_unavailable', 'storageError']] as const)('does not upload when preparation fails with %s', async (code, copy) => {
    mocks.prepare.mockRejectedValue(new ApplicationMaterialError(code)); render(<ApplicationMaterials {...scope} />); await open(); selectFile(); submit();
    expect(await screen.findByRole('alert')).toHaveTextContent(label(copy)); expect(mocks.uploadApplicationMaterial).not.toHaveBeenCalled();
  });
});

describe('ApplicationMaterials — pending upload recovery', () => {
  it('restores metadata only, requires reselection and uses the same attempt for a renamed identical PDF', async () => {
    attempts = [attempt]; render(<ApplicationMaterials {...scope} />); await open();
    expect(screen.getByTestId('application-material-pending')).toHaveTextContent(attempt.input.filename);
    expect(button('retrySave')).toBeDisabled(); expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    const file = selectFile('renamed.pdf'); fireEvent.click(button('retrySave')); await screen.findByText(label('saved'));
    expect(mocks.uploadApplicationMaterial).toHaveBeenCalledWith(attempt, file, expect.any(Object)); expect(attempt.input.filename).toBe('submitted-original.pdf');
  });
  it('rejects a different file without replacing an unresolved upload', async () => {
    attempts = [attempt]; mocks.prepare.mockResolvedValue({ status: 'pending_exists', attempts });
    render(<ApplicationMaterials {...scope} />); await open(); selectFile('different.pdf'); fireEvent.click(button('retrySave'));
    expect(await screen.findByRole('alert')).toHaveTextContent(label('fileMismatch')); expect(mocks.uploadApplicationMaterial).not.toHaveBeenCalled();
    expect(button('retrySave')).toBeDisabled(); expect(screen.getByTestId('application-material-pending')).toHaveTextContent(attempt.input.filename);
  });
  it('preserves an unknown upload through closing and reopening with no success claim', async () => {
    mocks.uploadApplicationMaterial.mockRejectedValue(new ApplicationMaterialError('timeout'));
    render(<ApplicationMaterials {...scope} />); await open(); selectFile(); submit();
    await screen.findByRole('alert'); expect(screen.queryByText(label('saved'))).not.toBeInTheDocument(); expect(attempts).toEqual([attempt]);
    fireEvent.click(button('close')); await open(); expect(screen.getByTestId('application-material-pending')).toHaveTextContent(label('unknown')); expect(button('retrySave')).toBeDisabled();
  });
  it('keeps staged as unconfirmed and does not call upload or settle during a check', async () => {
    attempts = [attempt]; mocks.getApplicationMaterial.mockResolvedValue(record({ status: 'staged', bytesSha256: null, archivedAt: null, linkedAt: null }));
    render(<ApplicationMaterials {...scope} />); await open(); fireEvent.click(button('check'));
    await screen.findByText(label('staged')); expect(screen.queryByText(label('saved'))).not.toBeInTheDocument(); expect(mocks.settle).not.toHaveBeenCalled(); expect(mocks.uploadApplicationMaterial).not.toHaveBeenCalled();
  });
  it('does not strand a still-loading history when a staged check finishes first', async () => {
    attempts = [attempt]; const reading = deferred<ReturnType<typeof page>>(); mocks.getApplicationMaterials.mockReturnValueOnce(reading.promise);
    mocks.getApplicationMaterial.mockResolvedValue(record({ status: 'staged', bytesSha256: null, archivedAt: null, linkedAt: null }));
    render(<ApplicationMaterials {...scope} />); await open(); fireEvent.click(button('check')); await screen.findByText(label('staged'));
    await act(async () => reading.resolve(page([]))); expect(screen.getByText(label('empty'))).toBeInTheDocument(); expect(screen.queryByText(label('loading'))).not.toBeInTheDocument();
  });
  it('keeps a not-found attempt for an exact retry', async () => {
    attempts = [attempt]; mocks.getApplicationMaterial.mockResolvedValue(null); render(<ApplicationMaterials {...scope} />); await open(); fireEvent.click(button('check'));
    expect(await screen.findByRole('alert')).toHaveTextContent(label('notFound')); expect(attempts).toEqual([attempt]); expect(mocks.settle).not.toHaveBeenCalled();
  });
  it('reconciles an exact saved receipt and removes the local pending record', async () => {
    attempts = [attempt]; records = [record()]; render(<ApplicationMaterials {...scope} />); await open(); fireEvent.click(button('check'));
    await screen.findByText(label('saved')); await waitFor(() => expect(screen.queryByTestId('application-material-pending')).not.toBeInTheDocument());
    expect(mocks.settle).toHaveBeenCalledWith(captureOwnerToken(), scope, record()); expect(mocks.uploadApplicationMaterial).not.toHaveBeenCalled();
  });
  it('does not publish a mismatched checked receipt as saved', async () => {
    attempts = [attempt]; mocks.getApplicationMaterial.mockResolvedValue(record({ bytesSha256: 'b'.repeat(64) }));
    render(<ApplicationMaterials {...scope} />); await open(); fireEvent.click(button('check'));
    expect(await screen.findByRole('alert')).toHaveTextContent(label('conflict')); expect(screen.queryByText(label('saved'))).not.toBeInTheDocument(); expect(mocks.settle).not.toHaveBeenCalled();
  });
  it('reports confirmed save and local cleanup failure separately, with no unsafe new record', async () => {
    mocks.settle.mockRejectedValue(new ApplicationMaterialError('storage_unavailable'));
    render(<ApplicationMaterials {...scope} />); await open(); selectFile(); submit();
    await screen.findByText(label('saved')); expect(await screen.findByRole('alert')).toHaveTextContent(label('storageError'));
    expect(screen.getByTestId('application-material-pending')).toHaveTextContent(label('cleanupPending'));
    expect(screen.queryByRole('button', { name: label('another') })).not.toBeInTheDocument();
  });
  it('never carries a prior saved label into a different unresolved upload arriving from another tab', async () => {
    attempts = [attempt]; records = [record()]; render(<ApplicationMaterials {...scope} />); await open(); fireEvent.click(button('check'));
    await screen.findByText(label('saved')); await waitFor(() => expect(attempts).toEqual([]));
    attempts = [{ scope, input: { ...attempt.input, recordId: '88888888-8888-4888-8888-888888888888', materialId: '99999999-9999-4999-8999-999999999999', filename: 'other-tab.pdf' } }];
    act(() => window.dispatchEvent(new StorageEvent('storage')));
    expect(screen.getByTestId('application-material-pending')).toHaveTextContent(label('unknown'));
    expect(screen.getByTestId('application-material-pending')).not.toHaveTextContent(label('cleanupPending'));
    expect(screen.queryByText(label('saved'))).not.toBeInTheDocument();
  });
  it('blocks file writes when pending storage is unreadable and offers retry', async () => {
    mocks.readAttempts.mockImplementation(() => { throw new ApplicationMaterialError('invalid_pending'); });
    render(<ApplicationMaterials {...scope} />); await open(); expect(screen.getByRole('alert')).toHaveTextContent(label('storageError')); expect(screen.getByLabelText(label('fileLabel'))).toBeDisabled();
    mocks.readAttempts.mockReturnValue([]); fireEvent.click(button('retry')); await waitFor(() => expect(screen.getByLabelText(label('fileLabel'))).toBeEnabled());
  });
});

describe('ApplicationMaterials — download and deletion recovery', () => {
  it('passes the selected exact record to the original download helper and shows safe errors', async () => {
    mocks.downloadApplicationMaterial.mockRejectedValue(new Error('private response')); await showRecord(); fireEvent.click(button('download'));
    expect(await screen.findByRole('alert')).toHaveTextContent(label('downloadError')); expect(mocks.downloadApplicationMaterial).toHaveBeenCalledWith(scope, record(), expect.objectContaining({ owner: captureOwnerToken() }));
    expect(screen.queryByText('private response')).not.toBeInTheDocument();
  });
  it('requires explicit deletion confirmation and supports Escape with focus return', async () => {
    await showRecord(); fireEvent.click(button('delete')); expect(screen.getByRole('alertdialog')).toHaveAccessibleName(label('deleteTitle')); expect(button('cancel')).toHaveFocus();
    fireEvent.keyDown(button('cancel'), { key: 'Escape' }); expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument(); expect(button('delete')).toHaveFocus(); expect(mocks.deleteApplicationMaterial).not.toHaveBeenCalled();
  });
  it('redacts filename and download after confirmed deletion, retaining distinct dates', async () => {
    await showRecord(); fireEvent.click(button('delete')); fireEvent.click(button('confirmDelete'));
    await waitFor(() => expect(screen.queryByText(attempt.input.filename)).not.toBeInTheDocument());
    const row = screen.getByTestId('application-material-record'); expect(within(row).getByText(label('deleted'))).toBeInTheDocument();
    expect(row.querySelectorAll('time')).toHaveLength(3); expect(screen.queryByRole('button', { name: label('download') })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: label('title') })).toHaveFocus();
  });
  it('retains unknown deletion as an opaque marker, blocks download, and restores that state on reopen', async () => {
    mocks.deleteApplicationMaterial.mockImplementation(async () => { deletions = [marker()]; throw new ApplicationMaterialError('timeout'); });
    await showRecord(); fireEvent.click(button('delete')); fireEvent.click(button('confirmDelete'));
    await screen.findByTestId('application-material-delete-pending'); expect(screen.queryByText(attempt.input.filename)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: label('download') })).not.toBeInTheDocument(); fireEvent.click(button('close')); await open();
    expect(screen.getByTestId('application-material-delete-pending')).toBeInTheDocument(); expect(screen.queryByRole('button', { name: label('download') })).not.toBeInTheDocument();
  });
  it('does not cancel deletion intent when a read still returns ready; retries the same IDs', async () => {
    deletions = [marker()]; records = [record()]; render(<ApplicationMaterials {...scope} />); await open(); fireEvent.click(button('check'));
    await screen.findByRole('alert'); expect(deletions).toEqual([marker()]); expect(mocks.settleDeletion).not.toHaveBeenCalled();
    fireEvent.click(button('retryDelete')); await waitFor(() => expect(deletions).toEqual([]));
    expect(mocks.deleteApplicationMaterial).toHaveBeenCalledWith(scope, marker(), expect.objectContaining({ owner: captureOwnerToken() }));
  });
  it('blocks upload recovery of a record with pending deletion, including a cross-tab storage notification', async () => {
    attempts = [attempt]; render(<ApplicationMaterials {...scope} />); await open(); expect(button('retrySave')).toBeInTheDocument();
    deletions = [marker()]; act(() => window.dispatchEvent(new StorageEvent('storage')));
    expect(screen.queryByLabelText(label('fileLabel'))).not.toBeInTheDocument(); expect(screen.queryByText(attempt.input.filename)).not.toBeInTheDocument();
    expect(screen.getByTestId('application-material-delete-pending')).toBeInTheDocument();
  });
  it('reconciles a tombstone without requiring private metadata and never redisplays its pending filename on cleanup failure', async () => {
    attempts = [attempt]; mocks.getApplicationMaterial.mockResolvedValue(removed()); mocks.settle.mockRejectedValue(new ApplicationMaterialError('storage_unavailable')); records = [removed()];
    render(<ApplicationMaterials {...scope} />); await open(); fireEvent.click(button('check'));
    await screen.findByRole('alert'); expect(screen.queryByText(attempt.input.filename)).not.toBeInTheDocument(); expect(screen.queryByLabelText(label('fileLabel'))).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: label('download') })).not.toBeInTheDocument(); expect(attempts).toEqual([attempt]);
  });
});

describe('ApplicationMaterials — paginated, isolated reads', () => {
  it('uses the returned cursor, deduplicates rows and prevents repeated pagination', async () => {
    const first = record(); const cursor = { linkedAt: first.linkedAt!, recordId: first.recordId }; const next = deferred<ReturnType<typeof page>>();
    mocks.getApplicationMaterials.mockResolvedValueOnce(page([first], cursor)).mockReturnValueOnce(next.promise);
    render(<ApplicationMaterials {...scope} />); await open(); const load = await screen.findByRole('button', { name: label('loadMore') }); fireEvent.click(load); fireEvent.click(load);
    expect(mocks.getApplicationMaterials).toHaveBeenCalledTimes(2); expect(mocks.getApplicationMaterials).toHaveBeenLastCalledWith(scope, expect.objectContaining({ cursor }));
    await act(async () => next.resolve(page([first, record({ recordId: '55555555-5555-4555-8555-555555555555', filename: 'older.pdf' })])));
    expect(screen.getAllByTestId('application-material-record')).toHaveLength(2); expect(screen.getByText('Saved records: 2')).toBeInTheDocument();
  });
  it('keeps visible rows on pagination failure and retries the same cursor', async () => {
    const first = record(); const cursor = { linkedAt: first.linkedAt!, recordId: first.recordId };
    mocks.getApplicationMaterials.mockResolvedValueOnce(page([first], cursor)).mockRejectedValueOnce(new Error('no')).mockResolvedValueOnce(page([]));
    render(<ApplicationMaterials {...scope} />); await open(); fireEvent.click(await screen.findByRole('button', { name: label('loadMore') }));
    await screen.findByText(label('moreError')); expect(screen.getByText(first.filename!)).toBeInTheDocument(); fireEvent.click(button('loadMore'));
    await waitFor(() => expect(screen.queryByText(label('moreError'))).not.toBeInTheDocument()); expect(mocks.getApplicationMaterials.mock.calls.slice(1).every(([, options]) => options.cursor === cursor)).toBe(true);
  });
  it('does not allow an older list response to overwrite a newly verified receipt', async () => {
    attempts = [attempt]; const oldRead = deferred<ReturnType<typeof page>>(); records = [record()];
    mocks.getApplicationMaterials.mockReturnValueOnce(oldRead.promise).mockImplementation(async () => page());
    render(<ApplicationMaterials {...scope} />); await open(); fireEvent.click(button('check')); await screen.findByText(label('saved')); await screen.findByText(attempt.input.filename);
    await act(async () => oldRead.resolve(page([]))); expect(screen.getByText(attempt.input.filename)).toBeInTheDocument();
  });
  it.each(['opportunity', 'application'] as const)('unmounts private state on %s change and ignores a late read', async changed => {
    const oldRead = deferred<ReturnType<typeof page>>(); mocks.getApplicationMaterials.mockReturnValueOnce(oldRead.promise).mockResolvedValueOnce(page([]));
    const view = render(<ApplicationMaterials {...scope} />); await open(); const signal = mocks.getApplicationMaterials.mock.calls[0][1].signal;
    const next = changed === 'opportunity' ? { ...scope, opportunityId: 'opp-B' } : { ...scope, applicationEventId: '66666666-6666-4666-8666-666666666666' };
    view.rerender(<ApplicationMaterials {...next} />); expect(button('open')).toBeInTheDocument(); expect(signal.aborted).toBe(true);
    await open(); await act(async () => oldRead.resolve(page([record()]))); expect(screen.queryByText(attempt.input.filename)).not.toBeInTheDocument();
    expect(mocks.getApplicationMaterials).toHaveBeenLastCalledWith(next, expect.any(Object));
  });
  it('removes old-account files immediately when owner changes, even before auth catches up', async () => {
    await showRecord(); await act(async () => owner('77777777-7777-4777-8777-777777777777'));
    expect(screen.queryByText(attempt.input.filename)).not.toBeInTheDocument(); expect(button('open')).toBeInTheDocument(); fireEvent.click(button('open'));
    await screen.findByText(label('ownerUnavailable'));
  });
  it('aborts a pending upload and hides private state on session revocation without losing its durable attempt', async () => {
    const upload = deferred<{ record: ApplicationMaterialRecord; replayed: boolean }>(); mocks.uploadApplicationMaterial.mockReturnValue(upload.promise);
    render(<ApplicationMaterials {...scope} />); await open(); selectFile(); submit(); await waitFor(() => expect(mocks.uploadApplicationMaterial).toHaveBeenCalled());
    const signal = mocks.uploadApplicationMaterial.mock.calls[0][2].signal; act(() => authChanged({ session: null, user: null, isAnonymous: false, email: null }));
    expect(signal.aborted).toBe(true); expect(button('signIn')).toBeInTheDocument(); await act(async () => upload.resolve({ record: record(), replayed: false }));
    expect(screen.queryByText(label('saved'))).not.toBeInTheDocument(); expect(mocks.settle).not.toHaveBeenCalled(); expect(attempts).toEqual([attempt]);
  });
  it('preserves an unsaved selection through a token refresh for the same formal account', async () => {
    render(<ApplicationMaterials {...scope} />); await open(); selectFile('unsaved-selection.pdf'); fireEvent.click(screen.getByRole('checkbox'));
    const reads = mocks.getApplicationMaterials.mock.calls.length; act(() => authChanged(auth()));
    expect(screen.getByText('unsaved-selection.pdf · 0.0 KiB')).toBeInTheDocument(); expect(screen.getByRole('checkbox')).toBeChecked();
    expect(button('save')).toBeEnabled(); expect(mocks.getApplicationMaterials).toHaveBeenCalledTimes(reads);
  });
  it('replaces private UI with the login gate when the API rejects a revoked session', async () => {
    mocks.getApplicationMaterials.mockRejectedValue(new ApplicationMaterialError('sign_in_required')); render(<ApplicationMaterials {...scope} />); fireEvent.click(button('open'));
    await screen.findByRole('button', { name: label('signIn') }); expect(screen.queryByLabelText(label('fileLabel'))).not.toBeInTheDocument();
  });
  it.each(['en', 'zh'] as const)('renders %s labels and a long hostile filename safely as wrapping text', async locale => {
    mocks.locale = locale; const filename = '<img src=x onerror=alert(1)>'.repeat(4) + '.pdf'; records = [record({ filename })];
    const { container } = render(<ApplicationMaterials {...scope} />); await open(); const name = await screen.findByText(filename);
    expect(container.querySelector('img,script,svg')).toBeNull(); expect(name).toHaveClass('[overflow-wrap:anywhere]'); expect(button('download')).toBeInTheDocument();
    expect(container.textContent).not.toContain('applicationRecord.materials.');
  });
});

describe('ApplicationMaterials — cancelling unresolved uploads', () => {
  it('requires explicit cancellation, then permits a different file only after the unarchived tombstone settles', async () => {
    mocks.uploadApplicationMaterial.mockRejectedValueOnce(new ApplicationMaterialError('invalid_pdf'));
    const cancelled = removed(); cancelled.archivedAt = null; cancelled.linkedAt = null;
    mocks.deleteApplicationMaterial.mockResolvedValue(cancelled);
    render(<ApplicationMaterials {...scope} />); await open(); selectFile('damaged.pdf'); submit(); await screen.findByRole('alert');
    expect(button('cancelUpload')).toBeInTheDocument(); fireEvent.click(button('cancelUpload')); expect(button('keepUpload')).toHaveFocus();
    expect(mocks.deleteApplicationMaterial).not.toHaveBeenCalled(); fireEvent.click(button('confirmCancelUpload'));
    await screen.findByText(label('cancelled')); await waitFor(() => expect(attempts).toEqual([])); expect(screen.queryByTestId('application-material-pending')).not.toBeInTheDocument();
    expect(mocks.deleteApplicationMaterial).toHaveBeenCalledWith(scope, attempt.input, expect.objectContaining({ owner: captureOwnerToken() }));
    const nextAttempt = { scope, input: { ...attempt.input, recordId: '55555555-5555-4555-8555-555555555555', materialId: '66666666-6666-4666-8666-666666666666' } };
    mocks.prepare.mockResolvedValue({ status: 'ready', attempt: nextAttempt, reused: false });
    mocks.uploadApplicationMaterial.mockResolvedValue({ record: record({ recordId: nextAttempt.input.recordId, materialId: nextAttempt.input.materialId }), replayed: false });
    fireEvent.click(button('another')); selectFile('new-export.pdf'); submit(); await screen.findByText(label('saved'));
    expect(mocks.uploadApplicationMaterial.mock.calls[1][0]).toEqual(nextAttempt);
  });
  it('keeps uncertain cancellation blocked through reopen; a 404 cannot discard its pending snapshot', async () => {
    attempts = [attempt]; mocks.deleteApplicationMaterial.mockImplementation(async () => { deletions = [marker()]; throw new ApplicationMaterialError('timeout'); });
    mocks.getApplicationMaterial.mockResolvedValue(null);
    render(<ApplicationMaterials {...scope} />); await open(); fireEvent.click(button('cancelUpload')); fireEvent.click(button('confirmCancelUpload'));
    expect(await screen.findByRole('alert')).toHaveTextContent(label('cancelUnknown')); expect(screen.queryByLabelText(label('fileLabel'))).not.toBeInTheDocument();
    fireEvent.click(button('close')); await open(); fireEvent.click(button('check')); expect(await screen.findByRole('alert')).toHaveTextContent(label('cancelUnknown'));
    expect(attempts).toEqual([attempt]); expect(deletions).toEqual([marker()]); expect(button('retryCancelUpload')).toBeInTheDocument(); expect(mocks.settle).not.toHaveBeenCalled();
    const cancelled = { ...removed(), archivedAt: null, linkedAt: null }; mocks.deleteApplicationMaterial.mockResolvedValue(cancelled); fireEvent.click(button('retryCancelUpload'));
    await screen.findByText(label('cancelled')); await waitFor(() => expect(attempts).toEqual([])); expect(deletions).toEqual([]);
  });
  it('cancelling a saved-but-unknown attempt deletes the existing private copy instead of silently forgetting it', async () => {
    attempts = [attempt]; records = [record()]; render(<ApplicationMaterials {...scope} />); await open(); fireEvent.click(button('cancelUpload'));
    expect(screen.getByRole('alertdialog')).toHaveTextContent(label('cancelUploadHint')); fireEvent.click(button('confirmCancelUpload'));
    await waitFor(() => expect(screen.queryByText(attempt.input.filename)).not.toBeInTheDocument()); expect(screen.getByTestId('application-material-record')).toHaveTextContent(label('deleted'));
    expect(screen.queryByRole('button', { name: label('download') })).not.toBeInTheDocument(); expect(attempts).toEqual([]);
  });
});
