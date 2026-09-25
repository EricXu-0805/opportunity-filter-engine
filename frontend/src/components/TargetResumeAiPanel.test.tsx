import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import golden from '../../../tests/fixtures/target-resume-ai-golden.json';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { prepareTargetResumeAI } from '@/lib/target-resume-ai';
import type { TargetResumeV1 } from '@/lib/target-resume';
import type { ProfileActionReceipt } from '@/lib/use-profile-refresh';
import { DEFAULT_PROFILE } from '@/app/home/types';
import type { PreparedTargetResumeAi, TargetResumeAiRequest, TargetResumeAiResponse } from '@/lib/target-resume-ai-protocol';
import { ApiError } from '@/lib/api';
import TargetResumeAiPanel, { type TargetResumeAiPanelProps } from './TargetResumeAiPanel';
const mocked = vi.hoisted(() => ({ generate: vi.fn(), locale: 'en' }));
vi.mock('@/i18n/client', () => ({ useLocale: () => mocked.locale }));
vi.mock('@/lib/api', async (load) => ({ ...await load<typeof import('@/lib/api')>(), generateTargetResumeSuggestions: mocked.generate }));
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((yes) => { resolve = yes; }); return { promise, resolve }; };
let prepared: PreparedTargetResumeAi;
const rewrite = 'I built a Python parser 😀 with my teammates. I did not lead the team.';
function response(payload: TargetResumeAiRequest, structureOnly = false): TargetResumeAiResponse {
  return { version: 1, pipeline_version: 'full-target-v1', request_id: payload.request_id, document_id: payload.draft.id,
    opportunity_id: payload.draft.opportunity_id, document_signature: payload.document_signature, base: clone(payload.draft.base),
    manifest: clone(golden.manifest), method: 'ai', logical_calls: 1, provider_attempts_upper_bound: 2,
    receipts: prepared.units.filter((unit) => payload.selected_unit_ids.includes(unit.unit_id)).map((unit) => ({
      unit_id: unit.unit_id, section_id: unit.section_id, block_id: unit.block_id, evidence: clone(unit.evidence), before_text: unit.before_text,
      status: unit.evidence.kind === 'experience' && !structureOnly ? 'suggested' : 'unchanged',
      reason_code: unit.evidence.kind === 'experience' && !structureOnly ? null : 'no_change',
      suggestion: { priority: structureOnly ? 'high' : 'normal', reason: 'The opportunity explicitly mentions Python.',
        target_evidence: [{ field: 'requirement', requirement_index: 0, start: 0, end: 6, quote: 'Python' }],
        proposed_text: unit.evidence.kind === 'experience' && !structureOnly ? rewrite : null },
    })) };
}
function props(): TargetResumeAiPanelProps {
  const draft = clone(golden.draft) as TargetResumeV1;
  return { profile: { ...DEFAULT_PROFILE, ...draft.base_snapshot }, draft, owner: captureOwnerToken()!, contextKey: 'source-and-target-one',
    currentContext: clone(golden.draft.base), enabled: true, onApply: vi.fn(), onDirtyChange: vi.fn() };
}
const generate = async () => { fireEvent.click(screen.getByRole('button', { name: 'Generate AI suggestions' })); await waitFor(() => expect(mocked.generate).toHaveBeenCalled()); };
const reviewReady = () => waitFor(() => expect(screen.getByRole('checkbox', { name: 'Use suggested section and block order' })).toBeEnabled());
beforeEach(async () => {
  vi.stubGlobal('crypto', webcrypto); localStorage.clear(); advanceOwnerEpoch('panel-owner'); await syncLocalIdentityOwner('panel-owner');
  mocked.locale = 'en'; mocked.generate.mockReset(); const result = await prepareTargetResumeAI(golden.draft); if (!result.ok) throw new Error(result.code); prepared = result.value;
  mocked.generate.mockImplementation(async (payload: TargetResumeAiRequest) => response(payload));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe('full résumé AI review workspace', () => {
  it('requires explicit selection, lets the user reject, and applies only the selected wording to the unchanged baseline', async () => {
    const p = props(); const original = JSON.stringify(p.draft); render(<TargetResumeAiPanel {...p} />); await generate(); await reviewReady();
    expect(p.onApply).not.toHaveBeenCalled(); expect(JSON.stringify(p.draft)).toBe(original);
    const unit = prepared.units.find((item) => item.evidence.kind === 'experience')!;
    const checkbox = screen.getByRole('checkbox', { name: `Use rewrite: ${unit.unit_id}` }); expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox); fireEvent.click(screen.getByRole('button', { name: `Dismiss suggestion: ${unit.unit_id}` }));
    expect(checkbox).toBeDisabled(); expect(checkbox).not.toBeChecked(); expect(screen.getByRole('button', { name: 'Apply selected suggestions' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: `Dismiss suggestion: ${unit.unit_id}` })); fireEvent.click(checkbox);
    expect(screen.getByText('Preview complete résumé before applying')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Apply selected suggestions' }));
    expect(p.onApply).toHaveBeenCalledTimes(1); const [canonical, next] = vi.mocked(p.onApply).mock.calls[0];
    expect(canonical).toBe(prepared.canonical_draft); expect(next.base_snapshot).toEqual(p.draft.base_snapshot);
    const lines = next.document.sections.flatMap((section) => section.blocks.flatMap((block) => block.lines));
    expect(lines.find((line) => line.id === unit.unit_id)!.text).toBe(rewrite); expect(JSON.stringify(p.draft)).toBe(original);
  });
  it.each(['document', 'source'] as const)('discards a late response after the %s changes', async (change) => {
    const pending = deferred<TargetResumeAiResponse>(); mocked.generate.mockReturnValueOnce(pending.promise);
    const p = props(); const view = render(<TargetResumeAiPanel {...p} />); await generate();
    const payload = mocked.generate.mock.calls[0][0]; const next = { ...p, draft: clone(p.draft) };
    if (change === 'document') next.draft.document.sections[0].blocks[0].lines[0].text = 'Later manual edit';
    else next.contextKey = 'new-source-revision';
    view.rerender(<TargetResumeAiPanel {...next} />); await act(async () => pending.resolve(response(payload)));
    expect(screen.queryByRole('checkbox', { name: /Use rewrite:/ })).toBeNull(); expect(p.onApply).not.toHaveBeenCalled();
    expect(screen.getByText(/Earlier suggestions were discarded/)).toBeVisible();
    expect(mocked.generate.mock.calls[0][1].signal.aborted).toBe(true);
  });
  it('cancels a pending request and does not show its late output', async () => {
    const pending = deferred<TargetResumeAiResponse>(); mocked.generate.mockReturnValueOnce(pending.promise);
    const p = props(); render(<TargetResumeAiPanel {...p} />); await generate(); const payload = mocked.generate.mock.calls[0][0];
    fireEvent.click(screen.getByRole('button', { name: 'Cancel generation' })); await act(async () => pending.resolve(response(payload)));
    expect(screen.queryByRole('checkbox', { name: /Use rewrite:/ })).toBeNull(); expect(p.onApply).not.toHaveBeenCalled();
    expect(mocked.generate.mock.calls[0][1].signal.aborted).toBe(true);
  });
  it('does not retry a failed request until Continue is clicked and uses safe target-change copy', async () => {
    mocked.generate.mockRejectedValueOnce(new ApiError(409, 'target_changed', 'PRIVATE PROVIDER BODY', false));
    const p = props(); render(<TargetResumeAiPanel {...p} />); await generate();
    expect(await screen.findByRole('alert')).toHaveTextContent('The opportunity changed.'); expect(screen.queryByText('PRIVATE PROVIDER BODY')).toBeNull();
    expect(mocked.generate).toHaveBeenCalledTimes(1); expect(p.onApply).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Continue remaining suggestions' })); await reviewReady(); expect(mocked.generate).toHaveBeenCalledTimes(2);
  });
  it('keeps structure-only advice in the unsaved close guard and clears it on owner invalidation', async () => {
    mocked.generate.mockImplementation(async (payload: TargetResumeAiRequest) => response(payload, true));
    const p = props(); render(<TargetResumeAiPanel {...p} />); await generate(); await reviewReady();
    expect(screen.queryByRole('checkbox', { name: /Use rewrite:/ })).toBeNull(); expect(p.onDirtyChange).toHaveBeenLastCalledWith(true);
    await act(async () => { advanceOwnerEpoch('other-owner'); });
    expect(screen.queryByRole('checkbox', { name: 'Use suggested section and block order' })).toBeNull(); expect(p.onDirtyChange).toHaveBeenLastCalledWith(false);
    expect(screen.getByRole('button', { name: 'Generate AI suggestions' })).toBeDisabled();
  });
  it('rejects a response with a fabricated target quote without presenting it as advice', async () => {
    mocked.generate.mockImplementation(async (payload: TargetResumeAiRequest) => { const result = response(payload); result.receipts[0].suggestion!.target_evidence[0].quote = 'Invented requirement'; return result; });
    const p = props(); render(<TargetResumeAiPanel {...p} />); await generate(); expect(await screen.findByRole('alert')).toHaveTextContent('could not be verified');
    expect(screen.queryByText('Invented requirement')).toBeNull(); expect(p.onApply).not.toHaveBeenCalled();
  });
});


describe('AI action profile checks and partial coverage', () => {
  const receipt = (p: TargetResumeAiPanelProps): ProfileActionReceipt => ({ checkId: 1, owner: captureOwnerToken(), revision: 2, source: 'cloud', profile: clone(p.profile) });
  it('retains verified partial receipts during Continue checking, then requests only remaining units', async () => {
    const p = props(), firstCheck = vi.fn().mockResolvedValue(receipt(p)), refresh = vi.fn().mockResolvedValue(true);
    const retriedUnit = prepared.units.find((unit) => unit.evidence.kind === 'experience')!.unit_id;
    mocked.generate.mockImplementationOnce(async (payload: TargetResumeAiRequest) => {
      const result = response(payload); const skipped = result.receipts.find((unit) => unit.unit_id === retriedUnit)!;
      result.method = 'partial'; skipped.status = 'skipped'; skipped.reason_code = 'budget_exhausted'; skipped.suggestion = null; return result;
    });
    const view = render(<TargetResumeAiPanel {...p} profileRefresh={{ status: 'ready', refresh, checkForAction: firstCheck }} />);
    await generate(); expect(await screen.findByRole('alert')).toHaveTextContent('allowance is used up');
    const coverage = screen.getByText(/Reviewed 8 of 9 items/); expect(coverage).toBeVisible();
    const wait = deferred<ProfileActionReceipt | null>(), checkForAction = vi.fn(() => wait.promise);
    view.rerender(<TargetResumeAiPanel {...p} profileRefresh={{ status: 'ready', refresh, checkForAction }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Continue remaining suggestions' }));
    await waitFor(() => expect(checkForAction).toHaveBeenCalledTimes(1)); expect(mocked.generate).toHaveBeenCalledTimes(1);
    view.rerender(<TargetResumeAiPanel {...p} enabled={false} readiness="waiting" profileRefresh={{ status: 'checking', refresh, checkForAction }} />);
    expect(coverage).toBeVisible(); expect(screen.getByRole('checkbox', { name: 'Use suggested section and block order' })).toBeDisabled();
    await act(async () => wait.resolve(receipt(p))); expect(mocked.generate).toHaveBeenCalledTimes(1);
    view.rerender(<TargetResumeAiPanel {...p} profileRefresh={{ status: 'ready', refresh, checkForAction }} />);
    await reviewReady(); expect(mocked.generate).toHaveBeenCalledTimes(2);
    expect(mocked.generate.mock.calls[1][0].selected_unit_ids).toEqual([retriedUnit]);
    expect(screen.getByText(/Reviewed 9 of 9 items/)).toBeVisible(); expect(p.onApply).not.toHaveBeenCalled();
  });
  it('aborts an in-flight batch on a read pause and rejects the late batch even after readiness returns', async () => {
    const p = props();
    const wait = deferred<TargetResumeAiResponse>();
    mocked.generate.mockReturnValueOnce(wait.promise);
    const view = render(<TargetResumeAiPanel {...p} />); await generate(); const payload = mocked.generate.mock.calls[0][0];
    view.rerender(<TargetResumeAiPanel {...p} enabled={false} readiness="waiting" />);
    expect(mocked.generate.mock.calls[0][1].signal.aborted).toBe(true);
    view.rerender(<TargetResumeAiPanel {...p} />);
    await act(async () => wait.resolve(response(payload)));
    expect(screen.queryByRole('checkbox', { name: /Use rewrite:/ })).toBeNull(); expect(p.onApply).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Continue remaining suggestions' })).toBeEnabled();
  });
  it.each(['document', 'source'] as const)('cancels a queued AI intent when the %s changes during the check', async (kind) => {
    const p = props(), wait = deferred<ProfileActionReceipt | null>(), checkForAction = vi.fn(() => wait.promise), refresh = vi.fn().mockResolvedValue(true);
    const view = render(<TargetResumeAiPanel {...p} profileRefresh={{ status: 'ready', refresh, checkForAction }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Generate AI suggestions' })); await waitFor(() => expect(checkForAction).toHaveBeenCalledTimes(1));
    const changed = clone(p.draft); if (kind === 'document') changed.document.sections[0].blocks[0].lines[0].text = 'Latest hand edit';
    view.rerender(<TargetResumeAiPanel {...p} draft={changed} contextKey={kind === 'source' ? 'changed-source' : p.contextKey} profileRefresh={{ status: 'ready', refresh, checkForAction }} />);
    await act(async () => wait.resolve(receipt(p))); expect(mocked.generate).not.toHaveBeenCalled(); expect(p.onApply).not.toHaveBeenCalled();
    expect(screen.getByText(/changed during the check/)).toBeVisible();
  });
  it('keeps existing suggestions on a failed recheck and does not silently retry the model', async () => {
    const p = props(), checkForAction = vi.fn().mockResolvedValue(receipt(p)), refresh = vi.fn().mockResolvedValue(true);
    render(<TargetResumeAiPanel {...p} profileRefresh={{ status: 'ready', refresh, checkForAction }} />); await generate(); await reviewReady();
    fireEvent.click(screen.getByRole('checkbox', { name: /Use rewrite:/ }));
    expect(screen.getByRole('button', { name: 'Apply selected suggestions' })).toBeEnabled();
    checkForAction.mockResolvedValue(null); fireEvent.click(screen.getByRole('button', { name: 'Generate AI suggestions' }));
    await screen.findByText(/Current profile could not be verified/);
    expect(screen.getByText(/Reviewed 9 of 9 items/)).toBeVisible(); expect(screen.getByRole('button', { name: 'Apply selected suggestions' })).toBeDisabled(); expect(mocked.generate).toHaveBeenCalledTimes(1); expect(p.onApply).not.toHaveBeenCalled();
  });
});
