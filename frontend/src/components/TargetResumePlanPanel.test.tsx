import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import golden from '../../../tests/fixtures/target-resume-context-v4-golden.json';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { appendTargetResumeProvenance } from '@/lib/target-resume-provenance';
import { prepareTargetResumePlan, measureTargetResumeLength } from '@/lib/target-resume-plan';
import { createTargetResume, type TargetResumeV1 } from '@/lib/target-resume';
import type { ProfileActionReceipt } from '@/lib/use-profile-refresh';
import { DEFAULT_PROFILE } from '@/app/home/types';
import type { TargetResumePlanRequest, TargetResumePlanResponse } from '@/lib/target-resume-plan-protocol';
import { ApiError } from '@/lib/api';
import TargetResumePlanPanel, { type TargetResumePlanPanelProps } from './TargetResumePlanPanel';

const mocked = vi.hoisted(() => ({ generate: vi.fn(), locale: 'en' }));
vi.mock('@/i18n/client', () => ({ useLocale: () => mocked.locale }));
vi.mock('@/lib/api', async load => ({ ...await load<typeof import('@/lib/api')>(), generateTargetResumePlan: mocked.generate }));
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(yes => { resolve = yes; }); return { promise, resolve }; };
const shorter = 'I did not lead the team.';
async function response(payload: TargetResumePlanRequest): Promise<TargetResumePlanResponse> {
  const p = await prepareTargetResumePlan(payload.draft, payload.options); if (!p.ok) throw new Error(p.code);
  return { version: 1, pipeline_version: 'full-target-plan-v3', request_id: payload.request_id, document_id: payload.draft.id,
    opportunity_id: payload.draft.opportunity_id, document_signature: payload.document_signature, base: clone(payload.draft.base), options: payload.options,
    manifest: p.value.manifest, scope: p.value.scope, method: 'ai', complete: true, reason_code: null, logical_calls: 1, provider_attempts_upper_bound: 2,
    items: p.value.manifest.map(item => {
      const block = payload.draft.document.sections.find(section => section.id === item.section_id)!.blocks.find(block => block.id === item.block_id)!;
      const source = block.lines[0];
      return { section_id: item.section_id, block_id: item.block_id, action: item.block_id === 'project-one' ? 'compress' : item.block_id === 'publication-one' ? 'omit' : 'keep',
        reason: 'The opportunity mentions Python; review the cited source before choosing.',
        target_evidence: [{ field: 'requirement', requirement_index: 0, start: 0, end: 6, quote: 'Python' }],
        source_evidence: [{ unit_id: source.id, start: 0, end: Array.from(source.original).length, quote: source.original }],
        rewrites: block.lines.filter(line => line.evidence.kind === 'experience').map(line => ({ unit_id: line.id, status: 'suggested', reason_code: null, proposed_text: shorter })),
      };
    }) };
}
function props(): TargetResumePlanPanelProps {
  const draft = clone(golden.draft) as TargetResumeV1;
  return { profile: { ...DEFAULT_PROFILE, ...draft.base_snapshot }, draft, owner: captureOwnerToken(), contextKey: 'source-and-target', currentContext: { profile_signature: draft.base.profile_signature, source_signature: draft.base.source_signature, target_signature: draft.base.target_signature }, enabled: true, onApply: vi.fn(), onDirtyChange: vi.fn(), onAuthorityRefusal: vi.fn() };
}
const generate = async () => { fireEvent.click(screen.getByRole('button', { name: 'Generate content plan' })); await waitFor(() => expect(mocked.generate).toHaveBeenCalled()); };
const reviewReady = () => screen.findByText('All 5 content blocks in this draft were reviewed. Nothing has been applied.');
const select = (id: string) => fireEvent.click(screen.getByRole('checkbox', { name: `Use content choice: ${id}` }));
const selectRewrite = () => fireEvent.click(screen.getByRole('checkbox', { name: 'Use shorter wording: line-6' }));
const apply = () => fireEvent.click(screen.getByRole('button', { name: 'Apply selected content choices' }));
const project = (doc: TargetResumeV1) => doc.document.sections.find(section => section.id === 'activities')!.blocks[0];
beforeEach(async () => {
  vi.stubGlobal('crypto', webcrypto); localStorage.clear(); advanceOwnerEpoch('plan-owner'); await syncLocalIdentityOwner('plan-owner');
  mocked.locale = 'en'; mocked.generate.mockReset().mockImplementation(response);
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('whole draft content planning', () => {
  it('shows a complete unselected plan, original/current wording, citations and honest length/scope labels', async () => {
    const p = props(), before = JSON.stringify(p.draft); render(<TargetResumePlanPanel {...p} />); await generate(); await reviewReady();
    expect(mocked.generate.mock.calls[0][0].draft).toEqual(p.draft);
    expect(screen.getAllByRole('checkbox')).toHaveLength(6);
    for (const control of screen.getAllByRole('checkbox')) expect(control).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Apply selected content choices' })).toBeDisabled();
    expect(screen.getByTestId('plan-current-length')).toHaveTextContent(String(measureTargetResumeLength(p.draft)));
    expect(screen.getByText(/not a page guarantee/)).toBeVisible();
    expect(screen.getByText('Materials outside this draft')).toBeVisible();
    expect(screen.getByText(/Confirmed experiences outside this draft:/)).toBeInTheDocument();
    const card = document.querySelector('[data-plan-block-id="project-one"]') as HTMLElement;
    fireEvent.click(within(card).getByText('Read complete original and current text'));
    expect(within(card).getByText(project(p.draft).lines[1].original)).toBeVisible();
    expect(within(card).getByText(project(p.draft).lines[1].text)).toBeVisible();
    expect(within(card).getByText('Opportunity evidence')).toBeVisible();
    expect(p.onApply).not.toHaveBeenCalled(); expect(JSON.stringify(p.draft)).toBe(before); expect(p.onDirtyChange).toHaveBeenLastCalledWith(true);
  });
  it('applies only an explicitly selected omission, keeping originals, wording and master unchanged', async () => {
    const p = props(); render(<TargetResumePlanPanel {...p} />); await generate(); await reviewReady(); select('publication-one');
    fireEvent.click(screen.getByText('Compare complete draft before applying'));
    expect(within(screen.getByRole('region', { name: 'After selected content choices' })).queryByText('研究记录')).toBeNull();
    expect(within(screen.getByRole('region', { name: 'Before content choices' })).getByText('研究记录')).toBeVisible();
    apply(); const [canonical, next] = vi.mocked(p.onApply).mock.calls[0]; const expected = await prepareTargetResumePlan(p.draft, { target_pages: 1 });
    expect(expected.ok && canonical).toBe(expected.ok && expected.value.canonical_draft);
    expect(next.document.sections.find(section => section.id === 'publications')!.blocks[0].included).toBe(false);
    expect(project(next)).toEqual(project(p.draft)); expect(next.base_snapshot).toEqual(p.draft.base_snapshot);
    expect(next.document.sections[0]).toEqual(p.draft.document.sections[0]);
    expect(screen.getByTestId('plan-preview-length')).toHaveTextContent(String(measureTargetResumeLength(next)));
  });
  it('allows shorter wording independently without selecting its hidden block, section or fields', async () => {
    const p = props(); const section = p.draft.document.sections.find(section => section.id === 'activities')!;
    section.included = false; section.blocks[0].included = false; section.blocks[0].lines[1].included = false;
    render(<TargetResumePlanPanel {...p} />); await generate(); await reviewReady();
    expect(screen.getByText(/Selecting its block does not restore the section/)).toBeVisible();
    expect(screen.getByText(/Hidden fields stay hidden/)).toBeVisible();
    expect(screen.getByText('Re-include this block using this choice')).toBeVisible();
    selectRewrite(); apply(); const next = vi.mocked(p.onApply).mock.calls[0][1];
    expect(project(next).lines[1].text).toBe(shorter); expect(project(next).lines[1].original).toBe(project(p.draft).lines[1].original);
    expect(project(next).included).toBe(false); expect(project(next).lines[1].included).toBe(false);
    expect(next.document.sections.find(section => section.id === 'activities')!.included).toBe(false);
  });
  it('re-includes only a selected hidden block and does not silently shorten its wording', async () => {
    const p = props(); project(p.draft).included = false; render(<TargetResumePlanPanel {...p} />); await generate(); await reviewReady();
    select('project-one'); apply(); const next = vi.mocked(p.onApply).mock.calls[0][1];
    expect(project(next).included).toBe(true); expect(project(next).lines).toEqual(project(p.draft).lines);
  });
  it.each(['ungrounded_rewrite', 'not_shorter'] as const)('keeps a %s compression unavailable without disabling the separate content choice', async code => {
    mocked.generate.mockImplementation(async payload => { const value = await response(payload); value.items.find(item => item.block_id === 'project-one')!.rewrites[0] = { unit_id: 'line-6', status: 'skipped', reason_code: code, proposed_text: null }; return value; });
    const p = props(); render(<TargetResumePlanPanel {...p} />); await generate(); await reviewReady();
    expect(screen.queryByRole('checkbox', { name: 'Use shorter wording: line-6' })).toBeNull();
    expect(screen.getByText(code === 'not_shorter' ? 'The candidate was not shorter. Current wording is kept.' : 'The candidate failed source checks. Current wording is kept.')).toBeVisible();
    select('project-one'); apply(); expect(project(vi.mocked(p.onApply).mock.calls[0][1]).lines).toEqual(project(p.draft).lines);
  });
  it.each(['missing block', 'false quote'] as const)('rejects an invalid whole plan (%s) instead of showing partial advice', async defect => {
    mocked.generate.mockImplementation(async payload => { const value = await response(payload); if (defect === 'missing block') value.items.pop(); else value.items[0].source_evidence[0].quote = 'FABRICATED'; return value; });
    const p = props(); render(<TargetResumePlanPanel {...p} />); await generate(); expect(await screen.findByRole('alert')).toHaveTextContent('could not be verified');
    expect(screen.queryByRole('checkbox')).toBeNull(); expect(screen.queryByText('FABRICATED')).toBeNull(); expect(p.onApply).not.toHaveBeenCalled();
  });
  it.each(['document', 'target', 'pages'] as const)('retires a pending result after %s changes', async change => {
    const pending = deferred<TargetResumePlanResponse>(); mocked.generate.mockReturnValueOnce(pending.promise);
    const p = props(); const view = render(<TargetResumePlanPanel {...p} />); await generate(); const payload = mocked.generate.mock.calls[0][0];
    const next = { ...p, draft: clone(p.draft) };
    if (change === 'document') next.draft.document.sections[0].blocks[0].lines[0].text = 'Latest manual name';
    if (change === 'target') next.contextKey = 'another-target-source';
    if (change === 'pages') fireEvent.change(screen.getByRole('combobox', { name: 'Length target' }), { target: { value: '2' } });
    else view.rerender(<TargetResumePlanPanel {...next} />);
    await act(async () => pending.resolve(await response(payload)));
    expect(screen.queryByRole('checkbox')).toBeNull(); expect(mocked.generate.mock.calls[0][1].signal.aborted).toBe(true); expect(p.onApply).not.toHaveBeenCalled();
    expect(screen.getByText(/old plan was cleared/)).toBeVisible();
  });
  it('clears already reviewed choices after a source change and tolerates a replacement document with different IDs', async () => {
    const p = props(); const view = render(<TargetResumePlanPanel {...p} />); await generate(); await reviewReady(); selectRewrite();
    const next = clone(p.draft); next.document.sections = next.document.sections.filter(section => section.kind === 'basics');
    view.rerender(<TargetResumePlanPanel {...p} draft={next} contextKey="replacement" />);
    expect(screen.queryByRole('checkbox')).toBeNull(); expect(p.onDirtyChange).toHaveBeenLastCalledWith(false); expect(p.onApply).not.toHaveBeenCalled();
  });
  it.each(['cancel', 'unmount', 'owner'] as const)('rejects a late result after %s', async change => {
    const pending = deferred<TargetResumePlanResponse>(); mocked.generate.mockReturnValueOnce(pending.promise);
    const p = props(); const view = render(<TargetResumePlanPanel {...p} />); await generate(); const payload = mocked.generate.mock.calls[0][0];
    if (change === 'cancel') fireEvent.click(screen.getByRole('button', { name: 'Cancel planning' }));
    if (change === 'unmount') view.unmount();
    if (change === 'owner') await act(async () => { advanceOwnerEpoch('next-owner'); });
    await act(async () => pending.resolve(await response(payload)));
    expect(screen.queryByRole('checkbox')).toBeNull(); expect(p.onApply).not.toHaveBeenCalled(); expect(mocked.generate.mock.calls[0][1].signal.aborted).toBe(true);
    expect(p.onDirtyChange).toHaveBeenLastCalledWith(false);
  });
  it('keeps verified advice and explicit choices through a temporary readiness pause', async () => {
    const p = props(); const view = render(<TargetResumePlanPanel {...p} />); await generate(); await reviewReady(); selectRewrite();
    view.rerender(<TargetResumePlanPanel {...p} enabled={false} readiness="waiting" />);
    expect(screen.getByRole('checkbox', { name: 'Use shorter wording: line-6' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Use shorter wording: line-6' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Apply selected content choices' })).toBeDisabled();
    view.rerender(<TargetResumePlanPanel {...p} />);
    expect(screen.getByRole('button', { name: 'Apply selected content choices' })).toBeEnabled(); expect(mocked.generate).toHaveBeenCalledTimes(1);
  });
  it('does not revive an in-flight result when readiness returns unchanged', async () => {
    const pending = deferred<TargetResumePlanResponse>(); mocked.generate.mockReturnValueOnce(pending.promise);
    const p = props(); const view = render(<TargetResumePlanPanel {...p} />); await generate(); const payload = mocked.generate.mock.calls[0][0];
    view.rerender(<TargetResumePlanPanel {...p} enabled={false} readiness="waiting" />); view.rerender(<TargetResumePlanPanel {...p} />);
    await act(async () => pending.resolve(await response(payload)));
    expect(screen.queryByRole('checkbox')).toBeNull(); expect(p.onApply).not.toHaveBeenCalled(); expect(mocked.generate).toHaveBeenCalledTimes(1);
  });
  it.each([['target_changed', 409], ['target_not_found', 404], ['TARGET_NOT_ACTIONABLE', 409], ['legacy_target_context', 409]] as const)('retires an earlier selected plan after authority rejection %s', async (code, status) => {
    const p = props(), original = JSON.stringify(p.draft); const view = render(<TargetResumePlanPanel {...p} />);
    await generate(); await reviewReady(); select('publication-one'); selectRewrite();
    expect(screen.getByRole('button', { name: 'Apply selected content choices' })).toBeEnabled();
    mocked.generate.mockRejectedValueOnce(new ApiError(status, code, 'PRIVATE PROVIDER MESSAGE', false));
    fireEvent.click(screen.getByRole('button', { name: 'Generate content plan' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(code === 'target_changed' ? 'The opportunity changed.' : code === 'legacy_target_context' ? 'This older draft lacks complete opportunity requirements.' : code === 'TARGET_NOT_ACTIONABLE' ? 'This opportunity is currently unavailable for résumé planning.' : 'This opportunity is unavailable');
    expect(p.onAuthorityRefusal).toHaveBeenCalledWith(code);
    expect(screen.queryByRole('checkbox', { name: /Use content choice:/ })).toBeNull();
    expect(screen.queryByRole('checkbox', { name: /Use shorter wording:/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Apply selected content choices' })).toBeNull();
    view.rerender(<TargetResumePlanPanel {...p} enabled={false} readiness="waiting" />); view.rerender(<TargetResumePlanPanel {...p} />);
    expect(screen.queryByRole('button', { name: 'Apply selected content choices' })).toBeNull();
    expect(p.onApply).not.toHaveBeenCalled(); expect(JSON.stringify(p.draft)).toBe(original); expect(p.onDirtyChange).toHaveBeenLastCalledWith(false);
    expect(screen.queryByText('PRIVATE PROVIDER MESSAGE')).toBeNull(); expect(mocked.generate).toHaveBeenCalledTimes(2);
  });
  it.each([['budget_exhausted', 429], ['REQUEST_TIMEOUT', 504]] as const)('preserves the current draft, earlier plan and choices when regeneration returns %s', async (code, status) => {
    const p = props(); render(<TargetResumePlanPanel {...p} />); await generate(); await reviewReady(); selectRewrite();
    mocked.generate.mockRejectedValueOnce(new ApiError(status, code, 'PRIVATE PROVIDER MESSAGE', false));
    fireEvent.click(screen.getByRole('button', { name: 'Generate content plan' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(code === 'budget_exhausted' ? 'allowance is used up' : 'did not finish in time');
    expect(screen.getByRole('checkbox', { name: 'Use shorter wording: line-6' })).toBeChecked(); expect(p.onAuthorityRefusal).not.toHaveBeenCalled();
    expect(screen.queryByText('PRIVATE PROVIDER MESSAGE')).toBeNull(); expect(p.onApply).not.toHaveBeenCalled(); expect(mocked.generate).toHaveBeenCalledTimes(2);
  });
  it('cancels a queued generation when the page target changes during live profile verification', async () => {
    const p = props(), pending = deferred<ProfileActionReceipt | null>();
    const checkForAction = vi.fn(() => pending.promise), refresh = vi.fn().mockResolvedValue(true);
    render(<TargetResumePlanPanel {...p} profileRefresh={{ status: 'ready', checkForAction, refresh }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Generate content plan' })); await waitFor(() => expect(checkForAction).toHaveBeenCalledTimes(1));
    expect(mocked.generate).not.toHaveBeenCalled(); expect(p.onDirtyChange).toHaveBeenLastCalledWith(true);
    fireEvent.change(screen.getByRole('combobox', { name: 'Length target' }), { target: { value: '2' } });
    await act(async () => pending.resolve({ checkId: 1, owner: captureOwnerToken(), revision: 2, source: 'cloud', profile: clone(p.profile) }));
    expect(mocked.generate).not.toHaveBeenCalled(); expect(screen.getByText(/changed during the check/)).toBeVisible();
  });
  it('shows the final block beyond 24 items and sends every original rather than only the first batch', async () => {
    const p = props();
    for (let index = 0; index < 26; index += 1) p.profile.resume_master!.skills.push({ id: `additional-skill-${index}`, revision: 1, value: `Confirmed skill ${index}`, status: 'confirmed', source: { kind: 'manual' } });
    p.draft = await createTargetResume(p.profile, p.draft.target_snapshot);
    p.currentContext = { profile_signature: p.draft.base.profile_signature, source_signature: p.draft.base.source_signature, target_signature: p.draft.base.target_signature };
    render(<TargetResumePlanPanel {...p} />); await generate();
    expect(await screen.findByText('All 31 content blocks in this draft were reviewed. Nothing has been applied.')).toBeVisible();
    expect(screen.getByRole('checkbox', { name: 'Use content choice: additional-skill-25' })).not.toBeChecked();
    expect(document.querySelectorAll('[data-plan-block-id]')).toHaveLength(31);
    const payload = mocked.generate.mock.calls[0][0] as TargetResumePlanRequest;
    expect(payload.draft.document.sections.flatMap(section => section.blocks).at(-2)?.id).toBe('additional-skill-25');
    expect(JSON.stringify(payload.draft)).toContain('Confirmed skill 25'); expect(p.onApply).not.toHaveBeenCalled();
  });
  it('does not present an unavailable whole-plan response as a complete plan', async () => {
    mocked.generate.mockImplementation(async payload => ({ ...await response(payload), method: 'unavailable', complete: false, reason_code: 'context_too_large', items: [] }));
    const p = props(); render(<TargetResumePlanPanel {...p} />); await generate();
    expect(await screen.findByRole('alert')).toHaveTextContent('Nothing was cut');
    expect(screen.queryByRole('checkbox')).toBeNull(); expect(screen.queryByText(/All 5 content blocks/)).toBeNull(); expect(p.onApply).not.toHaveBeenCalled();
  });
  it('uses Chinese visible copy and clears dirty review state only after explicit dismissal', async () => {
    mocked.locale = 'zh'; const p = props(); render(<TargetResumePlanPanel {...p} />);
    fireEvent.change(screen.getByRole('combobox', { name: '篇幅目标' }), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: '生成选材建议' }));
    await screen.findByText('已覆盖本稿全部 5 个内容块，尚未应用。');
    expect(mocked.generate.mock.calls[0][0]).toMatchObject({ locale: 'zh', options: { target_pages: 2 } });
    expect(screen.getByText(/实际页数请查看导出文件/)).toBeVisible(); expect(p.onDirtyChange).toHaveBeenLastCalledWith(true);
    fireEvent.click(screen.getByRole('button', { name: '放弃本次安排' })); expect(screen.queryByRole('checkbox')).toBeNull(); expect(p.onDirtyChange).toHaveBeenLastCalledWith(false);
  });
});


describe('accepted content-plan operation records', () => {
  it('records only selected omission and compression, with a check only for rewritten text', async () => {
    mocked.generate.mockImplementation(async payload => ({ ...await response(payload), check_version: 'target-resume-source-checks-v1' }));
    const p = props(); render(<TargetResumePlanPanel {...p} />); await generate(); await reviewReady();
    expect(p.onApply).not.toHaveBeenCalled(); select('publication-one'); selectRewrite(); apply();
    const [, next, action] = vi.mocked(p.onApply).mock.calls[0];
    const records = appendTargetResumeProvenance(null, p.draft, next, action)!;
    expect(records.events).toHaveLength(1); expect(records.events[0].kind).toBe('plan');
    const changes = records.events[0].changes; expect(changes).toHaveLength(2);
    const inclusion = changes.find(item => item.field === 'included')!, text = changes.find(item => item.field === 'text')!;
    expect(inclusion.block_id).toBe('publication-one'); expect(inclusion.check).toBeNull(); expect(inclusion.after).toBe(false);
    expect(text.line_id).toBe('line-6'); expect(text.after).toBe(shorter); expect(text.check?.version).toBe('target-resume-source-checks-v1');
    expect(text.reason).toContain('mentions Python'); expect(text.target_evidence[0].quote).toBe('Python'); expect(text.source_evidence).not.toHaveLength(0);
    expect(changes.some(item => item.block_id === 'education-one')).toBe(false);
  });
  it('does not create a record for an accepted choice that changes nothing', async () => {
    const p = props(); render(<TargetResumePlanPanel {...p} />); await generate(); await reviewReady(); select('project-one'); apply();
    const [, next, action] = vi.mocked(p.onApply).mock.calls[0];
    expect(next).toEqual(p.draft); expect(appendTargetResumeProvenance(null, p.draft, next, action)).toBeNull();
  });
});
