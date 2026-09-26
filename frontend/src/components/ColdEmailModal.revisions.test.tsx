import { createHash } from 'node:crypto';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { emailReceipt, emailTarget } from './ColdEmailModal.test-fixtures';
import { writingTargetKey } from '@/lib/writing-target';
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
  const uid = `revision-owner-${++owner}`; advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
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
function pending<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
const bodyField = () => screen.getByLabelText('coldEmail.body') as HTMLTextAreaElement;
const input = () => screen.getByRole('textbox', { name: 'coldEmail.requestLabel' });
const preview = () => screen.queryByRole('region', { name: 'Pending edit suggestion' });
const accept = () => screen.getByRole('button', { name: 'Accept suggestion' });
const undo = () => screen.queryByRole('button', { name: 'Undo last accepted edit' });
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

describe('email suggestions and undo', () => {
  it('previews the second repeated passage, applies exactly there once, and undoes it', async () => {
    await open(); const { start, end } = select(); submit(); await proposed();
    expect(bodyField()).toHaveValue(ORIGINAL); expect(input()).toHaveValue('Make this precise');
    expect(api.refine.mock.calls[0][4]).toMatchObject({ selection: { start_utf16: start, end_utf16: end, text: 'same paragraph' }, subject: draft.subject });
    const button = accept(); fireEvent.click(button); fireEvent.click(button);
    const changed = ORIGINAL.slice(0, start) + '精修😀\nnew line' + ORIGINAL.slice(end);
    await waitFor(() => expect(bodyField()).toHaveValue(changed)); expect(api.refine).toHaveBeenCalledOnce(); expect(input()).toHaveValue('');
    expect(undo()).toBeVisible(); fireEvent.click(undo()!); expect(bodyField()).toHaveValue(ORIGINAL); expect(undo()).toBeNull(); expect(api.confirm).not.toHaveBeenCalled();
  });
  it('rejects a suggestion without changing the draft or losing its instruction', async () => {
    await open(); select(); submit(); await proposed(); fireEvent.click(screen.getByRole('button', { name: 'Reject suggestion' }));
    expect(bodyField()).toHaveValue(ORIGINAL); expect(input()).toHaveValue('Make this precise'); expect(preview()).toBeNull(); expect(undo()).toBeNull();
  });
  it('previews whole-body refinement and supports undo there too', async () => {
    await open(); submit(); await proposed(); expect(bodyField()).toHaveValue(ORIGINAL);
    expect(api.refine.mock.calls[0][4]).not.toHaveProperty('selection'); await apply(); expect(bodyField()).toHaveValue('Revised full body');
    fireEvent.click(undo()!); expect(bodyField()).toHaveValue(ORIGINAL);
  });
  it('supports deleting a selected passage', async () => {
    api.refine.mockImplementation((body, _i, _p, _id, opts) => selectionReply(body, opts.selection, ''));
    await open(); const { start, end } = select(); submit(); await proposed(); expect(within(preview()!).getByText('(Delete selected text)')).toBeVisible();
    await apply(); expect(bodyField()).toHaveValue(ORIGINAL.slice(0, start) + ORIGINAL.slice(end));
  });
  it.each(['body', 'subject', 'to'] as const)('permanently retires the proposal when %s is edited away and back', async field => {
    await open(); select(); submit(); await proposed(); const button = accept();
    const element = screen.getByLabelText('coldEmail.' + field) as HTMLInputElement; const before = element.value;
    fireEvent.change(element, { target: { value: 'manual' } }); fireEvent.change(element, { target: { value: before } });
    fireEvent.click(button); expect(preview()).toBeNull(); expect(bodyField()).toHaveValue(ORIGINAL); expect(undo()).toBeNull();
  });
  it('does not undo across a manual edit after accept, including editing back', async () => {
    await open(); submit(); await proposed(); await apply(); const staleUndo = undo()!;
    fireEvent.change(bodyField(), { target: { value: 'Manual version' } }); fireEvent.change(bodyField(), { target: { value: 'Revised full body' } });
    fireEvent.click(staleUndo); expect(bodyField()).toHaveValue('Revised full body'); expect(undo()).toBeNull();
  });
  it('keeps the request after a provider failure and retries the same selection', async () => {
    api.refine.mockRejectedValueOnce(new Error('offline'));
    await open(); const { start, end } = select(); submit(); await screen.findByText('coldEmail.editFailed');
    expect(input()).toHaveValue('Make this precise'); expect(bodyField()).toHaveValue(ORIGINAL);
    fireEvent.submit(input().closest('form')!); await proposed(); expect(api.refine.mock.calls[1][4].selection).toEqual({ start_utf16: start, end_utf16: end, text: 'same paragraph' });
  });
  it.each(['provider_unavailable', 'insufficient_evidence', 'review_required', 'invalid_output', 'fabrication', 'unchanged'])('preserves input and text when selection returns %s', async reason => {
    api.refine.mockResolvedValue({ scope: 'selection', outcome: 'no_change', method: 'none', reason });
    await open(); select(); submit(); await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.submitRequest' })).toBeEnabled());
    expect(api.refine).toHaveBeenCalledOnce(); expect(preview()).toBeNull(); expect(bodyField()).toHaveValue(ORIGINAL); expect(input()).toHaveValue('Make this precise');
  });
  it.each(['hash', 'range', 'text', 'scope'] as const)('rejects an incorrect %s receipt without offering acceptance', async fault => {
    api.refine.mockImplementation((body, _i, _p, _id, opts) => {
      const result = selectionReply(body, opts.selection);
      if (fault === 'hash') result.proposal.base_body_sha256 = '0'.repeat(64);
      if (fault === 'range') result.proposal.start_utf16 = 0;
      if (fault === 'text') result.proposal.original_text = 'wrong';
      if (fault === 'scope') return { body: 'Old server whole response', method: 'llm' };
      return result;
    });
    await open(); select(); submit(); await screen.findByText('coldEmail.editFailed'); expect(preview()).toBeNull(); expect(bodyField()).toHaveValue(ORIGINAL); expect(input()).toHaveValue('Make this precise');
  });
  it('rejects a delayed suggestion after manual editing back to the original body', async () => {
    const result = pending<ReturnType<typeof selectionReply>>(); api.refine.mockReturnValue(result.promise);
    await open(); select(); submit(); await waitFor(() => expect(api.refine).toHaveBeenCalledOnce());
    fireEvent.change(bodyField(), { target: { value: 'Changed' } }); fireEvent.change(bodyField(), { target: { value: ORIGINAL } });
    await act(async () => result.resolve(selectionReply(ORIGINAL, api.refine.mock.calls[0][4].selection)));
    expect(preview()).toBeNull(); expect(bodyField()).toHaveValue(ORIGINAL);
  });
  it.each(['profile', 'target', 'close', 'variant', 'context'] as const)('retires suggestions on a %s change', async change => {
    const view = await open(); select(); submit(); await proposed(); const button = accept();
    if (change === 'profile') view.show({ profile: { ...profile, research_interests: 'new interests' } });
    if (change === 'target') view.show({ target: { ...emailTarget('A'), description_clean: 'Different project' } });
    if (change === 'close') { view.show({ isOpen: false }); view.show({}); }
    if (change === 'variant') fireEvent.click(screen.getByRole('button', { name: 'Second' }));
    if (change === 'context') {
      fireEvent.click(screen.getByTestId('email-contact-context-panel').querySelector('summary')!);
      fireEvent.change(screen.getByLabelText('Contact purpose'), { target: { value: 'referral' } });
    }
    await act(async () => {}); fireEvent.click(button); expect(preview()).toBeNull(); expect(undo()).toBeNull();
    expect(bodyField()).toHaveValue(change === 'variant' ? 'Other variant' : ORIGINAL);
  });
  it('retires suggestions on owner change and never records contact', async () => {
    await open(); select(); submit(); await proposed(); const button = accept();
    await act(async () => { advanceOwnerEpoch('other-account'); await syncLocalIdentityOwner('other-account'); });
    fireEvent.click(button); expect(preview()).toBeNull(); expect(api.confirm).not.toHaveBeenCalled();
  });
  it('does not turn an invalid half-emoji selection into a whole-body request', async () => {
    await open(); const start = ORIGINAL.indexOf('😀'); select(start, start + 1); submit();
    expect(api.refine).not.toHaveBeenCalled(); expect(screen.getByRole('button', { name: 'coldEmail.submitRequest' })).toBeDisabled(); expect(bodyField()).toHaveValue(ORIGINAL);
  });
  it('rechecks the target before acceptance without requesting another model edit', async () => {
    const target = emailTarget('A'); const check = vi.fn(async () => ({ checkId: 1, owner: captureOwnerToken(), target, key: writingTargetKey(target)! }));
    await open({ target, targetRefresh: { status: 'ready', target, reason: null, refresh: async () => true, checkForAction: check } });
    select(); submit(); await proposed(); const before = check.mock.calls.length; await apply();
    expect(check).toHaveBeenCalledTimes(before + 1); expect(api.refine).toHaveBeenCalledOnce(); expect(bodyField().value).toContain('精修');
  });
  it.each(['failure', 'reject', 'unchanged'] as const)('keeps the last accepted undo when a later request ends with %s', async outcome => {
    await open(); submit(); await proposed(); await apply(); expect(undo()).toBeVisible();
    if (outcome === 'failure') api.refine.mockRejectedValueOnce(new Error('offline'));
    else api.refine.mockResolvedValueOnce({ body: outcome === 'unchanged' ? 'Revised full body' : 'Another proposal', method: 'llm' });
    submit('Another request');
    if (outcome === 'failure') await screen.findByText('coldEmail.editFailed');
    else if (outcome === 'unchanged') await screen.findByText('The body is unchanged. Your request is kept.');
    else { await proposed(); fireEvent.click(screen.getByRole('button', { name: 'Reject suggestion' })); }
    expect(undo()).toBeVisible(); fireEvent.click(undo()!); expect(bodyField()).toHaveValue(ORIGINAL);
  });
  it('disables whole-body coursework insertion while a passage is selected', async () => {
    await open({ profile: { ...profile, coursework: ['CS 225'] } }); select();
    const button = screen.getByRole('button', { name: 'coldEmail.quickActions.coursework' });
    expect(button).toBeDisabled(); fireEvent.click(button); expect(bodyField()).toHaveValue(ORIGINAL); expect(preview()).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Use full body' })); fireEvent.click(button); await proposed();
    expect(bodyField()).toHaveValue(ORIGINAL); await apply(); expect(bodyField().value).toContain('CS 225');
  });
  it('rejects acceptance when the fresh target receipt differs', async () => {
    const target = emailTarget('A'); const check = vi.fn(async () => ({ checkId: 1, owner: captureOwnerToken(), target, key: writingTargetKey(target)! }));
    const view = await open({ target, targetRefresh: { status: 'ready', target, reason: null, refresh: async () => true, checkForAction: check } });
    select(); submit(); await proposed(); const changed = { ...target, description_clean: 'Changed source' };
    check.mockResolvedValueOnce({ checkId: 2, owner: captureOwnerToken(), target: changed, key: writingTargetKey(changed)! });
    fireEvent.click(accept()); await act(async () => {});
    view.show({ target: changed, targetRefresh: { status: 'ready', target: changed, reason: null, refresh: async () => true, checkForAction: check } });
    expect(preview()).toBeNull(); expect(bodyField()).toHaveValue(ORIGINAL); expect(undo()).toBeNull(); expect(api.refine).toHaveBeenCalledOnce();
  });
});
