import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { advanceOwnerEpoch, captureOwnerToken, PRIVATE_STORAGE_LOCK, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { createColdEmailDraftWriter, readColdEmailDraft } from '@/lib/cold-email-draft';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { writingTargetKey } from '@/lib/writing-target';
import type { ProfileActionReceipt } from '@/lib/use-profile-refresh';
import type { TargetActionReceipt } from '@/lib/use-writing-target';
import type { EmailContactContext, Opportunity, ProfileData } from '@/lib/types';
import { emailReceipt, emailTarget } from './ColdEmailModal.test-fixtures';

const api = vi.hoisted(() => ({ variants: vi.fn(), stream: vi.fn(), refine: vi.fn(), recipient: vi.fn(), confirm: vi.fn() }));
vi.mock('@/lib/api', () => ({
  getEmailVariants: (...args: unknown[]) => emailReceipt(api.variants(...args), args[1] as string,
    (args[3] as { expectedTargetVersion: string }).expectedTargetVersion,
    (args[3] as { contactContext: EmailContactContext }).contactContext),
  generateColdEmailStream: (...args: unknown[]) => emailReceipt(api.stream(...args), args[1] as string,
    (args[2] as { expectedTargetVersion: string }).expectedTargetVersion,
    (args[2] as { contactContext: EmailContactContext }).contactContext),
  refineEmail: api.refine, generateColdEmail: vi.fn(), getVapidPublicKey: vi.fn(),
}));
vi.mock('@/lib/email-compose', () => ({ verifyComposeRecipient: api.recipient }));
vi.mock('@/lib/supabase', () => ({ onAuthChange: () => () => {}, confirmContactEvent: api.confirm, updateInteractionDetails: vi.fn() }));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: vi.fn() }) }));
vi.mock('@/i18n/client', () => { const t = (key: string) => key; return { useT: () => ({ t, locale: 'en' }) }; });
vi.mock('./ResumeSupplementPanel', () => ({ default: () => <div /> }));
import ColdEmailModal from './ColdEmailModal';

const profile: ProfileData = { name: 'Alex', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore',
  is_international: false, research_interests: 'sensors', skills: [], coursework: [] };
const target = emailTarget('recovery-target');
const draft = { id: 'v1', label: 'Template', subject: 'Original subject', body: 'Original complete draft', recipient_email: 'lab@example.edu', mailto_link: '' };
const edits = { subject: 'My manually edited subject', body: 'My complete handwritten paragraph.\nDo not replace it.', recipient: 'chosen@example.edu', request: 'Keep my project contribution and shorten the introduction.' };
type Props = ComponentProps<typeof ColdEmailModal>;
let ownerNumber = 0;

beforeEach(async () => {
  localStorage.clear(); advanceOwnerEpoch('draft-recovery-' + ++ownerNumber); await syncLocalIdentityOwner('draft-recovery-' + ownerNumber);
  api.variants.mockReset().mockResolvedValue({ variants: [draft], recipient_status: 'revealed' });
  api.stream.mockReset().mockResolvedValue({ ...draft, method: 'template' }); api.refine.mockReset();
  api.recipient.mockReset().mockResolvedValue(undefined); api.confirm.mockReset().mockResolvedValue({ interaction: { type: 'contacted' } });
  vi.spyOn(window, 'open').mockImplementation(() => ({ closed: false, opener: null, location: { href: 'about:blank' }, close: vi.fn() }) as unknown as Window);
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
});
function mount(overrides: Partial<Props> = {}) {
  const props: Props = { isOpen: true, onClose: vi.fn(), profile, opportunityId: target.id, opportunityTitle: 'Lab', target, ...overrides };
  return { ...render(<ColdEmailModal {...props} />), props };
}
const field = (name: 'subject' | 'body' | 'to' | 'requestLabel') => screen.getByLabelText('coldEmail.' + name);
const button = (name: string) => screen.getByRole('button', { name: 'coldEmail.' + name });
const change = (name: Parameters<typeof field>[0], value: string) => fireEvent.change(field(name), { target: { value } });
async function ready() {
  await screen.findByDisplayValue(draft.body);
  await waitFor(() => expect(api.stream).toHaveBeenCalledOnce());
  await act(async () => {});
}
function edit() { change('subject', edits.subject); change('body', edits.body); change('to', edits.recipient); change('requestLabel', edits.request); }
function expectEdits() {
  expect(field('subject')).toHaveValue(edits.subject); expect(field('body')).toHaveValue(edits.body);
  expect(field('to')).toHaveValue(edits.recipient); expect(field('requestLabel')).toHaveValue(edits.request);
}
async function close(view: ReturnType<typeof mount>) {
  fireEvent.click(button('closeAria'));
  await waitFor(() => expect(view.props.onClose).toHaveBeenCalledOnce());
  view.unmount();
}
async function restored() {
  await waitFor(() => expect(field('body')).toHaveValue(edits.body)); await act(async () => {}); expectEdits();
  expect(api.stream).not.toHaveBeenCalled(); expect(api.refine).not.toHaveBeenCalled(); expect(api.confirm).not.toHaveBeenCalled();
}
async function saved(body = edits.body) {
  await waitFor(() => {
    const record = readColdEmailDraft(captureOwnerToken(), target.id);
    expect(record.status).toBe('present');
    if (record.status === 'present') expect(record.draft.body).toBe(body);
    expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent(/Saved on this browser/);
  });
}
function clearCalls() { api.variants.mockClear(); api.stream.mockClear(); api.refine.mockClear(); api.confirm.mockClear(); }
function openContext() { const panel = screen.getByTestId('email-contact-context-panel'); fireEvent.click(panel.querySelector('summary')!); fireEvent(panel, new Event('toggle')); return panel; }

// Real identity authority, Web Locks, persistence store and contact panel. Only
// network/model/composer boundaries are faked; restored content must survive a
// fresh component instance rather than accidentally remaining in React state.
describe('persistent cold-email draft recovery', () => {
  it('restores all manual editor fields after close and a fresh mount without automatic AI', async () => {
    const first = mount(); await ready(); edit(); await close(first); clearCalls();
    api.variants.mockResolvedValue({ variants: [{ ...draft, subject: 'A new template', body: 'A replacement must not overwrite the draft' }], recipient_status: 'revealed' });
    mount(); await restored();
    expect(screen.getByTestId('cold-email-draft-status')).toBeVisible();
  });

  it('restores on the same mounted component after close and reopen', async () => {
    const view = mount(); await ready(); edit(); fireEvent.click(button('closeAria'));
    await waitFor(() => expect(view.props.onClose).toHaveBeenCalledOnce());
    view.rerender(<ColdEmailModal {...view.props} isOpen={false} />); clearCalls();
    view.rerender(<ColdEmailModal {...view.props} isOpen />); await restored();
  });

  it('recovers persisted edits after a parent navigation unmount without a modal close callback', async () => {
    const view = mount(); await ready(); edit();
    await waitFor(() => expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent(/Saved on this browser/));
    view.unmount(); clearCalls(); mount(); await restored();
  });

  it('restores incomplete background answers as pending without applying them or requesting another draft', async () => {
    const view = mount(); await ready(); edit(); openContext();
    fireEvent.change(screen.getByLabelText('Contact purpose'), { target: { value: 'referral' } });
    fireEvent.change(screen.getByLabelText('Who referred you? (required)'), { target: { value: 'A person I still need to ask' } });
    fireEvent.change(screen.getByLabelText('When could you participate? (optional)'), { target: { value: 'Possibly Tuesdays; not confirmed' } });
    await close(view); clearCalls(); mount(); await restored();
    expect(screen.getByTestId('email-contact-context-panel')).toHaveAttribute('open');
    expect(screen.getByLabelText('Contact purpose')).toHaveValue('referral');
    expect(screen.getByLabelText('Who referred you? (required)')).toHaveValue('A person I still need to ask');
    expect(screen.getByLabelText('When could you participate? (optional)')).toHaveValue('Possibly Tuesdays; not confirmed');
    expect(screen.getByLabelText('I confirm this availability is accurate.')).not.toBeChecked();
    expect(screen.getByTestId('email-contact-context-status')).toHaveTextContent('Changes are not applied');
    expect(button('gmail')).toBeDisabled(); expect(api.variants).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Apply background to this draft' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Fill in the required details');
    expect(api.variants).not.toHaveBeenCalled(); expect(api.stream).not.toHaveBeenCalled();
  });

  it('restores formerly applied reading as pending when the target version changed even if the paper still exists', async () => {
    const paperTarget: Opportunity = { ...target, metadata: { ...target.metadata,
      publication_attribution_status: 'verified_author_id', recent_works: [{ title: 'Verified sensor study', year: 2025 }] } };
    const view = mount({ target: paperTarget }); await ready(); openContext();
    fireEvent.change(screen.getByLabelText('Paper you looked at (optional)'), { target: { value: JSON.stringify(['Verified sensor study', 2025]) } });
    fireEvent.change(screen.getByLabelText('How much did you read?'), { target: { value: 'abstract' } });
    fireEvent.click(screen.getByLabelText('I confirm this reading level for the selected paper.'));
    fireEvent.click(screen.getByRole('button', { name: 'Apply background to this draft' }));
    fireEvent.click(button('regenerateFromProfile'));
    await waitFor(() => expect(api.stream).toHaveBeenCalledTimes(2)); await act(async () => {});
    edit(); await close(view); clearCalls();
    mount({ target: { ...paperTarget, writing_target_version: `wt1:${'b'.repeat(64)}` } }); await restored();
    expect(screen.getByLabelText('How much did you read?')).toHaveValue('abstract');
    expect(screen.getByLabelText('I confirm this reading level for the selected paper.')).not.toBeChecked();
    expect(screen.getByTestId('email-contact-context-status')).toHaveTextContent('Changes are not applied');
    expect(button('regenerateFromProfile')).toBeDisabled(); expect(button('gmail')).toBeDisabled();
    fireEvent.click(button('regenerateFromProfile')); expect(api.variants).not.toHaveBeenCalled(); expect(api.stream).not.toHaveBeenCalled();
  });

  for (const changed of ['profile', 'target'] as const) {
    it('keeps the original draft after ' + changed + ' changes but requires deliberate regeneration before compose', async () => {
      const view = mount(); await ready(); edit(); await close(view);
      const original = readColdEmailDraft(captureOwnerToken(), target.id); clearCalls();
      mount(changed === 'profile' ? { profile: { ...profile, research_interests: 'A different research direction' } }
        : { target: { ...target, writing_target_version: `wt1:${'b'.repeat(64)}` } });
      await restored(); expect(button('gmail')).toBeDisabled();
      const recovered = readColdEmailDraft(captureOwnerToken(), target.id);
      expect(original.status).toBe('present'); expect(recovered.status).toBe('present');
      if (original.status === 'present' && recovered.status === 'present') expect(recovered.draft.sources).toEqual(original.draft.sources);
      expect(button('regenerateFromProfile')).toBeVisible();
      fireEvent.click(button('copy'));
      await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(`Subject: ${edits.subject}\n\n${edits.body}`));
      expect(window.open).not.toHaveBeenCalled();
    });
  }

  it('allows an explicit refine of a recovered draft whose source versions still match', async () => {
    const view = mount(); await ready(); edit(); await close(view); clearCalls(); mount(); await restored();
    api.refine.mockImplementation((_body, _instruction, _profile, id, options) => emailReceipt(
      { body: 'Explicitly revised from the recovered draft', method: 'llm' }, id, options.expectedTargetVersion, options.contactContext));
    await waitFor(() => expect(button('submitRequest')).toBeEnabled()); fireEvent.click(button('submitRequest'));
    await screen.findByDisplayValue('Explicitly revised from the recovered draft');
    expect(api.refine).toHaveBeenCalledOnce(); expect(api.refine.mock.calls[0][0]).toBe(edits.body);
    expect(api.refine.mock.calls[0][1]).toBe(edits.request); expect(api.stream).not.toHaveBeenCalled();
    expect(field('subject')).toHaveValue(edits.subject); expect(field('to')).toHaveValue(edits.recipient);
  });

  it('does not display one target draft for another target and retains the first target draft', async () => {
    const first = mount(); await ready(); edit(); await close(first); clearCalls();
    const other = emailTarget('other-recovery-target'); const second = mount({ opportunityId: other.id, target: other }); await ready();
    expect(field('body')).toHaveValue(draft.body); expect(field('to')).toHaveValue(draft.recipient_email);
    expect(field('requestLabel')).toHaveValue(''); expect(screen.queryByDisplayValue(edits.body)).toBeNull();
    await close(second); clearCalls(); mount(); await restored();
  });

  it('cannot recover private editor values after an account switch', async () => {
    const view = mount(); await ready(); edit(); await close(view); clearCalls();
    advanceOwnerEpoch('another-recovery-owner'); await syncLocalIdentityOwner('another-recovery-owner');
    mount(); await ready(); expect(screen.queryByDisplayValue(edits.body)).toBeNull();
    expect(field('to')).toHaveValue(draft.recipient_email); expect(field('requestLabel')).toHaveValue('');
    expect(api.confirm).not.toHaveBeenCalled();
  });

  it('does not restore an opened/sent confirmation, actual send time or subject-format attestation', async () => {
    const formatted: Opportunity = { ...target, contact_instructions: { version: 1, status: 'known', email_policy: 'allowed', rules: [{
      kind: 'subject', subject_template: 'Research - [LastName]', source_url: 'https://example.edu/lab', checked_at: '2026-09-25T00:00:00Z', quote: 'Use Research - [LastName]',
    }] } };
    const view = mount({ target: formatted }); await ready(); edit(); change('subject', 'Research - Xu');
    fireEvent.click(screen.getByTestId('contact-instructions').parentElement!.querySelector('summary')!);
    fireEvent.click(screen.getByLabelText('I filled in the required subject and checked it against the source.'));
    fireEvent.change(screen.getByLabelText('coldEmail.actualSentAt'), { target: { value: '2026-01-01T10:00' } });
    fireEvent.click(button('copy')); await screen.findByTestId('cold-email-confirm-sent');
    fireEvent.click(screen.getByTestId('cold-email-confirm-sent'));
    await waitFor(() => expect(api.confirm).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.queryByTestId('cold-email-confirm-sent')).toBeNull());
    await close(view); clearCalls(); mount({ target: formatted });
    await waitFor(() => expect(field('body')).toHaveValue(edits.body)); expect(field('subject')).toHaveValue('Research - Xu');
    expect(screen.getByLabelText('coldEmail.actualSentAt')).toHaveValue('');
    expect(screen.getByLabelText('I filled in the required subject and checked it against the source.')).not.toBeChecked();
    expect(screen.queryByTestId('cold-email-confirm-sent')).toBeNull(); expect(button('gmail')).toBeDisabled();
    expect(api.confirm).not.toHaveBeenCalled(); expect(api.stream).not.toHaveBeenCalled();
  });

  it('records a recovered historical email with its original source hashes after the current sources change', async () => {
    const view = mount(); await ready(); edit(); await saved();
    const original = readColdEmailDraft(captureOwnerToken(), target.id);
    expect(original.status).toBe('present'); if (original.status !== 'present') throw new Error('Expected saved draft');
    expect(original.draft.sources.profile_sig).toMatch(/^[a-f0-9]{64}$/);
    expect(original.draft.sources.contact_sig).toMatch(/^[a-f0-9]{64}$/);
    await close(view); clearCalls();
    mount({ profile: { ...profile, research_interests: 'A different current profile' },
      target: { ...target, writing_target_version: `wt1:${'b'.repeat(64)}` } }); await restored();
    expect(button('gmail')).toBeDisabled(); fireEvent.click(button('copy'));
    await screen.findByTestId('cold-email-confirm-sent'); fireEvent.click(screen.getByTestId('cold-email-confirm-sent'));
    await waitFor(() => expect(api.confirm).toHaveBeenCalledOnce());
    expect(api.confirm.mock.calls[0][1]).toMatchObject({ recipient: edits.recipient, subject: edits.subject, body: edits.body,
      materialRefs: [
        { kind: 'profile', version: original.draft.sources.profile_sig },
        { kind: 'target', version: original.draft.sources.target_version },
        { kind: 'contact_context', version: original.draft.sources.contact_sig },
      ],
    });
    expect(api.stream).not.toHaveBeenCalled();
  });

  it('checks both fresh source receipts before composing a recovered manual-recipient draft', async () => {
    const view = mount(); await ready(); edit(); await close(view); clearCalls();
    const profileCheck = vi.fn().mockImplementation(() => Promise.resolve({ checkId: 1, owner: captureOwnerToken(), profile, revision: 1, source: 'cloud' } satisfies ProfileActionReceipt));
    const targetCheck = vi.fn().mockImplementation(() => Promise.resolve({ checkId: 1, owner: captureOwnerToken(), target, key: writingTargetKey(target)! } satisfies TargetActionReceipt));
    const popup = { closed: false, opener: null, location: { href: 'about:blank' }, close: vi.fn() };
    vi.mocked(window.open).mockReturnValue(popup as unknown as Window);
    mount({ profileRefresh: { status: 'ready', refresh: vi.fn(), checkForAction: profileCheck },
      targetRefresh: { status: 'ready', target, reason: null, refresh: vi.fn(), checkForAction: targetCheck } });
    await restored(); profileCheck.mockClear(); targetCheck.mockClear();
    profileCheck.mockResolvedValue(null); fireEvent.click(button('gmail'));
    await waitFor(() => expect(popup.close).toHaveBeenCalledOnce());
    expect(profileCheck).toHaveBeenCalledOnce(); expect(targetCheck).toHaveBeenCalledOnce();
    expect(popup.location.href).toBe('about:blank'); expectEdits(); expect(api.recipient).not.toHaveBeenCalled();
    expect(api.confirm).not.toHaveBeenCalled(); expect(screen.queryByTestId('cold-email-confirm-sent')).toBeNull();
  });

  it('waits for a queued durable save before reporting a successful normal close', async () => {
    const view = mount(); await ready(); await saved(draft.body);
    let release!: () => void;
    const held = new Promise<void>(resolve => { release = resolve; });
    const lock = navigator.locks.request(PRIVATE_STORAGE_LOCK, { mode: 'exclusive' }, () => held);
    try {
      edit(); fireEvent.click(button('closeAria')); await act(async () => {});
      expect(view.props.onClose).not.toHaveBeenCalled(); expectEdits();
      expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent(/Saving/);
    } finally { await act(async () => { release(); await lock; }); }
    await waitFor(() => expect(view.props.onClose).toHaveBeenCalledOnce());
    const record = readColdEmailDraft(captureOwnerToken(), target.id);
    expect(record.status).toBe('present'); if (record.status === 'present') expect(record.draft.body).toBe(edits.body);
  });

  it('keeps the current editor open when persistence fails instead of claiming it is saved', async () => {
    const view = mount(); await ready(); await saved(draft.body);
    const original = localStorage.setItem.bind(localStorage);
    vi.spyOn(localStorage, 'setItem').mockImplementation((key, value) => {
      if (key.includes(STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX)) throw new DOMException('Fixture quota failure', 'QuotaExceededError');
      original(key, value);
    });
    edit(); await waitFor(() => expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent(/Could not save/));
    fireEvent.click(button('closeAria')); await act(async () => {});
    expectEdits(); expect(view.props.onClose).not.toHaveBeenCalled();
    expect(screen.getByTestId('cold-email-draft-status')).not.toHaveTextContent(/Saved on this browser/);
    expect(screen.getByRole('button', { name: 'Close without saving' })).toBeVisible();
  });

  it('cannot overwrite a newer draft saved by another editor', async () => {
    mount(); await ready(); edit(); await saved();
    const owner = captureOwnerToken(); const record = readColdEmailDraft(owner, target.id);
    expect(record.status).toBe('present'); if (record.status !== 'present') throw new Error('Expected saved draft');
    const newer = { ...record.draft, body: 'Newer draft from another editor' };
    await act(async () => { expect((await createColdEmailDraftWriter(owner, target.id, record.revision).save(newer)).status).toBe('saved'); });
    change('body', 'This older editor changed after the newer save'); await act(async () => {});
    await waitFor(() => expect(screen.getByTestId('cold-email-draft-status')).not.toHaveTextContent(/Saving|Saved on this browser/));
    const after = readColdEmailDraft(owner, target.id);
    expect(after.status).toBe('present'); if (after.status === 'present') expect(after.draft.body).toBe(newer.body);
    expect(field('body')).toHaveValue('This older editor changed after the newer save');
  });

  it('cannot resurrect a draft deleted by another editor with a delayed local edit', async () => {
    mount(); await ready(); edit(); await saved();
    const owner = captureOwnerToken(); const record = readColdEmailDraft(owner, target.id);
    expect(record.status).toBe('present');
    await act(async () => { expect((await createColdEmailDraftWriter(owner, target.id, record.revision).delete()).status).toBe('deleted'); });
    change('body', 'Older editor text after deletion'); await act(async () => {});
    await waitFor(() => expect(screen.getByTestId('cold-email-draft-status')).not.toHaveTextContent(/Saving|Saved on this browser/));
    expect(readColdEmailDraft(owner, target.id).status).toBe('missing');
    expect(field('body')).toHaveValue('Older editor text after deletion');
    expect(api.confirm).not.toHaveBeenCalled();
  });

  it('requires explicit retry after oversized background is shortened and saves the current valid text', async () => {
    mount(); await ready(); edit(); await saved(); openContext();
    const availability = screen.getByLabelText('When could you participate? (optional)');
    const oversized = '原'.repeat(66000); fireEvent.change(availability, { target: { value: oversized } });
    await waitFor(() => expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent('Could not save'));
    expect(availability).toHaveValue(oversized); expect(screen.getByTestId('cold-email-draft-retry')).toBeDisabled();
    fireEvent.change(availability, { target: { value: 'Possibly Tuesday; not confirmed' } });
    expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent('Could not save');
    await waitFor(() => expect(screen.getByTestId('cold-email-draft-retry')).toBeEnabled());
    fireEvent.click(screen.getByTestId('cold-email-draft-retry')); await saved();
    const record = readColdEmailDraft(captureOwnerToken(), target.id);
    expect(record.status).toBe('present');
    if (record.status === 'present') expect(record.draft.pendingPanel?.fields.availability).toBe('Possibly Tuesday; not confirmed');
    expect(availability).toHaveValue('Possibly Tuesday; not confirmed'); expect(button('gmail')).toBeDisabled();
  });

  it('does not reset a newer target when an older target deletion finishes late', async () => {
    const view = mount(); await ready(); edit(); await saved();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    let release!: () => void; const held = new Promise<void>(resolve => { release = resolve; });
    const lock = navigator.locks.request(PRIVATE_STORAGE_LOCK, { mode: 'exclusive' }, () => held);
    const other = emailTarget('newer-delete-target');
    try {
      fireEvent.click(screen.getByTestId('cold-email-draft-clear')); await act(async () => {});
      view.rerender(<ColdEmailModal {...view.props} target={other} opportunityId={other.id} />);
      await waitFor(() => expect(field('body')).toHaveValue(draft.body));
      change('body', 'Private current target B text');
    } finally { await act(async () => { release(); await lock; }); }
    await waitFor(() => expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent('Saved on this browser'));
    expect(field('body')).toHaveValue('Private current target B text');
    const owner = captureOwnerToken(), old = readColdEmailDraft(owner, target.id), current = readColdEmailDraft(owner, other.id);
    expect(old.status).toBe('missing'); expect(current.status).toBe('present');
    if (current.status === 'present') expect(current.draft.body).toBe('Private current target B text');
  });

  it('keeps the draft when delete is cancelled and starts a new draft only after confirmed deletion', async () => {
    const view = mount(); await ready(); edit(); await close(view); clearCalls(); mount(); await restored();
    const confirmation = vi.spyOn(window, 'confirm').mockReturnValue(false);
    fireEvent.click(screen.getByTestId('cold-email-draft-clear')); expectEdits(); expect(api.stream).not.toHaveBeenCalled();
    confirmation.mockReturnValue(true); fireEvent.click(screen.getByTestId('cold-email-draft-clear'));
    await screen.findByDisplayValue(draft.body); expect(field('requestLabel')).toHaveValue('');
    expect(field('to')).toHaveValue(draft.recipient_email); expect(api.confirm).not.toHaveBeenCalled();
  });
});
