import { emailValidationReceipt } from './ColdEmailModal.test-fixtures';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import type { EmailContactContext, Opportunity, ProfileData } from '@/lib/types';
import type { ProfileViewSnapshot } from '@/lib/profile-sync';
import type { ResumeSupplementPanelProps } from './ResumeSupplementPanel';
import { emailReceipt, emailTarget } from './ColdEmailModal.test-fixtures';
const api = vi.hoisted(() => ({ variants: vi.fn(), stream: vi.fn(), refine: vi.fn(), confirm: vi.fn(), supplement: null as ResumeSupplementPanelProps | null }));
vi.mock('@/lib/api', () => ({
  validateEmailDraft: emailValidationReceipt,
  getEmailVariants: (...args: unknown[]) => emailReceipt(api.variants(...args), args[1] as string, (args[3] as { expectedTargetVersion: string }).expectedTargetVersion, (args[3] as { contactContext: EmailContactContext }).contactContext),
  generateColdEmailStream: (...args: unknown[]) => emailReceipt(api.stream(...args), args[1] as string, (args[2] as { expectedTargetVersion: string }).expectedTargetVersion, (args[2] as { contactContext: EmailContactContext }).contactContext),
  refineEmail: api.refine, generateColdEmail: vi.fn(), getVapidPublicKey: vi.fn(),
}));
vi.mock('@/lib/email-compose', () => ({ verifyComposeRecipient: vi.fn().mockResolvedValue(undefined) }));
vi.mock('@/lib/supabase', () => ({ onAuthChange: () => () => {}, confirmContactEvent: api.confirm, updateInteractionDetails: vi.fn() }));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: vi.fn() }) }));
vi.mock('@/i18n/client', () => { const t = (key: string) => key; return { useT: () => ({ t, locale: 'en' }) }; });
vi.mock('./ResumeSupplementPanel', () => ({ default: (props: ResumeSupplementPanelProps) => { api.supplement = props; return <input aria-label="Private supplemental answer" />; } }));
import ColdEmailModal from './ColdEmailModal';
const profile: ProfileData = { name: 'Alex', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore', is_international: false, research_interests: 'sensors', skills: [], coursework: [] };
const draft = { id: 'v1', label: 'Template', subject: 'Subject', body: 'My complete draft', recipient_email: 'lab@example.edu', mailto_link: '' };
const rule = { source_url: 'https://example.edu/lab', checked_at: '2026-09-25T00:00:00Z', quote: 'Contact instructions from the official page.' };
const withRules = (rules: NonNullable<Opportunity['contact_instructions']>['rules'], policy: NonNullable<Opportunity['contact_instructions']>['email_policy'] = 'allowed'): Opportunity => ({ ...emailTarget('A'), contact_instructions: { version: 1, status: policy === 'conflicting' ? 'conflicting' : 'known', email_policy: policy, rules } });
let owner = 0;
beforeEach(async () => {
  localStorage.clear(); advanceOwnerEpoch('prepare-' + ++owner); await syncLocalIdentityOwner('prepare-' + owner);
  api.variants.mockReset().mockResolvedValue({ variants: [draft], recipient_status: 'revealed' });
  api.stream.mockReset().mockResolvedValue({ ...draft, method: 'template' }); api.refine.mockReset(); api.confirm.mockReset(); api.supplement = null;
  vi.spyOn(window, 'open').mockImplementation(() => ({ closed: false, opener: null, location: { href: 'about:blank' }, close: vi.fn() }) as unknown as Window);
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
});
function mount(target = emailTarget('A')) { const props = { isOpen: true, onClose: vi.fn(), profile, opportunityId: target.id, opportunityTitle: 'Lab', target }; return { ...render(<ColdEmailModal {...props} />), props }; }
async function ready() {
  await screen.findByDisplayValue(draft.body);
  await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' })).toBeEnabled()); await act(async () => {});
  expect(api.stream).not.toHaveBeenCalled();
}
const compose = () => screen.getByRole('button', { name: 'coldEmail.gmail' });
const subject = () => screen.getByLabelText('coldEmail.subject');
const openRules = () => fireEvent.click(screen.getByTestId('contact-instructions').parentElement!.querySelector('summary')!);
const snapshot = (value: ProfileData): ProfileViewSnapshot => ({ viewId: crypto.randomUUID(), baseProfile: value, renderedProfile: value, revision: 2, token: captureOwnerToken(), identityGeneration: captureOwnerToken().epoch, source: 'hydration' });
async function supplement() { const panel = screen.getByTestId('cold-email-supplement'); fireEvent.click(panel.querySelector('summary')!); await screen.findByLabelText('Private supplemental answer'); }

describe('source instructions and personal preparation', () => {
  for (const policy of ['not_accepted', 'form_only', 'conflicting'] as const) {
    it('does not request a draft for official policy ' + policy, async () => {
      mount(withRules([{ ...rule, kind: policy === 'not_accepted' ? 'no_email' : 'form_only' }], policy));
      await act(async () => {}); expect(api.variants).not.toHaveBeenCalled(); expect(api.stream).not.toHaveBeenCalled();
      expect(screen.getByTestId('contact-instructions')).toBeVisible(); expect(window.open).not.toHaveBeenCalled();
    });
  }
  it('uses an exact required subject without overwriting the body or claiming attachments', async () => {
    mount(withRules([{ ...rule, kind: 'subject', subject: 'Required research application' }, { ...rule, kind: 'materials', materials: ['resume_cv'] }])); await ready();
    expect(compose()).toBeDisabled(); openRules(); fireEvent.click(screen.getByRole('button', { name: 'Use this subject' }));
    expect(subject()).toHaveValue('Required research application'); expect(screen.getByDisplayValue(draft.body)).toBeVisible();
    expect(screen.getByText('Preparing a draft does not attach files or submit an application.')).toBeVisible(); expect(compose()).toBeEnabled();
    expect(api.variants).toHaveBeenCalledOnce(); expect(api.confirm).not.toHaveBeenCalled();
  });
  it('requires a subject-format confirmation, rejects placeholders and invalidates confirmation after any subject edit', async () => {
    mount(withRules([{ ...rule, kind: 'subject', subject_template: 'Research - [LastName]' }])); await ready(); openRules();
    const checkbox = screen.getByLabelText('I filled in the required subject and checked it against the source.');
    fireEvent.change(subject(), { target: { value: 'Research - [LastName]' } }); fireEvent.click(checkbox); expect(compose()).toBeDisabled();
    fireEvent.change(subject(), { target: { value: 'Research - Xu' } }); expect(checkbox).not.toBeChecked(); expect(compose()).toBeDisabled();
    fireEvent.click(checkbox); expect(compose()).toBeEnabled();
    fireEvent.change(subject(), { target: { value: 'Other' } }); fireEvent.change(subject(), { target: { value: 'Research - Xu' } });
    expect(checkbox).not.toBeChecked(); expect(compose()).toBeDisabled();
  });
  it('revokes source-format confirmation for a new target version and keeps Copy', async () => {
    const target = withRules([{ ...rule, kind: 'subject', subject_template: 'Research - [LastName]' }]); const view = mount(target); await ready(); openRules();
    fireEvent.change(subject(), { target: { value: 'Research - Xu' } }); fireEvent.click(screen.getByRole('checkbox'));
    view.rerender(<ColdEmailModal {...view.props} target={{ ...target, writing_target_version: `wt1:${'b'.repeat(64)}` }} />);
    expect(screen.getByRole('checkbox')).not.toBeChecked(); expect(compose()).toBeDisabled();
    fireEvent.click(screen.getByTestId('copy-draft-only')); await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith('Subject: Research - Xu\n\nMy complete draft'));
  });
  it('returns a rejected reading claim to the open background panel without replacing or replaying the draft', async () => {
    mount(); await ready(); api.refine.mockRejectedValue(Object.assign(new Error('changed'), { code: 'EMAIL_READING_CHANGED' }));
    fireEvent.change(screen.getByLabelText('coldEmail.body'), { target: { value: 'Kept manual draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.quickActions.formal' }));
    expect(await screen.findByTestId('cold-email-reading-changed')).toBeVisible();
    expect(screen.getByText('Your draft is kept. Review or skip paper reading in Contact purpose and background.')).toBeVisible();
    expect(screen.queryByText('coldEmail.editFailed')).not.toBeInTheDocument();
    expect(screen.getByTestId('email-contact-context-panel')).toHaveAttribute('open'); expect(screen.getByDisplayValue('Kept manual draft')).toBeVisible();
    expect(api.refine).toHaveBeenCalledOnce(); expect(api.variants).toHaveBeenCalledOnce(); expect(compose()).toBeDisabled();
  });
  it('loads contribution answers only when opened and preserves the draft after explicit accepted saving', async () => {
    mount(); await ready(); expect(api.supplement).toBeNull(); await supplement(); expect(api.supplement!.purpose).toBe('cold_email');
    const next = { ...profile, research_interests: 'Sensors; personally designed the acquisition circuit' };
    act(() => api.supplement!.onAcceptedProfile?.(snapshot(next), snapshot(profile)));
    expect(screen.getByDisplayValue(draft.body)).toBeVisible(); expect(api.variants).toHaveBeenCalledOnce(); expect(compose()).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.regenerateFromProfile' }));
    await waitFor(() => expect(api.variants).toHaveBeenCalledTimes(2)); expect(api.variants.mock.calls[1][0].research_interests).toBe(next.research_interests);
  });
  it('rejects a delayed contribution callback after a newer profile or closed session', async () => {
    const view = mount(); await ready(); await supplement(); const callback = api.supplement!.onAcceptedProfile!;
    const newer = { ...profile, research_interests: 'Newer independently accepted profile' };
    view.rerender(<ColdEmailModal {...view.props} profile={newer} />);
    act(() => callback(snapshot({ ...profile, research_interests: 'Stale supplemental response' }), snapshot(profile)));
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.regenerateFromProfile' }));
    await waitFor(() => expect(api.variants).toHaveBeenCalledTimes(2)); expect(api.variants.mock.calls[1][0].research_interests).toBe(newer.research_interests);
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.closeAria' })); act(() => callback(snapshot(profile), snapshot(newer)));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull()); expect(api.variants).toHaveBeenCalledTimes(2);
  });
  it('does not reactivate an accepted contribution overlay after a profile disappears and returns', async () => {
    const view = mount(); await ready(); await supplement();
    act(() => api.supplement!.onAcceptedProfile?.(snapshot({ ...profile, research_interests: 'Retired supplement' }), snapshot(profile)));
    view.rerender(<ColdEmailModal {...view.props} profileAvailable={false} />); view.rerender(<ColdEmailModal {...view.props} profileAvailable />);
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.regenerateFromProfile' }));
    await waitFor(() => expect(api.variants).toHaveBeenCalledTimes(2)); expect(api.variants.mock.calls[1][0].research_interests).toBe(profile.research_interests);
  });
});
