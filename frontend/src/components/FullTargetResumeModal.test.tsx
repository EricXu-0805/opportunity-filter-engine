import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as contract from '@/lib/target-resume';
import { createEmptyResumeMaster } from '@/lib/resume-master';
import { advanceOwnerEpoch, captureOwnerToken, isLocalOwnerReady, syncLocalIdentityOwner } from '@/lib/identity-owner';
import type { ProfileViewSnapshot } from '@/lib/profile-sync';
import type { ProfileActionReceipt } from '@/lib/use-profile-refresh';
import { prepareTargetResumeAI } from '@/lib/target-resume-ai';
import type { TargetResumeAiPanelProps } from './TargetResumeAiPanel';
import type { ResumeSupplementPanelProps } from './ResumeSupplementPanel';
import type { Opportunity, ProfileData, ResumeFact } from '@/lib/types';
import type { LoadedTargetResume, TargetResumeSaveResult, TargetResumeV1 } from '@/lib/target-resume';
import { DEFAULT_PROFILE } from '@/app/home/types';
import FullTargetResumeModal from './FullTargetResumeModal';

const storage = vi.hoisted(() => ({ load: vi.fn(), save: vi.fn(), history: vi.fn(), version: vi.fn() }));
vi.mock('@/lib/target-resume-storage', () => ({
  loadTargetResume: (...args: unknown[]) => storage.load(...args), saveTargetResume: (...args: unknown[]) => storage.save(...args),
  loadTargetResumeHistory: (...args: unknown[]) => storage.history(...args), loadTargetResumeVersion: (...args: unknown[]) => storage.version(...args),
}));
vi.mock('@/i18n/client', () => ({ useLocale: () => 'en' }));
const supplement = vi.hoisted(() => ({ props: null as ResumeSupplementPanelProps | null, push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: supplement.push }) }));
vi.mock('./ResumeSupplementPanel', () => ({ default: (props: ResumeSupplementPanelProps) => {
  supplement.props = props;
  return <div><label>Supplement test answer<textarea aria-label="Supplement test answer" onChange={(event) => props.onDirtyChange?.(!!event.target.value)} /></label>
    <button onClick={props.onOpenProfile}>Review master from supplement</button></div>;
} }));

const ai = vi.hoisted(() => ({ props: null as TargetResumeAiPanelProps | null }));
vi.mock('./TargetResumeAiPanel', () => ({ default: (props: TargetResumeAiPanelProps) => {
  ai.props = props;
  return <button onClick={() => props.onDirtyChange?.(true)}>AI suggestions awaiting review</button>;
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
  ai.props = null; supplement.props = null; supplement.push.mockReset();
  storage.load.mockReset().mockResolvedValue(null); storage.save.mockReset().mockResolvedValue({ status: 'failed' });
  storage.history.mockReset().mockResolvedValue([]); storage.version.mockReset().mockResolvedValue(null);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

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
  it('keeps focus through multi-character typing and preserves edits made while a save is pending', async () => {
    const user = userEvent.setup(); await createUI();
    const input = screen.getByRole('textbox', { name: 'Edit Full name' });
    await user.click(input); await user.type(input, ' - edited in full');
    expect(input).toHaveFocus(); expect(input).toHaveValue('Alex 王 - edited in full');
    const pending = deferred<TargetResumeSaveResult>(); storage.save.mockReturnValueOnce(pending.promise);
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    expect(storage.save).toHaveBeenCalledWith(expect.anything(), 0, captureOwnerToken());
    const submitted = clone(storage.save.mock.calls[0][0]) as TargetResumeV1;
    await user.click(input); await user.type(input, ' plus later');
    await act(async () => pending.resolve({ status: 'saved', value: loaded(submitted, 1) }));
    expect(input).toHaveValue('Alex 王 - edited in full plus later');
    expect(screen.getByText('Unsaved local edits')).toBeVisible();
    storage.save.mockImplementationOnce(async (doc: TargetResumeV1) => ({ status: 'saved', value: loaded(doc, 2) }));
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    await screen.findByText('Saved version 2'); expect(storage.save.mock.calls[1][1]).toBe(1);
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
    expect(storage.history.mock.calls[2]).toEqual([opportunity.id, captureOwnerToken(), 11]);
    expect(screen.queryByRole('button', { name: 'Load older versions' })).toBeNull(); expect(storage.version).not.toHaveBeenCalled();
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
    expect(storage.save.mock.calls[0]).toEqual([oldTwo.doc, 3, captureOwnerToken()]);
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
    act(() => ai.props!.onApply(prepared.value.canonical_draft, next));
    expect(preview().getByText('Reviewed robot trials; did not lead the team.')).toBeVisible();
    expect(storage.save).not.toHaveBeenCalled();
    storage.save.mockImplementationOnce(async (draft: TargetResumeV1) => ({ status: 'saved', value: loaded(draft, 1) }));
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' })); await screen.findByText('Saved version 1');
    expect(storage.save.mock.calls[0][0].base_snapshot).toEqual(before.base_snapshot);
  });
  it('refuses an old apply callback after later manual edits', async () => {
    await createUI(); const old = ai.props!; const prepared = await prepareTargetResumeAI(old.draft); if (!prepared.ok) throw new Error(prepared.code);
    editName('Keep my later edit'); const next = withName(old.draft, 'Stale change');
    act(() => old.onApply(prepared.value.canonical_draft, next));
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
    act(() => old.onApply(prepared.value.canonical_draft, withName(old.draft, 'Late AI overwrite')));
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
  act(() => oldAi.onApply(prepared.value.canonical_draft, withName(oldAi.draft, 'Late deleted profile AI')));
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
