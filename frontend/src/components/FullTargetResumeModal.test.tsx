import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createHash, webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { appendTargetResumeProvenance, type TargetResumeProvenance, type TargetResumeProvenanceAction } from '@/lib/target-resume-provenance';
import * as contract from '@/lib/target-resume';
import { createEmptyResumeMaster } from '@/lib/resume-master';
import { advanceOwnerEpoch, captureOwnerToken, isLocalOwnerReady, syncLocalIdentityOwner } from '@/lib/identity-owner';
import type { ProfileViewSnapshot } from '@/lib/profile-sync';
import type { ProfileActionReceipt } from '@/lib/use-profile-refresh';
import { prepareTargetResumeAI } from '@/lib/target-resume-ai';
import { prepareTargetResumePlan } from '@/lib/target-resume-plan';
import type { TargetResumeAiPanelProps } from './TargetResumeAiPanel';
import type { TargetResumePlanPanelProps } from './TargetResumePlanPanel';
import type { ResumeSupplementPanelProps } from './ResumeSupplementPanel';
import type { Opportunity, ProfileData, ResumeFact } from '@/lib/types';
import type { LoadedTargetResume, TargetResumeSaveResult, TargetResumeV1 } from '@/lib/target-resume';
import { DEFAULT_PROFILE } from '@/app/home/types';
import FullTargetResumeModal from './FullTargetResumeModal';
import privateGolden from '../../../tests/fixtures/private-resume-context-v5-golden.json';
import { privateResumeKey, type PrivateResumeContext } from '@/lib/private-resume-context';
import type { PrivateResumeTargetState } from '@/lib/use-private-resume-target';

const storage = vi.hoisted(() => ({ load: vi.fn(), save: vi.fn(), history: vi.fn(), version: vi.fn() }));
vi.mock('./ResumeExperienceAssignmentPanel', () => ({ default: () => null }));
vi.mock('@/lib/target-resume-storage', () => ({
  loadTargetResume: (...args: unknown[]) => storage.load(...args), saveTargetResume: (...args: unknown[]) => storage.save(...args),
  loadTargetResumeHistory: (...args: unknown[]) => storage.history(...args), loadTargetResumeVersion: (...args: unknown[]) => storage.version(...args),
}));
const i18n = vi.hoisted(() => ({ locale: 'en' as 'en' | 'zh' }));
vi.mock('@/i18n/client', () => ({ useLocale: () => i18n.locale }));
const supplement = vi.hoisted(() => ({ props: null as ResumeSupplementPanelProps | null, push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: supplement.push }) }));
vi.mock('./ResumeSupplementPanel', () => ({ default: (props: ResumeSupplementPanelProps) => {
  supplement.props = props;
  return <div><label>Supplement test answer<textarea aria-label="Supplement test answer" onChange={(event) => props.onDirtyChange?.(!!event.target.value)} /></label>
    <button onClick={props.onOpenProfile}>Review master from supplement</button></div>;
} }));

// Lifecycle tests use explicit manual mock actions; real panel receipt capture is tested separately.
const ai = vi.hoisted(() => ({ props: null as TargetResumeAiPanelProps | null }));
vi.mock('./TargetResumeAiPanel', () => ({ default: (props: TargetResumeAiPanelProps) => {
  ai.props = props;
  return <button onClick={() => props.onDirtyChange?.(true)}>AI suggestions awaiting review</button>;
} }));

const plan = vi.hoisted(() => ({ props: null as TargetResumePlanPanelProps | null }));
vi.mock('./TargetResumePlanPanel', () => ({ default: (props: TargetResumePlanPanelProps) => {
  plan.props = props;
  return <button onClick={() => props.onDirtyChange?.(true)}>Content plan awaiting review</button>;
} }));

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const opportunity: Opportunity = {
  id: 'opportunity-one', title: 'Robotics research', organization: 'Example Lab', opportunity_type: 'research',
  paid: 'unknown', location: 'Example campus', on_campus: true, description_clean: 'Work on robotics with Python.', keywords: ['robotics'],
  source_url: 'https://example.test/lab', eligibility: { international_friendly: 'unknown', preferred_year: [], majors: [], skills_required: ['Python'], citizenship_required: null },
  application: { application_effort: 'low', requires_resume: 'yes', contact_method: 'email' },
  metadata: { is_active: true, confidence_score: 1 },
};
const fact = (value: string, status: ResumeFact['status'] = 'confirmed'): ResumeFact => ({ id: crypto.randomUUID(), revision: 1, value, status, source: { kind: 'manual' } });
function profile(): ProfileData {
  const master = createEmptyResumeMaster(); master.basics.name = fact('Alex 王'); master.basics.email = fact('alex@example.test', 'candidate');
  master.education = [{ id: 'school', school: fact('Example University'), degree: fact('B.S. expected'), start: fact('Autumn 2024'), end: fact('Spring 2028'), details: [] }];
  master.activities = [{ id: 'art', kind: 'project', title: fact('Art project'), details: [] }, { id: 'robotics', kind: 'research', title: fact('Python robotics project'), details: [{ id: 'experience', revision: 1 }] }];
  return { ...DEFAULT_PROFILE, resume_text: 'Complete raw source, including unconfirmed material.', resume_master: master,
    experience_entries: [{ id: 'experience', revision: 1, status: 'confirmed', text: 'Measured robot trials; did not lead the team.', source: { kind: 'manual' } },
      { id: 'unlinked', revision: 1, status: 'confirmed', text: 'Unlinked experience should not enter draft.', source: { kind: 'manual' } }] };
}
const docFor = (p: ProfileData, target = opportunity) => contract.createTargetResume(p, contract.targetResumeContextFromOpportunity(target), 'target-doc');
const loaded = (doc: TargetResumeV1, revision = 1): LoadedTargetResume => ({ doc, revision, updated_at: '2026-09-24T18:00:00Z' });
const withName = (doc: TargetResumeV1, text: string) => { const next = clone(doc); next.document.sections.find((section) => section.kind === 'basics')!.blocks[0].lines.find((line) => line.role === 'name')!.text = text; return next; };
const preview = () => within(screen.getByRole('region', { name: 'Current target draft preview' }));
const editName = (text: string) => fireEvent.change(screen.getByRole('textbox', { name: 'Edit Full name' }), { target: { value: text } });
const historyOpen = () => { screen.getByText('Version history').closest('details')!.open = true; };
const deferred = <T,>() => { let resolve!: (value: T) => void; let reject!: (error: unknown) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
function renderModal(p = profile(), target = opportunity, props: { onClose?: () => void; onOpenLegacy?: () => void; isOpen?: boolean } = {}) {
  return render(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={target} {...props} />);
}
async function createUI(p = profile()) {
  const result = renderModal(p);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Create from confirmed master' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Create from confirmed master' }));
  await screen.findByRole('textbox', { name: 'Edit Full name' });
  return result;
}
beforeEach(async () => {
  vi.stubGlobal('crypto', webcrypto); localStorage.clear();
  advanceOwnerEpoch('target-resume-owner-a'); await syncLocalIdentityOwner('target-resume-owner-a');
  await waitFor(() => expect(isLocalOwnerReady('target-resume-owner-a')).toBe(true));
  i18n.locale = 'en'; ai.props = null; plan.props = null; supplement.props = null; supplement.push.mockReset();
  storage.load.mockReset().mockResolvedValue(null); storage.save.mockReset().mockResolvedValue({ status: 'failed' });
  storage.history.mockReset().mockResolvedValue([]); storage.version.mockReset().mockResolvedValue(null);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

async function privateUI(target = clone(privateGolden.receipt.context) as PrivateResumeContext) {
  advanceOwnerEpoch(target.private_source.owner_id); await syncLocalIdentityOwner(target.private_source.owner_id);
  const check = vi.fn().mockImplementation(async () => ({ checkId: 1, owner: captureOwnerToken(), target, key: privateResumeKey(target) }));
  const refresh: PrivateResumeTargetState = { target, status: 'ready', reason: null, checkForAction: check, refresh: vi.fn().mockResolvedValue(true) };
  const p = profile(), close = vi.fn();
  const props = { isOpen: true, onClose: close, profile: p, privateTarget: target, privateResumeRefresh: refresh };
  const view = render(<FullTargetResumeModal {...props} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Create from confirmed master' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Create from confirmed master' }));
  await screen.findByRole('textbox', { name: 'Edit Full name' });
  return { ...view, props, check, target, close };
}
describe('private full résumé workspace', () => {
  it('reports the complete draft size limit instead of creating a truncated private draft', async () => {
    // The source alone fits the 2 MiB draft limit; with the résumé the complete draft does not.
    const length = 2 * 1024 * 1024 - 2048;
    const target = { ...clone(privateGolden.receipt.context), description: 'x'.repeat(length) } as PrivateResumeContext;
    advanceOwnerEpoch(target.private_source.owner_id); await syncLocalIdentityOwner(target.private_source.owner_id);
    const refresh: PrivateResumeTargetState = { target, status: 'ready', reason: null, refresh: async () => true,
      checkForAction: async () => ({ checkId: 1, owner: captureOwnerToken(), target, key: privateResumeKey(target)! }) };
    render(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={profile()} privateTarget={target} privateResumeRefresh={refresh} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create from confirmed master' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Create from confirmed master' }));
    expect(await screen.findByText(/complete résumé and opportunity text exceed/)).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Edit Full name' })).toBeNull(); expect(storage.save).not.toHaveBeenCalled();
    expect(target.description).toHaveLength(length);
  });
  it('creates from checked complete private materials, opens supplements and saves without public AI panels', async () => {
    const { check, target } = await privateUI();
    expect(check).toHaveBeenCalledOnce(); expect(ai.props).toBeNull(); expect(plan.props).toBeNull();
    expect(screen.getByText(/AI adaptation for private imports is not available yet/)).toBeInTheDocument();
    expect(screen.queryByText(/older draft did not save all/)).toBeNull();
    expect(screen.getByText(/Study parsers and research tools\./).textContent).toBe(target.description);
    fireEvent.click(screen.getByRole('button', { name: 'Add experience details' }));
    expect(supplement.props?.opportunityId).toBe(target.opportunity_id);
    editName('Private manual name');
    storage.save.mockImplementation(async (doc, _revision, _owner, provenance) => ({ status: 'saved', value: { doc, provenance, revision: 1, updated_at: new Date().toISOString() } }));
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    await waitFor(() => expect(storage.save).toHaveBeenCalledOnce());
    expect(check).toHaveBeenCalledTimes(2);
    expect(storage.save.mock.calls[0][0].target_snapshot).toEqual(target);
    expect(storage.save.mock.calls[0][0].base_snapshot.resume_text).toBe(profile().resume_text);
    expect(storage.save.mock.calls[0][3].events[0].kind).toBe('manual');
  });
  it('keeps the draft when a private pre-save source read fails; retry cannot overwrite later typing', async () => {
    const { check } = await privateUI(); editName('Keep my first edit');
    check.mockResolvedValueOnce(null);
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save target draft' })).toBeEnabled());
    expect(storage.save).not.toHaveBeenCalled(); expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Keep my first edit');
    let finish!: (value: unknown) => void;
    storage.save.mockImplementation((doc, _revision, _owner, provenance) => new Promise(resolve => { finish = () => resolve({ status: 'saved', value: { doc, provenance, revision: 1, updated_at: new Date().toISOString() } }); }));
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' })); await waitFor(() => expect(storage.save).toHaveBeenCalledOnce());
    editName('A later edit'); await act(async () => finish(null));
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('A later edit');
    expect(screen.getByRole('button', { name: 'Save target draft' })).toBeEnabled();
  });
  it.each(['newer source', 'another account'] as const)('refuses to save on a failed pre-save source check (%s)', async fault => {
    const { check, target } = await privateUI(); editName('Kept private edit');
    const changed = { ...target, description: target.description + '\nNewer source' };
    const owner = fault === 'another account' ? { ...captureOwnerToken(), uid: 'b1000000-0000-4000-8000-000000000001' } : captureOwnerToken();
    const checked = fault === 'newer source' ? changed : target;
    check.mockResolvedValueOnce({ checkId: 2, owner, target: checked, key: privateResumeKey(checked) });
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    expect(await screen.findByText(/private source changed or could not be checked\. Your edits are kept/)).toBeInTheDocument();
    expect(storage.save).not.toHaveBeenCalled(); expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Kept private edit');
  });
  it('retains edits when the private source changes during a pending save check', async () => {
    const { check, target, props, rerender } = await privateUI(); editName('Retained private edit');
    let resolve!: (value: unknown) => void;
    check.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' })); await waitFor(() => expect(check).toHaveBeenCalledTimes(2));
    const changed = { ...target, description: target.description + '\nChanged source' };
    rerender(<FullTargetResumeModal {...props} privateTarget={changed} privateResumeRefresh={{ ...props.privateResumeRefresh, target: changed }} />);
    await act(async () => resolve({ owner: captureOwnerToken(), target, key: privateResumeKey(target) }));
    expect(storage.save).not.toHaveBeenCalled(); expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Retained private edit');
    expect(screen.getByText(/Study parsers and research tools\./).textContent).toBe(target.description);
    expect(await screen.findByText(/created from different profile or target/)).toBeInTheDocument();
  });
  it('checks the private source before an export and keeps the draft when the check fails', async () => {
    const { check } = await privateUI(); editName('Exported private edit'); const before = check.mock.calls.length;
    check.mockResolvedValueOnce(null);
    fireEvent.click(screen.getByRole('button', { name: 'Export PDF' }));
    expect(await screen.findByText(/private source changed or could not be checked\. Your draft is kept/)).toBeInTheDocument();
    expect(check).toHaveBeenCalledTimes(before + 1); expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Exported private edit');
  });
  it('marks a private snapshot as not independently verified, with the source version it was built on', async () => {
    const target = clone(privateGolden.receipt.context) as PrivateResumeContext, source = target.private_source;
    source.revision = 7;
    source.source_version = 'pit1:' + createHash('sha256').update(JSON.stringify({ id: target.opportunity_id, owner_id: source.owner_id, revision: 7 })).digest('hex');
    await privateUI(target);
    expect(screen.getByText('Private import — not independently verified. Saved source version: 7')).toBeInTheDocument();
  });
  it.each(['private', 'public'] as const)('names the organization after the snapshot title only when there is one (%s)', async kind => {
    if (kind === 'private') await privateUI(); else await createUI();
    const line = screen.getByText('Target requirements and original materials').nextElementSibling;
    expect(line?.textContent).toBe(kind === 'private' ? 'Private research note' : 'Robotics research · Example Lab');
  });
  it('does not mark a public snapshot as a private import', async () => {
    await createUI();
    expect(screen.queryByText(/Private import|not independently verified/)).toBeNull();
  });
  it('says the draft is kept only while a private draft is open', async () => {
    const target = clone(privateGolden.receipt.context) as PrivateResumeContext;
    advanceOwnerEpoch(target.private_source.owner_id); await syncLocalIdentityOwner(target.private_source.owner_id);
    const failed: PrivateResumeTargetState = { target, status: 'failed', reason: 'read_failed', refresh: async () => false, checkForAction: async () => null };
    const props = { isOpen: true, onClose: vi.fn(), profile: profile(), privateTarget: target };
    const view = render(<FullTargetResumeModal {...props} privateResumeRefresh={failed} />);
    await screen.findByRole('button', { name: 'Create from confirmed master' });
    expect(screen.getByText('Could not check this private source. Try again.')).toBeInTheDocument();
    view.unmount();
    const { rerender, props: open } = await privateUI(target);
    rerender(<FullTargetResumeModal {...open} privateResumeRefresh={{ ...open.privateResumeRefresh, status: 'offline' }} />);
    expect(screen.getByText('You are offline. Your draft is kept; reconnect to check the source.')).toBeInTheDocument();
    rerender(<FullTargetResumeModal {...open} privateResumeRefresh={{ ...open.privateResumeRefresh, status: 'failed', reason: 'read_failed' }} />);
    expect(screen.getByText('Could not check this private source. Your draft is kept; try again.')).toBeInTheDocument();
  });
  it.each([
    ['page membership lost', 'en'], ['source missing', 'en'], ['page membership lost', 'zh'],
  ] as const)('says plainly that a deleted import cannot be saved or exported (%s, %s)', async (fault, locale) => {
    const { check, props, rerender } = await privateUI(); editName('Edit on a deleted import');
    check.mockResolvedValue(null); i18n.locale = locale;
    const gone = fault === 'page membership lost' ? { targetMembershipReady: false }
      : { privateResumeRefresh: { ...props.privateResumeRefresh, status: 'missing' as const } };
    rerender(<FullTargetResumeModal {...props} {...gone} />);
    const [status, refused] = locale === 'zh'
      ? ['这条私有导入已不可用。已删除的导入无法保存或导出文稿。', '已删除的导入无法保存或导出文稿。']
      : ['This private import is no longer available. Saving and export are unavailable for a deleted import.', 'Saving and export are unavailable for a deleted import.'];
    expect(screen.getByText(status)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: locale === 'zh' ? '保存目标文稿' : 'Save target draft' }));
    expect(await screen.findByText(refused)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: locale === 'zh' ? '导出 PDF' : 'Export PDF' }));
    await waitFor(() => expect(screen.getAllByText(refused)).toHaveLength(2));
    expect(screen.queryByText(/draft is kept|edits are kept|review the source|文稿仍保留|编辑仍保留|核对来源后/)).toBeNull();
    expect(storage.save).not.toHaveBeenCalled(); expect(screen.getByDisplayValue('Edit on a deleted import')).toBeInTheDocument();
  });
  it('keeps source-deleted drafts editable, then confirms before closing unsaved work', async () => {
    const { props, rerender, close } = await privateUI();
    rerender(<FullTargetResumeModal {...props} privateResumeRefresh={{ ...props.privateResumeRefresh, status: 'missing', checkForAction: async () => null }} />);
    editName('Offline retained edit');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(close).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Discard unsaved edits and continue' }));
    expect(close).toHaveBeenCalledOnce();
  });
});

describe('full target résumé modal', () => {
  it('does nothing while closed and does not create from absent or candidate-only master data', async () => {
    const p = profile(); p.resume_master!.basics.name!.status = 'candidate'; p.resume_master!.education = []; p.resume_master!.activities = [];
    const { rerender } = renderModal(p, opportunity, { isOpen: false });
    expect(screen.queryByRole('dialog')).toBeNull(); expect(storage.load).not.toHaveBeenCalled();
    rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={{ ...DEFAULT_PROFILE }} opportunity={opportunity} />);
    await waitFor(() => expect(storage.load).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('button', { name: 'Create from confirmed master' })).toBeDisabled();
    expect(screen.getByRole('link', { name: 'Confirm your master résumé first' })).toHaveAttribute('href', '/#resume-master');
    rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={opportunity} />);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(screen.getByRole('button', { name: 'Create from confirmed master' })).toBeDisabled();
  });
  it('gives the title its own row on a narrow screen, with Close beside it and the supplement action below', () => {
    renderModal();
    const header = screen.getByRole('heading', { level: 2, name: 'Target résumé' }).closest('header')!;
    const close = within(header).getByRole('button', { name: 'Close target résumé' });
    const supplement = within(header).getByRole('button', { name: 'Add experience details' });
    // jsdom has no layout: this pins the grid placement that was measured in Chromium at 320 and 390 px.
    expect(header).toHaveClass('grid', 'grid-cols-[minmax(0,1fr)_auto]', 'sm:flex');
    expect(close).toHaveClass('col-start-2', 'row-start-1');
    expect(supplement).toHaveClass('col-start-1', 'row-start-2');
    expect(supplement.parentElement).toHaveClass('contents', 'sm:flex');
  });
  it('creates a complete independent draft from confirmed linked items, preserving exact dates and selection boundaries', async () => {
    const p = profile(); await createUI(p);
    expect(screen.getByText(/Uses only confirmed items/)).toBeVisible();
    expect(preview().getByText('Alex 王')).toBeVisible(); expect(preview().getByText('Autumn 2024')).toBeVisible();
    expect(preview().getByText('Spring 2028')).toBeVisible();
    expect(preview().queryByText('alex@example.test')).toBeNull(); expect(preview().queryByText('Unlinked experience should not enter draft.')).toBeNull();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Include field: Degree' }));
    expect(preview().queryByText('B.S. expected')).toBeNull();
    editName('New target-only name'); expect(p.resume_master?.basics.name?.value).toBe('Alex 王');
    expect(screen.getByText('Edited from the confirmed source. Check the original and target requirements; this wording has not been fully fact-checked.')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Restore original Full name' }));
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Alex 王');
    const secondBlock = screen.getByTestId('target-block-robotics');
    fireEvent.click(within(secondBlock).getByRole('checkbox', { name: /Include whole block/ }));
    expect(preview().queryByText('Measured robot trials; did not lead the team.')).toBeNull();
    expect(storage.save).not.toHaveBeenCalled();
  });
  it('keeps Save and the save status outside the scrolling editor, so they stay reachable from its last field', async () => {
    await createUI(); editName('Edited in the editor');
    const editor = screen.getByRole('textbox', { name: 'Edit Full name' }).closest('.overflow-y-auto');
    expect(editor).not.toBeNull();
    expect(editor!.contains(screen.getByRole('button', { name: 'Save target draft' }))).toBe(false);
    expect(editor!.contains(screen.getByText('Unsaved local edits'))).toBe(false);
    expect(screen.getByRole('dialog').contains(screen.getByRole('button', { name: 'Save target draft' }))).toBe(true);
  });
  it('keeps focus through multi-character typing and preserves edits made while a save is pending', async () => {
    const user = userEvent.setup(); await createUI();
    const input = screen.getByRole('textbox', { name: 'Edit Full name' });
    await user.click(input); await user.type(input, ' - edited in full');
    expect(input).toHaveFocus(); expect(input).toHaveValue('Alex 王 - edited in full');
    const pending = deferred<TargetResumeSaveResult>(); storage.save.mockReturnValueOnce(pending.promise);
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    expect(storage.save).toHaveBeenCalledWith(expect.anything(), 0, captureOwnerToken(), expect.anything());
    const submitted = clone(storage.save.mock.calls[0][0]) as TargetResumeV1;
    await user.click(input); await user.type(input, ' plus later');
    await act(async () => pending.resolve({ status: 'saved', value: loaded(submitted, 1) }));
    expect(input).toHaveValue('Alex 王 - edited in full plus later');
    expect(screen.getByText('Unsaved local edits')).toBeVisible();
    storage.save.mockImplementationOnce(async (doc: TargetResumeV1) => ({ status: 'saved', value: loaded(doc, 2) }));
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    await screen.findByText('Saved version 2'); expect(storage.save.mock.calls[1][1]).toBe(1);
  });
  it.each([
    ['en', 'guest', ['up to 10 target résumés', 'Sign in to keep your work across devices', 'up to 100']],
    ['en', 'member', ['maximum of 100 saved target résumés']],
    ['en', 'unknown', ['10 for guest sessions, 100 for signed-in accounts']],
    ['zh', 'guest', ['最多保存 10 份目标简历', '登录后可在不同设备上保留', '最多可保存 100 份']],
    ['zh', 'member', ['已保存 100 份目标简历']],
  ] as const)('explains a %s %s target-résumé cap without offering a save that cannot succeed', async (locale, account, phrases) => {
    await createUI(); const name = screen.getByRole('textbox', { name: 'Edit Full name' });
    storage.save.mockResolvedValue({ status: 'quota', account });
    i18n.locale = locale; editName('Alex 王 at the cap');
    const saveName = locale === 'zh' ? '保存目标文稿' : 'Save target draft';
    fireEvent.click(await screen.findByRole('button', { name: saveName }));
    const alert = await screen.findByRole('alert');
    for (const phrase of phrases) expect(alert).toHaveTextContent(phrase);
    expect(alert.textContent).not.toMatch(/retry|try again|重试/i);
    expect(screen.queryByText(/retry saving|请重试保存/)).toBeNull();
    expect(screen.getByRole('button', { name: saveName })).toBeDisabled();
    if (account !== 'guest') expect(alert.textContent).not.toMatch(/Sign in|登录后/);
    fireEvent.change(name, { target: { value: 'Another edit' } }); expect(name).toHaveValue('Another edit');
    expect(screen.getByRole('alert')).toBe(alert);
    expect(screen.getByRole('button', { name: saveName })).toBeDisabled();
    expect(storage.save).toHaveBeenCalledTimes(1);
  });
  it('keeps the generic retryable save message for a failure that is not the cap', async () => {
    await createUI(); editName('Alex 王 unconfirmed'); storage.save.mockResolvedValue({ status: 'failed' });
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The save was not confirmed. Your local edits remain here; retry saving.');
    expect(screen.getByRole('button', { name: 'Save target draft' })).toBeEnabled();
  });
  it('shows cloud read failures and retries without treating errors as an absent draft', async () => {
    const p = profile(); const doc = await docFor(p);
    storage.load.mockRejectedValueOnce(new Error('private raw failure: must not render')).mockResolvedValueOnce(loaded(withName(doc, 'Saved hand edit')));
    renderModal(p);
    await screen.findByText(/The saved résumé could not be read/);
    expect(screen.queryByText(/private raw failure/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Create from confirmed master' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Retry reading saved résumé' }));
    expect(await screen.findByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Saved hand edit');
    expect(storage.save).not.toHaveBeenCalled();
  });
  it('opens historical data without a current master and marks its original profile as outdated', async () => {
    const doc = await docFor(profile()); storage.load.mockResolvedValue(loaded(doc));
    renderModal({ ...DEFAULT_PROFILE });
    expect(await screen.findByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Alex 王');
    await screen.findByText(/created from different profile or target materials/);
    expect(screen.getByRole('button', { name: 'Rebuild from current confirmed master' })).toBeDisabled();
    editName('Manual change on old draft');
    storage.save.mockImplementationOnce(async (draft: TargetResumeV1) => ({ status: 'saved', value: loaded(draft, 2) }));
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    await screen.findByText('Saved version 2');
    expect(storage.save.mock.calls[0][0].base).toEqual(doc.base);
  });
  it('does not offer its master-navigation link while historical edits are unsaved', async () => {
    const original = await docFor(profile()); storage.load.mockResolvedValue(loaded(original));
    const onClose = vi.fn(); renderModal({ ...DEFAULT_PROFILE }, opportunity, { onClose });
    await screen.findByRole('textbox', { name: 'Edit Full name' });
    expect(screen.getByRole('link', { name: 'Confirm your master résumé first' })).toHaveAttribute('href', '/#resume-master');
    editName('Unsaved historical edit');
    expect(screen.queryByRole('link', { name: 'Confirm your master résumé first' })).toBeNull();
    expect(screen.getByText(/Save this draft or close it before opening the master résumé/)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Close target résumé' }));
    expect(onClose).not.toHaveBeenCalled(); expect(screen.getByRole('alert')).toHaveTextContent('unsaved edits');
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Unsaved historical edit');
  });
  it.each(['profile', 'target'] as const)('retires creation when the %s changes and does not replace current materials with a late result', async (kind) => {
    const p = profile(); const oldDoc = await docFor(p); const pending = deferred<TargetResumeV1>();
    vi.spyOn(contract, 'createTargetResume').mockReturnValueOnce(pending.promise);
    const { rerender } = renderModal(p);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create from confirmed master' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Create from confirmed master' }));
    const nextProfile = kind === 'profile' ? { ...p, research_interests: 'changed' } : p;
    const nextTarget = kind === 'target' ? { ...opportunity, description_clean: 'Changed requirements' } : opportunity;
    rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={nextProfile} opportunity={nextTarget} />);
    await act(async () => pending.resolve(oldDoc));
    expect(screen.queryByRole('textbox', { name: 'Edit Full name' })).toBeNull();
    expect(screen.getByRole('alert')).toHaveTextContent('late result was discarded'); expect(storage.save).not.toHaveBeenCalled();
  });
  it('preserves a local draft on source changes without reloading or rebinding its snapshots', async () => {
    const p = profile(); const initial = await docFor(p); storage.load.mockResolvedValue(loaded(initial));
    const { rerender } = renderModal(p); await screen.findByRole('textbox', { name: 'Edit Full name' }); editName('Keep my unsaved edit');
    rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={{ ...p, resume_text: 'Replacement source' }} opportunity={opportunity} />);
    await screen.findByText(/created from different profile or target materials/);
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Keep my unsaved edit'); expect(storage.load).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    expect(storage.save.mock.calls[0][0].base_snapshot.resume_text).toBe(p.resume_text);
    expect(storage.save.mock.calls[0][0].base).toEqual(initial.base);
  });
  it('retires old-target load results and clears private edits after an owner switch', async () => {
    const p = profile(); const first = await docFor(p); const nextTarget = { ...opportunity, id: 'second', title: 'Second target' };
    const second = await docFor(p, nextTarget); const pending = deferred<LoadedTargetResume | null>();
    storage.load.mockReturnValueOnce(pending.promise).mockResolvedValueOnce(loaded(withName(second, 'Second owner-scoped draft')));
    const onClose = vi.fn(); const { rerender } = renderModal(p, opportunity, { onClose });
    rerender(<FullTargetResumeModal isOpen onClose={onClose} profile={p} opportunity={nextTarget} />);
    await screen.findByDisplayValue('Second owner-scoped draft');
    await act(async () => pending.resolve(loaded(withName(first, 'Late first draft'))));
    expect(screen.queryByDisplayValue('Late first draft')).toBeNull();
    editName('Private local edit');
    act(() => advanceOwnerEpoch('target-resume-owner-b'));
    expect(onClose).toHaveBeenCalled(); expect(screen.queryByDisplayValue('Private local edit')).toBeNull();
    expect(storage.save).not.toHaveBeenCalled();
  });
  it('ignores a late save receipt after switching owners', async () => {
    const p = profile(); const doc = await docFor(p); const pending = deferred<TargetResumeSaveResult>();
    storage.load.mockResolvedValue(loaded(doc)); storage.save.mockReturnValueOnce(pending.promise);
    const onClose = vi.fn(); renderModal(p, opportunity, { onClose });
    await screen.findByRole('textbox', { name: 'Edit Full name' }); editName('Private in-flight save');
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    const submitted = clone(storage.save.mock.calls[0][0]) as TargetResumeV1;
    const owner = clone(storage.save.mock.calls[0][2]);
    act(() => advanceOwnerEpoch('target-resume-owner-b'));
    await act(async () => pending.resolve({ status: 'saved', value: loaded(submitted, 2) }));
    expect(onClose).toHaveBeenCalled(); expect(screen.queryByDisplayValue('Private in-flight save')).toBeNull();
    expect(screen.queryByText('Saved version 2')).toBeNull(); expect(owner.uid).toBe('target-resume-owner-a');
    expect(storage.save).toHaveBeenCalledTimes(1);
  });
  it('keeps edits on CAS conflict, preserves them after reload failure, and replaces them only on explicit successful server reload', async () => {
    const p = profile(); const original = await docFor(p); const server = loaded(withName(original, 'Newer server text'), 2);
    storage.load.mockResolvedValueOnce(loaded(original)).mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(server);
    storage.save.mockResolvedValue({ status: 'conflict', current: server });
    renderModal(p); await screen.findByRole('textbox', { name: 'Edit Full name' }); editName('My conflicting local edit');
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    await screen.findByText(/A newer server version exists/);
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('My conflicting local edit');
    expect(screen.getByRole('button', { name: 'Save target draft' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Discard local edits and load server version' }));
    await screen.findByText(/server version could not be read/);
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('My conflicting local edit');
    fireEvent.click(screen.getByRole('button', { name: 'Discard local edits and load server version' }));
    await screen.findByDisplayValue('Newer server text'); expect(screen.getByText('Saved version 2')).toBeVisible();
    expect(storage.save).toHaveBeenCalledTimes(1);
  });
  it('uses one unsaved-discard guard for close, Escape and the legacy editor switch', async () => {
    const onClose = vi.fn(); const onOpenLegacy = vi.fn();
    renderModal(profile(), opportunity, { onClose, onOpenLegacy });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create from confirmed master' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Create from confirmed master' })); await screen.findByRole('textbox', { name: 'Edit Full name' });
    fireEvent.click(screen.getByRole('button', { name: 'Close target résumé' }));
    expect(onClose).not.toHaveBeenCalled(); fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
    fireEvent.keyDown(document, { key: 'Escape' }); expect(screen.getByRole('alert')).toHaveTextContent('unsaved edits');
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit résumé bullets' })); expect(onOpenLegacy).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Discard unsaved edits and continue' })); expect(onOpenLegacy).toHaveBeenCalledTimes(1); expect(onClose).not.toHaveBeenCalled();
  });
  it('retains long manual text and blank draft fields, blocks invalid saves, and never truncates the original', async () => {
    const p = profile(); const long = `${'Full context with no invented result. '.repeat(190)}Tail retained.`;
    p.resume_master!.basics.name!.value = long; await createUI(p);
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue(long); expect(preview().getByText(long)).toBeVisible();
    editName(''); expect(preview().getByText('[Empty selected field]')).toBeVisible();
    expect(screen.getByText(long)).toBeVisible();
    editName(long + ' Manual ending.');
    vi.spyOn(contract, 'validateTargetResume').mockReturnValueOnce({ ok: false, code: 'document_too_large' });
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    expect(screen.getByRole('alert')).toHaveTextContent('complete input is still here'); expect(storage.save).not.toHaveBeenCalled();
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue(long + ' Manual ending.');
  });
  it('suggests and manually changes whole-block order without rewriting or dropping any content', async () => {
    await createUI();
    const before = screen.getAllByRole('textbox').map((input) => (input as HTMLTextAreaElement).value).sort();
    fireEvent.click(screen.getByRole('button', { name: 'Suggest order of whole blocks' }));
    const activities = screen.getByRole('group', { name: 'Experience and projects' });
    expect(within(activities).getAllByRole('textbox', { name: 'Edit Title' })[0]).toHaveValue('Python robotics project');
    expect(screen.getAllByRole('textbox').map((input) => (input as HTMLTextAreaElement).value).sort()).toEqual(before);
    fireEvent.click(within(activities).getByRole('button', { name: 'Move block down 1 Experience and projects' }));
    expect(within(activities).getAllByRole('textbox', { name: 'Edit Title' })[0]).toHaveValue('Art project');
  });
  it('loads bounded history metadata, preserves pages after a failed older request, and loads bodies only on selection', async () => {
    const p = profile(); storage.load.mockResolvedValue(loaded(await docFor(p), 30));
    const first = Array.from({ length: 20 }, (_, index) => ({ revision: 30 - index, updated_at: '2026-09-24' }));
    const second = Array.from({ length: 10 }, (_, index) => ({ revision: 10 - index, updated_at: '2026-09-23' }));
    storage.history.mockResolvedValueOnce(first).mockRejectedValueOnce(new Error('no details')).mockResolvedValueOnce(second);
    renderModal(p); await screen.findByRole('textbox', { name: 'Edit Full name' }); historyOpen();
    fireEvent.click(screen.getByRole('button', { name: 'Load latest 20 versions' }));
    await screen.findByRole('button', { name: /View version 30 ·/ }); expect(storage.version).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Load older versions' }));
    await screen.findByText(/History could not be read/); expect(screen.getAllByRole('button', { name: /^View version / })).toHaveLength(20);
    fireEvent.click(screen.getByRole('button', { name: 'Load older versions' }));
    await screen.findByRole('button', { name: /View version 1 ·/ });
    expect(screen.getAllByRole('button', { name: /^View version / })).toHaveLength(30);
    expect(storage.history.mock.calls[2]).toEqual([opportunity.id, captureOwnerToken(), 11, { signal: expect.any(AbortSignal) }]);
    expect(screen.queryByRole('button', { name: 'Load older versions' })).toBeNull(); expect(storage.version).not.toHaveBeenCalled();
  });
  it.each([
    ['en', 'en-US', 'Edit Full name', 'Version history', 'Load latest 20 versions', 'View version 2 · ', /^[A-Z][a-z]{2} \d{1,2}, 2026, \d{1,2}:\d{2}\s[AP]M$/],
    ['zh', 'zh-CN', '编辑 姓名', '版本历史', '读取最近 20 个版本', '查看版本 2 · ', /^2026年\d{1,2}月\d{1,2}日 \d{2}:\d{2}$/],
  ] as const)('shows saved version times as a local date and time, not raw UTC timestamps (%s)', async (locale, tag, field, summary, load, prefix, shape) => {
    i18n.locale = locale; const p = profile(); storage.load.mockResolvedValue(loaded(await docFor(p), 2));
    const savedAt = '2026-09-30T12:22:24.741331+00:00';
    storage.history.mockResolvedValueOnce([{ revision: 2, updated_at: savedAt }]);
    renderModal(p); await screen.findByRole('textbox', { name: field }); screen.getByText(summary).closest('details')!.open = true;
    fireEvent.click(screen.getByRole('button', { name: load }));
    const version = await screen.findByRole('button', { name: new RegExp(`^${prefix}`) });
    // The runner's own time zone decides the date and minute (Sep 30 or Oct 1, :22 or :52).
    const local = new Date(savedAt).toLocaleString(tag, { dateStyle: 'medium', timeStyle: 'short' });
    expect(local).toMatch(shape);
    expect(version.textContent).toBe(prefix + local);
    expect(version.textContent).not.toMatch(/741331|\+00:00|T12:22/);
  });
  it('ignores out-of-order history bodies and restores the selected immutable version through a new CAS save', async () => {
    const p = profile(); const original = await docFor(p); const oldOne = loaded(withName(original, 'Version one hand edit'), 1); const oldTwo = loaded(withName(original, 'Version two hand edit'), 2);
    storage.load.mockResolvedValue(loaded(original, 3)); storage.history.mockResolvedValue([{ revision: 2, updated_at: 'two' }, { revision: 1, updated_at: 'one' }]);
    const first = deferred<LoadedTargetResume | null>(); storage.version.mockReturnValueOnce(first.promise).mockResolvedValueOnce(oldTwo);
    renderModal(p); await screen.findByRole('textbox', { name: 'Edit Full name' }); editName('My current unsaved draft'); historyOpen();
    fireEvent.click(screen.getByRole('button', { name: 'Load latest 20 versions' })); await screen.findByRole('button', { name: 'View version 1 · one' });
    fireEvent.click(screen.getByRole('button', { name: 'View version 1 · one' }));
    fireEvent.click(screen.getByRole('button', { name: 'View version 2 · two' }));
    await screen.findByRole('region', { name: 'Selected historical version preview' });
    await act(async () => first.resolve(oldOne));
    expect(within(screen.getByRole('region', { name: 'Selected historical version preview' })).getByText('Version two hand edit')).toBeVisible();
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('My current unsaved draft');
    storage.save.mockImplementationOnce(async (doc: TargetResumeV1) => ({ status: 'saved', value: loaded(doc, 4) }));
    fireEvent.click(screen.getByRole('button', { name: 'Restore selected version as a new save' }));
    await screen.findByText('Saved version 4');
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Version two hand edit');
    expect(storage.save.mock.calls[0]).toEqual([oldTwo.doc, 3, captureOwnerToken(), null]);
    expect(oldTwo.revision).toBe(2); expect(oldTwo.doc.document.sections[0].blocks[0].lines[0].text).toBe('Version two hand edit');
  });
  it('retires pending history metadata after saving and a selected old body when rebuilding', async () => {
    const p = profile(); const original = await docFor(p); storage.load.mockResolvedValue(loaded(original));
    const pending = deferred<Array<{ revision: number; updated_at: string }>>(); storage.history.mockReturnValueOnce(pending.promise);
    renderModal(p); await screen.findByRole('textbox', { name: 'Edit Full name' }); editName('New save'); historyOpen();
    fireEvent.click(screen.getByRole('button', { name: 'Load latest 20 versions' }));
    storage.save.mockImplementationOnce(async (doc: TargetResumeV1) => ({ status: 'saved', value: loaded(doc, 2) }));
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' })); await screen.findByText('Saved version 2');
    await act(async () => pending.resolve([{ revision: 1, updated_at: 'old' }]));
    expect(screen.queryByRole('button', { name: 'View version 1 · old' })).toBeNull();
    storage.history.mockResolvedValueOnce([{ revision: 1, updated_at: 'old' }]); const body = deferred<LoadedTargetResume | null>(); storage.version.mockReturnValueOnce(body.promise);
    fireEvent.click(screen.getByRole('button', { name: 'Load latest 20 versions' })); await screen.findByRole('button', { name: 'View version 1 · old' });
    fireEvent.click(screen.getByRole('button', { name: 'View version 1 · old' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Rebuild from current confirmed master' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Rebuild from current confirmed master' }));
    fireEvent.click(screen.getByRole('button', { name: 'Create new draft' }));
    await screen.findByDisplayValue('Alex 王');
    await act(async () => body.resolve(loaded(withName(original, 'Late history'))));
    expect(screen.queryByRole('region', { name: 'Selected historical version preview' })).toBeNull();
  });
});


describe('supplement panel integration', () => {
  const viewOf = (p: ProfileData): ProfileViewSnapshot => ({ viewId: crypto.randomUUID(), baseProfile: clone(p), renderedProfile: clone(p),
    revision: 2, token: captureOwnerToken(), identityGeneration: captureOwnerToken().epoch, source: 'hydration' });
  async function savedUI(p = profile(), onClose = vi.fn()) {
    storage.load.mockResolvedValue(loaded(withName(await docFor(p), 'Saved hand-written name')));
    const rendered = renderModal(p, opportunity, { onClose });
    await screen.findByDisplayValue('Saved hand-written name');
    fireEvent.click(screen.getByRole('button', { name: 'Add experience details' }));
    return { ...rendered, onClose };
  }
  it('keeps unconfirmed answers when collapsed or a close is cancelled, then guards master navigation', async () => {
    const { onClose } = await savedUI();
    fireEvent.change(screen.getByRole('textbox', { name: 'Supplement test answer' }), { target: { value: 'I measured the samples, not the whole team.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add experience details' }));
    expect(screen.queryByRole('textbox', { name: 'Supplement test answer' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Close target résumé' }));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add experience details' }));
    expect(screen.getByRole('textbox', { name: 'Supplement test answer' })).toHaveValue('I measured the samples, not the whole team.');
    fireEvent.click(screen.getByRole('button', { name: 'Review master from supplement' }));
    expect(supplement.push).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Discard unsaved edits and continue' }));
    expect(supplement.push).toHaveBeenCalledWith('/#resume-master'); expect(onClose).toHaveBeenCalledTimes(1);
  });
  it('keeps supplemental answers across a failed target-document read and its retry', async () => {
    const p = profile(); const onClose = vi.fn();
    storage.load.mockRejectedValueOnce(new Error('failed target read')).mockResolvedValueOnce(loaded(await docFor(p)));
    renderModal(p, opportunity, { onClose });
    await screen.findByText(/The saved résumé could not be read/);
    fireEvent.click(screen.getByRole('button', { name: 'Add experience details' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Supplement test answer' }), { target: { value: 'Keep this independent answer' } });
    fireEvent.click(screen.getByRole('button', { name: 'Retry reading saved résumé' }));
    await screen.findByRole('textbox', { name: 'Edit Full name' });
    expect(screen.getByRole('textbox', { name: 'Supplement test answer' })).toHaveValue('Keep this independent answer');
    fireEvent.click(screen.getByRole('button', { name: 'Close target résumé' }));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('unsaved edits, suggestions or answers');
  });
  it('registers browser-close requests through the same unsaved-answer guard', async () => {
    const p = profile(); storage.load.mockResolvedValue(loaded(await docFor(p)));
    const onClose = vi.fn(); const register = vi.fn();
    const { unmount } = render(<FullTargetResumeModal isOpen onClose={onClose} profile={p} opportunity={opportunity} onCloseRequestChange={register} />);
    await screen.findByRole('textbox', { name: 'Edit Full name' });
    fireEvent.click(screen.getByRole('button', { name: 'Add experience details' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Supplement test answer' }), { target: { value: 'Keep on browser Back' } });
    const request = register.mock.calls.at(-1)![0] as () => boolean;
    let closed: boolean | undefined; act(() => { closed = request(); });
    expect(closed).toBe(false); expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('unsaved edits, suggestions or answers');
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
    expect(screen.getByRole('textbox', { name: 'Supplement test answer' })).toHaveValue('Keep on browser Back');
    act(() => { closed = request(); }); expect(closed).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Discard unsaved edits and continue' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    unmount(); expect(register).toHaveBeenLastCalledWith(null);
  });
  it('keeps even saved hand edits until the user explicitly accepts a rebuild', async () => {
    await savedUI();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Rebuild from current confirmed master' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Rebuild from current confirmed master' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Existing edits will not carry over');
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Saved hand-written name');
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Saved hand-written name');
    fireEvent.click(screen.getByRole('button', { name: 'Rebuild from current confirmed master' }));
    fireEvent.click(screen.getByRole('button', { name: 'Create new draft' }));
    await screen.findByDisplayValue('Alex 王'); expect(storage.save).not.toHaveBeenCalled();
  });
  it('accepts supplemented profile only for future creation without modifying the current target', async () => {
    const p = profile(); await savedUI(p);
    editName('Unsaved name after opening panel');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Include field: Degree' }));
    const next = clone(p); next.resume_master!.basics.name!.value = 'Updated master name'; next.resume_master!.revision += 1;
    act(() => supplement.props!.onAcceptedProfile?.(viewOf(next), viewOf(p)));
    await screen.findByText(/created from different profile or target materials/);
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Unsaved name after opening panel');
    expect(screen.getByRole('checkbox', { name: 'Include field: Degree' })).not.toBeChecked();
    storage.save.mockImplementationOnce(async (doc: TargetResumeV1) => ({ status: 'saved', value: loaded(doc, 2) }));
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' })); await screen.findByText('Saved version 2');
    expect(storage.save.mock.calls[0][0].base_snapshot.resume_master.basics.name.value).toBe('Alex 王');
    fireEvent.click(screen.getByRole('button', { name: 'Rebuild from current confirmed master' }));
    fireEvent.click(screen.getByRole('button', { name: 'Create new draft' }));
    await screen.findByDisplayValue('Updated master name');
  });
  it('accepts a supplement made after explicitly reviewing a newer parent profile', async () => {
    const p = profile(); const { rerender } = await savedUI(p);
    const newer = clone(p); newer.resume_master!.basics.name!.value = 'Reviewed parent name';
    rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={newer} opportunity={opportunity} />);
    const supplemented = clone(newer); supplemented.resume_master!.basics.name!.value = 'Supplement after review';
    act(() => supplement.props!.onAcceptedProfile?.(viewOf(supplemented), viewOf(newer)));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Rebuild from current confirmed master' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Rebuild from current confirmed master' }));
    fireEvent.click(screen.getByRole('button', { name: 'Create new draft' }));
    await screen.findByDisplayValue('Supplement after review');
  });
  it('does not replace a newer parent profile with a late supplement callback', async () => {
    const p = profile(); const { rerender } = await savedUI(p);
    const callback = supplement.props!.onAcceptedProfile!;
    const newer = clone(p); newer.resume_master!.basics.name!.value = 'Newer parent name';
    rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={newer} opportunity={opportunity} />);
    const obsolete = clone(p); obsolete.resume_master!.basics.name!.value = 'Obsolete callback name';
    act(() => callback(viewOf(obsolete), viewOf(p)));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Rebuild from current confirmed master' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Rebuild from current confirmed master' }));
    fireEvent.click(screen.getByRole('button', { name: 'Create new draft' }));
    await screen.findByDisplayValue('Newer parent name');
    expect(screen.queryByDisplayValue('Obsolete callback name')).toBeNull();
  });
});


describe('full target AI integration', () => {
  it('protects unsaved suggestions when the target draft itself was already saved', async () => {
    const p = profile(); const doc = await docFor(p); storage.load.mockResolvedValue(loaded(doc)); const onClose = vi.fn();
    renderModal(p, opportunity, { onClose }); await screen.findByText('AI suggestions awaiting review');
    fireEvent.click(screen.getByText('AI suggestions awaiting review')); fireEvent.click(screen.getByRole('button', { name: 'Close target résumé' }));
    expect(onClose).not.toHaveBeenCalled(); expect(screen.getByRole('alert')).toHaveTextContent('unsaved edits, suggestions or answers');
    expect(storage.save).not.toHaveBeenCalled();
  });
  it('applies against the exact current draft locally and saves only on an explicit save', async () => {
    await createUI(); const before = ai.props!.draft; const prepared = await prepareTargetResumeAI(before); if (!prepared.ok) throw new Error(prepared.code);
    const next = clone(before); next.document.sections.flatMap((s) => s.blocks.flatMap((b) => b.lines)).find((line) => line.evidence.kind === 'experience')!.text = 'Reviewed robot trials; did not lead the team.';
    act(() => ai.props!.onApply(prepared.value.canonical_draft, next, { kind: 'manual' }));
    expect(preview().getByText('Reviewed robot trials; did not lead the team.')).toBeVisible();
    expect(storage.save).not.toHaveBeenCalled();
    storage.save.mockImplementationOnce(async (draft: TargetResumeV1) => ({ status: 'saved', value: loaded(draft, 1) }));
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' })); await screen.findByText('Saved version 1');
    expect(storage.save.mock.calls[0][0].base_snapshot).toEqual(before.base_snapshot);
  });
  it('refuses an old apply callback after later manual edits', async () => {
    await createUI(); const old = ai.props!; const prepared = await prepareTargetResumeAI(old.draft); if (!prepared.ok) throw new Error(prepared.code);
    editName('Keep my later edit'); const next = withName(old.draft, 'Stale change');
    act(() => old.onApply(prepared.value.canonical_draft, next, { kind: 'manual' }));
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Keep my later edit');
    expect(storage.save).not.toHaveBeenCalled();
  });
});


describe('profile refresh preserves the full target document', () => {
  it('keeps manual edits and selection through failed/retried checks and retires an old AI apply callback', async () => {
    const p = profile(); const { rerender } = await createUI(p); const refresh = vi.fn().mockResolvedValue(true);
    editName('My uncommitted name');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Include field: Degree' }));
    const old = ai.props!;
    const base = clone(old.draft.base);
    const renderState = (status: 'checking' | 'failed' | 'ready') => rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={opportunity} profileRefresh={{ status, refresh }} />);
    renderState('checking');
    expect(ai.props!.enabled).toBe(false);
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toBeEnabled();
    renderState('failed'); fireEvent.click(screen.getByRole('button', { name: 'Retry' })); expect(refresh).toHaveBeenCalledTimes(1);
    renderState('ready');
    const prepared = await prepareTargetResumeAI(old.draft); if (!prepared.ok) throw new Error(prepared.code);
    act(() => old.onApply(prepared.value.canonical_draft, withName(old.draft, 'Late AI overwrite'), { kind: 'manual' }));
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('My uncommitted name');
    expect(screen.getByRole('checkbox', { name: 'Include field: Degree' })).not.toBeChecked();
    expect(ai.props!.draft.base).toEqual(base);
    expect(storage.load).toHaveBeenCalledTimes(1); expect(storage.save).not.toHaveBeenCalled();
  });

  it('rejects a pending creation after a check starts and finishes with the same profile', async () => {
    const p = profile(); const old = await docFor(p); const pending = deferred<TargetResumeV1>();
    vi.spyOn(contract, 'createTargetResume').mockReturnValueOnce(pending.promise);
    const { rerender } = renderModal(p); const refresh = vi.fn().mockResolvedValue(true);
    const create = await screen.findByRole('button', { name: 'Create from confirmed master' });
    await waitFor(() => expect(create).toBeEnabled()); fireEvent.click(create);
    rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={opportunity} profileRefresh={{ status: 'checking', refresh }} />);
    rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={opportunity} profileRefresh={{ status: 'ready', refresh }} />);
    await act(async () => pending.resolve(old));
    expect(screen.queryByRole('textbox', { name: 'Edit Full name' })).toBeNull(); expect(storage.save).not.toHaveBeenCalled();
    expect(create).toBeEnabled();
  });
});


it('keeps dirty work when opening profile conflict review and waits for the existing leave decision', async () => {
  const p = profile(); const { rerender } = await createUI(p); editName('Unsaved before conflict review');
  const refresh = vi.fn().mockResolvedValue(false);
  rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={opportunity} profileRefresh={{ status: 'conflict', refresh }} />);
  fireEvent.click(screen.getByRole('link', { name: 'Review profile' }));
  expect(screen.getByRole('button', { name: 'Keep editing' })).toBeVisible();
  expect(supplement.push).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
  expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Unsaved before conflict review');
});

it('asks before leaving a pending save even after the displayed text is edited back to the saved version', async () => {
  const p = profile(); const original = await docFor(p); storage.load.mockResolvedValue(loaded(original));
  const pending = deferred<TargetResumeSaveResult>(); storage.save.mockReturnValue(pending.promise);
  const onClose = vi.fn(); renderModal(p, opportunity, { onClose });
  await screen.findByRole('textbox', { name: 'Edit Full name' }); editName('Pending saved name');
  fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
  await waitFor(() => expect(storage.save).toHaveBeenCalledTimes(1));
  editName('Alex 王'); fireEvent.click(screen.getByRole('button', { name: 'Close target résumé' }));
  expect(onClose).not.toHaveBeenCalled(); expect(screen.getByRole('button', { name: 'Keep editing' })).toBeVisible();
  await act(async () => pending.resolve({ status: 'failed' }));
});


it('keeps an independent target draft when its profile disappears, without treating the snapshot as current', async () => {
  const p = profile(); const { rerender } = await createUI(p);
  editName('Keep this independently edited résumé');
  fireEvent.click(screen.getByRole('checkbox', { name: 'Include field: Degree' }));
  fireEvent.click(screen.getByRole('button', { name: 'Add experience details' }));
  const answer = screen.getByRole('textbox', { name: 'Supplement test answer' });
  fireEvent.change(answer, { target: { value: 'Unsubmitted answer survives' } });
  const oldAi = ai.props!; const base = clone(oldAi.draft.base);
  rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={opportunity} profileAvailable={false} targetReady={false} />);
  expect(screen.getByTestId('profile-refresh-status')).toHaveTextContent('Your profile is no longer available.');
  expect(screen.queryByText(/This target is not confirmed/)).toBeNull();
  expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Keep this independently edited résumé');
  expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toBeEnabled();
  expect(screen.getByRole('checkbox', { name: 'Include field: Degree' })).not.toBeChecked();
  expect(answer).toHaveValue('Unsubmitted answer survives');
  expect(supplement.props!.profileAvailable).toBe(false);
  expect(ai.props!.enabled).toBe(false);
  expect(screen.getByRole('button', { name: 'Rebuild from current confirmed master' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Export PDF' })).toBeEnabled();
  expect(screen.getByText(/Exports this retained draft without restoring your profile/)).toBeVisible();
  expect(storage.save).not.toHaveBeenCalled();
  const prepared = await prepareTargetResumeAI(oldAi.draft); if (!prepared.ok) throw new Error(prepared.code);
  act(() => oldAi.onApply(prepared.value.canonical_draft, withName(oldAi.draft, 'Late deleted profile AI'), { kind: 'manual' }));
  expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Keep this independently edited résumé');
  fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
  await waitFor(() => expect(storage.save).toHaveBeenCalledTimes(1));
  expect(storage.save.mock.calls[0][0].base).toEqual(base);
  expect(JSON.stringify(storage.save.mock.calls[0][0])).toContain('Keep this independently edited résumé');
});


it('does not reactivate an accepted supplement overlay after profile removal and same-value restoration', async () => {
  const p = profile(); const { rerender } = await createUI(p);
  editName('Preserve my target edit');
  fireEvent.click(screen.getByRole('button', { name: 'Add experience details' }));
  const viewOf = (value: ProfileData): ProfileViewSnapshot => ({ viewId: crypto.randomUUID(), baseProfile: clone(value), renderedProfile: clone(value),
    revision: 2, token: captureOwnerToken(), identityGeneration: captureOwnerToken().epoch, source: 'hydration' });
  const overlay = { ...p, resume_text: 'Supplement previously accepted before removal' };
  const acceptedBeforeRemoval = supplement.props!.onAcceptedProfile!;
  const overlayView = viewOf(overlay), originalView = viewOf(p);
  act(() => acceptedBeforeRemoval(overlayView, originalView));
  const overlaySignature = await contract.targetResumeProfileSignature(overlay);
  await waitFor(() => expect(ai.props!.currentContext?.profile_signature).toBe(overlaySignature));
  rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={opportunity} profileAvailable={false} />);
  rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={opportunity} profileAvailable />);
  act(() => acceptedBeforeRemoval(overlayView, originalView));
  const restoredSignature = await contract.targetResumeProfileSignature(p);
  await waitFor(() => expect(ai.props!.currentContext?.profile_signature).toBe(restoredSignature));
  expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Preserve my target edit');
  expect(storage.save).not.toHaveBeenCalled();
});


describe('full résumé creation action checks', () => {
  const receipt = (p: ProfileData): ProfileActionReceipt => ({ checkId: 1, owner: captureOwnerToken(), revision: 2, source: 'cloud', profile: clone(p) });
  it('checks once, waits for the accepted latest profile and target readiness, then builds the complete new source without saving', async () => {
    const p = profile(), newer = clone(p); newer.resume_text = 'Complete new source 😀 including its final tail';
    newer.resume_master!.basics.name!.value = 'Freshly confirmed name';
    const signature = await contract.targetResumeProfileSignature(newer), signatureWait = deferred<string>();
    const originalSignature = contract.targetResumeProfileSignature;
    const signatureRead = vi.spyOn(contract, 'targetResumeProfileSignature').mockImplementation((value) => value.resume_text === newer.resume_text ? signatureWait.promise : originalSignature(value));
    const wait = deferred<ProfileActionReceipt | null>();
    const checkForAction = vi.fn(() => wait.promise), refresh = vi.fn().mockResolvedValue(true);
    const build = vi.spyOn(contract, 'createTargetResume');
    const view = render(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={opportunity} profileRefresh={{ status: 'ready', refresh, checkForAction }} />);
    const button = await screen.findByRole('button', { name: 'Create from confirmed master' });
    await waitFor(() => expect(button).toBeEnabled()); fireEvent.click(button); fireEvent.click(button);
    await waitFor(() => expect(checkForAction).toHaveBeenCalledTimes(1)); expect(build).not.toHaveBeenCalled();
    await act(async () => wait.resolve(receipt(newer)));
    expect(build).not.toHaveBeenCalled();
    view.rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={newer} opportunity={opportunity} targetReady={false} targetChecking profileRefresh={{ status: 'ready', refresh, checkForAction }} />);
    await waitFor(() => expect(signatureRead).toHaveBeenCalledWith(newer));
    expect(build).not.toHaveBeenCalled();
    await act(async () => signatureWait.resolve(signature));
    expect(build).not.toHaveBeenCalled();
    view.rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={newer} opportunity={opportunity} profileRefresh={{ status: 'ready', refresh, checkForAction }} />);
    expect(await screen.findByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Freshly confirmed name');
    expect(build).toHaveBeenCalledTimes(1); expect(build.mock.calls[0][0].resume_text).toBe(newer.resume_text);
    expect(storage.save).not.toHaveBeenCalled();
  });
  it('keeps the discard decision and cancels rebuilding if the user edits during the profile check', async () => {
    const p = profile(); const initial = await docFor(p); storage.load.mockResolvedValue(loaded(initial));
    const wait = deferred<ProfileActionReceipt | null>(), checkForAction = vi.fn(() => wait.promise), refresh = vi.fn().mockResolvedValue(true);
    const build = vi.spyOn(contract, 'createTargetResume');
    render(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={opportunity} profileRefresh={{ status: 'ready', refresh, checkForAction }} />);
    await screen.findByRole('textbox', { name: 'Edit Full name' }); editName('Before checking');
    const rebuild = screen.getByRole('button', { name: 'Rebuild from current confirmed master' }); await waitFor(() => expect(rebuild).toBeEnabled());
    fireEvent.click(rebuild); expect(checkForAction).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Create new draft' })); await waitFor(() => expect(checkForAction).toHaveBeenCalledTimes(1));
    editName('New hand edit during check');
    await act(async () => wait.resolve(receipt(p)));
    expect(build).not.toHaveBeenCalled(); expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('New hand edit during check');
    expect(screen.getByText(/Your draft or target changed during the check/)).toBeVisible(); expect(storage.save).not.toHaveBeenCalled();
  });
  it('does not create from a failed or deleted-profile check', async () => {
    const p = profile(), checkForAction = vi.fn().mockResolvedValue(null), refresh = vi.fn().mockResolvedValue(false);
    const build = vi.spyOn(contract, 'createTargetResume');
    render(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={opportunity} profileRefresh={{ status: 'ready', refresh, checkForAction }} />);
    const button = await screen.findByRole('button', { name: 'Create from confirmed master' }); await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button); await screen.findByText(/Current profile could not be verified/); expect(build).not.toHaveBeenCalled();
    checkForAction.mockResolvedValue({ ...receipt(p), source: 'cloud-absent', profile: null });
    fireEvent.click(button); await waitFor(() => expect(checkForAction).toHaveBeenCalledTimes(2)); expect(build).not.toHaveBeenCalled(); expect(storage.save).not.toHaveBeenCalled();
  });
});


describe('whole draft content plan integration', () => {
  it('includes a pending content plan in the close warning even when the current draft is saved', async () => {
    const p = profile(), doc = await docFor(p), onClose = vi.fn(); storage.load.mockResolvedValue(loaded(doc));
    renderModal(p, opportunity, { onClose }); await screen.findByRole('textbox', { name: 'Edit Full name' });
    fireEvent.click(screen.getByRole('button', { name: 'Content plan awaiting review' }));
    fireEvent.click(screen.getByRole('button', { name: 'Close target résumé' }));
    expect(screen.getByText(/unsaved edits, suggestions or answers/)).toBeVisible(); expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' })); expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Alex 王');
  });
  it('applies plan changes locally and rejects a competing stale AI apply, preserving the original snapshot', async () => {
    const p = profile(), doc = await docFor(p); storage.load.mockResolvedValue(loaded(doc)); renderModal(p);
    await screen.findByRole('textbox', { name: 'Edit Full name' }); await waitFor(() => expect(plan.props?.enabled).toBe(true));
    const oldAI = ai.props!, oldPlan = plan.props!, prepared = await prepareTargetResumeAI(oldPlan.draft); if (!prepared.ok) throw new Error(prepared.code);
    const next = clone(oldPlan.draft); next.document.sections.find(section => section.kind === 'activities')!.blocks[0].included = false;
    act(() => oldPlan.onApply(prepared.value.canonical_draft, next, { kind: 'manual' }));
    expect(preview().queryByText('Art project')).toBeNull(); expect(screen.getByText('Unsaved local edits')).toBeVisible();
    expect(plan.props!.draft.base_snapshot).toEqual(doc.base_snapshot); expect(storage.save).not.toHaveBeenCalled();
    act(() => oldAI.onApply(prepared.value.canonical_draft, withName(doc, 'Late stale AI name'), { kind: 'manual' }));
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Alex 王');
  });
  it('rejects an old plan apply after explicit user editing', async () => {
    await createUI(); await waitFor(() => expect(plan.props?.enabled).toBe(true));
    const old = plan.props!, prepared = await prepareTargetResumeAI(old.draft); if (!prepared.ok) throw new Error(prepared.code);
    editName('Current hand edit');
    act(() => old.onApply(prepared.value.canonical_draft, withName(old.draft, 'Late plan text'), { kind: 'manual' }));
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Current hand edit'); expect(storage.save).not.toHaveBeenCalled();
  });
});


describe('plan and wording baselines remain separate', () => {
  it('rejects the old content plan after a wording edit is applied on the same original baseline', async () => {
    await createUI(); await waitFor(() => expect(plan.props?.enabled).toBe(true));
    const oldPlan = plan.props!, oldAI = ai.props!, prepared = await prepareTargetResumeAI(oldPlan.draft); if (!prepared.ok) throw new Error(prepared.code);
    act(() => oldAI.onApply(prepared.value.canonical_draft, withName(oldAI.draft, 'Accepted current edit'), { kind: 'manual' }));
    const latePlan = clone(oldPlan.draft); latePlan.document.sections.find(section => section.kind === 'activities')!.blocks[0].included = false;
    act(() => oldPlan.onApply(prepared.value.canonical_draft, latePlan, { kind: 'manual' }));
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Accepted current edit');
    expect(preview().getByText('Art project')).toBeVisible(); expect(storage.save).not.toHaveBeenCalled();
  });
});


describe('shared target authority refusal', () => {
  it.each(['plan', 'wording'] as const)('blocks both AI tools immediately after a %s refusal without blocking manual/save/export', async source => {
    const p = profile(), doc = await docFor(p), onClose = vi.fn(); storage.load.mockResolvedValue(loaded(doc));
    const view = renderModal(p, opportunity, { onClose }); await screen.findByRole('textbox', { name: 'Edit Full name' });
    await waitFor(() => expect(plan.props?.enabled && ai.props?.enabled).toBe(true));
    const oldPlan = plan.props!, oldAI = ai.props!, prepared = await prepareTargetResumeAI(oldPlan.draft); if (!prepared.ok) throw new Error(prepared.code);
    act(() => {
      (source === 'plan' ? oldPlan : oldAI).onAuthorityRefusal?.('target_changed');
      // Both callbacks run before React can render the disabled props.
      oldPlan.onApply(prepared.value.canonical_draft, withName(oldPlan.draft, 'Unsafe late plan'), { kind: 'manual' });
      oldAI.onApply(prepared.value.canonical_draft, withName(oldAI.draft, 'Unsafe late wording'), { kind: 'manual' });
    });
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Alex 王');
    expect(plan.props!.enabled).toBe(false); expect(ai.props!.enabled).toBe(false);
    expect(screen.getByText(/Both AI tools are paused/)).toBeVisible();
    const refresh = vi.fn().mockResolvedValue(true);
    view.rerender(<FullTargetResumeModal isOpen onClose={onClose} profile={p} opportunity={opportunity} profileRefresh={{ status: 'checking', refresh }} />);
    view.rerender(<FullTargetResumeModal isOpen onClose={onClose} profile={p} opportunity={opportunity} profileRefresh={{ status: 'ready', refresh }} />);
    expect(plan.props!.enabled).toBe(false); expect(ai.props!.enabled).toBe(false);
    editName('Preserved manual draft');
    storage.save.mockImplementationOnce(async (draft: TargetResumeV1) => ({ status: 'saved', value: loaded(draft, 2) }));
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' })); await screen.findByText('Saved version 2');
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Preserved manual draft');
    expect(screen.getByRole('button', { name: 'Export PDF' })).toBeEnabled(); expect(screen.getByRole('button', { name: 'Export Word' })).toBeEnabled();
    expect(plan.props!.enabled).toBe(false); expect(ai.props!.enabled).toBe(false);
    view.rerender(<FullTargetResumeModal isOpen={false} onClose={onClose} profile={p} opportunity={opportunity} />);
    view.rerender(<FullTargetResumeModal isOpen onClose={onClose} profile={p} opportunity={opportunity} />);
    await screen.findByRole('textbox', { name: 'Edit Full name' }); await waitFor(() => expect(plan.props?.enabled && ai.props?.enabled).toBe(true));
    expect(screen.queryByText(/Both AI tools are paused/)).toBeNull();
    // The previous workspace cannot re-block the fresh one or apply its draft.
    act(() => { oldPlan.onAuthorityRefusal?.('target_changed'); oldAI.onApply(prepared.value.canonical_draft, withName(oldAI.draft, 'Old workspace'), { kind: 'manual' }); });
    expect(plan.props!.enabled).toBe(true); expect(ai.props!.enabled).toBe(true); expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Alex 王');
  });
  it('removes the refusal marker on a real target change but still requires a draft based on the new target', async () => {
    const p = profile(), doc = await docFor(p); storage.load.mockResolvedValue(loaded(doc)); const view = renderModal(p);
    await screen.findByRole('textbox', { name: 'Edit Full name' }); await waitFor(() => expect(plan.props?.enabled).toBe(true));
    act(() => plan.props!.onAuthorityRefusal?.('TARGET_NOT_ACTIONABLE')); expect(screen.getByText(/Both AI tools are paused/)).toBeVisible();
    view.rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={{ ...opportunity, description_clean: 'Current new research requirements.' }} />);
    await waitFor(() => expect(screen.queryByText(/Both AI tools are paused/)).toBeNull());
    expect(plan.props!.enabled).toBe(false); expect(ai.props!.enabled).toBe(false);
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Alex 王');
  });
});

describe('saved operation records', () => {
  const experienceLine = (doc: TargetResumeV1) => doc.document.sections.flatMap(s => s.blocks.flatMap(b => b.lines)).find(l => l.role === 'experience')!;
  const recordLoaded = (doc: TargetResumeV1, provenance: TargetResumeProvenance | null, revision = 1): LoadedTargetResume => ({ ...loaded(doc, revision), provenance });
  async function checkedEdit(doc: TargetResumeV1, version = 'target-resume-source-checks-v1') {
    const prepared = await prepareTargetResumeAI(doc); if (!prepared.ok) throw new Error(prepared.code);
    const unit = prepared.value.units.find(item => item.evidence.kind === 'experience')!;
    const next = clone(doc); experienceLine(next).text = 'Measured robot trials without leading the team.';
    const action: TargetResumeProvenanceAction = { kind: 'ai_rewrite', annotations: [{ section_id: unit.section_id, block_id: unit.block_id, line_id: unit.unit_id, field: 'text', reason: 'Keep the stated contribution.', target_evidence: [], source_evidence: [],
      check: { version, pipeline_version: 'full-target-v2', request_id: 'controlled-request', document_signature: prepared.value.document_signature, original: unit.original, evidence: unit.evidence } }] };
    return { next, action, canonical: prepared.value.canonical_draft, provenance: appendTargetResumeProvenance(null, doc, next, action)! };
  }
  const saveEcho = () => storage.save.mockImplementationOnce(async (doc: TargetResumeV1, revision: number, _owner: unknown, provenance: TargetResumeProvenance | null) => ({ status: 'saved', value: recordLoaded(doc, provenance, revision + 1) }));
  // This build writes no generation record, so a V4 history is one that arrives from storage.
  const withGeneration = (record: TargetResumeProvenance, version: string | null) => {
    const value = clone(record), check = value.events[0].changes[0].check!; value.version = 4;
    if (version) value.events[0].generation = { version, pipeline_version: check.pipeline_version, document_signature: check.document_signature, request_ids: [check.request_id] };
    return value;
  };
  it('shows a saved generation record in history and restores it without taking the newer one', async () => {
    const p = profile(), original = await docFor(p), edit = await checkedEdit(original);
    const record = withGeneration(edit.provenance, 'target-resume-generation-v1:' + 'a'.repeat(64));
    record.events[0].generation!.request_ids.push('second-request');
    const current = withGeneration(edit.provenance, 'target-resume-generation-v1:' + 'b'.repeat(64));
    storage.load.mockResolvedValue(recordLoaded(edit.next, current, 4));
    storage.history.mockResolvedValue([{ revision: 2, updated_at: 'old' }]);
    storage.version.mockResolvedValue(recordLoaded(edit.next, record, 2));
    renderModal(p); await screen.findByRole('textbox', { name: 'Edit Full name' }); historyOpen();
    fireEvent.click(screen.getByRole('button', { name: 'Load latest 20 versions' }));
    fireEvent.click(await screen.findByRole('button', { name: 'View version 2 · old' }));
    await screen.findByRole('region', { name: 'Selected historical version preview' });
    fireEvent.click(screen.getByText('Historical change records'));
    const historical = screen.getByText('Historical change records').closest('details')!;
    fireEvent.click(within(historical).getByText('Generation details'));
    expect(within(historical).getByText('Configuration ID: target-resume-generation-v1:' + 'a'.repeat(64))).toBeVisible();
    expect(within(historical).getByText('Pipeline version: full-target-v2')).toBeVisible();
    expect(within(historical).getByText('Source draft signature: ' + record.events[0].generation!.document_signature)).toBeVisible();
    expect(within(historical).getByText('Request IDs: controlled-request, second-request')).toBeVisible();
    expect(historical.textContent).not.toContain('b'.repeat(64));
    saveEcho(); fireEvent.click(screen.getByRole('button', { name: 'Restore selected version as a new save' }));
    await screen.findByText('Saved version 5'); expect(storage.save.mock.calls[0][3]).toEqual(record);
  });
  it('shows a plan event\'s generation record in a V4 history, after the event\'s changes', async () => {
    const p = profile(), doc = await docFor(p), next = clone(doc);
    next.document.sections.flatMap(s => s.blocks).find(b => b.lines.some(l => l.text === 'Art project'))!.included = false;
    const record = clone(appendTargetResumeProvenance(null, doc, next, { kind: 'plan' })!); record.version = 4;
    record.events[0].generation = { version: 'target-resume-generation-v1:' + 'c'.repeat(64), pipeline_version: 'full-target-plan-v6',
      document_signature: 'v1:sha256:' + 'd'.repeat(64), request_ids: ['plan-request'] };
    storage.load.mockResolvedValue(recordLoaded(next, record)); renderModal(p);
    await screen.findByRole('textbox', { name: 'Edit Full name' }); fireEvent.click(screen.getByText('Change records'));
    const summary = screen.getByText('Generation details'); fireEvent.click(summary);
    expect(screen.getByText('Pipeline version: full-target-plan-v6')).toBeVisible(); expect(screen.getByText('Request IDs: plan-request')).toBeVisible();
    const change = screen.getByText(/^Accepted content choice · /);
    expect(change.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
  it('says a V4 AI change has an unknown generation configuration and keeps the history V4 through a later edit', async () => {
    const p = profile(), doc = await docFor(p), edit = await checkedEdit(doc), record = withGeneration(edit.provenance, null);
    storage.load.mockResolvedValue(recordLoaded(edit.next, record)); renderModal(p);
    await screen.findByRole('textbox', { name: 'Edit Full name' }); fireEvent.click(screen.getByText('Change records'));
    expect(screen.getByText('Generation configuration: unknown')).toBeVisible(); expect(screen.queryByText('Generation details')).toBeNull();
    editName('Later name'); saveEcho(); fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    await screen.findByText('Saved version 2');
    const saved = storage.save.mock.calls[0][3] as TargetResumeProvenance;
    expect(saved.version).toBe(4); expect(saved.events[0]).toEqual(record.events[0]); expect(saved.events[1].kind).toBe('manual');
    expect(screen.getAllByText('Generation configuration: unknown')).toHaveLength(1);
  });
  it('saves an accepted AI change with its generation record as V4', async () => {
    const p = profile(), doc = await docFor(p), edit = await checkedEdit(doc), check = edit.action.annotations![0].check!;
    const generation = { version: 'target-resume-generation-v1:' + 'a'.repeat(64), pipeline_version: check.pipeline_version,
      document_signature: check.document_signature, request_ids: [check.request_id] };
    storage.load.mockResolvedValue(loaded(doc)); renderModal(p); await waitFor(() => expect(ai.props?.enabled).toBe(true));
    act(() => ai.props!.onApply(edit.canonical, edit.next, { ...edit.action, generation }));
    fireEvent.click(screen.getByText('Change records')); fireEvent.click(screen.getByText('Generation details'));
    expect(screen.getByText('Request IDs: controlled-request')).toBeVisible();
    saveEcho(); fireEvent.click(screen.getByRole('button', { name: 'Save target draft' })); await screen.findByText('Saved version 2');
    const saved = storage.save.mock.calls[0][3] as TargetResumeProvenance;
    expect(saved.version).toBe(4); expect(saved.events[0].generation).toEqual(generation);
  });
  it.each([['en', 1], ['en', 3], ['en', 4], ['zh', 1], ['zh', 3], ['zh', 4]] as const)(
    'labels every AI and plan event without a generation record as unknown, and no manual event (%s, V%s history)', async (locale, version) => {
    i18n.locale = locale;
    const [records, unknown, details] = locale === 'zh' ? ['修改记录', '生成配置：未知', '生成记录'] : ['Change records', 'Generation configuration: unknown', 'Generation details'];
    const p = profile(), doc = await docFor(p), edit = await checkedEdit(doc), planned = clone(edit.next);
    planned.document.sections.flatMap(s => s.blocks).find(b => b.lines.some(l => l.text === 'Art project'))!.included = false;
    const typed = withName(planned, 'Later name');
    const record = clone(appendTargetResumeProvenance(appendTargetResumeProvenance(edit.provenance, edit.next, planned, { kind: 'plan' }), planned, typed, { kind: 'manual' })!);
    expect(record.version).toBe(3); expect(record.events.map(event => event.kind)).toEqual(['ai_rewrite', 'plan', 'manual']);
    record.version = version;
    if (version === 4) record.events[1].generation = { version: 'target-resume-generation-v1:' + 'c'.repeat(64), pipeline_version: 'full-target-plan-v6',
      document_signature: 'v1:sha256:' + 'd'.repeat(64), request_ids: ['plan-request'] };
    storage.load.mockResolvedValue(recordLoaded(typed, record)); renderModal(p);
    await screen.findByDisplayValue('Later name'); fireEvent.click(screen.getByText(records));
    expect(screen.getAllByText(unknown)).toHaveLength(version === 4 ? 1 : 2);
    if (version === 4) expect(screen.getByText(details)).toBeVisible(); else expect(screen.queryByText(details)).toBeNull();
  });
  it('shows legacy unknown and keeps a manual marker when text returns to the original', async () => {
    const p = profile(), doc = await docFor(p); storage.load.mockResolvedValue(loaded(doc)); renderModal(p); await screen.findByRole('textbox', { name: 'Edit Full name' });
    fireEvent.click(screen.getByText('Change records')); expect(screen.getByText(/Change source unknown/)).toBeVisible();
    editName('Changed once'); editName('Alex 王'); expect(screen.getByText('Unsaved local edits')).toBeVisible();
    saveEcho(); fireEvent.click(screen.getByRole('button', { name: 'Save target draft' })); await screen.findByText('Saved version 2');
    const record = storage.save.mock.calls[0][3] as TargetResumeProvenance;
    expect(record.events).toHaveLength(1); expect(record.events[0].kind).toBe('manual');
    expect(record.events[0].changes[0]).toMatchObject({ before: 'Alex 王', after: 'Alex 王', check: null });
  });
  it('shows an accepted check version and a later manual marker even after returning to the AI text', async () => {
    const p = profile(), doc = await docFor(p), edit = await checkedEdit(doc); storage.load.mockResolvedValue(loaded(doc)); renderModal(p); await waitFor(() => expect(ai.props?.enabled).toBe(true));
    act(() => ai.props!.onApply(edit.canonical, edit.next, edit.action));
    fireEvent.click(screen.getByText('Change records')); expect(screen.getByText('Reason: Keep the stated contribution.')).toBeVisible();
    expect(screen.getAllByText(/Recorded check version: target-resume-source-checks-v1/)).not.toHaveLength(0);
    const input = screen.getByRole('textbox', { name: 'Edit Experience detail' });
    fireEvent.change(input, { target: { value: 'Manual wording' } }); fireEvent.change(input, { target: { value: experienceLine(edit.next).text } });
    expect(screen.getByText(/Manual edit\. Earlier AI checks do not cover this manual wording/)).toBeVisible();
    saveEcho(); fireEvent.click(screen.getByRole('button', { name: 'Save target draft' })); await screen.findByText('Saved version 2');
    const record = storage.save.mock.calls[0][3] as TargetResumeProvenance;
    expect(record.events.map(item => item.kind)).toEqual(['ai_rewrite', 'manual']);
    expect(record.events[0].changes[0].check?.version).toBe('target-resume-source-checks-v1'); expect(record.events[1].changes[0].check).toBeNull();
  });
  it.each([['en', 'Change records', 'AI-linked text from the opportunity', 'Opportunity citation', 'Student original', 'Source citation'],
    ['zh', '修改记录', 'AI 关联的机会原文', '机会引用', '学生原文', '原文引用']] as const)(
    'records an accepted content choice\'s opportunity quote as text the AI linked, with the student\'s line under its own heading (%s)', async (locale, records, label, citation, student, source) => {
      // M133: the plan's quote is only checked to be in the opportunity's text; it can bear on nothing in the block.
      // Round 2: under the quote's heading alone, the student's own line read as opportunity text.
      i18n.locale = locale;
      const p = profile(), doc = await docFor(p); storage.load.mockResolvedValue(loaded(doc)); renderModal(p);
      await waitFor(() => expect(plan.props?.enabled).toBe(true));
      const prepared = await prepareTargetResumePlan(doc, { target_pages: 1 }); if (!prepared.ok) throw new Error(prepared.code);
      const block = doc.document.sections.flatMap(s => s.blocks.map(b => ({ s, b }))).find(({ b }) => b.lines.some(l => l.role === 'experience'))!;
      const line = block.b.lines.find(l => l.role === 'experience')!, quote = doc.target_snapshot.description;
      expect(quote).toBe('Work on robotics with Python.');
      const next = clone(doc); next.document.sections.find(s => s.id === block.s.id)!.blocks.find(b => b.id === block.b.id)!.included = false;
      const action: TargetResumeProvenanceAction = { kind: 'plan', annotations: [{ section_id: block.s.id, block_id: block.b.id, line_id: null, field: 'included',
        reason: 'Omit suggestion: Review the cited material before giving this block less space.', check: null,
        target_evidence: [{ field: 'description', requirement_index: null, start: 0, end: Array.from(quote).length, quote }],
        source_evidence: [{ unit_id: line.id, start: 0, end: Array.from(line.original).length, quote: line.original }] }] };
      act(() => plan.props!.onApply(prepared.value.canonical_draft, next, action));
      fireEvent.click(screen.getByText(records));
      const rows = [screen.getByText(label), screen.getByText(`${citation}: ${quote}`), screen.getByText(student), screen.getByText(`${source}: ${line.original}`)];
      for (const row of rows) expect(row).toBeVisible();
      for (let i = 1; i < rows.length; i += 1) expect(rows[i - 1].compareDocumentPosition(rows[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });
  it.each([['full-target-v5', true], ['full-target-v2', true], ['full-target-v6', false]] as const)(
    'says whether a saved line an AI step wrote under %s was fact-checked (flagged: %s)', async (pipeline, flagged) => {
      // Round-2 review (criteria 1 and 3): wording applied from a pre-v6 suggestion had no faithfulness review.
      const p = profile(), doc = await docFor(p), edit = await checkedEdit(doc);
      edit.action.annotations![0].check!.pipeline_version = pipeline;
      storage.load.mockResolvedValue(recordLoaded(edit.next, appendTargetResumeProvenance(null, doc, edit.next, edit.action)!));
      renderModal(p); await screen.findByRole('textbox', { name: 'Edit Experience detail' });
      expect(screen.queryByTestId('target-line-unreviewed') !== null).toBe(flagged);
      if (!flagged) return;
      fireEvent.click(screen.getByRole('button', { name: 'Restore original Experience detail' }));
      expect(screen.getByRole('textbox', { name: 'Edit Experience detail' })).toHaveValue(experienceLine(doc).text);
      expect(screen.queryByTestId('target-line-unreviewed')).toBeNull();
    });
  it.each([['no saved record', false], ['a record for other lines only', true]] as const)(
    'flags a changed line with %s as possibly written before review', async (_name, otherRecord) => {
      // Round-3 re-measure (criterion 1): a legacy draft's changed line with no change record was not flagged.
      const p = profile(), doc = await docFor(p), edit = await checkedEdit(doc);
      const named = withName(edit.next, 'Alex Wang');
      const provenance = otherRecord ? appendTargetResumeProvenance(null, edit.next, named, { kind: 'manual' })! : null;
      storage.load.mockResolvedValue(recordLoaded(otherRecord ? named : edit.next, provenance));
      renderModal(p); await screen.findByRole('textbox', { name: 'Edit Experience detail' });
      expect(screen.getAllByTestId('target-line-unreviewed')).toHaveLength(1);
      expect(screen.getByTestId('target-line-unreviewed')).toHaveTextContent(/no change record says who wrote this wording/);
      fireEvent.click(screen.getByRole('button', { name: 'Restore original Experience detail' }));
      expect(screen.getByRole('textbox', { name: 'Edit Experience detail' })).toHaveValue(experienceLine(doc).text);
      expect(screen.queryByTestId('target-line-unreviewed')).toBeNull();
    });
  it('does not flag an unchanged line that has no change record', async () => {
    const p = profile(), doc = await docFor(p); storage.load.mockResolvedValue(recordLoaded(doc, null));
    renderModal(p); await screen.findByRole('textbox', { name: 'Edit Experience detail' });
    expect(screen.queryByTestId('target-line-unreviewed')).toBeNull();
  });
  it('keeps submitted and later manual records apart while saving', async () => {
    const p = profile(), doc = await docFor(p); storage.load.mockResolvedValue(loaded(doc)); renderModal(p); await screen.findByRole('textbox', { name: 'Edit Full name' });
    editName('Submitted name'); const pending = deferred<TargetResumeSaveResult>(); storage.save.mockReturnValueOnce(pending.promise); fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    const submitted = clone(storage.save.mock.calls[0][0]) as TargetResumeV1, record = clone(storage.save.mock.calls[0][3]) as TargetResumeProvenance;
    editName('Later local name'); await act(async () => pending.resolve({ status: 'saved', value: recordLoaded(submitted, record, 2) }));
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Later local name'); expect(screen.getByText('Unsaved local edits')).toBeVisible(); expect(record.events[0].changes[0].after).toBe('Submitted name');
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' })); expect(storage.save.mock.calls[1][1]).toBe(2); expect(storage.save.mock.calls[1][3].events[0].changes[0].after).toBe('Later local name');
  });
  it.each([true, false])('restores historical metadata unchanged, present=%s', async present => {
    const p = profile(), original = await docFor(p), edit = await checkedEdit(original, 'older-checks-v0'), record = present ? edit.provenance : null;
    storage.load.mockResolvedValue(loaded(original, 4)); storage.history.mockResolvedValue([{ revision: 2, updated_at: 'old' }]); storage.version.mockResolvedValue(recordLoaded(edit.next, record, 2)); renderModal(p); await screen.findByRole('textbox', { name: 'Edit Full name' }); editName('Before restore'); historyOpen();
    fireEvent.click(screen.getByRole('button', { name: 'Load latest 20 versions' })); await screen.findByRole('button', { name: 'View version 2 · old' }); fireEvent.click(screen.getByRole('button', { name: 'View version 2 · old' })); await screen.findByRole('region', { name: 'Selected historical version preview' });
    fireEvent.click(screen.getByText('Historical change records')); expect(screen.getByText(present ? 'Recorded check version: older-checks-v0' : 'Change source unknown. This version has no saved operation record.')).toBeVisible();
    saveEcho(); fireEvent.click(screen.getByRole('button', { name: 'Restore selected version as a new save' })); await screen.findByText('Saved version 5');
    expect(storage.save.mock.calls[0][3]).toEqual(record); expect(storage.save.mock.calls[0][0]).toEqual(edit.next); expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Alex 王');
  });
  it('preserves oversized manual input and blocks saving and AI until explicit reload', async () => {
    const p = profile(), doc = await docFor(p); storage.load.mockResolvedValue(loaded(doc)); renderModal(p); await waitFor(() => expect(ai.props?.enabled).toBe(true));
    const huge = 'x'.repeat(270_000); editName(huge); expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue(huge);
    expect(screen.getByText(/full draft is kept, but its change record/)).toBeVisible(); expect(screen.getByRole('button', { name: 'Save target draft' })).toBeDisabled(); expect(ai.props?.enabled).toBe(false); expect(plan.props?.enabled).toBe(false);
    expect(screen.getByRole('button', { name: 'Export PDF' })).toBeEnabled(); expect(screen.getByRole('button', { name: 'Export Word' })).toBeEnabled();
    editName('Short but still unrecorded'); expect(screen.getByRole('button', { name: 'Save target draft' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Discard local changes and reload saved version' })); await waitFor(() => expect(ai.props?.enabled).toBe(true));
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Alex 王'); expect(screen.queryByText(/full draft is kept, but its change record/)).toBeNull(); expect(storage.save).not.toHaveBeenCalled();
  });
  it.each(['ai', 'plan'] as const)('keeps the valid current draft saveable when a %s acceptance record exceeds capacity', async panel => {
    const p = profile(), doc = await docFor(p); storage.load.mockResolvedValue(loaded(doc)); renderModal(p); await waitFor(() => expect(ai.props?.enabled).toBe(true));
    editName('My existing manual name'); const edit = await checkedEdit(ai.props!.draft); edit.action.annotations![0].reason = 'r'.repeat(270_000);
    if (panel === 'plan') edit.action.kind = 'plan';
    act(() => (panel === 'plan' ? plan.props! : ai.props!).onApply(edit.canonical, edit.next, edit.action));
    expect(screen.getByText(/suggestion was not applied because its change record/)).toBeVisible(); expect(screen.queryByText(/full draft is kept, but its change record/)).toBeNull();
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('My existing manual name'); expect(screen.getByRole('textbox', { name: 'Edit Experience detail' })).toHaveValue(experienceLine(doc).text);
    expect(screen.getByRole('button', { name: 'Save target draft' })).toBeEnabled(); expect(ai.props?.enabled).toBe(true); expect(plan.props?.enabled).toBe(true);
    saveEcho(); fireEvent.click(screen.getByRole('button', { name: 'Save target draft' })); await screen.findByText('Saved version 2');
    expect((storage.save.mock.calls[0][3] as TargetResumeProvenance).events.map(item => item.kind)).toEqual(['manual']);
  });
  it('shows readable order names and records deterministic order separately from AI checks', async () => {
    const p = profile(), doc = await docFor(p); storage.load.mockResolvedValue(loaded(doc)); renderModal(p); await screen.findByRole('textbox', { name: 'Edit Full name' });
    fireEvent.click(screen.getByRole('button', { name: 'Suggest order of whole blocks' })); fireEvent.click(screen.getByText('Change records'));
    const details = screen.getByText('Change records').closest('details')!;
    expect(within(details).getByText('Before: Art project → Python robotics project')).toBeVisible(); expect(within(details).getByText('After: Python robotics project → Art project')).toBeVisible();
    expect(details.textContent).not.toContain('robotics → art'); expect(details.textContent).not.toContain('Recorded check version');
    saveEcho(); fireEvent.click(screen.getByRole('button', { name: 'Save target draft' })); await screen.findByText('Saved version 2');
    const record = storage.save.mock.calls[0][3] as TargetResumeProvenance;
    expect(record.events[0].kind).toBe('target_order'); expect(record.events[0].changes.every(change => change.field === 'order' && change.check === null)).toBe(true);
  });
  it('refuses AI content without operation metadata', async () => {
    const p = profile(), doc = await docFor(p); storage.load.mockResolvedValue(loaded(doc)); renderModal(p); await waitFor(() => expect(ai.props?.enabled).toBe(true)); const prepared = await prepareTargetResumeAI(doc); if (!prepared.ok) throw new Error(prepared.code);
    act(() => ai.props!.onApply(prepared.value.canonical_draft, withName(doc, 'Unrecorded overwrite'), undefined as unknown as TargetResumeProvenanceAction));
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Alex 王'); expect(screen.getByText('Saved version 1')).toBeVisible();
  });
});


describe('resume read retirement and retry', () => {
  it('shows a timed-out read as retryable, keeps side-panel answers, and aborts the retired attempt', async () => {
    storage.load.mockRejectedValueOnce({ code: 'timeout' });
    const result = renderModal();
    await screen.findByText('Reading the saved résumé took too long. Nothing was replaced; try reading it again.');
    const firstSignal = storage.load.mock.calls[0][2].signal as AbortSignal;
    fireEvent.click(screen.getByRole('button', { name: 'Add experience details' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Supplement test answer' }), { target: { value: 'Keep this unfinished contribution' } });
    fireEvent.click(screen.getByRole('button', { name: 'Retry reading saved résumé' }));
    await waitFor(() => expect(storage.load).toHaveBeenCalledTimes(2));
    expect(firstSignal.aborted).toBe(true);
    expect(screen.getByRole('textbox', { name: 'Supplement test answer' })).toHaveValue('Keep this unfinished contribution');
    result.unmount(); expect((storage.load.mock.calls[1][2].signal as AbortSignal).aborted).toBe(true);
  });
  it('aborts an old target read and ignores its later result after a new target is editable', async () => {
    const p=profile(); const old=await docFor(p); const pending=deferred<LoadedTargetResume|null>();
    storage.load.mockReturnValueOnce(pending.promise);
    const mounted=renderModal(p); await waitFor(()=>expect(storage.load).toHaveBeenCalledOnce());
    const signal=storage.load.mock.calls[0][2].signal as AbortSignal;
    const target={...opportunity,id:'other-target'}; const next=await docFor(p,target);
    storage.load.mockResolvedValueOnce(loaded(next));
    mounted.rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={target}/>);
    await screen.findByRole('textbox',{name:'Edit Full name'});editName('Keep newer edit');expect(signal.aborted).toBe(true);
    await act(async()=>pending.resolve(loaded(withName(old,'Late old owner material'))));
    expect(screen.getByRole('textbox',{name:'Edit Full name'})).toHaveValue('Keep newer edit');expect(storage.save).not.toHaveBeenCalled();
  });
});
