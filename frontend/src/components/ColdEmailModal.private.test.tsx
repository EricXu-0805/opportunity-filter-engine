import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { setupOwner, deferred, owner as changeOwner, OTHER, OWNER } from '@/lib/application-material.test-utils';
import { captureOwnerToken } from '@/lib/identity-owner';
import { privateEmailKey, type PrivateEmailContext } from '@/lib/private-email';
import type { PrivateEmailActionReceipt, PrivateEmailTargetState } from '@/lib/use-private-email-target';
import type { ProfileData } from '@/lib/types';
const api = vi.hoisted(() => ({ variants: vi.fn(), validate: vi.fn(), publicVariants: vi.fn(), ai: vi.fn(), refine: vi.fn(), confirm: vi.fn(), recipient: vi.fn() }));
vi.mock('@/lib/private-email', async original => ({ ...await original<typeof import('@/lib/private-email')>(),
  privateEmailVariants: (...args: unknown[]) => api.variants(...args), validatePrivateEmail: (...args: unknown[]) => api.validate(...args) }));
vi.mock('@/lib/api', () => ({ getEmailVariants: api.publicVariants, generateColdEmail: api.ai, generateColdEmailStream: api.ai,
  refineEmail: api.refine, validateEmailDraft: vi.fn(), getVapidPublicKey: vi.fn() }));
vi.mock('@/lib/email-compose', () => ({ verifyComposeRecipient: api.recipient }));
vi.mock('@/lib/supabase', () => ({ onAuthChange: () => () => {}, confirmContactEvent: api.confirm, updateInteractionDetails: vi.fn() }));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: vi.fn() }) }));
vi.mock('@/i18n/client', () => { const t = (key: string) => key; return { useT: () => ({ t, locale: 'en' }), useLocale: () => 'en' }; });
import ColdEmailModal from './ColdEmailModal';
import { emailReceipt } from './ColdEmailModal.test-fixtures';
const id = 'private-import:cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const profile: ProfileData = { name: 'Alex', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore', is_international: false, research_interests: 'sensors', skills: [], coursework: [] };
const target: PrivateEmailContext = { version: 1, target_scope: 'private_import', verification: 'unverified', purpose: 'first_contact',
  id, owner_id: OWNER, revision: 1, source_version: 'pit1:' + '1'.repeat(64), writing_version: 'pwt1:' + '2'.repeat(64), projection_version: 1, policy_version: 1,
  title: 'Saved source', organization: null, source_url: 'https://example.edu/source', import_source: null, provider_allowed: false,
  contact_policy: { state: 'unknown', reason: 'unverified_import', quotes: [] } };
const draft = { id: 'private-first-contact', label: 'First contact', subject: 'Private subject', body: 'My full private draft.', recipient_email: '', mailto_link: '' };
const receipt = (value = target): PrivateEmailActionReceipt => ({ checkId: 1, owner: captureOwnerToken(), target: value, key: privateEmailKey(value)! });
beforeEach(async () => {
  await setupOwner();
  api.variants.mockReset().mockImplementation(async (_p, targetId, context) => emailReceipt({ variants: [draft], recipient_status: 'unavailable', grounding: 'no_target_data', pipeline_version: 'private-cold-email-v1' }, targetId, context.writing_version));
  api.validate.mockReset().mockResolvedValue({ outcome: 'ready', issues: [] }); api.ai.mockClear(); api.publicVariants.mockClear(); api.refine.mockClear(); api.recipient.mockClear(); api.confirm.mockReset().mockResolvedValue({ interaction: null });
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
});
async function harness() {
  const check = vi.fn().mockImplementation(async () => receipt());
  const refresh: PrivateEmailTargetState = { status: 'ready', target, reason: null, refresh: vi.fn().mockResolvedValue(true), checkForAction: check };
  const profileCheck = vi.fn().mockImplementation(async () => ({ checkId: 1, owner: captureOwnerToken(), profile, revision: 1, source: 'cloud' }));
  const onContactConfirmed = vi.fn(); const close = vi.fn();
  const props = { isOpen: true, onClose: close, profile, opportunityId: id, opportunityTitle: target.title,
    privateTargetRefresh: refresh, targetReady: true, profileRefresh: { status: 'ready' as const, refresh: vi.fn(), checkForAction: profileCheck }, onContactConfirmed };
  const view = render(<ColdEmailModal {...props} />); await screen.findByDisplayValue(draft.body, {}, { timeout: 1000 }); await act(async () => {});
  check.mockClear(); profileCheck.mockClear();
  const popup = { closed: false, opener: 'original', location: { href: 'about:blank' }, close: vi.fn() };
  const open = vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window);
  return { ...view, props, check, profileCheck, onContactConfirmed, close, popup, open };
}
const compose = () => screen.getByRole('button', { name: 'coldEmail.gmail' });
function enterRecipient() { fireEvent.change(screen.getByLabelText('coldEmail.to'), { target: { value: 'person@example.edu' } }); }
function review() { fireEvent.click(screen.getByRole('checkbox', { name: /reviewed the current source/ })); }

describe('private email in the shared editor', () => {
  it('shows an honest manual template, with no public or AI request and no research controls', async () => {
    await harness(); expect(api.variants).toHaveBeenCalledOnce(); expect(api.publicVariants).not.toHaveBeenCalled(); expect(api.ai).not.toHaveBeenCalled(); expect(api.refine).not.toHaveBeenCalled();
    expect(screen.getByTestId('private-email-source')).toHaveTextContent('AI writing is not connected');
    expect(screen.queryByText('coldEmail.aiVariantLabel')).toBeNull(); expect(screen.queryByTestId('cold-email-chat-history')).toBeNull();
    expect(screen.getByLabelText('coldEmail.to')).toHaveValue(''); expect(compose()).toBeDisabled();
  });
  it('requires a valid recipient and fresh user review, opens only after both checks, and records only explicit sent confirmation', async () => {
    const view = await harness(); enterRecipient(); expect(compose()).toBeDisabled(); review(); expect(compose()).toBeEnabled();
    fireEvent.click(compose()); await waitFor(() => expect(view.popup.location.href).toContain('person%40example.edu'));
    expect(view.check).toHaveBeenCalledOnce(); expect(view.profileCheck).toHaveBeenCalledOnce();
    expect(api.validate).toHaveBeenCalledWith(draft.subject, draft.body, 'person@example.edu', true, profile, id, target, expect.any(Object), expect.any(AbortSignal));
    expect(api.recipient).not.toHaveBeenCalled(); expect(api.confirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('cold-email-confirm-sent'));
    await waitFor(() => expect(api.confirm).toHaveBeenCalledOnce());
    expect(api.confirm.mock.calls[0][0]).toBe(id); expect(api.confirm.mock.calls[0][1].materialRefs).toContainEqual({ kind: 'target', version: target.writing_version });
    await waitFor(() => expect(view.onContactConfirmed).toHaveBeenCalledOnce());
  });
  it('withdraws review after changing recipient and rejects invalid manual syntax before opening', async () => {
    const view = await harness(); enterRecipient(); review();
    fireEvent.change(screen.getByLabelText('coldEmail.to'), { target: { value: 'not-an-email' } });
    expect(screen.getByRole('checkbox', { name: /reviewed the current source/ })).not.toBeChecked();
    expect(compose()).toBeDisabled(); fireEvent.click(compose()); expect(view.open).not.toHaveBeenCalled();
  });
  it('keeps manual changes when a private version changes during the pre-action read', async () => {
    const view = await harness(); enterRecipient(); review(); const changed = { ...target, revision: 2, writing_version: 'pwt1:' + '3'.repeat(64) };
    const held = deferred<PrivateEmailActionReceipt | null>(); view.check.mockReturnValue(held.promise);
    fireEvent.click(compose()); await waitFor(() => expect(view.check).toHaveBeenCalledOnce());
    view.rerender(<ColdEmailModal {...view.props} privateTargetRefresh={{ ...view.props.privateTargetRefresh, target: changed }} />);
    await act(async () => held.resolve(receipt(changed)));
    expect(view.popup.location.href).toBe('about:blank'); expect(view.popup.close).toHaveBeenCalledOnce();
    expect(screen.getByDisplayValue(draft.body)).toBeInTheDocument(); expect(api.validate).not.toHaveBeenCalled();
    expect(screen.getByRole('checkbox', { name: /reviewed the current source/ })).not.toBeChecked();
  });
  it('retires an action after editing while a private check is pending', async () => {
    const view = await harness(); enterRecipient(); review(); const held = deferred<PrivateEmailActionReceipt | null>(); view.check.mockReturnValue(held.promise);
    fireEvent.click(compose()); await waitFor(() => expect(view.check).toHaveBeenCalledOnce());
    fireEvent.change(screen.getByLabelText('coldEmail.body'), { target: { value: 'My untouched manual changes.' } });
    await act(async () => held.resolve(receipt())); expect(view.popup.close).toHaveBeenCalledOnce();
    expect(view.popup.location.href).toBe('about:blank'); expect(api.validate).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue('My untouched manual changes.')).toBeInTheDocument();
  });
  it('keeps the draft when server validation finds a new contact restriction', async () => {
    const view = await harness(); enterRecipient(); review(); api.validate.mockResolvedValue({ outcome: 'review_required', issues: ['contact_blocked'] });
    fireEvent.click(compose()); await waitFor(() => expect(view.popup.close).toHaveBeenCalledOnce());
    expect(screen.getByTestId('email-condition-review')).toHaveTextContent('contact restrictions'); expect(screen.getByDisplayValue(draft.body)).toBeInTheDocument();
    expect(api.confirm).not.toHaveBeenCalled();
  });
  it('can copy a blocked draft as a backup without a contact record', async () => {
    const view = await harness(); const blocked: PrivateEmailContext = { ...target, contact_policy: { state: 'blocked', reason: 'no_email', quotes: [{ start: 0, end: 13, quote: 'Do not email.', restriction: 'no_email' }] } };
    view.rerender(<ColdEmailModal {...view.props} targetReady={false} privateTargetRefresh={{ ...view.props.privateTargetRefresh, status: 'blocked', target: blocked }} />);
    expect(compose()).toBeDisabled(); fireEvent.click(screen.getByRole('button', { name: 'Copy draft only' }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalled()); expect(api.confirm).not.toHaveBeenCalled(); expect(view.open).not.toHaveBeenCalled();
  });
  it('does not navigate or confirm when the owner changes during private validation', async () => {
    const view = await harness(); enterRecipient(); review(); const held = deferred<{ outcome: 'ready'; issues: [] }>(); api.validate.mockReturnValue(held.promise);
    fireEvent.click(compose()); await waitFor(() => expect(api.validate).toHaveBeenCalledOnce());
    await act(async () => { await changeOwner(OTHER); }); await act(async () => held.resolve({ outcome: 'ready', issues: [] }));
    expect(view.popup.location.href).toBe('about:blank'); expect(view.popup.close).toHaveBeenCalledOnce(); expect(api.confirm).not.toHaveBeenCalled();
  });
  it('restores full manual text and recipient after reopening, with review reset', async () => {
    const view = await harness(); enterRecipient(); review();
    fireEvent.change(screen.getByLabelText('coldEmail.body'), { target: { value: 'Saved private manual draft END.' } });
    await waitFor(() => expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent('Saved on this browser'));
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.closeAria' })); await waitFor(() => expect(view.close).toHaveBeenCalledOnce()); view.unmount();
    render(<ColdEmailModal {...view.props} />); await screen.findByDisplayValue('Saved private manual draft END.');
    expect(screen.getByDisplayValue('person@example.edu')).toBeInTheDocument(); expect(screen.getByRole('checkbox', { name: /reviewed the current source/ })).not.toBeChecked();
    expect(api.ai).not.toHaveBeenCalled();
  });
});
