import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { writingTargetKey } from '@/lib/writing-target';
import type { ProfileActionReceipt } from '@/lib/use-profile-refresh';
import type { TargetActionReceipt } from '@/lib/use-writing-target';
import type { ProfileData } from '@/lib/types';

const api = vi.hoisted(() => ({ variants: vi.fn(), stream: vi.fn(), recipient: vi.fn(), confirm: vi.fn() }));
vi.mock('@/lib/api', () => ({
  getEmailVariants: (...args: unknown[]) => emailReceipt(api.variants(), args[1] as string),
  generateColdEmailStream: (...args: unknown[]) => emailReceipt(api.stream(), args[1] as string),
  generateColdEmail: vi.fn(), refineEmail: vi.fn(), getVapidPublicKey: vi.fn(),
}));
vi.mock('@/lib/email-compose', () => ({ verifyComposeRecipient: api.recipient }));
vi.mock('@/lib/supabase', () => ({ onAuthChange: () => () => {}, confirmContactEvent: api.confirm, updateInteractionDetails: vi.fn() }));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: vi.fn() }) }));
vi.mock('@/i18n/client', () => { const t = (key: string) => key; return { useT: () => ({ t, locale: 'en' }), useLocale: () => 'en' }; });
import ColdEmailModal from './ColdEmailModal';
import { emailReceipt, emailTarget } from './ColdEmailModal.test-fixtures';

const profile: ProfileData = { name: 'Alex', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore', is_international: false, research_interests: 'sensors', skills: [], coursework: [] };
const draft = { id: 'v1', label: 'Template', subject: 'Subject', body: 'My complete draft', recipient_email: 'lab@example.edu', mailto_link: '' };
const target = emailTarget('compose-target');
const popup = () => ({ closed: false, opener: 'original', location: { href: 'about:blank' }, close: vi.fn() });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { resolve, promise }; }
const targetReceipt = (): TargetActionReceipt => ({ checkId: 1, owner: captureOwnerToken(), target, key: writingTargetKey(target)! });
const profileReceipt = (): ProfileActionReceipt => ({ checkId: 1, owner: captureOwnerToken(), profile, revision: 1, source: 'cloud' });
let sequence = 0;
beforeEach(async () => {
  localStorage.clear(); advanceOwnerEpoch('compose-' + ++sequence); await syncLocalIdentityOwner('compose-' + sequence);
  api.variants.mockReset().mockResolvedValue({ variants: [draft], pipeline_version: 'test', recipient_status: 'revealed' });
  api.stream.mockReset().mockResolvedValue({ ...draft, method: 'template' }); api.recipient.mockReset().mockResolvedValue(undefined); api.confirm.mockReset();
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
});
async function harness() {
  const profileCheck = vi.fn().mockImplementation(() => Promise.resolve(profileReceipt()));
  const targetCheck = vi.fn().mockImplementation(() => Promise.resolve(targetReceipt()));
  const close = vi.fn(); const window = popup(); const open = vi.spyOn(globalThis.window, 'open').mockReturnValue(window as unknown as Window);
  const props = { isOpen: true, onClose: close, profile, opportunityId: target.id, opportunityTitle: 'Lab', target,
    profileRefresh: { status: 'ready' as const, refresh: vi.fn(), checkForAction: profileCheck },
    targetRefresh: { status: 'ready' as const, target, reason: null, refresh: vi.fn(), checkForAction: targetCheck } };
  const view = render(<ColdEmailModal {...props} />); await screen.findByDisplayValue(draft.body);
  await waitFor(() => expect(api.stream).toHaveBeenCalledOnce()); await act(async () => {});
  profileCheck.mockClear(); targetCheck.mockClear();
  return { ...view, props, profileCheck, targetCheck, close, window, open };
}
const button = (provider = 'openInEmail') => screen.getByRole('button', { name: 'coldEmail.' + provider });

describe('new composer source checks', () => {
  for (const [provider, prefix] of [['openInEmail', 'mailto:'], ['gmail', 'https://mail.google.com/'], ['outlook', 'https://outlook.office365.com/']] as const) {
    it('reserves a blank ' + provider + ' window and navigates only after both fresh checks and recipient verification', async () => {
      const view = await harness(); const held = deferred<TargetActionReceipt | null>(); view.targetCheck.mockReturnValue(held.promise);
      fireEvent.click(button(provider));
      expect(view.open).toHaveBeenCalledWith('about:blank', '_blank'); expect(view.window.opener).toBeNull(); expect(view.window.location.href).toBe('about:blank');
      await waitFor(() => expect(view.targetCheck).toHaveBeenCalledOnce()); expect(view.profileCheck).toHaveBeenCalledOnce();
      expect(screen.queryByTestId('cold-email-confirm-sent')).toBeNull(); expect(button(provider)).toBeDisabled();
      await act(async () => held.resolve(targetReceipt()));
      await waitFor(() => expect(view.window.location.href.startsWith(prefix)).toBe(true));
      expect(api.recipient).toHaveBeenCalledWith(target.id, target.writing_target_version, draft.recipient_email, expect.any(AbortSignal));
      expect(view.window.close).not.toHaveBeenCalled(); expect(api.confirm).not.toHaveBeenCalled();
      expect(screen.getByTestId('cold-email-confirm-sent')).toBeVisible();
    });
  }
  it('closes an unused blank window after a failed profile check and retains all text', async () => {
    const view = await harness(); view.profileCheck.mockResolvedValue(null); fireEvent.click(button());
    await waitFor(() => expect(view.window.close).toHaveBeenCalledOnce()); expect(view.window.location.href).toBe('about:blank');
    expect(screen.getByDisplayValue(draft.body)).toBeVisible(); expect(screen.getByTestId('cold-email-compose-status')).toHaveTextContent('no email was opened');
    expect(api.recipient).not.toHaveBeenCalled(); expect(screen.queryByTestId('cold-email-confirm-sent')).toBeNull();
  });
  it('does not navigate when the verified server recipient was revoked or replaced', async () => {
    const view = await harness(); api.recipient.mockRejectedValue(new Error('recipient_changed')); fireEvent.click(button());
    await waitFor(() => expect(view.window.close).toHaveBeenCalledOnce()); expect(view.window.location.href).toBe('about:blank');
    expect(screen.getByDisplayValue(draft.recipient_email)).toBeVisible(); expect(screen.getByTestId('cold-email-compose-status')).toHaveTextContent('review the recipient');
    expect(screen.queryByTestId('cold-email-confirm-sent')).toBeNull();
  });
  it('preserves a user-entered address while still checking current profile and target', async () => {
    const view = await harness(); fireEvent.change(screen.getByLabelText('coldEmail.to'), { target: { value: 'chosen@example.edu' } }); fireEvent.click(button('gmail'));
    await waitFor(() => expect(view.window.location.href).toContain('chosen%40example.edu'));
    expect(view.profileCheck).toHaveBeenCalledOnce(); expect(view.targetCheck).toHaveBeenCalledOnce(); expect(api.recipient).not.toHaveBeenCalled();
  });
  it('closes and silently cancels after editing during a pending source read, even if the old response succeeds', async () => {
    const view = await harness(); const held = deferred<TargetActionReceipt>(); view.targetCheck.mockReturnValue(held.promise); fireEvent.click(button());
    await waitFor(() => expect(view.targetCheck).toHaveBeenCalledOnce()); fireEvent.change(screen.getByLabelText('coldEmail.body'), { target: { value: 'New manual draft' } });
    await act(async () => held.resolve(targetReceipt())); expect(view.window.close).toHaveBeenCalledOnce(); expect(view.window.location.href).toBe('about:blank');
    expect(screen.queryByTestId('cold-email-compose-status')).toBeNull(); expect(screen.queryByRole('alert')).toBeNull(); expect(api.confirm).not.toHaveBeenCalled();
  });
  it('closes on dialog retirement and ignores a delayed recipient check', async () => {
    const view = await harness(); const held = deferred<void>(); api.recipient.mockReturnValue(held.promise); fireEvent.click(button());
    await waitFor(() => expect(api.recipient).toHaveBeenCalledOnce()); fireEvent.click(screen.getByRole('button', { name: 'coldEmail.closeAria' }));
    await act(async () => held.resolve()); expect(view.window.close).toHaveBeenCalledOnce(); expect(view.window.location.href).toBe('about:blank'); expect(view.close).toHaveBeenCalledOnce();
  });
  it('reports popup blocking before any new reads or attestation', async () => {
    const view = await harness(); view.open.mockReturnValue(null); fireEvent.click(button());
    expect(screen.getByTestId('cold-email-compose-status')).toHaveTextContent('browser blocked');
    expect(view.profileCheck).not.toHaveBeenCalled(); expect(view.targetCheck).not.toHaveBeenCalled(); expect(api.recipient).not.toHaveBeenCalled(); expect(screen.queryByTestId('cold-email-confirm-sent')).toBeNull();
  });
  it('keeps Copy available after source change but disables new external composition', async () => {
    const view = await harness(); view.rerender(<ColdEmailModal {...view.props} profile={{ ...profile, research_interests: 'new interests' }} />);
    expect(button()).toBeDisabled(); fireEvent.click(button('copy'));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith('Subject: Subject\n\nMy complete draft'));
    expect(view.open).not.toHaveBeenCalled(); expect(api.confirm).not.toHaveBeenCalled();
  });
});
