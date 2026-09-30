import { createHash, webcrypto } from 'node:crypto';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Opportunity, ProfileData, RenovationDoc } from '@/lib/types';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { writingTargetKey } from '@/lib/writing-target';
import type { WritingTargetState } from '@/lib/use-writing-target';
import ResumeRenovationModal from './ResumeRenovationModal';
const mocks = vi.hoisted(() => ({ structure: vi.fn(), renovate: vi.fn(), optimize: vi.fn(), load: vi.fn(), save: vi.fn(), list: vi.fn(), read: vi.fn() }));
vi.mock('@/lib/api', () => ({ structureResume: mocks.structure, renovateResume: mocks.renovate, optimizeBullet: mocks.optimize }));
vi.mock('@/lib/supabase', () => ({ loadRenovation: mocks.load, saveRenovation: mocks.save, listRenovationVersions: mocks.list, readRenovationVersion: mocks.read }));
vi.mock('@/i18n/client', () => { const t = (key: string) => key; return { useT: () => ({ t, locale: 'en' }) }; });
const VERSION = `wt1:${'a'.repeat(64)}`;
const OTHER_VERSION = `wt1:${'b'.repeat(64)}`;
const target: Opportunity = {
  id: 'opp-1', title: 'Research lab', organization: 'UIUC', opportunity_type: 'research',
  paid: 'unknown', location: 'Urbana', on_campus: true, description_clean: 'Study vision systems', keywords: ['vision'],
  eligibility: { international_friendly: 'yes', preferred_year: ['Sophomore'], majors: ['CS'], skills_required: ['Python'], citizenship_required: null },
  application: { application_effort: 'low', requires_resume: 'yes', contact_method: 'email' },
  metadata: { is_active: true, confidence_score: 0.9 }, writing_target_version: VERSION,
};
const profile: ProfileData = { institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore', is_international: false,
  research_interests: 'vision', skills: [{ name: 'Python', level: 'experienced' }], coursework: ['CS225'], resume_text: 'Built a data pipeline' };
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(',')}}`;
  return JSON.stringify(value);
}
const signature = (value: unknown) => `v1:sha256:${createHash('sha256').update(canonical(value)).digest('hex')}`;
const doc: RenovationDoc = { sections: [{ id: 's1', heading: 'Projects', kind: 'projects', bullets: [
  { id: 'b1', base_text: 'Built a data pipeline', variants: [{ source: 'user', text: 'My complete saved wording', source_evidence: '' }], current: 0, action: 'keep' },
  { id: 'b2', base_text: 'Helped maintain a robot', variants: [], current: -1, action: 'keep' },
] }], method: 'ai', warnings: [], profile_sig: signature(profile), target_sig: signature(target) };
const structured = { sections: [{ id: 's1', heading: 'Projects', kind: 'projects', bullets: [{ id: 'b1', text: 'Built a data pipeline' }] }], method: 'ai', warnings: [] };
function receipt(extra: Record<string, unknown> = {}) { return { ...doc, opportunity_id: target.id, target_version: VERSION, ...extra }; }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
function show(current: Opportunity | null = target, refresh?: WritingTargetState) {
  return <ResumeRenovationModal isOpen onClose={vi.fn()} profile={profile} opportunityId="opp-1" opportunityTitle="Research lab"
    target={current} targetKey={JSON.stringify(current ?? target)} targetRefresh={refresh} />;
}
async function start() { const button = await screen.findByRole('button', { name: 'renovate.rerun' }); await waitFor(() => expect(button).toBeEnabled()); fireEvent.click(button); }
async function optimize(index = 0) { await waitFor(() => expect(screen.getAllByRole('button', { name: 'renovate.reoptimizeAria' })[index]).toBeEnabled()); fireEvent.click(screen.getAllByRole('button', { name: 'renovate.reoptimizeAria' })[index]); }
const fullText = (text: string) => (_content: string, element: Element | null) => element?.textContent === text && !Array.from(element.children).some(child => child.textContent === text);
beforeEach(async () => {
  vi.resetAllMocks(); window.localStorage.clear(); vi.stubGlobal('crypto', webcrypto); window.confirm = vi.fn(() => true);
  Element.prototype.scrollIntoView = vi.fn(); advanceOwnerEpoch('renovation-version-owner'); await syncLocalIdentityOwner('renovation-version-owner');
  mocks.load.mockResolvedValue({ doc: structuredClone(doc), base_snapshot: { sections: structured.sections, retained: 'original source' }, method: 'ai', warnings: [],
    updated_at: '2026-09-25T00:00:00Z', revision: 3, owner_id: 'renovation-version-owner', opportunity_id: target.id });
  mocks.save.mockImplementation(async (opportunity_id, value, base_snapshot, method, warnings, owner, revision) => ({ status: 'saved', current: {
    doc: value, base_snapshot, method, warnings, owner_id: owner.uid, opportunity_id, revision: revision + 1, updated_at: '2026-09-25T00:01:00Z' } }));
  mocks.list.mockResolvedValue({ items: [], next_cursor: null }); mocks.read.mockResolvedValue(null);
  mocks.structure.mockResolvedValue(structured); mocks.renovate.mockResolvedValue(receipt());
  mocks.optimize.mockResolvedValue({ opportunity_id: target.id, target_version: VERSION, text: 'Accepted rewrite', changed: true, source_evidence: 'Built a data pipeline', warnings: [] });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('legacy renovation exact target-version receipts', () => {
  it.each(['missing target', 'missing version', 'malformed version', 'wrong ID', 'card only'] as const)('keeps saved text but makes no dependent calls with %s', async kind => {
    const current = kind === 'missing target' ? null : kind === 'missing version' ? { ...target, writing_target_version: undefined }
      : kind === 'malformed version' ? { ...target, writing_target_version: 'opaque' }
      : kind === 'wrong ID' ? { ...target, id: 'other' }
      : { ...target, metadata: undefined } as unknown as Opportunity;
    render(show(current)); await screen.findByText(fullText('My complete saved wording'));
    expect(screen.getByRole('button', { name: 'renovate.rerun' })).toBeDisabled();
    expect(screen.getAllByRole('button', { name: 'renovate.reoptimizeAria' })[0]).toBeDisabled();
    expect(screen.getByText('renovate.targetVersionUnavailable')).toBeInTheDocument();
    expect(mocks.structure).not.toHaveBeenCalled(); expect(mocks.renovate).not.toHaveBeenCalled(); expect(mocks.optimize).not.toHaveBeenCalled(); expect(mocks.save).not.toHaveBeenCalled();
  });
  it('sends the verified version in both model paths and persists only exact receipts', async () => {
    render(show()); await optimize(); await waitFor(() => expect(mocks.save).toHaveBeenCalledOnce());
    expect(mocks.optimize.mock.calls[0][4]).toEqual({ locale: 'en', expectedTargetVersion: VERSION });
    expect(mocks.save.mock.calls[0][1].sections[0].bullets[0].variants.at(-1).text).toBe('Accepted rewrite');
    await start(); await waitFor(() => expect(mocks.save).toHaveBeenCalledTimes(2));
    expect(mocks.renovate.mock.calls[0][3]).toEqual({ locale: 'en', expectedTargetVersion: VERSION });
  });
  it.each(['missing', 'missing ID', 'wrong version', 'wrong ID', '409'] as const)('rejects a %s whole-document receipt without touching saved/manual history', async kind => {
    if (kind === '409') mocks.renovate.mockRejectedValue(Object.assign(new Error('private backend detail'), { status: 409, code: 'WRITING_TARGET_CHANGED' }));
    else mocks.renovate.mockResolvedValue(receipt(kind === 'missing' ? { target_version: undefined } : kind === 'missing ID' ? { opportunity_id: undefined } : kind === 'wrong ID' ? { opportunity_id: 'other' } : { target_version: OTHER_VERSION }));
    render(show()); await screen.findByText(fullText('My complete saved wording'));
    fireEvent.click(screen.getAllByRole('button', { name: 'renovate.editAria' })[0]);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Unsaved manual wording' } });
    await start(); await screen.findByText(kind === '409' ? 'renovate.targetVersionChanged' : 'renovate.targetVersionUnavailable');
    expect(screen.getByRole('textbox')).toHaveValue('Unsaved manual wording');
    expect(screen.getByText('Helped maintain a robot')).toBeInTheDocument();
    expect(mocks.save).not.toHaveBeenCalled(); expect(mocks.renovate).toHaveBeenCalledOnce();
    expect(screen.queryByText('private backend detail')).toBeNull();
    expect(screen.getByRole('button', { name: 'renovate.rerun' })).toBeDisabled();
  });
  it.each(['missing', 'missing ID', 'wrong version', 'wrong ID', '409'] as const)('rejects a %s single-bullet receipt without appending a variant or saving', async kind => {
    if (kind === '409') mocks.optimize.mockRejectedValue(Object.assign(new Error('private backend detail'), { status: 409, code: 'WRITING_TARGET_CHANGED' }));
    else mocks.optimize.mockResolvedValue({ text: 'Wrong rewrite', changed: true, opportunity_id: kind === 'missing ID' ? undefined : kind === 'wrong ID' ? 'other' : target.id,
      ...(kind === 'missing' ? {} : { target_version: kind === 'wrong version' ? OTHER_VERSION : VERSION }) });
    render(show()); await optimize(); await screen.findByText(kind === '409' ? 'renovate.targetVersionChanged' : 'renovate.targetVersionUnavailable');
    expect(screen.getByText(fullText('My complete saved wording'))).toBeInTheDocument(); expect(screen.queryByText('Wrong rewrite')).toBeNull();
    expect(mocks.save).not.toHaveBeenCalled(); expect(mocks.optimize).toHaveBeenCalledOnce();
  });
  it.each(['whole', 'bullet'] as const)('does not call an unrelated 409 a target change in the %s path', async path => {
    const failure = Object.assign(new Error('Unrelated service conflict'), { status: 409, code: 'OTHER_CONFLICT' });
    if (path === 'whole') mocks.renovate.mockRejectedValue(failure); else mocks.optimize.mockRejectedValue(failure);
    render(show());
    if (path === 'whole') { await start(); await screen.findByText('Unrelated service conflict'); }
    else { await optimize(); await screen.findByText('renovate.bulletFailed'); }
    expect(screen.queryByTestId('renovation-target-version')).toBeNull();
    expect(screen.getByText(fullText('My complete saved wording'))).toBeInTheDocument(); expect(mocks.save).not.toHaveBeenCalled();
  });
  it('keeps a failed recheck blocked; an accepted explicit recheck never replays model work', async () => {
    const refresh = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    const targetRefresh: WritingTargetState = { status: 'ready', target, reason: null, refresh,
      checkForAction: vi.fn(async () => ({ checkId: 1, owner: captureOwnerToken(), target, key: writingTargetKey(target)! })) };
    mocks.optimize.mockResolvedValueOnce({ text: 'Wrong rewrite', changed: true, opportunity_id: target.id, target_version: OTHER_VERSION });
    render(show(target, targetRefresh)); await optimize(); await screen.findByText('renovate.targetVersionUnavailable');
    fireEvent.click(screen.getByRole('button', { name: 'renovate.targetVersionRetry' }));
    await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.getByRole('button', { name: 'renovate.targetVersionRetry' })).toBeEnabled());
    expect(screen.getAllByRole('button', { name: 'renovate.reoptimizeAria' })[0]).toBeDisabled();
    expect(mocks.optimize).toHaveBeenCalledOnce(); expect(mocks.save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'renovate.targetVersionRetry' }));
    await waitFor(() => expect(screen.queryByTestId('renovation-target-version')).toBeNull());
    expect(mocks.optimize).toHaveBeenCalledOnce(); expect(mocks.renovate).not.toHaveBeenCalled(); expect(mocks.save).not.toHaveBeenCalled();
    await optimize(); await waitFor(() => expect(mocks.save).toHaveBeenCalledOnce());
    expect(mocks.optimize).toHaveBeenCalledTimes(2);
  });
  it('retires structure when the exact server version changes even if targetKey was not refreshed', async () => {
    const pending = deferred<typeof structured>(); mocks.structure.mockReturnValue(pending.promise);
    const view = render(show()); await start(); await waitFor(() => expect(mocks.structure).toHaveBeenCalledOnce());
    view.rerender(<ResumeRenovationModal isOpen onClose={vi.fn()} profile={profile} opportunityId="opp-1" opportunityTitle="Research lab"
      target={{ ...target, writing_target_version: OTHER_VERSION }} targetKey={JSON.stringify(target)} />);
    await act(async () => { pending.resolve(structured); });
    expect(mocks.renovate).not.toHaveBeenCalled(); expect(mocks.save).not.toHaveBeenCalled();
    expect(screen.getByText(fullText('My complete saved wording'))).toBeInTheDocument();
  });
});
