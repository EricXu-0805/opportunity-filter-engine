import { createHash } from 'node:crypto';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { emailReceipt, emailTarget } from './ColdEmailModal.test-fixtures';
import { readColdEmailDraft, saveColdEmailDraft } from '@/lib/cold-email-draft';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { writeUserScopedRaw } from '@/lib/identity-owner';
import type { ProfileData } from '@/lib/types';
import type { EmailTextSelection } from '@/lib/email-revision';

const api = vi.hoisted(() => ({ variants: vi.fn(), stream: vi.fn(), refine: vi.fn(), confirm: vi.fn() }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key, locale: 'en' }) }));
vi.mock('@/lib/api', () => ({
  getEmailVariants: (...args: unknown[]) => emailReceipt(api.variants(...args), args[1] as string),
  generateColdEmailStream: (...args: unknown[]) => emailReceipt(api.stream(...args), args[1] as string),
  refineEmail: (...args: unknown[]) => emailReceipt(api.refine(...args), args[3] as string),
  generateColdEmail: vi.fn(), getVapidPublicKey: vi.fn(),
}));
vi.mock('@/lib/supabase', () => ({ onAuthChange: () => () => {}, confirmContactEvent: api.confirm, updateInteractionDetails: vi.fn() }));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: vi.fn() }) }));
import ColdEmailModal from './ColdEmailModal';

const ORIGINAL = 'Dear Professor,\n\n😀 中文：same paragraph\n\nsame paragraph\n\nBest,\nAlex';
const profile: ProfileData = { name: 'Alex', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore',
  is_international: false, research_interests: 'sensors', skills: [], coursework: [] };
const draft = { id: 'first', label: 'First', subject: 'Sensor research', body: ORIGINAL, recipient_email: 'lab@example.edu', mailto_link: '', method: 'template' };
let owner = 0;
beforeEach(async () => {
  const uid = `history-owner-${++owner}`; advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  api.variants.mockReset().mockResolvedValue({ variants: [draft, { ...draft, id: 'second', label: 'Second', body: 'Other variant' }] });
  api.stream.mockReset().mockResolvedValue(draft); api.refine.mockReset(); api.confirm.mockReset();
  api.refine.mockImplementation((body: string, _request: string, _profile: unknown, _id: string, options: { selection?: EmailTextSelection }) => options.selection
    ? selectionReply(body, options.selection) : { body: 'Revised full body', method: 'llm' });
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});
function selectionReply(body: string, selection: EmailTextSelection, replacement = '精修😀\nnew line') {
  return { scope: 'selection', outcome: 'proposal', method: 'llm', proposal: {
    start_utf16: selection.start_utf16, end_utf16: selection.end_utf16, original_text: selection.text,
    replacement, base_body_sha256: createHash('sha256').update(body).digest('hex'),
  } };
}
const bodyField = () => screen.getByLabelText('coldEmail.body') as HTMLTextAreaElement;
const input = () => screen.getByRole('textbox', { name: 'coldEmail.requestLabel' });
const preview = () => screen.queryByRole('region', { name: 'Pending edit suggestion' });
const accept = () => screen.getByRole('button', { name: 'Accept suggestion' });
function select(start = ORIGINAL.lastIndexOf('same paragraph'), end = start + 'same paragraph'.length) {
  const field = bodyField(); act(() => { field.focus(); field.setSelectionRange(start, end); fireEvent.select(field); }); return { start, end };
}
function submit(request = 'Make this precise') {
  fireEvent.change(input(), { target: { value: request } });
  fireEvent.submit(input().closest('form')!);
}
async function open(extra: Partial<Parameters<typeof ColdEmailModal>[0]> = {}) {
  const props = { isOpen: true, onClose: vi.fn(), profile, opportunityId: 'A', opportunityTitle: 'Lab', target: emailTarget('A'), ...extra };
  const view = render(<ColdEmailModal {...props} />);
  await waitFor(() => expect(bodyField()).toHaveValue(ORIGINAL)); await waitFor(() => expect(api.stream).toHaveBeenCalledOnce()); await act(async () => {});
  return { ...view, props, show: (next: Partial<typeof props>) => view.rerender(<ColdEmailModal {...props} {...next} />) };
}
async function proposed() { await screen.findByRole('region', { name: 'Pending edit suggestion' }); }
async function apply() { fireEvent.click(accept()); await waitFor(() => expect(preview()).toBeNull()); }


const stored = () => {
  const item = readColdEmailDraft(captureOwnerToken(), 'A');
  if (item.status !== 'present') throw new Error('No saved draft');
  return item;
};
async function saved(value = bodyField().value) {
  await waitFor(() => { expect(stored().draft.body).toBe(value); expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent(/Saved on this browser/); });
}
function history() {
  const panel = screen.getByTestId('cold-email-history');
  if (!panel.hasAttribute('open')) fireEvent.click(panel.querySelector('summary')!);
  return panel;
}
function compare(index = 0) { fireEvent.click(within(history()).getAllByRole('button', { name: 'Compare and restore' })[index]); }
async function editAndAccept(body = 'Revised full body') {
  api.refine.mockResolvedValue({ body, method: 'llm' }); submit(); await proposed(); await apply(); await saved(body);
}
async function closeAndReopen(view: Awaited<ReturnType<typeof open>>) {
  fireEvent.click(screen.getByRole('button', { name: 'coldEmail.closeAria' }));
  await waitFor(() => expect(view.props.onClose).toHaveBeenCalled());
  view.show({ isOpen: false }); view.show({ isOpen: true });
  await waitFor(() => expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent(/Restored draft/));
}

describe('recoverable email versions', () => {
  it('atomically saves the previous draft, then compares and restores it without creating a contact record', async () => {
    await open(); await saved(); const before = stored().draft.sources;
    await editAndAccept();
    expect(stored().draft.history).toHaveLength(1);
    expect(stored().draft.history[0]).toMatchObject({ body: ORIGINAL, subject: draft.subject, sources: before, reason: 'accepted_edit' });
    compare(); const comparison = screen.getByRole('region', { name: 'Compare email versions' });
    expect(comparison).toHaveTextContent('Revised full body'); expect(comparison).toHaveTextContent('same paragraph');
    expect(bodyField()).toHaveValue('Revised full body');
    fireEvent.click(within(comparison).getByRole('button', { name: 'Restore this version' }));
    await waitFor(() => expect(bodyField()).toHaveValue(ORIGINAL)); await saved();
    expect(stored().draft.history.map(v => v.body)).toEqual([ORIGINAL, 'Revised full body']);
    expect(stored().draft.sources).toEqual(before); expect(api.confirm).not.toHaveBeenCalled();
  });
  it('cancels comparison without altering the current draft or adding a version', async () => {
    await open(); await editAndAccept(); compare(); fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(bodyField()).toHaveValue('Revised full body'); expect(stored().draft.history).toHaveLength(1);
  });
  it('restores version history after close and deletes only the chosen stable id', async () => {
    const view = await open(); await editAndAccept('First revision'); await editAndAccept('Second revision');
    const ids = stored().draft.history.map(v => v.id); await closeAndReopen(view);
    expect(stored().draft.history).toHaveLength(2); history();
    const row = screen.getAllByTestId('cold-email-history-item').find(row => row.dataset.versionId === ids[0])!;
    fireEvent.click(within(row).getByRole('button', { name: 'Delete this version' }));
    await waitFor(() => expect(stored().draft.history.map(v => v.id)).toEqual([ids[1]]));
    expect(bodyField()).toHaveValue('Second revision');
  });
  it('does not create history entries for typing, rejection, failed refinement, or close/reopen', async () => {
    const view = await open(); fireEvent.change(bodyField(), { target: { value: 'Manual draft' } }); await saved();
    submit(); await proposed(); fireEvent.click(screen.getByRole('button', { name: 'Reject suggestion' }));
    api.refine.mockRejectedValueOnce(new Error('service unavailable')); submit(); await screen.findByText('coldEmail.editFailed');
    expect(stored().draft.history).toEqual([]); await closeAndReopen(view); expect(stored().draft.history).toEqual([]);
  });
  it('checkpoints template switches and undo with their original source binding', async () => {
    await open(); await saved(); fireEvent.click(screen.getByRole('button', { name: 'Second' }));
    await waitFor(() => expect(bodyField()).toHaveValue('Other variant')); await saved();
    expect(stored().draft.history[0]).toMatchObject({ reason: 'variant', body: ORIGINAL });
    await editAndAccept(); fireEvent.click(screen.getByRole('button', { name: 'Undo last accepted edit' }));
    await waitFor(() => expect(bodyField()).toHaveValue('Other variant')); await saved();
    expect(stored().draft.history.at(-1)).toMatchObject({ reason: 'undo', body: 'Revised full body' });
  });
  it('keeps the exact selected occurrence after closing and reopening', async () => {
    const view = await open(); const range = select(); fireEvent.change(input(), { target: { value: 'Only this second occurrence' } }); await saved();
    await closeAndReopen(view); await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.submitRequest' })).toBeEnabled()); api.refine.mockClear(); fireEvent.submit(input().closest('form')!); await proposed();
    expect(api.refine.mock.calls[0][4].selection).toEqual({ start_utf16: range.start, end_utf16: range.end, text: 'same paragraph' });
  });
  it('requires an explicit scope choice after a manual edit invalidates the selected range', async () => {
    await open(); select(); fireEvent.change(input(), { target: { value: 'Only this paragraph' } });
    fireEvent.change(bodyField(), { target: { value: 'New body with changed offsets' } });
    expect(screen.getByTestId('cold-email-edit-scope-review')).toBeVisible();
    fireEvent.submit(input().closest('form')!); expect(api.refine).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Use full body' })); await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.submitRequest' })).toBeEnabled()); fireEvent.submit(input().closest('form')!); await proposed();
    expect(api.refine.mock.calls[0][4]).not.toHaveProperty('selection');
  });
  it('migrates v1 typed requests as unknown scope and never silently edits the whole body', async () => {
    const view = await open(); await saved(); const record = stored(); view.show({ isOpen: false });
    const { history: _history, editScope: _scope, ...legacy } = record.draft;
    const owner = captureOwnerToken();
    const key = STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX + encodeURIComponent(JSON.stringify([owner.uid, 'A']));
    expect(writeUserScopedRaw(key, JSON.stringify({ version: 1, ownerId: owner.uid, opportunityId: 'A', revision: record.revision, draft: { ...legacy, pendingEdit: 'Polish my selected paragraph' } }), owner)).toBe(true);
    view.show({ isOpen: true }); await screen.findByTestId('cold-email-edit-scope-review');
    fireEvent.submit(input().closest('form')!); expect(api.refine).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Use full body' })); await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.submitRequest' })).toBeEnabled()); fireEvent.submit(input().closest('form')!); await proposed();
    expect(api.refine.mock.calls[0][4]).not.toHaveProperty('selection');
  });
  it('rejects over-limit input without spending a refinement or losing the complete body', async () => {
    await open(); const long = 'a'.repeat(5000) + '尾😀'; fireEvent.change(bodyField(), { target: { value: long } }); submit();
    await screen.findByText(/Body exceeds the editing limit/); expect(api.refine).not.toHaveBeenCalled(); expect(bodyField()).toHaveValue(long); expect(input()).toHaveValue('Make this precise');
  });
  it('shows server limit errors without losing the typed request', async () => {
    api.refine.mockRejectedValue({ detail: { code: 'EMAIL_REFINE_LIMIT', field: 'instruction', max_utf16: 500 } });
    await open(); submit(); await screen.findByText(/Request exceeds the editing limit/); expect(bodyField()).toHaveValue(ORIGINAL); expect(input()).toHaveValue('Make this precise');
  });
  it('cannot apply a comparison after a manual edit away and back', async () => {
    await open(); await editAndAccept(); compare(); const restore = screen.getByRole('button', { name: 'Restore this version' });
    fireEvent.change(bodyField(), { target: { value: 'Temporary change' } }); fireEvent.change(bodyField(), { target: { value: 'Revised full body' } });
    fireEvent.click(restore); expect(screen.queryByRole('region', { name: 'Compare email versions' })).toBeNull(); expect(bodyField()).toHaveValue('Revised full body');
  });
  it('refuses an eleventh version without deleting history or replacing the current draft', async () => {
    const view = await open(); await editAndAccept(); const record = stored();
    view.show({ isOpen: false });
    const value = { ...record.draft, history: Array.from({ length: 10 }, () => ({ ...record.draft.history[0], id: crypto.randomUUID() })) };
    const latest = stored(); await saveColdEmailDraft(captureOwnerToken(), 'A', latest.revision, value);
    view.show({ isOpen: true }); await waitFor(() => expect(bodyField()).toHaveValue('Revised full body')); await act(async () => {});
    api.refine.mockResolvedValue({ body: 'Eleventh change', method: 'llm' }); fireEvent.change(input(), { target: { value: 'Eleventh request' } }); await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.submitRequest' })).toBeEnabled()); fireEvent.submit(input().closest('form')!); await proposed(); fireEvent.click(accept());
    await waitFor(() => expect(screen.getAllByText(/There are 10 saved versions/).length).toBeGreaterThan(0));
    expect(bodyField()).toHaveValue('Revised full body'); expect(stored().draft.history).toHaveLength(10);
  });
  it.each(['manual', 'close', 'owner'] as const)('cancels a held acceptance on %s without writing the candidate', async change => {
    const view = await open(); await saved(); submit(); await proposed(); await saved();
    const original = navigator.locks.request.bind(navigator.locks);
    let release!: () => void; const gate = new Promise<void>(resolve => { release = resolve; }); let held = false;
    const lock = vi.spyOn(navigator.locks, 'request').mockImplementation((async (...args: unknown[]) => {
      held = true; await gate; return original(...args as Parameters<typeof original>);
    }) as typeof navigator.locks.request);
    fireEvent.click(accept()); await waitFor(() => expect(held).toBe(true));
    if (change === 'manual') { fireEvent.change(bodyField(), { target: { value: 'Manual while saving' } }); fireEvent.change(bodyField(), { target: { value: ORIGINAL } }); }
    if (change === 'close') fireEvent.click(screen.getByRole('button', { name: 'coldEmail.closeAria' }));
    if (change === 'owner') act(() => { advanceOwnerEpoch('new-history-owner'); });
    await act(async () => { release(); if (change === 'owner') await syncLocalIdentityOwner('new-history-owner'); }); lock.mockRestore();
    if (change === 'close') await waitFor(() => expect(view.props.onClose).toHaveBeenCalledOnce());
    if (change !== 'owner') { expect(stored().draft.body).toBe(ORIGINAL); expect(stored().draft.history).toEqual([]); }
    expect(api.confirm).not.toHaveBeenCalled();
  });
  it('keeps the original durable packet on quota failure and still permits clearing it', async () => {
    await open(); await saved(); submit(); await proposed(); await saved(); const before = stored();
    const original = localStorage.setItem.bind(localStorage);
    const fail = vi.spyOn(localStorage, 'setItem').mockImplementation((key, value) => {
      if (String(value).includes('accepted_edit')) throw new DOMException('quota', 'QuotaExceededError');
      return original(key, value);
    });
    fireEvent.click(accept()); await waitFor(() => expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent(/Could not save/));
    expect(bodyField()).toHaveValue(ORIGINAL); expect(stored()).toEqual(before);
    const clear = screen.getByTestId('cold-email-draft-clear'); expect(clear).toBeEnabled(); fail.mockRestore(); api.variants.mockReturnValue(new Promise(() => {})); fireEvent.click(clear);
    await waitFor(() => expect(readColdEmailDraft(captureOwnerToken(), 'A').status).toBe('missing'));
    expect(api.confirm).not.toHaveBeenCalled();
  });

  it('keeps the reselect requirement after a valid selection is replaced by an invalid half-emoji range', async () => {
    const view = await open(); select(); select(ORIGINAL.indexOf('😀'), ORIGINAL.indexOf('😀') + 1);
    fireEvent.change(input(), { target: { value: 'Only this range' } }); await saved();
    expect(stored().draft.editScope).toBe('reselect'); await closeAndReopen(view);
    expect(screen.getByTestId('cold-email-edit-scope-review')).toBeVisible();
    expect(screen.getByRole('button', { name: 'coldEmail.submitRequest' })).toBeDisabled();
  });

  it('labels a manually changed template as manual in the saved version', async () => {
    await open(); fireEvent.change(bodyField(), { target: { value: 'My manually written draft' } }); await saved();
    await editAndAccept(); expect(stored().draft.history[0]).toMatchObject({ body: 'My manually written draft', origin: 'manual' });
  });

});
