import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProfileViewSnapshot } from '@/lib/profile-sync';
import type { OwnerToken } from '@/lib/identity-owner';
import { createEmptyResumeMaster } from '@/lib/resume-master';
import type { ResumeFact } from '@/lib/types';
import { DEFAULT_PROFILE } from '@/app/home/types';
import type { ResumeSupplementOptions, useResumeSupplement } from './use-resume-supplement';
import ResumeSupplementPanel, { type ResumeSupplementPanelProps } from './ResumeSupplementPanel';

const mocked = vi.hoisted(() => ({ controller: null as unknown, options: null as unknown, locale: 'en' }));
vi.mock('./use-resume-supplement', () => ({ useResumeSupplement: (options: unknown) => { mocked.options = options; return mocked.controller; } }));
vi.mock('@/i18n/client', () => ({ useLocale: () => mocked.locale }));
type Controller = ReturnType<typeof useResumeSupplement>;
const owner: OwnerToken = { uid: 'panel-owner-a', epoch: 4, generation: 0 };
const fact = (id: string, value: string): ResumeFact => ({ id, value, revision: 1, status: 'confirmed', source: { kind: 'manual' } });
function view(token = owner): ProfileViewSnapshot {
  const master = createEmptyResumeMaster('master-one');
  master.activities = [
    { id: 'project-one', kind: 'project', title: fact('title-one', 'Sensor project'), details: [{ id: 'old-entry', revision: 2 }] },
    { id: 'project-two', kind: 'research', title: fact('title-two', 'Literature study'), details: [] },
  ];
  const profile = { ...DEFAULT_PROFILE, resume_master: master, experience_entries: [{ id: 'old-entry', revision: 2,
    status: 'confirmed' as const, text: 'Existing full source; I did not lead the team.', source: { kind: 'manual' as const } }] };
  return { viewId: 'view-one', baseProfile: profile, renderedProfile: profile, revision: 1, token,
    identityGeneration: token.epoch, source: 'hydration' };
}
function controller(overrides: Partial<Controller> = {}): Controller {
  return { view: view(), acceptedView: view(), phase: 'ready', error: null, ownerScopeKey: 'owner-a', operationLocked: false,
    confirmedEntryId: null, acceptCurrent: vi.fn().mockResolvedValue(undefined), confirm: vi.fn().mockResolvedValue({ durable: false, reason: 'record-failed' }),
    retryRecorded: vi.fn().mockResolvedValue({ status: 'error', message: 'unavailable' }),
    baseline: vi.fn((activityId: string) => ({ view: current().view!, activityId, targetKey: (mocked.options as ResumeSupplementOptions).targetKey })), ...overrides };
}
function current(): Controller { return mocked.controller as Controller; }
function mount(props: Partial<ResumeSupplementPanelProps> = {}) {
  const full = { owner, targetKey: 'target-one-v1', ...props };
  return { ...render(<ResumeSupplementPanel {...full} />), props: full };
}
const task = () => screen.getByRole('textbox', { name: 'What was the task?' });
const confirm = () => screen.getByRole('checkbox', { name: 'I confirm the selected information is accurate.' });
const submit = () => screen.getByRole('button', { name: 'Confirm and add to my master résumé' });
function fill(value = 'I helped test the sensor; I did not lead the project.') {
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'project-one' } });
  fireEvent.change(task(), { target: { value } });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Include task' }));
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((yes) => { resolve = yes; }); return { promise, resolve }; }
beforeEach(() => { vi.stubGlobal('crypto', webcrypto); mocked.locale = 'en'; mocked.controller = controller(); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('resume supplement panel', () => {
  it('only submits explicitly selected complete answers after the user confirms accuracy, with optional outcome left empty', async () => {
    const onDirtyChange = vi.fn(); const onAcceptedProfile = vi.fn();
    mount({ onDirtyChange, onAcceptedProfile });
    const text = '  Tested C++ sensors.\nI helped; I did not lead or measure an outcome.  ';
    fill(text);
    fireEvent.change(screen.getByRole('textbox', { name: 'What methods or tools did you use?' }), { target: { value: 'Unselected private draft' } });
    const preview = within(screen.getByRole('region', { name: 'Information to confirm' }));
    expect(preview.getByText((_, element) => element?.tagName === 'PRE' && element.textContent === `Task: ${text}`)).toBeInTheDocument();
    expect(preview.queryByText('Unselected private draft')).toBeNull();
    expect(submit()).toBeDisabled(); expect(current().confirm).not.toHaveBeenCalled();
    fireEvent.click(confirm()); fireEvent.click(submit());
    await waitFor(() => expect(current().confirm).toHaveBeenCalledTimes(1));
    const [draft, baseline] = vi.mocked(current().confirm).mock.calls[0];
    expect(draft).toMatchObject({ activityId: 'project-one', selected: ['task'], answers: { task: text, outcome: '', outcomeBasis: '' } });
    expect(draft.entryId).toEqual(expect.any(String)); expect(baseline.view).toBe(current().view);
    expect(onDirtyChange).toHaveBeenLastCalledWith(true); expect(onAcceptedProfile).not.toHaveBeenCalled();
    expect((mocked.options as ResumeSupplementOptions).onAcceptedProfile).toBe(onAcceptedProfile);
  });

  it('keeps the same entry identity across retry, prevents double submission and requires re-confirmation after edits', async () => {
    const pending = deferred<Awaited<ReturnType<Controller['confirm']>>>();
    vi.mocked(current().confirm).mockReturnValueOnce(pending.promise);
    mount(); fill(); fireEvent.click(confirm()); fireEvent.click(submit()); fireEvent.click(submit());
    expect(current().confirm).toHaveBeenCalledTimes(1);
    const originalId = vi.mocked(current().confirm).mock.calls[0][0].entryId;
    await act(async () => pending.resolve({ durable: false, reason: 'record-failed' }));
    fireEvent.change(task(), { target: { value: 'Rechecked original task, without invented numbers.' } });
    expect(confirm()).not.toBeChecked(); expect(submit()).toBeDisabled();
    fireEvent.click(confirm()); fireEvent.click(submit());
    await waitFor(() => expect(current().confirm).toHaveBeenCalledTimes(2));
    expect(vi.mocked(current().confirm).mock.calls[1][0].entryId).toBe(originalId);
    expect(vi.mocked(current().confirm).mock.calls[1][0].answers.task).toContain('without invented numbers');
  });

  it('keeps focus while typing and clears the truth confirmation after changing activity or selected fields', async () => {
    mount(); fill(); fireEvent.click(confirm());
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'project-two' } });
    expect(confirm()).not.toBeChecked();
    fireEvent.click(confirm()); fireEvent.click(screen.getByRole('checkbox', { name: 'Include method' }));
    expect(confirm()).not.toBeChecked();
    const input = task(); const user = userEvent.setup(); await user.clear(input); await user.type(input, 'Continuous detail text');
    expect(input).toHaveFocus(); expect(input).toHaveValue('Continuous detail text');
  });

  it('shows complete over-limit text without truncating it or allowing confirmation', () => {
    mount(); const long = '否'.repeat(6001) + '\nTail survives.'; fill(long);
    expect(task()).toHaveValue(long);
    const preview = screen.getByRole('region', { name: 'Information to confirm' });
    expect(preview.textContent).toContain(long); expect(preview).toHaveTextContent('too long for one entry');
    expect(confirm()).toBeDisabled(); expect(submit()).toBeDisabled();
    expect(current().confirm).not.toHaveBeenCalled();
  });

  it('clears answers on an owner generation change while retaining them through same-owner target review', async () => {
    const dirty = vi.fn(); const mounted = mount({ onDirtyChange: dirty }); fill('Answers for this target'); fireEvent.click(confirm());
    const accept = vi.fn().mockResolvedValue(undefined);
    mocked.controller = controller({ phase: 'stale', view: null, acceptCurrent: accept });
    mounted.rerender(<ResumeSupplementPanel {...mounted.props} targetKey="target-one-v2" />);
    expect(task()).toHaveValue('Answers for this target'); expect(submit()).toBeDisabled(); expect(confirm()).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Review current materials' })); await waitFor(() => expect(accept).toHaveBeenCalledTimes(1));
    mocked.controller = controller({ view: { ...view(), viewId: 'reviewed-v2' } });
    mounted.rerender(<ResumeSupplementPanel {...mounted.props} targetKey="target-one-v2" />);
    expect(task()).toHaveValue('Answers for this target'); expect(confirm()).not.toBeChecked();
    const nextOwner = { ...owner, generation: 1 };
    mocked.controller = controller({ view: view(nextOwner) });
    mounted.rerender(<ResumeSupplementPanel {...mounted.props} owner={nextOwner} targetKey="target-one-v2" />);
    expect(task()).toHaveValue(''); expect(screen.getByRole('combobox')).toHaveValue(''); expect(dirty).toHaveBeenLastCalledWith(false);
  });

  it.each(['load-error', 'not-saved', 'conflict'] as const)('keeps answers through %s and exposes the appropriate recovery action', async (phase) => {
    const onOpenProfile = vi.fn(); const mounted = mount({ onOpenProfile }); fill();
    const retry = vi.fn().mockResolvedValue(undefined);
    mocked.controller = controller({ phase, acceptCurrent: retry, error: 'PRIVATE backend detail must not appear' });
    mounted.rerender(<ResumeSupplementPanel {...mounted.props} />);
    expect(task()).toHaveValue('I helped test the sensor; I did not lead the project.'); expect(submit()).toBeDisabled();
    expect(screen.queryByText('PRIVATE backend detail must not appear')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: phase === 'load-error' ? 'Retry reading profile' : 'Review current materials' }));
    await waitFor(() => expect(retry).toHaveBeenCalledTimes(1));
    if (phase !== 'load-error') { fireEvent.click(screen.getByRole('button', { name: 'Review my profile' })); expect(onOpenProfile).toHaveBeenCalledTimes(1); }
  });

  it.each(['recorded', 'save-unknown'] as const)('locks the original answers and retries the same operation for %s', async (phase) => {
    const mounted = mount(); fill();
    const retry = vi.fn().mockResolvedValue({ status: 'error', message: 'still unavailable' });
    mocked.controller = controller({ phase, operationLocked: true, retryRecorded: retry });
    mounted.rerender(<ResumeSupplementPanel {...mounted.props} />);
    expect(task()).toBeDisabled(); expect(submit()).toBeDisabled();
    expect(task()).toHaveValue('I helped test the sensor; I did not lead the project.');
    fireEvent.click(screen.getByRole('button', { name: 'Retry cloud save' }));
    await waitFor(() => expect(retry).toHaveBeenCalledTimes(1)); expect(current().confirm).not.toHaveBeenCalled();
    if (phase === 'save-unknown') expect(screen.queryByText(/Recorded on this device/)).toBeNull();
  });

  it('keeps a recorded operation locked even when its target or profile becomes stale', () => {
    const mounted = mount(); fill();
    mocked.controller = controller({ phase: 'stale', operationLocked: true });
    mounted.rerender(<ResumeSupplementPanel {...mounted.props} />);
    expect(task()).toBeDisabled(); expect(submit()).toBeDisabled();
  });

  it.each(['master', 'activity'] as const)('provides a guarded profile exit when the %s is missing', (kind) => {
    const missing = view();
    if (kind === 'master') delete missing.renderedProfile.resume_master;
    else missing.renderedProfile.resume_master!.activities = [];
    mocked.controller = controller({ view: missing });
    const onOpenProfile = vi.fn(); mount({ onOpenProfile });
    expect(screen.getByRole('combobox')).toBeDisabled(); expect(submit()).toBeDisabled();
    expect(screen.getByText(kind === 'master' ? 'Create your master résumé before adding details here.'
      : 'Add a project or experience to your master résumé first.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Review my profile' }));
    expect(onOpenProfile).toHaveBeenCalledTimes(1); expect(current().confirm).not.toHaveBeenCalled();
  });

  it('keeps the confirmed appearance and shows success at the submit button after the saved view changes', async () => {
    const dirty = vi.fn(); const mounted = mount({ onDirtyChange: dirty }); fill('Confirmed task');
    fireEvent.change(screen.getByRole('textbox', { name: 'What was the outcome, if known?' }), { target: { value: 'Unselected draft remains private' } });
    fireEvent.click(confirm()); fireEvent.click(submit());
    await waitFor(() => expect(current().confirm).toHaveBeenCalledTimes(1));
    const entryId = vi.mocked(current().confirm).mock.calls[0][0].entryId;
    mocked.controller = controller({ phase: 'saved', confirmedEntryId: entryId, operationLocked: true,
      view: { ...view(), viewId: 'saved-receipt-view' } });
    mounted.rerender(<ResumeSupplementPanel {...mounted.props} />);
    expect(confirm()).toBeChecked(); expect(confirm()).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Added to master résumé' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Confirm and add to my master résumé' })).toBeNull();
    expect(screen.getByRole('textbox', { name: 'What was the outcome, if known?' })).toHaveValue('Unselected draft remains private');
    expect(dirty).toHaveBeenLastCalledWith(true);
    mocked.locale = 'zh'; mounted.rerender(<ResumeSupplementPanel {...mounted.props} />);
    expect(screen.getByRole('checkbox', { name: '我确认所选内容属实。' })).toBeChecked();
    expect(screen.getByRole('button', { name: '已加入母版简历' })).toBeDisabled();
  });

  it('preserves unselected drafts after saved confirmation and starts a new ID only after explicit clearing and accepted refresh', async () => {
    const dirty = vi.fn(); const mounted = mount({ onDirtyChange: dirty }); fill('Confirmed task only');
    fireEvent.change(screen.getByRole('textbox', { name: 'What was the outcome, if known?' }), { target: { value: 'Unselected outcome to revisit' } });
    fireEvent.click(confirm()); fireEvent.click(submit()); await waitFor(() => expect(current().confirm).toHaveBeenCalledTimes(1));
    const savedId = vi.mocked(current().confirm).mock.calls[0][0].entryId;
    const accept = vi.fn().mockResolvedValue(undefined);
    mocked.controller = controller({ phase: 'saved', confirmedEntryId: savedId, operationLocked: true, acceptCurrent: accept });
    mounted.rerender(<ResumeSupplementPanel {...mounted.props} />);
    expect(dirty).toHaveBeenLastCalledWith(true); expect(screen.getByText(/current target draft is unchanged/)).toBeInTheDocument();
    const ask = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add another detail' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Add another detail' })); expect(accept).not.toHaveBeenCalled();
    expect(screen.getByRole('textbox', { name: 'What was the outcome, if known?' })).toHaveValue('Unselected outcome to revisit');
    ask.mockReturnValue(true); fireEvent.click(screen.getByRole('button', { name: 'Add another detail' }));
    await waitFor(() => expect(accept).toHaveBeenCalledTimes(1));
    mocked.controller = controller({ view: { ...view(), viewId: 'saved-refreshed' } });
    mounted.rerender(<ResumeSupplementPanel {...mounted.props} />);
    await waitFor(() => expect(task()).toHaveValue('')); expect(dirty).toHaveBeenLastCalledWith(false);
    fill('A separate new detail'); fireEvent.click(confirm()); fireEvent.click(submit());
    await waitFor(() => expect(current().confirm).toHaveBeenCalledTimes(1));
    expect(vi.mocked(current().confirm).mock.calls[0][0].entryId).not.toBe(savedId);
  });


  it('hides private answers immediately when the controller retires an old owner before parent props catch up', () => {
    const dirty = vi.fn(); const mounted = mount({ onDirtyChange: dirty }); fill('Private old-owner draft');
    mocked.controller = controller({ phase: 'retired', view: null, operationLocked: true });
    mounted.rerender(<ResumeSupplementPanel {...mounted.props} />);
    expect(screen.queryByRole('textbox')).toBeNull(); expect(screen.queryByText('Private old-owner draft')).toBeNull();
    expect(dirty).toHaveBeenLastCalledWith(false);
  });

  it('does not clear answers when a new-round profile refresh fails', async () => {
    const mounted = mount(); fill('Already confirmed content'); fireEvent.click(confirm()); fireEvent.click(submit());
    await waitFor(() => expect(current().confirm).toHaveBeenCalledTimes(1));
    const entryId = vi.mocked(current().confirm).mock.calls[0][0].entryId;
    mocked.controller = controller({ phase: 'saved', confirmedEntryId: entryId, operationLocked: true });
    mounted.rerender(<ResumeSupplementPanel {...mounted.props} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add another detail' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Add another detail' }));
    await waitFor(() => expect(current().acceptCurrent).toHaveBeenCalledTimes(1));
    mocked.controller = controller({ phase: 'load-error' });
    mounted.rerender(<ResumeSupplementPanel {...mounted.props} />);
    expect(task()).toHaveValue('Already confirmed content'); expect(task()).toBeDisabled();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Retry reading profile' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Retry reading profile' }));
    await waitFor(() => expect(current().acceptCurrent).toHaveBeenCalledTimes(1));
    mocked.controller = controller({ view: { ...view(), viewId: 'fresh-after-retry' } });
    mounted.rerender(<ResumeSupplementPanel {...mounted.props} />);
    await waitFor(() => expect(task()).toHaveValue('')); expect(task()).toBeEnabled();
  });

  it('shows concise Chinese questions and never calls the writer for an empty selection', () => {
    mocked.locale = 'zh'; mount();
    expect(screen.getByRole('textbox', { name: '你本人具体做了什么？' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '确认并加入简历母版' })).toBeDisabled();
    expect(screen.getByText(/不必写数字或结果/)).toBeInTheDocument(); expect(current().confirm).not.toHaveBeenCalled();
  });
});
