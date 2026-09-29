import { emailValidationReceipt } from './ColdEmailModal.test-fixtures';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { advanceOwnerEpoch, captureOwnerToken, PRIVATE_STORAGE_LOCK, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { readColdEmailDraft } from '@/lib/cold-email-draft';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { writingTargetKey } from '@/lib/writing-target';
import type { ProfileActionReceipt } from '@/lib/use-profile-refresh';
import type { TargetActionReceipt } from '@/lib/use-writing-target';
import type { ColdEmailResponse, EmailContactContext, ProfileData } from '@/lib/types';
import { emailReceipt, emailTarget } from './ColdEmailModal.test-fixtures';

const api = vi.hoisted(() => ({ variants: vi.fn(), stream: vi.fn(), refine: vi.fn(), recipient: vi.fn(), confirm: vi.fn() }));
vi.mock('@/lib/api', () => ({
  validateEmailDraft: emailValidationReceipt,
  getEmailVariants: (...args: unknown[]) => emailReceipt(api.variants(...args), args[1] as string,
    (args[3] as { expectedTargetVersion: string }).expectedTargetVersion,
    (args[3] as { contactContext: EmailContactContext }).contactContext),
  generateColdEmailStream: (...args: unknown[]) => emailReceipt(api.stream(...args), args[1] as string,
    (args[2] as { expectedTargetVersion: string }).expectedTargetVersion,
    (args[2] as { contactContext: EmailContactContext }).contactContext),
  refineEmail: (...args: unknown[]) => emailReceipt(api.refine(...args), args[3] as string,
    (args[4] as { expectedTargetVersion: string }).expectedTargetVersion,
    (args[4] as { contactContext: EmailContactContext }).contactContext),
  generateColdEmail: vi.fn(), getVapidPublicKey: vi.fn(),
}));
vi.mock('@/lib/email-compose', () => ({ verifyComposeRecipient: api.recipient }));
vi.mock('@/lib/supabase', () => ({ onAuthChange: () => () => {}, confirmContactEvent: api.confirm, updateInteractionDetails: vi.fn() }));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: vi.fn() }) }));
vi.mock('@/i18n/client', () => { const t = (key: string) => key; return { useT: () => ({ t, locale: 'en' }) }; });
vi.mock('./ResumeSupplementPanel', () => ({ default: () => <div /> }));
import ColdEmailModal from './ColdEmailModal';

const profile: ProfileData = { name: 'Alex', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore',
  is_international: false, research_interests: 'sensors', skills: [], coursework: [] };
const target = emailTarget('draft-lifecycle-target');
const draft = { id: 'v1', label: 'Template', subject: 'Original subject', body: 'Original complete draft', recipient_email: 'lab@example.edu', mailto_link: '' };
type Props = ComponentProps<typeof ColdEmailModal>;
let ownerNumber = 0;
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { resolve, promise }; }

beforeEach(async () => {
  localStorage.clear(); advanceOwnerEpoch('draft-lifecycle-' + ++ownerNumber); await syncLocalIdentityOwner('draft-lifecycle-' + ownerNumber);
  api.variants.mockReset().mockResolvedValue({ variants: [draft], recipient_status: 'revealed' });
  api.stream.mockReset().mockResolvedValue({ ...draft, method: 'template' }); api.refine.mockReset();
  api.recipient.mockReset().mockResolvedValue(undefined); api.confirm.mockReset();
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
});
function mount(overrides: Partial<Props> = {}) {
  const props: Props = { isOpen: true, onClose: vi.fn(), profile, opportunityId: target.id, opportunityTitle: 'Lab', target, ...overrides };
  return { ...render(<ColdEmailModal {...props} />), props };
}
const field = (name: 'body' | 'requestLabel') => screen.getByLabelText('coldEmail.' + name);
const button = (name: string) => screen.getByRole('button', { name: 'coldEmail.' + name });
async function ready() {
  await screen.findByDisplayValue(draft.body);
  await waitFor(() => expect(api.stream).toHaveBeenCalledOnce());
  await waitFor(() => expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent(/Saved on this browser/));
}
async function holdSave() {
  const acquired = deferred<void>(); const held = deferred<void>();
  const lock = navigator.locks.request(PRIVATE_STORAGE_LOCK, { mode: 'exclusive' }, () => { acquired.resolve(); return held.promise; });
  await act(async () => { await acquired.promise; });
  fireEvent.change(field('requestLabel'), { target: { value: 'This instruction must survive closing.' } });
  await waitFor(() => expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent(/Saving/));
  return async () => { await act(async () => { held.resolve(); await lock; }); };
}
function beginLeave(kind: 'close' | 'profile') {
  if (kind === 'close') { fireEvent.click(button('closeAria')); return; }
  const link = screen.getByRole('link', { name: 'coldEmail.experienceReviewCta' });
  // Only the flush waiting window is under test, not jsdom navigation.
  vi.spyOn(link as HTMLAnchorElement, 'click').mockImplementation(() => {});
  fireEvent.click(link);
}

// The store, identity authority and Web Lock are real. Only provider/network
// boundaries are deferred so a successful close cannot hide the waiting race.
describe('cold-email close while durable saving is pending', () => {
  it('retires an in-flight AI result on the close click before the save completes', async () => {
    const pending = deferred<ColdEmailResponse>(); api.stream.mockReturnValue(pending.promise);
    const view = mount(); await ready(); const release = await holdSave();
    try {
      beginLeave('close'); expect(view.props.onClose).not.toHaveBeenCalled();
      await act(async () => { pending.resolve({ ...draft, body: 'Late AI must be discarded', method: 'ai' }); });
      expect(field('body')).toHaveValue(draft.body); expect(screen.queryByDisplayValue('Late AI must be discarded')).toBeNull();
      expect(field('requestLabel')).toHaveValue('This instruction must survive closing.');
    } finally { await release(); }
    await waitFor(() => expect(view.props.onClose).toHaveBeenCalledOnce());
    const record = readColdEmailDraft(captureOwnerToken(), target.id);
    expect(record.status).toBe('present'); if (record.status === 'present') expect(record.draft.body).toBe(draft.body);
  });

  it.each(['close', 'profile'] as const)('retires a refine before %s navigation even while flush is blocked', async kind => {
    const pending = deferred<{ body: string; method: string }>(); api.refine.mockReturnValue(pending.promise);
    const view = mount({ profile: { ...profile, resume_text: 'Unreviewed resume text.' } }); await ready();
    fireEvent.click(button('quickActions.formal')); await waitFor(() => expect(api.refine).toHaveBeenCalledOnce());
    const release = await holdSave();
    try {
      beginLeave(kind); expect(view.props.onClose).not.toHaveBeenCalled();
      await act(async () => { pending.resolve({ body: 'Late refinement must be discarded', method: 'llm' }); });
      expect(field('body')).toHaveValue(draft.body); expect(screen.queryByDisplayValue('Late refinement must be discarded')).toBeNull();
      expect(field('requestLabel')).toHaveValue('This instruction must survive closing.');
    } finally { await release(); }
    if (kind === 'close') await waitFor(() => expect(view.props.onClose).toHaveBeenCalledOnce());
  });

  it.each(['close', 'profile'] as const)('cancels a pending recipient check on %s before waiting for storage', async kind => {
    const usingProfile = { ...profile, resume_text: 'Unreviewed resume text.' };
    const profileCheck = vi.fn().mockImplementation(() => Promise.resolve({ checkId: 1, owner: captureOwnerToken(), profile: usingProfile, revision: 1, source: 'cloud' } satisfies ProfileActionReceipt));
    const targetCheck = vi.fn().mockImplementation(() => Promise.resolve({ checkId: 1, owner: captureOwnerToken(), target, key: writingTargetKey(target)! } satisfies TargetActionReceipt));
    const popup = { closed: false, opener: null, location: { href: 'about:blank' }, close: vi.fn() };
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window);
    const view = mount({ profile: usingProfile,
      profileRefresh: { status: 'ready', refresh: vi.fn(), checkForAction: profileCheck },
      targetRefresh: { status: 'ready', target, reason: null, refresh: vi.fn(), checkForAction: targetCheck } });
    await ready(); const pending = deferred<void>(); api.recipient.mockReturnValue(pending.promise);
    const release = await holdSave();
    try {
      fireEvent.click(button('gmail')); await waitFor(() => expect(api.recipient).toHaveBeenCalledOnce());
      expect(popup.location.href).toBe('about:blank'); beginLeave(kind);
      expect(popup.close).toHaveBeenCalledOnce(); expect(view.props.onClose).not.toHaveBeenCalled();
      await act(async () => { pending.resolve(); });
      expect(popup.location.href).toBe('about:blank'); expect(screen.queryByTestId('cold-email-confirm-sent')).toBeNull();
      expect(api.confirm).not.toHaveBeenCalled(); expect(field('body')).toHaveValue(draft.body);
    } finally { await release(); }
    if (kind === 'close') await waitFor(() => expect(view.props.onClose).toHaveBeenCalledOnce());
  });

  it('keeps the editor available after a failed close save, without reviving the retired refine', async () => {
    const pending = deferred<{ body: string; method: string }>(); api.refine.mockReturnValue(pending.promise);
    const view = mount(); await ready(); fireEvent.click(button('quickActions.formal'));
    await waitFor(() => expect(api.refine).toHaveBeenCalledOnce());
    const release = await holdSave();
    const original = localStorage.setItem.bind(localStorage);
    vi.spyOn(localStorage, 'setItem').mockImplementation((key, value) => {
      if (key.includes(STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX)) throw new DOMException('Fixture quota failure', 'QuotaExceededError');
      original(key, value);
    });
    beginLeave('close'); await release();
    await waitFor(() => expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent(/Could not save/));
    expect(view.props.onClose).not.toHaveBeenCalled();
    await act(async () => { pending.resolve({ body: 'Failed-save stale refine', method: 'llm' }); });
    expect(field('body')).toHaveValue(draft.body);
    fireEvent.change(field('body'), { target: { value: 'Still editable after the failed close.' } });
    expect(field('body')).toHaveValue('Still editable after the failed close.');
    expect(screen.getByRole('button', { name: 'Close without saving' })).toBeVisible();
  });
});


it('retires a refine intent still waiting for fresh profile checks before a close save finishes', async () => {
  const profileCheck = vi.fn().mockImplementation(() => Promise.resolve({ checkId: 1, owner: captureOwnerToken(), profile, revision: 1, source: 'cloud' } satisfies ProfileActionReceipt));
  const targetCheck = vi.fn().mockImplementation(() => Promise.resolve({ checkId: 1, owner: captureOwnerToken(), target, key: writingTargetKey(target)! } satisfies TargetActionReceipt));
  const view = mount({ profileRefresh: { status: 'ready', refresh: vi.fn(), checkForAction: profileCheck },
    targetRefresh: { status: 'ready', target, reason: null, refresh: vi.fn(), checkForAction: targetCheck } });
  await ready(); const release = await holdSave();
  const pending = deferred<ProfileActionReceipt>(); profileCheck.mockClear().mockReturnValueOnce(pending.promise);
  api.refine.mockResolvedValue({ body: 'An obsolete queued instruction', method: 'llm' });
  try {
    fireEvent.click(button('quickActions.formal')); await waitFor(() => expect(profileCheck).toHaveBeenCalledOnce());
    expect(api.refine).not.toHaveBeenCalled(); beginLeave('close');
    expect(view.props.onClose).not.toHaveBeenCalled();
    await act(async () => { pending.resolve({ checkId: 2, owner: captureOwnerToken(), profile, revision: 1, source: 'cloud' }); });
    expect(api.refine).not.toHaveBeenCalled(); expect(field('body')).toHaveValue(draft.body);
  } finally { await release(); }
  await waitFor(() => expect(view.props.onClose).toHaveBeenCalledOnce());
});
