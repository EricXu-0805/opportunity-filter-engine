'use client';

import { targetResumeEvidenceLabel } from '@/lib/target-resume-evidence';

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useLocale } from '@/i18n/client';
import { ApiError, generateTargetResumePlan } from '@/lib/api';
import { isOwnerTokenValid, onLocalOwnerStateChange } from '@/lib/identity-owner';
import { useProfileAction } from '@/lib/use-profile-action';
import { applyTargetResumePlan, measureTargetResumeLength, prepareTargetResumePlan, validateTargetResumePlanResponse } from '@/lib/target-resume-plan';
import type { PreparedTargetResumePlan, TargetResumePlanRequest, TargetResumePlanResponse } from '@/lib/target-resume-plan-protocol';
import type { TargetResumeProvenanceAnnotation } from '@/lib/target-resume-provenance';
import type { TargetResumeV1 } from '@/lib/target-resume';
import type { TargetResumeAiPanelProps } from './TargetResumeAiPanel';

export type TargetResumePlanPanelProps = TargetResumeAiPanelProps;
type Review = { prepared: PreparedTargetResumePlan; response: TargetResumePlanResponse };
const authorityRefusals = new Set(['target_changed', 'target_not_found', 'TARGET_NOT_ACTIONABLE', 'legacy_target_context']);
const button = 'rounded-lg border border-gray-300 px-3 py-2 text-sm disabled:opacity-40';
const toggle = (values: Set<string>, id: string, checked: boolean) => {
  const next = new Set(values); if (checked) next.add(id); else next.delete(id); return next;
};

export default function TargetResumePlanPanel({ supportGroups, draft, profile, profileAvailable = true, profileRefresh, target, targetRefresh, readiness, owner, contextKey, currentContext, enabled, onApply, onDirtyChange, onAuthorityRefusal }: TargetResumePlanPanelProps) {
  const locale = useLocale();
  const copy = (en: string, zh: string) => locale === 'zh' ? zh : en;
  const [pages, setPages] = useState<1 | 2>(1);
  const draftKey = useMemo(() => JSON.stringify(draft), [draft]);
  const binding = `${owner.uid}:${owner.epoch}:${owner.generation}\n${contextKey}\n${draftKey}\n${pages}\n${JSON.stringify(supportGroups ?? null)}`;
  const [review, setReview] = useState<Review | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<'stale' | 'applied' | 'cancelled' | null>(null);
  const [selections, setSelections] = useState<Set<string>>(new Set());
  const [rewrites, setRewrites] = useState<Set<string>>(new Set());
  const state = useRef({ binding, enabled, owner });
  const reviewRef = useRef(review);
  const operation = useRef<{ generation: number; controller: AbortController | null; busy: boolean }>({ generation: 0, controller: null, busy: false });
  const appliedKey = useRef<string | null>(null);
  const dirtyCallback = useRef(onDirtyChange);
  useLayoutEffect(() => { dirtyCallback.current = onDirtyChange; }, [onDirtyChange]);
  useLayoutEffect(() => { reviewRef.current = review; }, [review]);
  useLayoutEffect(() => {
    const changed = state.current.binding !== binding;
    const paused = state.current.enabled && !enabled;
    state.current = { binding, enabled, owner };
    if (!changed && !paused && profileAvailable) return;
    const hadWork = !!reviewRef.current || operation.current.busy;
    operation.current.generation += 1; operation.current.controller?.abort(); operation.current.busy = false;
    setBusy(false);
    // A temporary readiness check can retain only the identical verified plan.
    if (!changed && profileAvailable) return;
    setReview(null); reviewRef.current = null; setSelections(new Set()); setRewrites(new Set()); setError(null);
    setNotice(appliedKey.current === draftKey ? 'applied' : hadWork ? 'stale' : null); appliedKey.current = null;
  }, [binding, draftKey, enabled, owner, profileAvailable]);
  useEffect(() => {
    const request = operation.current;
    const unsubscribe = onLocalOwnerStateChange(() => {
      if (isOwnerTokenValid(state.current.owner, state.current.owner.uid)) return;
      request.generation += 1; request.controller?.abort(); request.busy = false;
      setBusy(false); setReview(null); reviewRef.current = null; setSelections(new Set()); setRewrites(new Set()); setNotice(null); setError(null);
    });
    return () => {
      request.generation += 1; request.controller?.abort(); request.busy = false;
      unsubscribe(); dirtyCallback.current?.(false);
    };
  }, []);
  const ready = enabled && !!currentContext && isOwnerTokenValid(owner, owner.uid);
  const live = (generation: number, expected: string) => operation.current.generation === generation
    && state.current.binding === expected && state.current.enabled && isOwnerTokenValid(state.current.owner, state.current.owner.uid);
  const reason = (code: string | null) => ({
    context_too_large: copy('The complete materials exceed this request’s limit. Nothing was cut; your draft is kept.', '完整材料超过本次处理容量，内容没有截断，原稿保留。'),
    target_too_large: copy('The opportunity details exceed this request’s limit. Your draft is kept.', '机会资料超过本次处理容量，原稿保留。'),
    no_plan_items: copy('This draft has no content blocks to plan beyond contact details.', '本稿除基本信息外，没有可安排的内容块。'),
    budget_exhausted: copy('The AI allowance is used up. Your draft and any earlier plan are kept.', 'AI 额度已用完，原稿及已有安排保留。'),
    timeout: copy('The plan did not finish in time. Your draft and any earlier plan are kept.', '选材未及时完成，原稿及已有安排保留。'),
    invalid_response: copy('The complete plan could not be verified. Your draft is unchanged.', '无法核对完整选材安排，文稿未变。'),
    invalid_model_response: copy('The complete plan could not be verified. Your draft is unchanged.', '无法核对完整选材安排，文稿未变。'),
    no_target_evidence: copy('The plan lacks a verifiable opportunity citation. Your draft is unchanged.', '选材缺少可核对的机会依据，文稿未变。'),
    no_source_evidence: copy('The plan lacks a verifiable source citation. Your draft is unchanged.', '选材缺少可核对的经历原文，文稿未变。'),
    stale_document: copy('Your draft changed. Generate a plan for the current version.', '文稿已修改，请基于当前版本重新生成选材安排。'),
    stale_context: copy('Your materials or target changed. Review them before generating again.', '资料或目标已变更，请核对后重新生成。'),
    stale_options: copy('The length target changed. Generate a new plan.', '篇幅目标已变更，请重新生成选材安排。'),
    target_changed: copy('The opportunity changed. Reopen its details before generating again.', '机会已变更，请重新打开详情后再生成。'),
    target_not_found: copy('This opportunity is unavailable for AI planning.', '此机会目前无法用于 AI 选材。'),
    TARGET_NOT_ACTIONABLE: copy('This opportunity is currently unavailable for résumé planning. The old plan was cleared; your draft is kept.', '此机会目前不能用于简历选材，旧安排已作废，文稿保留。'),
    legacy_target_context: copy('This older draft lacks complete opportunity requirements. Rebuild before AI planning.', '旧稿缺少完整机会要求，请重新创建后再用 AI 选材。'),
    document_too_large: copy('The complete draft exceeds this request’s limit. Nothing was cut.', '完整稿超过请求容量，内容没有截断。'),
  } as Record<string, string>)[code ?? ''] ?? copy('The plan is unavailable. Your draft and any earlier plan are kept.', '暂未完成选材，原稿及已有安排保留。');
  const generate = async () => {
    if (!ready || operation.current.busy) return;
    const generation = ++operation.current.generation, expected = binding;
    const controller = new AbortController(); operation.current.controller = controller; operation.current.busy = true;
    setBusy(true); setError(null); setNotice(null);
    try {
      const prepared = await prepareTargetResumePlan(draft, { target_pages: pages }, supportGroups);
      if (!live(generation, expected)) return;
      if (!prepared.ok) { setError(prepared.code); return; }
      const payload: TargetResumePlanRequest = { version: 1, request_id: crypto.randomUUID(), locale: locale === 'zh' ? 'zh' : 'en',
        draft: prepared.value.draft, document_signature: prepared.value.document_signature, options: prepared.value.options, ...(prepared.value.support_groups === undefined ? {} : {support_groups:prepared.value.support_groups}) };
      const response = await generateTargetResumePlan(payload, { owner, signal: controller.signal });
      if (!live(generation, expected)) return;
      const checked = validateTargetResumePlanResponse(prepared.value, payload, response);
      if (!checked.ok) { setError(checked.code); return; }
      if (checked.value.method !== 'ai' || !checked.value.complete) { setError(checked.value.reason_code ?? 'invalid_response'); return; }
      const next = { prepared: prepared.value, response: checked.value };
      setReview(next); reviewRef.current = next; setSelections(new Set()); setRewrites(new Set());
    } catch (caught) {
      if (!live(generation, expected)) return;
      if (caught instanceof ApiError && authorityRefusals.has(caught.code)) {
        // A server refusal invalidates the authority behind the earlier plan,
        // even when the caller's cached target and document are unchanged.
        reviewRef.current = null; setReview(null); setSelections(new Set()); setRewrites(new Set()); appliedKey.current = null;
        setError(caught.code); onAuthorityRefusal?.(caught.code);
      } else setError(caught instanceof ApiError && caught.status === 429 ? 'budget_exhausted'
        : caught instanceof ApiError && (caught.code === 'REQUEST_TIMEOUT' || caught.status === 504) ? 'timeout'
          : caught instanceof ApiError && caught.status === 413 ? 'document_too_large' : 'model_unavailable');
    } finally {
      if (operation.current.generation === generation) { operation.current.busy = false; operation.current.controller = null; setBusy(false); }
    }
  };
  const action = useProfileAction<'generate'>({ isOpen: true, profile, profileAvailable, scopeKey: binding, editRevision: binding,
    refresh: profileRefresh, target, targetRefresh, readiness: readiness ?? (enabled ? 'ready' : 'blocked'), execute: () => { void generate(); } });
  const working = busy || action.busy;
  const dirty = working || !!review;
  useEffect(() => { dirtyCallback.current?.(dirty); }, [dirty]);
  const cancel = () => {
    action.cancel(); operation.current.generation += 1; operation.current.controller?.abort(); operation.current.busy = false;
    setBusy(false); setNotice('cancelled');
  };
  const hasSelection = selections.size > 0 || rewrites.size > 0;
  const options = currentContext ? { selection_block_ids: [...selections], rewrite_unit_ids: [...rewrites], current_context: currentContext, options: { target_pages: pages }, ...(supportGroups === undefined ? {} : {support_groups:supportGroups}) } : null;
  const preview = review && ready && !working && !action.error && hasSelection && options
    ? applyTargetResumePlan(review.prepared, draft, review.response, options) : null;
  const apply = () => {
    if (!review || reviewRef.current !== review || !ready || working || action.error || !options || !hasSelection) return;
    const result = applyTargetResumePlan(review.prepared, draft, review.response, options);
    if (!result.ok) { setError(result.code); return; }
    appliedKey.current = JSON.stringify(result.value);
    if (appliedKey.current === draftKey) { setNotice('applied'); setReview(null); reviewRef.current = null; setSelections(new Set()); setRewrites(new Set()); }
    const annotations: TargetResumeProvenanceAnnotation[] = [];
    for (const item of review.response.items) {
      if (selections.has(item.block_id)) annotations.push({ section_id: item.section_id, block_id: item.block_id, line_id: null,
        field: 'included', reason: item.reason, target_evidence: item.target_evidence, source_evidence: item.source_evidence, check: null });
      for (const rewrite of item.rewrites) {
        if (!rewrites.has(rewrite.unit_id) || rewrite.status !== 'suggested') continue;
        const line = review.prepared.draft.document.sections.find(section => section.id === item.section_id)?.blocks
          .find(block => block.id === item.block_id)?.lines.find(line => line.id === rewrite.unit_id);
        if (!line) { setError('invalid_response'); return; }
        annotations.push({ section_id: item.section_id, block_id: item.block_id, line_id: line.id, field: 'text',
          reason: item.reason, target_evidence: item.target_evidence, source_evidence: rewrite.source_evidence ?? item.source_evidence,
          check: review.response.check_version ? { version: review.response.check_version, pipeline_version: review.response.pipeline_version,
            request_id: review.response.request_id, document_signature: review.response.document_signature, original: line.original, evidence: line.evidence } : null });
      }
    }
    onApply(review.prepared.canonical_draft, result.value, { kind: 'plan', annotations });
  };
  const sectionTitle = (section: TargetResumeV1['document']['sections'][number]) => section.heading || ({
    basics: copy('Contact', '基本信息'), education: copy('Education', '教育'), activities: copy('Experience and projects', '经历与项目'),
    publications: copy('Publications', '论文'), skills: copy('Skills', '技能'), other: copy('Other', '其他'),
  })[section.kind];
  const fullPreview = (value: TargetResumeV1, title: string) => <section aria-label={title} className="min-w-0 rounded-lg border p-3">
    <h4 className="font-medium">{title}</h4>
    {value.document.sections.filter(section => section.included).map(section => <div key={section.id} className="mt-3">
      <h5 className="text-sm font-medium">{sectionTitle(section)}</h5>
      {section.blocks.filter(block => block.included).map(block => <div key={block.id} className="mt-2 space-y-1">
        {block.lines.filter(line => line.included).map(line => <p key={line.id} className="whitespace-pre-wrap break-words text-sm">{line.text}</p>)}
      </div>)}
    </div>)}
  </section>;
  return <section aria-label={copy('Résumé content plan', '简历选材')} className="my-5 min-w-0 rounded-xl border border-indigo-200 p-4">
    <h3 className="font-semibold">{copy('Résumé content plan', '简历选材')}</h3>
    <p className="mt-1 text-sm text-gray-600">{copy('Review what to keep, shorten or leave out of this draft. Content choices and shorter wording need separate approval. Reasons for applied changes are saved with the draft. Unapplied advice stays only in this workspace.', '核对本稿哪些内容保留、压缩或暂不选用。选材安排与短稿分开确认；已应用修改的理由随文稿保存；未应用建议仅在当前工作区保留。')}</p>
    <div className="mt-3 flex flex-wrap items-center gap-3">
      <label className="text-sm">{copy('Length target', '篇幅目标')}<select aria-label={copy('Length target', '篇幅目标')} className={`${button} ml-2`} value={pages} disabled={!isOwnerTokenValid(owner, owner.uid)}
        onChange={event => setPages(event.target.value === '2' ? 2 : 1)}><option value="1">{copy('1 page', '1 页')}</option><option value="2">{copy('2 pages', '2 页')}</option></select></label>
      <p className="text-sm" data-testid="plan-current-length">{copy(`Current selected text: ${measureTargetResumeLength(draft)} characters`, `当前选用正文：${measureTargetResumeLength(draft)} 字符`)}</p>
    </div>
    <p className="mt-1 text-xs text-gray-500">{copy('This is a length target, not a page guarantee. Character counts exclude headings and labels; check the exported file for actual pages.', '页数只是目标，不是保证。字符数不含标题和字段标签，实际页数请查看导出文件。')}</p>
    {!ready && <p className="mt-2 text-sm text-amber-800">{copy('Use current, verified profile and opportunity materials before planning.', '请先核对当前资料和机会，再生成选材安排。')}</p>}
    <div className="mt-3 flex flex-wrap gap-2">
      <button type="button" className={button} disabled={!ready || working} onClick={() => action.request('generate')}>{copy('Generate content plan', '生成选材建议')}</button>
      {working && <button type="button" className={button} onClick={cancel}>{copy('Cancel planning', '停止选材')}</button>}
      {review && <button type="button" className={button} disabled={working} onClick={() => { setReview(null); reviewRef.current = null; setSelections(new Set()); setRewrites(new Set()); setError(null); setNotice(null); }}>{copy('Dismiss this plan', '放弃本次安排')}</button>}
    </div>
    {action.busy && <p role="status" className="mt-2 text-sm">{copy('Checking current materials before planning…', '选材前正在核对最新资料…')}</p>}
    {busy && <p role="status" className="mt-2 text-sm">{copy('Reviewing every content block in this draft…', '正在核对本稿全部内容块…')}</p>}
    {action.error && <p role="alert" className="mt-2 text-sm text-amber-800">{action.error === 'changed'
      ? copy('The draft, materials or length target changed during the check. Review them before trying again.', '核对期间文稿、资料或篇幅目标已变更，请核对后重试。')
      : copy('Current materials could not be verified. Your draft and any earlier plan are kept.', '未能核对当前资料，文稿及已有安排保留。')}</p>}
    {error && <p role="alert" className="mt-3 rounded-lg bg-amber-50 p-3 text-sm">{reason(error)}</p>}
    {notice && <p role="status" className="mt-2 text-sm">{notice === 'applied' ? copy('Selected changes applied locally. Review the draft, then save.', '已应用到本地稿，请核对后保存。')
      : notice === 'stale' ? copy('The draft, materials or length target changed. The old plan was cleared; your edits are kept.', '文稿、资料或篇幅目标已变更，旧安排已作废，编辑保留。')
        : copy('Planning stopped. Your draft and any earlier plan are kept.', '已停止选材，文稿及已有安排保留。')}</p>}
    {review && <>
      <p role="status" className="mt-3 text-sm">{copy(`All ${review.response.manifest.length} content blocks in this draft were reviewed. Nothing has been applied.`, `已覆盖本稿全部 ${review.response.manifest.length} 个内容块，尚未应用。`)}</p>
      <details className="mt-3 rounded-lg border p-3"><summary className="cursor-pointer text-sm font-medium">{copy('Materials outside this draft', '未进入本稿的材料')}</summary>
        <ul className="mt-2 space-y-1 text-sm">
          <li>{copy(`Confirmed experiences outside this draft: ${review.response.scope.unreferenced_experience_ids.length}`, `未进入本稿的已确认经历：${review.response.scope.unreferenced_experience_ids.length}`)}</li>
          <li>{copy(`Pending experiences: ${review.response.scope.pending_experience_ids.length}`, `待确认经历：${review.response.scope.pending_experience_ids.length}`)}</li>
          <li>{copy(`Outdated confirmed experiences: ${review.response.scope.stale_experience_ids.length}`, `已失效的确认经历：${review.response.scope.stale_experience_ids.length}`)}</li>
          <li>{copy(`Unmapped source ranges: ${review.response.scope.unmapped_range_count}`, `未映射原文片段：${review.response.scope.unmapped_range_count}`)}</li>
        </ul>
        {review.response.scope.unreferenced_experience_ids.map(id => { const entry=review.prepared.draft.base_snapshot.experience_entries.find(item=>item.id===id);return entry ? <pre key={id} className="mt-2 whitespace-pre-wrap break-words rounded-lg border bg-white p-3 font-sans text-sm">{entry.text}</pre> : null; })}
        <p className="mt-2 text-xs text-gray-500">{copy('These materials are outside the plan. Review your master résumé to add or confirm them.', '以上材料不在本次选材范围内，可回母版补充或确认。')}</p>
      </details>
      {review.response.items.map(item => {
        const section = review.prepared.draft.document.sections.find(value => value.id === item.section_id)!;
        const block = section.blocks.find(value => value.id === item.block_id)!;
        const title = block.lines.find(line => line.role === 'title')?.text || sectionTitle(section);
        return <article key={item.block_id} data-plan-block-id={item.block_id} className="mt-4 min-w-0 rounded-lg border p-3">
          <h4 className="break-words font-medium">{title}</h4>
          <p className="mt-1 text-sm font-medium">{copy('Suggestion', '建议')}：{item.action === 'keep' ? copy('Keep', '保留') : item.action === 'compress' ? copy('Shorten', '压缩') : copy('Leave out for now', '暂不选用')}</p>
          <details className="mt-2 text-sm"><summary className="cursor-pointer">{copy('Review reason and sources', '查看理由和依据')}</summary>
          <p className="mt-2 whitespace-pre-wrap break-words text-sm">{item.reason}</p>
          <div className="mt-2 space-y-2 text-sm">
            <p className="font-medium">{copy('Opportunity evidence', '机会依据')}</p>
            {item.target_evidence.map((evidence, index) => <blockquote key={index} className="whitespace-pre-wrap break-words border-l-2 border-indigo-200 pl-2">{targetResumeEvidenceLabel(evidence, locale)}: {evidence.quote}</blockquote>)}
            <p className="font-medium">{copy('Source evidence', '原文依据')}</p>
            {item.source_evidence.map((evidence, index) => <blockquote key={index} className="whitespace-pre-wrap break-words border-l-2 border-gray-200 pl-2">{evidence.quote}</blockquote>)}
          </div>
          </details>
          <details className="mt-3"><summary className="cursor-pointer text-sm">{copy('Read complete original and current text', '查看完整原文与当前稿')}</summary>
            <div className="mt-2 grid min-w-0 gap-3 md:grid-cols-2">{(['original', 'text'] as const).map(field => <div key={field} className="min-w-0 rounded-lg bg-gray-50 p-3">
              <h5 className="text-sm font-medium">{field === 'original' ? copy('Original source', '完整原文') : copy('Current draft', '当前稿')}</h5>
              {block.lines.map(line => <p key={line.id} className="mt-2 whitespace-pre-wrap break-words text-sm">{line[field]}</p>)}
            </div>)}</div>
          </details>
          {!section.included && <p className="mt-2 text-sm text-amber-800">{copy('This section is hidden. Selecting its block does not restore the section; it stays out of the export until you include the section in the editor.', '此章节未选用。重新选用内容块不会恢复整章，需在编辑器选用该章节后才会导出。')}</p>}
          {block.lines.some(line => !line.included) && <p className="mt-2 text-xs text-gray-600">{copy('Hidden fields stay hidden. This choice does not change field selections.', '未选用的字段保持不选用，此安排不改变字段选择。')}</p>}
          <label className="mt-3 flex items-start gap-2 text-sm"><input type="checkbox" aria-label={`Use content choice: ${item.block_id}`} checked={selections.has(item.block_id)} disabled={!ready || working || !!action.error}
            onChange={event => setSelections(old => toggle(old, item.block_id, event.target.checked))} />{!block.included && item.action !== 'omit' ? copy('Re-include this block using this choice', '采用此安排，重新选用内容块') : copy('Use this content choice', '采用这项选材安排')}</label>
          {item.action === 'compress' && <p className="mt-2 text-xs text-gray-600">{copy('Shorter wording is optional below. Selecting the content choice alone keeps the current text.', '短稿需在下方另行确认。只采用选材安排会保留当前表述。')}</p>}
          {item.rewrites.map(rewrite => <div key={rewrite.unit_id} className="mt-3 rounded-lg border p-3" data-plan-rewrite-id={rewrite.unit_id}>
            {rewrite.status === 'suggested' ? <>
              <h5 className="text-sm font-medium">{rewrite.source_evidence ? copy('Combined wording — check the facts', '合并表述：请核对事实') : copy('Shorter wording — check the facts', '短稿：请核对事实')}</h5>
              <p className="mt-2 whitespace-pre-wrap break-words text-sm">{rewrite.proposed_text}</p>
              <label className="mt-2 flex items-start gap-2 text-sm"><input type="checkbox" aria-label={`Use shorter wording: ${rewrite.unit_id}`} checked={rewrites.has(rewrite.unit_id)} disabled={!ready || working || !!action.error}
                onChange={event => setRewrites(old => toggle(old, rewrite.unit_id, event.target.checked))} />{rewrite.source_evidence ? copy('Use this combined wording', '采用这条合并表述') : copy('Use this shorter wording only', '采用这条短稿')}</label>
              <p className="mt-1 text-xs text-gray-500">{copy('This changes wording only; it does not select a hidden block, section or field.', '仅修改表述，不会重新选用隐藏的内容块、章节或字段。')}</p>
            </> : <p className="text-sm text-amber-800">{rewrite.reason_code === 'not_shorter' ? copy('The candidate was not shorter. Current wording is kept.', '候选表述没有更短，保留当前稿。') : copy('The candidate failed source checks. Current wording is kept.', '候选短稿未通过来源核对，保留当前稿。')}</p>}
          </div>)}
        </article>;
      })}
      <p className="mt-4 text-sm" data-testid="plan-preview-length">{copy(`Preview selected text: ${measureTargetResumeLength(preview?.ok ? preview.value : draft)} characters`, `预览选用正文：${measureTargetResumeLength(preview?.ok ? preview.value : draft)} 字符`)}</p>
      {preview && !preview.ok && <p role="alert" className="mt-2 text-sm text-amber-800">{reason(preview.code)}</p>}
      <details className="mt-3"><summary className="cursor-pointer text-sm font-medium">{copy('Compare complete draft before applying', '应用前对比完整稿')}</summary>
        <div className="mt-3 grid min-w-0 gap-3 lg:grid-cols-2">{fullPreview(draft, copy('Before content choices', '选材前全文'))}{fullPreview(preview?.ok ? preview.value : draft, copy('After selected content choices', '采用所选安排后全文'))}</div>
      </details>
      <button type="button" className={`${button} mt-4 bg-indigo-600 text-white`} disabled={!ready || working || !!action.error || !preview?.ok} onClick={apply}>{copy('Apply selected content choices', '应用所选安排')}</button>
    </>}
  </section>;
}
