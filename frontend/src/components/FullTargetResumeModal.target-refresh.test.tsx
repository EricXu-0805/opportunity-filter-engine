import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_PROFILE } from '@/app/home/types';
import { createEmptyResumeMaster } from '@/lib/resume-master';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { createTargetResume, targetResumeContextFromOpportunity, targetResumeContextSignature, type TargetResumeV1 } from '@/lib/target-resume';
import { prepareTargetResumeAI } from '@/lib/target-resume-ai';
import type { TargetResumeAiRequest, TargetResumeAiResponse } from '@/lib/target-resume-ai-protocol';
import type { Opportunity, ProfileData, ResumeFact } from '@/lib/types';
import type { WritingTargetState } from '@/lib/use-writing-target';
import { writingTargetKey } from '@/lib/writing-target';
import FullTargetResumeModal from './FullTargetResumeModal';

const mocked = vi.hoisted(() => ({ load: vi.fn(), save: vi.fn(), generate: vi.fn(), exportFile: vi.fn(), download: vi.fn() }));
vi.mock('@/i18n/client', () => ({ useLocale: () => 'en' }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('./ResumeSupplementPanel', () => ({ default: () => null }));
vi.mock('@/lib/target-resume-storage', () => ({ loadTargetResume: mocked.load, saveTargetResume: mocked.save,
  loadTargetResumeHistory: vi.fn().mockResolvedValue([]), loadTargetResumeVersion: vi.fn().mockResolvedValue(null) }));
vi.mock('@/lib/api', async (load) => ({ ...await load<typeof import('@/lib/api')>(), generateTargetResumeSuggestions: mocked.generate }));
vi.mock('@/lib/target-resume-export-api', () => ({ fetchTargetResumeExport: mocked.exportFile, downloadTargetResumeExport: mocked.download }));

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((yes) => { resolve = yes; }); return { promise, resolve }; };
const target: Opportunity = {
  id: 'full-target-binding', title: 'Robotics research', organization: 'Example lab', opportunity_type: 'research',
  paid: 'unknown', location: 'Example campus', on_campus: true, description_clean: 'Work on robotics with Python.', keywords: ['robotics'],
  eligibility: { international_friendly: 'unknown', preferred_year: [], majors: [], skills_required: ['Python'], citizenship_required: null },
  application: { application_effort: 'low', requires_resume: 'yes', contact_method: 'email' }, metadata: { is_active: true, confidence_score: 1 },
};
const fact = (value: string): ResumeFact => ({ id: crypto.randomUUID(), revision: 1, value, status: 'confirmed', source: { kind: 'manual' } });
function profile(): ProfileData {
  const master = createEmptyResumeMaster(); master.basics.name = fact('Alex 王');
  master.education = [{ id: 'education', school: fact('Example University'), degree: fact('B.S.'), details: [] }];
  master.activities = [{ id: 'project', kind: 'research', title: fact('Robot trials'), details: [{ id: 'experience', revision: 1 }] }];
  return { ...DEFAULT_PROFILE, resume_master: master, experience_entries: [{ id: 'experience', revision: 1, status: 'confirmed',
    text: 'Measured robot trials; did not lead the team.', source: { kind: 'manual' } }] };
}
function reader(value = target, status: WritingTargetState['status'] = 'ready'): WritingTargetState {
  return { target: value, status, reason: status === 'blocked' ? 'listing_closed' : status === 'missing' ? 'not_found' : status === 'failed' ? 'timeout' : null,
    refresh: vi.fn().mockResolvedValue(true), checkForAction: vi.fn().mockResolvedValue({ checkId: 1, owner: captureOwnerToken(), target: value, key: writingTargetKey(value) }) };
}
const rewrite = 'Reviewed robot trials; did not lead the team.';
async function response(payload: TargetResumeAiRequest): Promise<TargetResumeAiResponse> {
  const result = await prepareTargetResumeAI(payload.draft); if (!result.ok) throw new Error(result.code);
  const prepared = result.value;
  return { version: 1, pipeline_version: 'full-target-v4', request_id: payload.request_id, document_id: payload.draft.id,
    opportunity_id: payload.draft.opportunity_id, document_signature: payload.document_signature, base: clone(payload.draft.base),
    manifest: { unit_ids: prepared.units.map((unit) => unit.unit_id), protected_unit_count: prepared.protected_unit_count },
    method: 'ai', logical_calls: 1, provider_attempts_upper_bound: 2,
    receipts: prepared.units.filter((unit) => payload.selected_unit_ids.includes(unit.unit_id)).map((unit) => ({
      unit_id: unit.unit_id, section_id: unit.section_id, block_id: unit.block_id, evidence: clone(unit.evidence), before_text: unit.before_text,
      status: unit.evidence.kind === 'experience' ? 'suggested' : 'unchanged', reason_code: unit.evidence.kind === 'experience' ? null : 'no_change',
      suggestion: { priority: 'normal', reason: 'The opportunity mentions Python.', target_evidence: [{ field: 'requirement', requirement_index: 0, start: 0, end: 6, quote: 'Python' }],
        proposed_text: unit.evidence.kind === 'experience' ? rewrite : null },
    })) };
}
async function setup() {
  const p = profile(); const doc = await createTargetResume(p, targetResumeContextFromOpportunity(target), 'independent-draft');
  mocked.load.mockResolvedValue({ doc, revision: 1, updated_at: '2026-09-24T00:00:00Z' });
  const view = render(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={target} targetRefresh={reader()} />);
  await screen.findByRole('textbox', { name: 'Edit Full name' });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Generate AI suggestions' })).toBeEnabled());
  fireEvent.change(screen.getByRole('textbox', { name: 'Edit Full name' }), { target: { value: 'Preserve my hand edit' } });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Include field: Degree' }));
  return { p, doc, ...view };
}
beforeEach(async () => {
  vi.stubGlobal('crypto', webcrypto); localStorage.clear(); advanceOwnerEpoch('full-target-owner'); await syncLocalIdentityOwner('full-target-owner');
  mocked.load.mockReset(); mocked.save.mockReset().mockResolvedValue({ status: 'failed' }); mocked.generate.mockReset();
  mocked.exportFile.mockReset().mockResolvedValue({ blob: new Blob(['pdf']), filename: 'retained.pdf' }); mocked.download.mockReset();
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('complete live target binding without replacing the saved snapshot', () => {
  it.each(['changed', 'same'] as const)('handles a held AI receipt after a %s full-public target read', async (change) => {
    const held = deferred<TargetResumeAiResponse>(); mocked.generate.mockReturnValue(held.promise);
    const { p, doc, rerender } = await setup();
    fireEvent.click(screen.getByRole('button', { name: 'Generate AI suggestions' }));
    await waitFor(() => expect(mocked.generate).toHaveBeenCalledTimes(1));
    const payload = mocked.generate.mock.calls[0][0] as TargetResumeAiRequest;
    const next = clone(target); if (change === 'changed') next.eligibility.citizenship_required = true;
    // A criteria-only change retires both live work and the saved target binding.
    expect(JSON.stringify(targetResumeContextFromOpportunity(next)) === JSON.stringify(targetResumeContextFromOpportunity(target))).toBe(change === 'same');
    rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={next} targetRefresh={reader(next)} />);
    const signal = mocked.generate.mock.calls[0][1].signal as AbortSignal;
    expect(signal.aborted).toBe(change === 'changed');
    await act(async () => held.resolve(await response(payload)));
    if (change === 'changed') {
      expect(screen.queryByRole('checkbox', { name: /Use rewrite:/ })).toBeNull();
      expect(screen.queryByText(rewrite)).toBeNull();
      expect(screen.queryByRole('button', { name: 'Apply selected suggestions' })).toBeNull();
    } else expect(await screen.findByRole('checkbox', { name: /Use rewrite:/ })).toBeEnabled();
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Preserve my hand edit');
    expect(screen.getByRole('checkbox', { name: 'Include field: Degree' })).not.toBeChecked();
    expect(mocked.load).toHaveBeenCalledTimes(1); expect(mocked.save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    await waitFor(() => expect(mocked.save).toHaveBeenCalledTimes(1));
    const saved = mocked.save.mock.calls[0][0] as TargetResumeV1;
    expect(saved.base).toEqual(doc.base); expect(saved.target_snapshot).toEqual(doc.target_snapshot);
  });
  it.each(['blocked', 'failed', 'missing', 'membership'] as const)('exports retained manual content when target is %s without enabling AI or rebinding sources', async (status) => {
    const { p, doc, rerender } = await setup();
    rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={target}
      targetReady={false} targetMembershipReady={status !== 'membership'} targetRefresh={reader(target, status === 'membership' ? 'ready' : status)} />);
    expect(screen.getByRole('button', { name: 'Generate AI suggestions' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Rebuild from current confirmed master' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Export PDF' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Export PDF' }));
    await waitFor(() => expect(mocked.download).toHaveBeenCalledTimes(1));
    const payload = mocked.exportFile.mock.calls[0][0];
    expect(JSON.stringify(payload.projection)).toContain('Preserve my hand edit');
    expect(JSON.stringify(payload.projection)).not.toContain('B.S.');
    expect(mocked.generate).not.toHaveBeenCalled(); expect(mocked.save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    await waitFor(() => expect(mocked.save).toHaveBeenCalledTimes(1));
    expect(mocked.save.mock.calls[0][0].base).toEqual(doc.base);
    expect(mocked.save.mock.calls[0][0].target_snapshot).toEqual(doc.target_snapshot);
  });
  it('continues to pause export when the existing profile check has failed', async () => {
    const { p, rerender } = await setup();
    rerender(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={target}
      profileRefresh={{ status: 'failed', refresh: vi.fn().mockResolvedValue(false) }} targetRefresh={reader(target, 'failed')} />);
    expect(screen.getByRole('button', { name: 'Export PDF' })).toBeDisabled();
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toHaveValue('Preserve my hand edit');
    expect(mocked.exportFile).not.toHaveBeenCalled(); expect(mocked.save).not.toHaveBeenCalled();
  });
});


describe('saved target criteria across editor lifetimes', () => {
  it('keeps a six-field legacy draft editable and exportable, but explains why AI needs a rebuild', async () => {
    const p = profile(); const current = await createTargetResume(p, targetResumeContextFromOpportunity(target), 'legacy-draft');
    const { opportunity_id, title, organization, source_url, description, requirements } = current.target_snapshot;
    const legacy = clone(current);
    legacy.target_snapshot = { opportunity_id, title, organization, source_url, description, requirements };
    legacy.base.target_signature = await targetResumeContextSignature(legacy.target_snapshot);
    mocked.load.mockResolvedValue({ doc: legacy, revision: 7, updated_at: '2026-09-24T00:00:00Z' });
    render(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={target} targetRefresh={reader()} />);
    await screen.findByRole('textbox', { name: 'Edit Full name' });
    expect(await screen.findByText('This older draft did not save all opportunity requirements. You can still edit, save and export it. Rebuild to use AI with the current requirements.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Generate AI suggestions' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Export PDF' })).toBeEnabled();
    fireEvent.change(screen.getByRole('textbox', { name: 'Edit Full name' }), { target: { value: 'Legacy manual wording 王' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save target draft' }));
    await waitFor(() => expect(mocked.save).toHaveBeenCalledTimes(1));
    expect(mocked.save.mock.calls[0][0].target_snapshot).toEqual(legacy.target_snapshot);
    expect(mocked.save.mock.calls[0][0].base.target_signature).toBe(legacy.base.target_signature);
    fireEvent.click(screen.getByRole('button', { name: 'Export PDF' }));
    await waitFor(() => expect(mocked.download).toHaveBeenCalledTimes(1));
    expect(mocked.generate).not.toHaveBeenCalled();
  });
  it.each(['citizenship', 'deadline', 'application'] as const)('reopens a draft as outdated after only %s changes', async (change) => {
    const p = profile(); const doc = await createTargetResume(p, targetResumeContextFromOpportunity(target), 'saved-criteria');
    mocked.load.mockResolvedValue({ doc, revision: 1, updated_at: '2026-09-24T00:00:00Z' });
    const next = clone(target);
    if (change === 'citizenship') next.eligibility.citizenship_required = true;
    if (change === 'deadline') next.deadline = '2026-10-31';
    if (change === 'application') next.application.requires_cover_letter = 'yes';
    render(<FullTargetResumeModal isOpen onClose={vi.fn()} profile={p} opportunity={next} targetRefresh={reader(next)} />);
    await screen.findByRole('textbox', { name: 'Edit Full name' });
    expect(await screen.findByText(/This draft was created from different profile or target materials/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Generate AI suggestions' })).toBeDisabled();
    expect(screen.getByRole('textbox', { name: 'Edit Full name' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Export PDF' })).toBeEnabled();
    expect(mocked.save).not.toHaveBeenCalled(); expect(mocked.generate).not.toHaveBeenCalled();
  });
});
