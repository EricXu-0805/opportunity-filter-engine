import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { EmailContactContext, ProfileData } from '@/lib/types';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { emailTarget, emailReceipt } from './ColdEmailModal.test-fixtures';

const api = vi.hoisted(() => ({ variants: vi.fn(), stream: vi.fn(), refine: vi.fn(), contact: vi.fn(), reminder: vi.fn() }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key, locale: 'en' }) }));
vi.mock('@/lib/api', () => ({
  getEmailVariants: (...args: unknown[]) => emailReceipt(api.variants(...args), args[1] as string, undefined, (args[3] as { contactContext: EmailContactContext }).contactContext),
  generateColdEmailStream: (...args: unknown[]) => emailReceipt(api.stream(...args), args[1] as string, undefined, (args[2] as { contactContext: EmailContactContext }).contactContext),
  generateColdEmail: vi.fn(),
  refineEmail: (...args: unknown[]) => emailReceipt(api.refine(...args), args[3] as string, undefined, (args[4] as { contactContext: EmailContactContext }).contactContext),
  getVapidPublicKey: vi.fn(),
}));
vi.mock('@/lib/supabase', () => ({ onAuthChange: () => () => {}, confirmInteractionContact: api.contact, updateInteractionDetails: api.reminder }));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: vi.fn() }) }));
import ColdEmailModal from './ColdEmailModal';

const profile: ProfileData = { name: 'Alex', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore',
  is_international: false, research_interests: 'sensors', skills: [], coursework: [] };
const draft = (purpose: string) => ({ id: 'template', label: 'Template', subject: `Subject ${purpose}`, body: `Draft ${purpose}`,
  recipient_email: 'lab@example.edu', mailto_link: '', method: 'template' });
let owner = 0;
beforeEach(async () => {
  const uid = `context-owner-${++owner}`; advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  api.variants.mockReset().mockImplementation((_p, _id, _unused, opts) => ({ variants: [draft(opts.contactContext.purpose)] }));
  api.stream.mockReset().mockResolvedValue(draft('fallback'));
  api.refine.mockReset().mockResolvedValue({ body: 'Refined draft', method: 'llm' });
  api.contact.mockReset(); api.reminder.mockReset();
});
function open() {
  const onClose = vi.fn(); const props = { isOpen: true, onClose, profile, opportunityId: 'A', opportunityTitle: 'Lab', target: emailTarget('A') };
  const view = render(<ColdEmailModal {...props} />);
  return { ...view, onClose, show: (next: Partial<typeof props>) => view.rerender(<ColdEmailModal {...props} {...next} />) };
}
async function ready() { await screen.findByDisplayValue('Draft first_contact'); await waitFor(() => expect(api.stream).toHaveBeenCalledTimes(1)); await act(async () => {}); }
function expand() { const details = screen.getByTestId('email-contact-context-panel'); if (!(details as HTMLDetailsElement).open) fireEvent.click(details.querySelector('summary')!); }
function purpose(value: string) { expand(); fireEvent.change(screen.getByLabelText('Contact purpose'), { target: { value } }); }
function apply() { fireEvent.click(screen.getByRole('button', { name: 'Apply background to this draft' })); }
function regenerate() { fireEvent.click(screen.getByRole('button', { name: 'coldEmail.regenerateFromProfile' })); }
function manual() {
  fireEvent.change(screen.getByLabelText('coldEmail.subject'), { target: { value: 'Manual subject' } });
  fireEvent.change(screen.getByLabelText('coldEmail.body'), { target: { value: 'Manual body' } });
  fireEvent.change(screen.getByLabelText('coldEmail.to'), { target: { value: 'manual@example.edu' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'coldEmail.requestLabel' }), { target: { value: 'Unsubmitted instruction' } });
}
function kept() {
  expect(screen.getByLabelText('coldEmail.subject')).toHaveValue('Manual subject');
  expect(screen.getByLabelText('coldEmail.body')).toHaveValue('Manual body');
  expect(screen.getByLabelText('coldEmail.to')).toHaveValue('manual@example.edu');
  expect(screen.getByRole('textbox', { name: 'coldEmail.requestLabel' })).toHaveValue('Unsubmitted instruction');
}
function referral() {
  purpose('referral');
  fireEvent.change(screen.getByLabelText('Who referred you? (required)'), { target: { value: 'Dr. Chen' } });
  fireEvent.change(screen.getByLabelText('What did they actually say or suggest? (required)'), { target: { value: 'Suggested asking about sensor methods.' } });
  fireEvent.click(screen.getByLabelText('I confirm these referral details are accurate and I may mention this person in the draft.'));
  apply();
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }

describe('confirmed contact context and editable email lifetime', () => {
  it('applies referral background without generating or recording contact, then explicitly rebuilds with that context', async () => {
    open(); await ready(); manual(); referral(); kept();
    expect(api.variants).toHaveBeenCalledTimes(1); expect(api.stream).toHaveBeenCalledTimes(1);
    expect(api.contact).not.toHaveBeenCalled(); expect(api.reminder).not.toHaveBeenCalled();
    regenerate(); await screen.findByDisplayValue('Draft referral');
    await waitFor(() => expect(api.stream).toHaveBeenCalledTimes(2));
    const context = api.variants.mock.calls[1][3].contactContext;
    expect(context).toEqual({ version: 1, purpose: 'referral', referral: { referrer_name: 'Dr. Chen', referral_note: 'Suggested asking about sensor methods.', confirmed: true } });
    expect(api.stream.mock.calls[1][2].contactContext).toEqual(context);
    expect(screen.getByLabelText('coldEmail.to')).toHaveValue('manual@example.edu');
    expect(screen.getByRole('textbox', { name: 'coldEmail.requestLabel' })).toHaveValue('Unsubmitted instruction');
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.quickActions.shorter' }));
    await screen.findByDisplayValue('Refined draft'); expect(api.refine.mock.calls[0][4].contactContext).toEqual(context);
  });
  it('requires confirmation and missing follow-up facts before allowing any new generation', async () => {
    open(); await ready(); manual(); purpose('follow_up'); apply(); kept();
    expect(screen.getByRole('button', { name: 'coldEmail.regenerateFromProfile' })).toBeDisabled();
    expect(api.variants).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByLabelText('Previous email you sent (required)'), { target: { value: 'I asked about your sensor project.' } });
    fireEvent.click(screen.getByLabelText('I confirm I actually sent this email to this target and these details are accurate. This does not record a new send.'));
    apply(); kept(); expect(api.variants).toHaveBeenCalledTimes(1);
    regenerate(); await screen.findByDisplayValue('Draft follow_up');
    expect(api.variants.mock.calls[1][3].contactContext.follow_up).toEqual({ sent_confirmed: true, previous_message: 'I asked about your sensor project.', reply_status: 'unknown' });
    expect(api.contact).not.toHaveBeenCalled();
  });
  it('retires a held AI response across first-contact to referral to first-contact even if the old context returns', async () => {
    const held = deferred<ReturnType<typeof draft>>(); api.stream.mockReturnValueOnce(held.promise);
    open(); await ready(); manual(); purpose('referral'); purpose('first_contact'); apply(); kept();
    await act(async () => held.resolve({ ...draft('STALE'), method: 'ai' })); kept();
    expect(screen.queryByDisplayValue('Draft STALE')).toBeNull(); expect(api.stream).toHaveBeenCalledTimes(1);
    regenerate(); await screen.findByDisplayValue('Draft first_contact'); await waitFor(() => expect(api.stream).toHaveBeenCalledTimes(2));
  });
  it('keeps all manual fields on a failed explicit rebuild and supports retry with the applied context', async () => {
    open(); await ready(); manual(); referral(); api.variants.mockRejectedValueOnce(new Error('offline'));
    regenerate(); await screen.findByText('coldEmail.profileRegenerateFailed'); kept();
    regenerate(); await screen.findByDisplayValue('Draft referral'); expect(api.variants).toHaveBeenCalledTimes(3);
  });
  it('rejects a same-target refinement with a receipt for different background', async () => {
    open(); await ready(); manual();
    api.refine.mockResolvedValueOnce({ body: 'WRONG CONTEXT', method: 'llm', contact_context_receipt: { version: 1, purpose: 'first_contact', context_sig: '0'.repeat(64) } });
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.quickActions.shorter' }));
    await screen.findByText('coldEmail.editFailed'); kept();
    expect(screen.queryByDisplayValue('WRONG CONTEXT')).toBeNull();
  });
  it('clears private background on target change and starts the new target with first contact', async () => {
    const view = open(); await ready(); referral();
    view.show({ opportunityId: 'B', target: emailTarget('B') });
    await waitFor(() => expect(api.variants).toHaveBeenCalledTimes(2));
    expect(api.variants.mock.calls[1][1]).toBe('B'); expect(api.variants.mock.calls[1][3].contactContext).toEqual({ version: 1, purpose: 'first_contact' });
    await screen.findByDisplayValue('Draft first_contact'); expand(); expect(screen.queryByDisplayValue('Dr. Chen')).toBeNull();
  });
  it.each([false, true])('allows a new send confirmation after rebuilding; an earlier held receipt cannot confirm the new draft (held=%s)', async held => {
    vi.spyOn(window, 'open').mockImplementation(() => null);
    const old = deferred<{ type: 'contacted'; last_contacted_at: string }>();
    const record = { type: 'contacted' as const, last_contacted_at: '2026-09-25T08:00:00Z' };
    api.contact.mockResolvedValue(record); if (held) api.contact.mockReturnValueOnce(old.promise);
    open(); await ready(); fireEvent.click(screen.getByRole('button', { name: 'coldEmail.gmail' }));
    fireEvent.click(screen.getByTestId('cold-email-confirm-sent'));
    expect(api.contact).toHaveBeenCalledTimes(1);
    if (!held) await waitFor(() => expect(screen.queryByTestId('cold-email-confirm-sent')).toBeNull());
    referral(); regenerate(); await screen.findByDisplayValue('Draft referral');
    if (held) await act(async () => old.resolve(record));
    expect(api.contact).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.gmail' }));
    const confirm = await screen.findByTestId('cold-email-confirm-sent'); expect(confirm).toBeEnabled();
    fireEvent.click(confirm); await waitFor(() => expect(api.contact).toHaveBeenCalledTimes(2));
    expect(api.reminder).not.toHaveBeenCalled();
  });
  it('does not use a delayed clipboard success from the old draft to prompt a send for the new draft', async () => {
    const copied = deferred<void>();
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn(() => copied.promise) } });
    open(); await ready(); fireEvent.click(screen.getByRole('button', { name: 'coldEmail.copy' }));
    referral(); regenerate(); await screen.findByDisplayValue('Draft referral');
    await act(async () => copied.resolve());
    expect(screen.queryByTestId('cold-email-confirm-sent')).toBeNull();
    expect(screen.queryByText('coldEmail.copied')).toBeNull();
    expect(api.contact).not.toHaveBeenCalled();
  });
  it('cannot prepare follow-up after a refusal and preserves the existing draft', async () => {
    open(); await ready(); manual(); purpose('follow_up');
    fireEvent.change(screen.getByLabelText('Reply status'), { target: { value: 'do_not_contact' } });
    expect(screen.getByRole('button', { name: 'Apply background to this draft' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'coldEmail.regenerateFromProfile' })).toBeDisabled(); kept(); expect(api.variants).toHaveBeenCalledTimes(1);
  });
});
