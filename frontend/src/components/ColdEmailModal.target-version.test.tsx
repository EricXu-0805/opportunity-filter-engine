import { emailValidationReceipt } from './ColdEmailModal.test-fixtures';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { EmailVariant, Opportunity, ProfileData } from '@/lib/types';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { writingTargetKey } from '@/lib/writing-target';
import { ColdEmailStreamError } from '@/lib/cold-email-stream';
import { emailTarget, FIRST_CONTACT_RECEIPT, EMAIL_TARGET_VERSION as A } from './ColdEmailModal.test-fixtures';
const localization = vi.hoisted(() => ({ locale: 'en' }));
vi.mock('@/i18n/client', () => { const t = (key: string) => key; return { useT: () => ({ t, locale: localization.locale }) }; });
const api = vi.hoisted(() => ({ variants: vi.fn(), stream: vi.fn(), generate: vi.fn(), refine: vi.fn(), auth: vi.fn(), confirm: vi.fn() }));
vi.mock('@/lib/api', () => ({
  validateEmailDraft: emailValidationReceipt, getEmailVariants: api.variants, generateColdEmailStream: api.stream, generateColdEmail: api.generate,
  refineEmail: api.refine, getVapidPublicKey: vi.fn() }));
vi.mock('@/lib/supabase', () => ({ onAuthChange: api.auth, confirmContactEvent: async (...args: unknown[]) => ({ interaction: await api.confirm(...args) }), updateInteractionDetails: vi.fn() }));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: vi.fn() }) }));
import ColdEmailModal, { aiCacheEntryIsStale } from './ColdEmailModal';
const ID = 'receipt-target', B = `wt1:${'b'.repeat(64)}`;
const profile: ProfileData = { name: 'Alex', institution: 'UIUC', college: 'Engineering', major: 'CS', grade: 'Junior',
  is_international: false, research_interests: 'sensors', skills: [] };
const variant: EmailVariant = { contact_context_receipt: FIRST_CONTACT_RECEIPT, id: 'template', label: 'Template', subject: 'Template subject', body: 'Template body', recipient_email: 'lab@example.edu', mailto_link: '' };
const receipt = { contact_context_receipt: FIRST_CONTACT_RECEIPT, opportunity_id: ID, target_version: A };
const templates = { ...receipt, variants: [variant], pipeline_version: 'current', corpus_version: 'corpus' };
const result = { ...receipt, ...variant, method: 'ai', pipeline_version: 'current', corpus_version: 'corpus' };
const props = { isOpen: true, onClose: vi.fn(), opportunityId: ID, opportunityTitle: 'Research', profile, target: emailTarget(ID) };
function pending<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(yes => { resolve = yes; }); return { promise, resolve }; }
async function drain() { await act(async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); }); }
async function open() { const view = render(<ColdEmailModal {...props} />); await screen.findByDisplayValue('Template body'); await drain(); return view; }
function edit() {
  fireEvent.change(screen.getByDisplayValue('Template subject'), { target: { value: 'Manual subject' } });
  fireEvent.change(screen.getByDisplayValue('Template body'), { target: { value: 'Manual body 王' } });
  fireEvent.change(screen.getByDisplayValue('lab@example.edu'), { target: { value: 'manual@example.edu' } });
}
function kept() { for (const value of ['Manual subject', 'Manual body 王', 'manual@example.edu']) expect(screen.getByDisplayValue(value)).toBeVisible(); }
function refine() { fireEvent.click(screen.getByRole('button', { name: 'coldEmail.quickActions.formal' })); }
beforeEach(async () => {
  vi.resetAllMocks(); localization.locale = 'en'; localStorage.clear(); advanceOwnerEpoch(null); advanceOwnerEpoch('receipt-owner'); await syncLocalIdentityOwner('receipt-owner');
  api.auth.mockReturnValue(() => {}); api.variants.mockResolvedValue(templates);
  api.stream.mockResolvedValue({ ...result, method: 'template' }); api.generate.mockResolvedValue(result);
  api.refine.mockResolvedValue({ ...receipt, body: 'Verified refinement', method: 'llm' });
});
afterEach(cleanup);

describe('ColdEmail authoritative target receipt', () => {
  it.each([undefined, '', `wt1:${'A'.repeat(64)}`])('makes no writing calls when the server token is %s', async token => {
    const target = emailTarget(ID); if (token === undefined) delete target.writing_target_version; else target.writing_target_version = token;
    render(<ColdEmailModal {...props} target={target} />); await drain();
    expect(api.variants).not.toHaveBeenCalled(); expect(api.stream).not.toHaveBeenCalled(); expect(api.generate).not.toHaveBeenCalled(); expect(api.refine).not.toHaveBeenCalled();
    expect(await screen.findByText('coldEmail.targetVersionUnavailable')).toBeVisible(); expect(screen.queryByText('coldEmail.generating')).toBeNull();
  });
  it('sends the same checked token for templates, streaming, and refinement', async () => {
    await open(); refine();
    expect(await screen.findByRole('region', { name: 'Pending edit suggestion' })).toHaveTextContent('Verified refinement');
    expect(screen.getByLabelText('coldEmail.body')).toHaveValue('Template body');
    fireEvent.click(screen.getByRole('button', { name: 'Accept suggestion' }));
    await screen.findByDisplayValue('Verified refinement');
    expect(api.variants).toHaveBeenCalledWith(profile, ID, undefined, { expectedTargetVersion: A, contactContext: { version: 1, purpose: 'first_contact' } });
    expect(api.stream).toHaveBeenCalledWith(profile, ID, { engine: 'ai', style: 'professional', expectedTargetVersion: A, contactContext: { version: 1, purpose: 'first_contact' } }, expect.any(Function));
    expect(api.refine).toHaveBeenCalledWith('Template body', expect.any(String), profile, ID, { expectedTargetVersion: A, contactContext: { version: 1, purpose: 'first_contact' }, subject: 'Template subject' });
  });
  it.each([{ target_version: undefined }, { target_version: B }, { opportunity_id: 'another-target' }])('rejects mismatched initial variants before editor/contact state: %j', async mismatch => {
    api.variants.mockResolvedValue({ ...templates, ...mismatch }); render(<ColdEmailModal {...props} />); await drain();
    expect(screen.queryByDisplayValue('Template body')).toBeNull(); expect(screen.queryByDisplayValue('lab@example.edu')).toBeNull();
    expect(api.stream).not.toHaveBeenCalled(); expect(api.confirm).not.toHaveBeenCalled();
    expect(await screen.findByText('coldEmail.targetVersionUnavailable')).toBeVisible();
  });
  it.each(['stream', 'compat'] as const)('rejects a mismatched %s response and never caches its text', async mode => {
    if (mode === 'stream') api.stream.mockResolvedValue({ ...result, target_version: B, body: 'WRONG TARGET' });
    else { api.stream.mockRejectedValue(new ColdEmailStreamError('unsupported', 404)); api.generate.mockResolvedValue({ ...result, target_version: B, body: 'WRONG TARGET' }); }
    const view = await open(); expect(screen.queryByDisplayValue('WRONG TARGET')).toBeNull();
    expect(await screen.findByText('coldEmail.targetVersionUnavailable')).toBeVisible();
    view.rerender(<ColdEmailModal {...props} isOpen={false} />); api.stream.mockResolvedValue({ ...result, body: 'Current AI' });
    view.rerender(<ColdEmailModal {...props} />); await screen.findByDisplayValue('Template body');
    await act(async () => {});
    const rebuild = screen.queryByRole('button', { name: 'coldEmail.regenerateFromProfile' });
    const ai = screen.getByRole('button', { name: 'coldEmail.aiVariantLabel' });
    await waitFor(() => expect(rebuild ?? ai).toBeEnabled()); fireEvent.click(rebuild ?? ai);
    await screen.findByDisplayValue('Current AI');
    expect(api.stream.mock.calls.length).toBeGreaterThan(1);
  });
  it.each([{ target_version: undefined }, { target_version: B }, { opportunity_id: 'another-target' }])('preserves every edited field on an invalid refine receipt: %j', async mismatch => {
    await open(); edit(); api.refine.mockResolvedValue({ ...receipt, ...mismatch, body: 'Unverified replacement', method: 'llm' }); refine(); await drain();
    kept(); expect(screen.queryByDisplayValue('Unverified replacement')).toBeNull(); expect(await screen.findByText('coldEmail.targetVersionUnavailable')).toBeVisible();
    expect(screen.queryByRole('region', { name: 'Pending edit suggestion' })).toBeNull();
  });
  it('keeps manual fields on target 409 without automatic replay, then regenerates using a newly verified target', async () => {
    const view = await open(); edit(); api.refine.mockRejectedValueOnce(Object.assign(new Error('PRIVATE'), { code: 'WRITING_TARGET_CHANGED', status: 409 }));
    refine(); await drain(); kept(); expect(api.refine).toHaveBeenCalledOnce(); expect(screen.queryByText('PRIVATE')).toBeNull();
    expect(await screen.findByText('coldEmail.targetVersionChanged')).toBeVisible();
    view.rerender(<ColdEmailModal {...props} target={{ ...props.target, writing_target_version: B }} />); await drain(); kept();
    api.variants.mockResolvedValue({ ...templates, target_version: B, variants: [{ ...variant, body: 'Current target body' }] });
    api.stream.mockResolvedValue({ ...result, target_version: B, method: 'template' });
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.regenerateFromProfile' })); await screen.findByDisplayValue('Current target body');
    expect(api.variants).toHaveBeenLastCalledWith(profile, ID, undefined, { expectedTargetVersion: B, contactContext: { version: 1, purpose: 'first_contact' } });
  });
  it('retires late streams on a target-only version change without losing human edits', async () => {
    const held = pending<typeof result>(); api.stream.mockReturnValue(held.promise); const view = await open(); edit();
    view.rerender(<ColdEmailModal {...props} target={{ ...props.target, writing_target_version: B }} />); await drain();
    await act(async () => held.resolve({ ...result, body: 'Late A text', recipient_email: 'wrong@example.edu' })); kept();
    expect(screen.queryByDisplayValue('Late A text')).toBeNull(); expect(api.stream).toHaveBeenCalledOnce();
  });
  it('keeps the manual editor when explicit regeneration receives a different target version', async () => {
    const view = await open(); edit();
    view.rerender(<ColdEmailModal {...props} profile={{ ...profile, coursework: ['New course'] }} />); await drain();
    api.variants.mockResolvedValue({ ...templates, target_version: B, variants: [{ ...variant, body: 'Wrong regeneration' }] });
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.regenerateFromProfile' })); await drain();
    kept(); expect(screen.queryByDisplayValue('Wrong regeneration')).toBeNull(); expect(api.stream).toHaveBeenCalledOnce();
    expect(await screen.findByText('coldEmail.targetVersionUnavailable')).toBeVisible();
  });
  it('does not reveal a recipient from variants for another target', async () => {
    api.variants.mockResolvedValueOnce({ ...templates, recipient_status: 'sign_in_required', variants: [{ ...variant, recipient_email: '' }] });
    await open(); const callback = api.auth.mock.calls.at(-1)?.[0]; expect(callback).toBeTypeOf('function');
    api.variants.mockResolvedValue({ ...templates, target_version: B, recipient_status: 'available', variants: [{ ...variant, recipient_email: 'wrong@example.edu' }] });
    await act(async () => callback({ session: { user: { id: 'receipt-owner' } }, isAnonymous: false })); await drain();
    expect(api.variants).toHaveBeenLastCalledWith(profile, ID, undefined, { expectedTargetVersion: A, contactContext: { version: 1, purpose: 'first_contact' } });
    expect(screen.queryByDisplayValue('wrong@example.edu')).toBeNull(); expect(screen.getByDisplayValue('Template body')).toBeVisible();
    expect(await screen.findByText('coldEmail.targetVersionUnavailable')).toBeVisible();
  });
  it('does not reuse cache metadata without its original exact target token', () => {
    const entry = { response: { ...result }, at: 100 };
    expect(aiCacheEntryIsStale(entry, 101, 'corpus', 'current', A)).toBe(false);
    expect(aiCacheEntryIsStale(entry, 101, 'corpus', 'current', B)).toBe(true);
    expect(aiCacheEntryIsStale({ ...entry, response: { ...result, target_version: undefined } }, 101, 'corpus', 'current', A)).toBe(true);
  });
  it.each(['variants', 'stream'] as const)('surfaces a target 409 from %s without replaying generation', async entry => {
    api[entry].mockRejectedValue(Object.assign(new Error('PRIVATE RESPONSE'), { code: 'WRITING_TARGET_CHANGED', status: 409 }));
    render(<ColdEmailModal {...props} />); await drain();
    expect(await screen.findByText('coldEmail.targetVersionChanged')).toBeVisible(); expect(screen.queryByText('PRIVATE RESPONSE')).toBeNull();
    expect(api[entry]).toHaveBeenCalledOnce(); expect(api.generate).not.toHaveBeenCalled();
    if (entry === 'stream') expect(screen.getByDisplayValue('Template body')).toBeVisible();
  });

  it('does not promote an id plus valid token into a verified full public target', async () => {
    render(<ColdEmailModal {...props} target={{ id: ID, writing_target_version: A } as Opportunity} />); await drain();
    expect(api.variants).not.toHaveBeenCalled(); expect(api.stream).not.toHaveBeenCalled();
    expect(await screen.findByText('coldEmail.targetVersionUnavailable')).toBeVisible();
  });
  it('checks the opportunity again without rebuilding the manual editor or replaying writing', async () => {
    const refresh = vi.fn(async () => true);
    const targetRefresh = { status: 'ready' as const, target: props.target, reason: null, refresh,
      checkForAction: async () => ({ checkId: 1, owner: captureOwnerToken(), target: props.target, key: writingTargetKey(props.target)! }) };
    render(<ColdEmailModal {...props} targetRefresh={targetRefresh} />); await screen.findByDisplayValue('Template body'); await drain(); edit();
    api.refine.mockResolvedValue({ ...receipt, target_version: B, body: 'WRONG', method: 'llm' }); refine(); await drain();
    const history = screen.getByTestId('cold-email-chat-history').textContent;
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.targetVersionRetry' })); await drain();
    expect(refresh).toHaveBeenCalledOnce(); kept(); expect(screen.getByTestId('cold-email-chat-history').textContent).toBe(history);
    expect(api.variants).toHaveBeenCalledOnce(); expect(api.stream).toHaveBeenCalledOnce(); expect(api.refine).toHaveBeenCalledOnce();
  });
  it.each(['refine', 'stream'] as const)('retires held %s after recipient reveal rejects the target receipt', async method => {
    api.variants.mockResolvedValueOnce({ ...templates, recipient_status: 'sign_in_required' });
    const held = pending<typeof result>(); api[method].mockReturnValue(held.promise);
    await open(); edit(); if (method === 'refine') refine(); await drain(); expect(api[method]).toHaveBeenCalledOnce();
    const callback = api.auth.mock.calls.at(-1)?.[0]; expect(callback).toBeTypeOf('function');
    api.variants.mockResolvedValue({ ...templates, target_version: B });
    await act(async () => callback({ session: { user: { id: 'receipt-owner' } }, isAnonymous: false })); await drain();
    expect(await screen.findByText('coldEmail.targetVersionUnavailable')).toBeVisible();
    await act(async () => held.resolve({ ...result, body: 'LATE REFINE AFTER REJECTION', method: method === 'stream' ? 'ai' : 'llm' })); await drain(); kept();
    expect(screen.queryByDisplayValue('LATE REFINE AFTER REJECTION')).toBeNull();
    expect(screen.queryByRole('region', { name: 'Pending edit suggestion' })).toBeNull();
  });

  it('does not auto-generate when an empty editor rechecks a newly available target version', async () => {
    const initial = emailTarget(ID); delete initial.writing_target_version;
    const refresh = vi.fn(async () => true);
    const show = (target: Opportunity) => <ColdEmailModal {...props} target={target} targetRefresh={{ status: 'ready', target, reason: null, refresh,
      checkForAction: async () => ({ checkId: 1, owner: captureOwnerToken(), target, key: writingTargetKey(target)! }) }} />;
    const view = render(show(initial)); await drain();
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.targetVersionRetry' })); await drain();
    view.rerender(show(props.target)); await drain();
    expect(refresh).toHaveBeenCalledOnce(); expect(api.variants).not.toHaveBeenCalled(); expect(api.stream).not.toHaveBeenCalled();
    expect(screen.queryByText('coldEmail.generating')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.tryAgain' })); await screen.findByDisplayValue('Template body');
    expect(api.variants).toHaveBeenCalledOnce();
  });

});


describe('oversized email material preserves the editor', () => {
  for (const locale of ['en', 'zh']) {
    const message = locale === 'zh'
      ? '用于写邮件的资料和修改要求合计太长。请减少本次选用的内容后重试；原稿和要求已保留。'
      : 'The selected email material and edit request are too long together. Reduce the selected content and try again. Your draft and request are kept.';
    it(`shows an explicit ${locale} automatic-generation warning without replay or erasing a draft`, async () => {
      localization.locale = locale;
      api.stream.mockRejectedValue(new ColdEmailStreamError('EMAIL_INPUT_TOO_LARGE', 413));
      await open(); expect(screen.getByText(message)).toBeVisible();
      expect(screen.getByDisplayValue('Template body')).toBeVisible();
      expect(api.stream).toHaveBeenCalledOnce(); expect(api.generate).not.toHaveBeenCalled(); expect(api.variants).toHaveBeenCalledOnce();
    });
    it.each(['stream', 'compat'] as const)(`keeps all edited fields after a ${locale} %s generation rejection`, async mode => {
      localization.locale = locale; await open(); edit();
      const failure = new ColdEmailStreamError('EMAIL_INPUT_TOO_LARGE', 413);
      api.stream.mockRejectedValue(mode === 'stream' ? failure : new ColdEmailStreamError('unsupported', 404));
      api.generate.mockRejectedValue(failure);
      fireEvent.click(screen.getByRole('button', { name: 'coldEmail.aiVariantLabel' }));
      await screen.findByText(message); kept();
      expect(api.stream).toHaveBeenCalledTimes(2);
      expect(api.generate).toHaveBeenCalledTimes(mode === 'stream' ? 0 : 1);
      expect(api.variants).toHaveBeenCalledOnce();
    });
    it(`keeps the manual draft and typed request after a ${locale} refinement rejection`, async () => {
      localization.locale = locale; await open(); edit();
      api.refine.mockRejectedValue(Object.assign(new Error('PRIVATE provider diagnostic'), { code: 'EMAIL_INPUT_TOO_LARGE', status: 413 }));
      fireEvent.change(screen.getByPlaceholderText('coldEmail.refinePlaceholder'), { target: { value: 'Keep every contribution and explain this precise request.' } });
      fireEvent.submit(screen.getByPlaceholderText('coldEmail.refinePlaceholder').closest('form')!);
      await screen.findByText(message); kept();
      expect(screen.getByPlaceholderText('coldEmail.refinePlaceholder')).toHaveValue('Keep every contribution and explain this precise request.');
      expect(api.refine).toHaveBeenCalledOnce(); expect(api.stream).toHaveBeenCalledOnce(); expect(api.generate).not.toHaveBeenCalled();
      expect(screen.queryByText('PRIVATE provider diagnostic')).toBeNull();
    });
  }
});

 describe('profile input rejection keeps the current editor', () => {
  it.each(['stream','refine'] as const)('shows a safe field issue after %s and keeps draft and request', async mode => {
    await open(); edit();
    const error = Object.assign(new Error('PRIVATE_PAYLOAD'), {code:'PROFILE_INPUT_LIMIT_EXCEEDED',status:422,detail:{field:'profile.research_interests_text',actual:60001,limit:60000,unit:'characters'}});
    api[mode].mockRejectedValue(error);
    if (mode === 'stream') fireEvent.click(screen.getByRole('button', { name: 'coldEmail.aiVariantLabel' }));
    else {fireEvent.change(screen.getByPlaceholderText('coldEmail.refinePlaceholder'), {target:{value:'Keep my precise edit request.'}}); fireEvent.submit(screen.getByPlaceholderText('coldEmail.refinePlaceholder').closest('form')!);}
    await screen.findByText('profileInput.characters'); kept();
    if(mode==='refine') expect(screen.getByPlaceholderText('coldEmail.refinePlaceholder')).toHaveValue('Keep my precise edit request.');
    expect(screen.queryByText('PRIVATE_PAYLOAD')).toBeNull();expect(api.generate).not.toHaveBeenCalled();
  });
 });
