import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { advanceOwnerEpoch, captureOwnerToken, isLocalOwnerReady, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { createEmptyResumeMaster } from '@/lib/resume-master';
import { prepareConfirmedSupplement } from '@/lib/resume-supplement';
import { readResumeSupplementDraft, resumeSupplementEditorLock, writeResumeSupplementDraft } from '@/lib/resume-supplement-draft';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import type { Opportunity, ProfileData } from '@/lib/types';
import { DEFAULT_PROFILE } from '@/app/home/types';
import type { ResumeSupplementOptions, useResumeSupplement } from './use-resume-supplement';
import FullTargetResumeModal from './FullTargetResumeModal';

vi.mock('@/lib/target-resume-storage', () => ({
  loadTargetResume: vi.fn().mockResolvedValue(null), saveTargetResume: vi.fn(),
  loadTargetResumeHistory: vi.fn().mockResolvedValue([]), loadTargetResumeVersion: vi.fn().mockResolvedValue(null),
}));
vi.mock('./ResumeExperienceAssignmentPanel', () => ({ default: () => null }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/i18n/client', () => ({ useLocale: () => 'en' }));
const supplement = vi.hoisted(() => ({ controller: null as unknown, options: null as unknown }));
vi.mock('./use-resume-supplement', () => ({ useResumeSupplement: (options: unknown) => { supplement.options = options; return supplement.controller; } }));

type Controller = ReturnType<typeof useResumeSupplement>;
const controller = () => supplement.controller as Controller;
const master = createEmptyResumeMaster('recovery-master');
master.activities = [{ id: 'project-one', kind: 'project', title: { id: 'title', revision: 1, status: 'confirmed', value: 'Sensor project', source: { kind: 'manual' } }, details: [] }];
const profile: ProfileData = { ...DEFAULT_PROFILE, resume_master: master, experience_entries: [] };
const opportunityFor = (id: string): Opportunity => ({
  id, title: 'Robotics research', organization: 'Example Lab', opportunity_type: 'research', paid: 'unknown', location: 'Example campus', on_campus: true,
  description_clean: 'Work on robotics with Python.', keywords: ['robotics'], source_url: 'https://example.test/lab',
  eligibility: { international_friendly: 'unknown', preferred_year: [], majors: [], skills_required: ['Python'], citizenship_required: null },
  application: { application_effort: 'low', requires_resume: 'yes', contact_method: 'email' }, metadata: { is_active: true, confidence_score: 1 },
});
const opportunity = opportunityFor('opportunity-one');
const TASK = 'Exact unsubmitted task 王';

async function useOwner(uid: string) {
  advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  await waitFor(() => expect(isLocalOwnerReady(uid)).toBe(true));
  const token = captureOwnerToken();
  const view = { viewId: 'fresh-view', baseProfile: profile, renderedProfile: profile, revision: 1, token, identityGeneration: token.epoch, source: 'hydration' as const };
  supplement.controller = { view, acceptedView: view, phase: 'ready', error: null, ownerScopeKey: 'scope', operationLocked: false, confirmedEntryId: null,
    acceptCurrent: vi.fn().mockResolvedValue(undefined), assign: vi.fn(), confirm: vi.fn(), retryRecorded: vi.fn(),
    baseline: vi.fn((activityId: string) => ({ view, activityId, targetKey: (supplement.options as ResumeSupplementOptions).targetKey })) } satisfies Controller;
}
function mount(target = opportunity) {
  const onClose = vi.fn();
  return { ...render(<FullTargetResumeModal isOpen onClose={onClose} profile={profile} opportunity={target} />), onClose };
}
const task = () => screen.getByLabelText('What was the task?');
const method = () => screen.getByLabelText('What methods or tools did you use?');
const accuracy = () => screen.getByLabelText(/(?:I confirm the selected information|I reviewed the current activity and profile, and confirm the selected information) is accurate\./);
async function openSupplement() {
  const toggle = screen.getByRole('button', { name: 'Add experience details' });
  await waitFor(() => expect(toggle).toBeEnabled()); fireEvent.click(toggle);
  await screen.findByLabelText('What was the task?');
}
function answer() {
  fireEvent.change(screen.getByRole('combobox', { name: 'Project or experience in your master résumé' }), { target: { value: 'project-one' } });
  fireEvent.change(task(), { target: { value: TASK } }); fireEvent.change(method(), { target: { value: 'Unselected private method' } });
  fireEvent.click(screen.getByLabelText('Include task'));
}
const storedKeys = () => Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index) ?? '').filter(key => key.includes(STORAGE_KEYS.RESUME_SUPPLEMENT_DRAFT_PREFIX));

let ownerNumber = 0;
beforeEach(async () => {
  vi.stubGlobal('crypto', webcrypto); localStorage.clear(); await useOwner('resume-supplement-owner-' + ++ownerNumber);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

// Real modal, supplement panel, owner authority and user-scoped storage.
// Only the profile controller and the saved target document are faked.
describe('target résumé unfinished supplement answers', () => {
  it('restores answers and selections after closing and reopening, without restoring the confirmation', async () => {
    const view = mount(); await openSupplement(); answer();
    expect(screen.getByText(/Unsubmitted answers are kept only in this browser, for this opportunity/)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Close target résumé' }));
    // Answers kept in this browser are not lost by closing, so no discard warning.
    expect(view.onClose).toHaveBeenCalledOnce(); expect(screen.queryByRole('alert')).toBeNull();
    view.unmount();
    mount();
    await waitFor(() => expect(task()).toHaveValue(TASK));
    expect(method()).toHaveValue('Unselected private method'); expect(screen.getByLabelText('Include task')).toBeChecked();
    expect(screen.getByRole('combobox', { name: 'Project or experience in your master résumé' })).toHaveValue('project-one');
    expect(screen.getByTestId('supplement-recovery-review')).toHaveTextContent('Your unfinished answers were restored from this browser.');
    expect(accuracy()).not.toBeChecked(); expect(controller().confirm).not.toHaveBeenCalled();
  });
  it('starts empty for another opportunity or another owner, and an owner change removes the stored answers', async () => {
    const view = mount(); await openSupplement(); answer(); view.unmount();
    expect(storedKeys()).toHaveLength(1);
    const other = mount(opportunityFor('opportunity-two')); await act(async () => {});
    expect(screen.queryByLabelText('What was the task?')).toBeNull();
    await openSupplement(); expect(task()).toHaveValue(''); expect(screen.queryByTestId('supplement-recovery-review')).toBeNull(); other.unmount();
    await useOwner('different-resume-supplement-owner');
    expect(storedKeys()).toEqual([]);
    mount(); await act(async () => {}); await openSupplement(); expect(task()).toHaveValue('');
  });
  it('removes the stored answers once a confirmed save records them', async () => {
    mount(); await openSupplement(); answer(); await act(async () => {});
    expect(readResumeSupplementDraft(captureOwnerToken(), opportunity.id)?.draft.answers.task).toBe(TASK);
    vi.mocked(controller().confirm).mockImplementation(async (draft) => {
      supplement.controller = { ...controller(), phase: 'saved', confirmedEntryId: draft.entryId };
      return { durable: true };
    });
    fireEvent.click(accuracy()); fireEvent.click(screen.getByRole('button', { name: 'Confirm and add to my master résumé' }));
    await screen.findByRole('button', { name: 'Added to master résumé' });
    expect(controller().confirm).toHaveBeenCalledOnce();
    expect(readResumeSupplementDraft(captureOwnerToken(), opportunity.id)).toBeNull(); expect(storedKeys()).toEqual([]);
  });
  it('removes the stored answers when recovered answers are explicitly discarded', async () => {
    const view = mount(); await openSupplement(); answer(); view.unmount(); mount();
    await waitFor(() => expect(task()).toHaveValue(TASK));
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: 'Discard recovered answers and start again' }));
    await waitFor(() => expect(task()).toHaveValue(''));
    expect(window.confirm).toHaveBeenCalledWith('Discard these recovered answers and start a new supplement? Your target résumé draft will be kept.');
    expect(storedKeys()).toEqual([]);
  });
  it('keeps each live editor on its own round, and both confirmations add separate entries', async () => {
    let server = profile; const results: boolean[] = [];
    vi.mocked(controller().confirm).mockImplementation(async (draft) => {
      const prepared = prepareConfirmedSupplement(server, draft); results.push(prepared.ok);
      if (prepared.ok) server = prepared.desired;
      return { durable: prepared.ok };
    });
    const first = mount(); const one = within(first.container);
    fireEvent.click(await one.findByRole('button', { name: 'Add experience details' }));
    fireEvent.change(one.getByRole('combobox', { name: 'Project or experience in your master résumé' }), { target: { value: 'project-one' } });
    fireEvent.change(one.getByLabelText('What was the task?'), { target: { value: 'First tab task' } }); fireEvent.click(one.getByLabelText('Include task'));
    const second = mount(); const two = within(second.container); await act(async () => {});
    // The first editor is still open, so its round is not offered to the second.
    expect(two.queryByLabelText('What was the task?')).toBeNull(); expect(two.queryByTestId('supplement-recovery-review')).toBeNull();
    const toggle = two.getByRole('button', { name: 'Add experience details' }); await waitFor(() => expect(toggle).toBeEnabled()); fireEvent.click(toggle);
    expect(two.getByLabelText('What was the task?')).toHaveValue(''); expect(two.queryByTestId('supplement-recovery-review')).toBeNull();
    fireEvent.change(two.getByRole('combobox', { name: 'Project or experience in your master résumé' }), { target: { value: 'project-one' } });
    fireEvent.change(two.getByLabelText('What was the task?'), { target: { value: 'Second tab task' } }); fireEvent.click(two.getByLabelText('Include task'));
    // The second editor's copy replaced the first's, so closing the first warns before its answers are lost.
    fireEvent.click(one.getByRole('button', { name: 'Close target résumé' }));
    expect(first.onClose).not.toHaveBeenCalled(); fireEvent.click(one.getByRole('button', { name: 'Keep editing' }));
    for (const scope of [two, one]) {
      fireEvent.click(scope.getByLabelText('I confirm the selected information is accurate.'));
      fireEvent.click(scope.getByRole('button', { name: 'Confirm and add to my master résumé' })); await act(async () => {});
    }
    const ids = vi.mocked(controller().confirm).mock.calls.map(([draft]) => draft.entryId);
    expect(ids).toHaveLength(2); expect(new Set(ids).size).toBe(2); expect(results).toEqual([true, true]);
    expect(server.experience_entries?.map(entry => entry.text)).toEqual([expect.stringContaining('Second tab task'), expect.stringContaining('First tab task')]);
  });
  it('restores a copy whose editor crashed (lock released) but not one whose editor still holds its lock', async () => {
    const answers = { task: TASK, method: '', personalRole: '', outcome: '', outcomeBasis: '' };
    writeResumeSupplementDraft(captureOwnerToken(), opportunity.id, 'crashed-editor', { version: 1, opportunityId: opportunity.id, targetKey: 'old target', entryId: 'kept-entry', activityId: 'project-one', answers, selected: ['task'] });
    const held: { name: string }[] = [{ name: resumeSupplementEditorLock('crashed-editor') }];
    // The shared test LockManager has no query(); add one for this test only.
    const locks = navigator.locks as unknown as { query?: () => Promise<{ held: { name: string }[]; pending: [] }> };
    locks.query = async () => ({ held, pending: [] });
    try {
      const live = mount(); await act(async () => {}); await act(async () => {});
      expect(screen.queryByLabelText('What was the task?')).toBeNull(); live.unmount();
      held.length = 0; mount();
      await waitFor(() => expect(task()).toHaveValue(TASK)); expect(screen.getByTestId('supplement-recovery-review')).toBeVisible();
    } finally { delete locks.query; }
  });
  it('discarding at the leave prompt removes kept answers, so an older copy does not come back', async () => {
    const view = mount(); await openSupplement(); answer(); await act(async () => {});
    // Answers too large to keep leave the older copy and ask before leaving.
    fireEvent.change(task(), { target: { value: 'x'.repeat(70_000) } });
    fireEvent.click(screen.getByRole('button', { name: 'Close target résumé' }));
    expect(view.onClose).not.toHaveBeenCalled(); expect(storedKeys()).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Discard unsaved edits and continue' }));
    expect(view.onClose).toHaveBeenCalledOnce(); expect(storedKeys()).toEqual([]);
    view.unmount(); mount(); await act(async () => {});
    expect(screen.queryByLabelText('What was the task?')).toBeNull();
  });
});
