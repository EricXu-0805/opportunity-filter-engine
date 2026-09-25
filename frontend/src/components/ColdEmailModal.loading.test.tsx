import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import type { ProfileData, EmailVariant } from '@/lib/types';
import type { ProfileActionReceipt, ProfileRefreshState } from '@/lib/use-profile-refresh';

vi.mock('@/i18n/client', () => {
  const t = (key: string) => key;
  return { useT: () => ({ t, locale: 'en' }), useLocale: () => 'en' };
});
const api = vi.hoisted(() => ({ variants: vi.fn(), stream: vi.fn(), generate: vi.fn(), refine: vi.fn(), extract: vi.fn() }));
vi.mock('@/lib/api', () => ({ getEmailVariants: api.variants, generateColdEmailStream: api.stream,
  generateColdEmail: api.generate, refineEmail: api.refine, extractResumeBullets: api.extract, getVapidPublicKey: vi.fn() }));
vi.mock('@/lib/supabase', () => ({ onAuthChange: () => () => {}, confirmInteractionContact: vi.fn(), updateInteractionDetails: vi.fn() }));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: vi.fn() }) }));
import ColdEmailModal from './ColdEmailModal';

const profile: ProfileData = { name: 'Alex', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore',
  is_international: false, research_interests: 'robotics', skills: [], coursework: [] };
const variant: EmailVariant = { id: 'template', label: 'Current template', subject: 'Checked subject', body: 'Checked body',
  recipient_email: 'lab@example.edu', mailto_link: '' };
const templates = { variants: [variant], pipeline_version: 'loading-test-current' };
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => { resolve = res; });
  return { resolve, promise };
}
const receipt = (): ProfileActionReceipt => ({ checkId: 1, owner: captureOwnerToken(), revision: 1, source: 'cloud', profile });
let sequence = 0;
beforeEach(async () => {
  localStorage.clear();
  const uid = `loading-owner-${++sequence}`;
  advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  api.variants.mockReset().mockResolvedValue(templates);
  api.stream.mockReset().mockResolvedValue({ ...variant, method: 'template' });
  api.generate.mockReset(); api.refine.mockReset(); api.extract.mockReset();
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
});
function harness(status: ProfileRefreshState['status'] = 'checking') {
  const check = deferred<ProfileActionReceipt | null>();
  const checkForAction = vi.fn(() => check.promise), refresh = vi.fn().mockResolvedValue(true);
  const show = (next: ProfileRefreshState['status'], available = true) => <ColdEmailModal isOpen onClose={vi.fn()}
    profile={profile} opportunityId="loading-target" opportunityTitle="Lab" profileAvailable={available}
    profileRefresh={{ status: next, refresh, checkForAction }} />;
  const view = render(show(status));
  return { ...view, show, check, checkForAction, refresh };
}

describe('cold email initial readiness versus a retained editor', () => {
  it('never mounts an actionable empty footer between the initial profile read and pending template generation', async () => {
    const generated = deferred<typeof templates>(); api.variants.mockReturnValue(generated.promise);
    const view = harness();
    await waitFor(() => expect(view.checkForAction).toHaveBeenCalledOnce());
    expect(screen.queryByTestId('cold-email-footer')).toBeNull();
    expect(screen.queryByTestId('cold-email-workspace')).toBeNull();
    expect(api.variants).not.toHaveBeenCalled(); expect(api.stream).not.toHaveBeenCalled();
    view.rerender(view.show('ready'));
    await act(async () => view.check.resolve(receipt()));
    await waitFor(() => expect(api.variants).toHaveBeenCalledOnce());
    expect(screen.getByText('coldEmail.generating')).toBeVisible();
    expect(screen.queryByTestId('cold-email-footer')).toBeNull();
    await act(async () => generated.resolve(templates));
    expect(await screen.findByDisplayValue('Checked body')).toBeVisible();
    expect(screen.getByTestId('cold-email-footer')).toBeVisible();
  });

  it('keeps the same existing editor and Copy during checking and failed reads, with generation paused', async () => {
    const view = harness('ready');
    await waitFor(() => expect(view.checkForAction).toHaveBeenCalledOnce());
    await act(async () => view.check.resolve(receipt()));
    await screen.findByDisplayValue('Checked body');
    await waitFor(() => expect(api.stream).toHaveBeenCalledOnce());
    fireEvent.change(screen.getByDisplayValue('Checked subject'), { target: { value: 'My subject' } });
    fireEvent.change(screen.getByDisplayValue('Checked body'), { target: { value: 'My manual body' } });
    fireEvent.change(screen.getByDisplayValue('lab@example.edu'), { target: { value: 'my@example.edu' } });
    const footer = screen.getByTestId('cold-email-footer'), editor = screen.getByDisplayValue('My manual body');
    for (const status of ['checking', 'failed'] as const) {
      view.rerender(view.show(status));
      expect(screen.getByTestId('cold-email-footer')).toBe(footer);
      expect(screen.getByDisplayValue('My manual body')).toBe(editor);
      expect(editor).toBeEnabled();
      expect(screen.getByRole('button', { name: 'coldEmail.openInEmail' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'coldEmail.quickActions.formal' })).toBeDisabled();
    }
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.copy' }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith('Subject: My subject\n\nMy manual body'));
    expect(screen.queryByText('coldEmail.generating')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' })); expect(view.refresh).toHaveBeenCalledOnce();
    expect(api.variants).toHaveBeenCalledOnce(); expect(api.refine).not.toHaveBeenCalled();
  });

  it('ends the initial waiting UI on a failed profile check and retries through the same read gate', async () => {
    const view = harness();
    await waitFor(() => expect(view.checkForAction).toHaveBeenCalledOnce());
    view.rerender(view.show('failed'));
    await act(async () => view.check.resolve(null));
    expect(screen.queryByText('coldEmail.generating')).toBeNull();
    expect(screen.queryByTestId('cold-email-footer')).toBeNull();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
    expect(api.variants).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(view.refresh).toHaveBeenCalledOnce();
    view.rerender(view.show('ready'));
    view.checkForAction.mockResolvedValue(receipt());
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.tryAgain' }));
    expect(await screen.findByDisplayValue('Checked body')).toBeVisible();
    expect(view.checkForAction.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it('does not spin or expose empty draft controls when the initial profile is missing', async () => {
    const view = harness(); view.rerender(view.show('ready', false));
    expect(await screen.findByText('This action did not run. Your draft and request are kept. Review your profile and try again.')).toBeVisible();
    expect(screen.queryByText('coldEmail.generating')).toBeNull();
    expect(screen.queryByTestId('cold-email-footer')).toBeNull();
    expect(screen.getByRole('button', { name: 'coldEmail.tryAgain' })).toBeDisabled();
    expect(api.variants).not.toHaveBeenCalled();
  });

  it.each(['empty', 'error'] as const)('shows a recoverable error when initial templates return %s', async (mode) => {
    if (mode === 'empty') api.variants.mockResolvedValueOnce({ variants: [] });
    else api.variants.mockRejectedValueOnce(new Error('Controlled template failure'));
    const view = harness('ready');
    await waitFor(() => expect(view.checkForAction).toHaveBeenCalledOnce());
    await act(async () => view.check.resolve(receipt()));
    expect(await screen.findByRole('button', { name: 'coldEmail.tryAgain' })).toBeVisible();
    expect(screen.queryByText('coldEmail.generating')).toBeNull();
    expect(screen.queryByTestId('cold-email-footer')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.tryAgain' }));
    expect(await screen.findByDisplayValue('Checked body')).toBeVisible();
  });
});
