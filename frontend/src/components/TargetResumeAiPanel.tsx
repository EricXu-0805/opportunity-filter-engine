'use client';

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useLocale } from '@/i18n/client';
import { ApiError, generateTargetResumeSuggestions } from '@/lib/api';
import { isOwnerTokenValid, onLocalOwnerStateChange, type OwnerToken } from '@/lib/identity-owner';
import {
  applyTargetResumeAI, mergeTargetResumeAIResponses, prepareTargetResumeAI, validateTargetResumeAIResponse,
  type TargetResumeAICurrentContext,
} from '@/lib/target-resume-ai';
import type { TargetResumeV1 } from '@/lib/target-resume';
import type { ProfileData } from '@/lib/types';
import type { ProfileRefreshState } from '@/lib/use-profile-refresh';
import { useProfileAction } from '@/lib/use-profile-action';
import type { PreparedTargetResumeAi, TargetResumeAiReceipt, TargetResumeAiResponse } from '@/lib/target-resume-ai-protocol';

export interface TargetResumeAiPanelProps {
  draft: TargetResumeV1;
  profile: ProfileData;
  profileAvailable?: boolean;
  profileRefresh?: ProfileRefreshState;
  readiness?: 'ready' | 'waiting' | 'blocked';
  owner: OwnerToken;
  contextKey: string;
  currentContext: TargetResumeAICurrentContext | null;
  enabled: boolean;
  onApply: (expectedCanonical: string, next: TargetResumeV1) => void;
  onDirtyChange?: (dirty: boolean) => void;
}
type Run = { prepared: PreparedTargetResumeAi; responses: TargetResumeAiResponse[] };
const button = 'rounded-lg border border-gray-300 px-3 py-2 text-sm disabled:opacity-40';
const permanent = new Set(['unit_too_large', 'context_too_large', 'target_too_large']);
const successful = (receipt: TargetResumeAiReceipt) => receipt.status !== 'skipped';

export default function TargetResumeAiPanel({ draft, profile, profileAvailable = true, profileRefresh, readiness, owner, contextKey, currentContext, enabled, onApply, onDirtyChange }: TargetResumeAiPanelProps) {
  const locale = useLocale();
  const copy = (en: string, zh: string) => locale === 'zh' ? zh : en;
  const draftKey = useMemo(() => JSON.stringify(draft), [draft]);
  const binding = `${owner.uid}:${owner.epoch}:${owner.generation}\n${contextKey}\n${draftKey}`;
  const [run, setRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<'stale' | 'applied' | 'cancelled' | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [order, setOrder] = useState(false);
  const stateRef = useRef({ binding, enabled, owner, currentContext });
  const runRef = useRef(run);
  const requestRef = useRef<{ generation: number; controller: AbortController | null; busy: boolean }>({ generation: 0, controller: null, busy: false });
  const appliedKey = useRef<string | null>(null);
  const dirtyCallback = useRef(onDirtyChange);
  useLayoutEffect(() => { dirtyCallback.current = onDirtyChange; }, [onDirtyChange]);
  useLayoutEffect(() => { runRef.current = run; }, [run]);

  useLayoutEffect(() => {
    const changed = stateRef.current.binding !== binding;
    const disabled = stateRef.current.enabled && !enabled;
    stateRef.current = { binding, enabled, owner, currentContext };
    if (!changed && !disabled && profileAvailable) return;
    const hadWork = !!runRef.current || requestRef.current.busy;
    requestRef.current.generation += 1;
    requestRef.current.controller?.abort();
    requestRef.current.busy = false;
    setBusy(false);
    // A read/readiness pause retires in-flight requests but keeps validated
    // receipts on the identical baseline. They remain disabled until ready.
    if (!changed && profileAvailable) return;
    // Actual source/document/availability changes invalidate the old advice.
    setRun(null); runRef.current = null; setSelected(new Set()); setDismissed(new Set()); setOrder(false); setError(null);
    setNotice(appliedKey.current === draftKey ? 'applied' : hadWork ? 'stale' : null);
    appliedKey.current = null;
  }, [binding, currentContext, draftKey, enabled, owner, profileAvailable]);

  useEffect(() => {
    const request = requestRef.current;
    const unsubscribe = onLocalOwnerStateChange(() => {
      if (isOwnerTokenValid(stateRef.current.owner, stateRef.current.owner.uid)) return;
      request.generation += 1; request.controller?.abort(); request.busy = false;
      setBusy(false); setRun(null); runRef.current = null; setSelected(new Set()); setDismissed(new Set()); setOrder(false); setNotice(null); setError(null);
    });
    return () => {
      request.generation += 1; request.controller?.abort(); request.busy = false;
      unsubscribe(); dirtyCallback.current?.(false);
    };
  }, []);

  const merged = run ? mergeTargetResumeAIResponses(run.prepared, run.responses) : null;
  const review = merged?.ok ? merged.value : null;
  const rewrites = review?.receipts.filter((item) => item.status === 'suggested' && typeof item.suggestion?.proposed_text === 'string'
    && item.suggestion?.proposed_text !== item.before_text && item.evidence.kind === 'experience') ?? [];
  const hasOrderAdvice = review?.receipts.some((item) => item.suggestion && item.suggestion.priority !== 'normal');
  const ready = enabled && !!currentContext && isOwnerTokenValid(owner, owner.uid);
  const live = (generation: number, expected: string) => requestRef.current.generation === generation
    && stateRef.current.binding === expected && stateRef.current.enabled
    && isOwnerTokenValid(stateRef.current.owner, stateRef.current.owner.uid);
  const reasonText = (code: string | null) => ({
    unit_too_large: copy('This item is too long for one AI review. Its full text is kept.', '此项超过单次 AI 处理范围，全文仍保留。'),
    context_too_large: copy('This item’s source context is too long. Review it manually.', '此项的来源上下文过长，请手动核对。'),
    target_too_large: copy('The target description is too long for this AI request.', '目标描述超过本次 AI 处理范围。'),
    budget_exhausted: copy('The AI allowance is used up. Continue after it becomes available.', 'AI 额度已用完，恢复后可继续。'),
    ungrounded_rewrite: copy('The proposed wording failed the source checks. Your wording is kept.', '建议未通过来源核对，保留现有表述。'),
    missing_result: copy('AI did not return this item. It remains unchanged.', 'AI 未返回此项结果，内容未变。'),
    no_target_evidence: copy('No usable target citation was returned.', '没有返回可核对的目标依据。'),
    no_change: copy('No change suggested.', '建议保留原文。'),
    invalid_response: copy('The suggestions could not be verified. Your draft is unchanged.', '无法核对这批建议，文稿未变。'),
    invalid_model_response: copy('AI returned an unusable result. Your draft is unchanged.', 'AI 返回结果不可用，文稿未变。'),
    stale_context: copy('Your materials changed. Review the current master before generating again.', '材料已变更，请核对当前母版后重新生成。'),
    stale_document: copy('Your draft changed. Generate suggestions for the latest version.', '文稿已修改，请基于最新版本重新生成建议。'),
    model_unavailable: copy('AI is unavailable. Your draft and earlier suggestions are kept.', 'AI 暂不可用，原稿及已有建议保留。'),
    timeout: copy('AI did not finish in time. Your draft is kept.', 'AI 未及时完成，原稿保留。'),
    target_changed: copy('The opportunity changed. Reopen its details and rebuild from the current target.', '机会内容已变更，请重新打开详情，再基于最新目标建稿。'),
    target_not_found: copy('This opportunity is no longer available for AI adaptation.', '此机会目前无法用于 AI 适配。'),
    document_too_large: copy('The complete draft exceeds the request limit. Its content is kept.', '完整文稿超过请求容量，内容仍保留。'),
    invalid_full_target_request: copy('The full draft could not be verified. Review your source materials before trying again.', '无法核对完整文稿，请检查来源材料后重试。'),
  } as Record<string, string>)[code ?? ''] ?? copy('This request did not finish. Your complete draft is kept.', '本次处理未完成，完整原稿保留。');

  const generate = async (resume: boolean) => {
    if (!ready || requestRef.current.busy) return;
    const generation = ++requestRef.current.generation;
    const expected = binding;
    const controller = new AbortController();
    requestRef.current.controller = controller; requestRef.current.busy = true;
    setBusy(true); setError(null); setNotice(null);
    try {
      let working = resume ? runRef.current : null;
      if (!working) {
        const prepared = await prepareTargetResumeAI(draft);
        if (!live(generation, expected)) return;
        if (!prepared.ok) { setError(prepared.code); return; }
        working = { prepared: prepared.value, responses: [] };
        setSelected(new Set()); setDismissed(new Set()); setOrder(false);
      }
      setRun(working); runRef.current = working;
      for (const batch of working.prepared.batches) {
        if (!live(generation, expected)) return;
        const coverage = mergeTargetResumeAIResponses(working.prepared, working.responses);
        if (!coverage.ok) { setError(coverage.code); return; }
        const previous = new Map(coverage.value.receipts.map((item) => [item.unit_id, item]));
        const ids = batch.filter((id) => {
          const item = previous.get(id);
          return !item || (!successful(item) && !permanent.has(item.reason_code ?? ''));
        });
        if (!ids.length) continue;
        const payload = { version: 1 as const, request_id: crypto.randomUUID(), locale: locale === 'zh' ? 'zh' as const : 'en' as const,
          draft: working.prepared.draft, document_signature: working.prepared.document_signature, selected_unit_ids: ids };
        const response = await generateTargetResumeSuggestions(payload, { owner, signal: controller.signal });
        if (!live(generation, expected)) return;
        const checked = validateTargetResumeAIResponse(working.prepared, payload, response);
        if (!checked.ok) { setError(checked.code); return; }
        working = { ...working, responses: [...working.responses, checked.value] };
        const combined = mergeTargetResumeAIResponses(working.prepared, working.responses);
        if (!combined.ok) { setError(combined.code); return; }
        setRun(working); runRef.current = working;
        const stopping = checked.value.receipts.find((item) => item.reason_code === 'budget_exhausted' || item.reason_code === 'target_too_large');
        if (stopping || checked.value.method === 'unavailable') {
          setError(stopping?.reason_code ?? checked.value.receipts.find((item) => item.status === 'skipped')?.reason_code ?? 'model_unavailable');
          return;
        }
      }
    } catch (caught) {
      if (live(generation, expected)) setError(caught instanceof ApiError && caught.status === 429 ? 'budget_exhausted'
        : caught instanceof ApiError && (caught.code === 'REQUEST_TIMEOUT' || caught.status === 504) ? 'timeout'
        : caught instanceof ApiError && ['target_changed', 'target_not_found', 'invalid_full_target_request'].includes(caught.code) ? caught.code
          : caught instanceof ApiError && caught.status === 413 ? 'document_too_large' : 'model_unavailable');
    } finally {
      if (requestRef.current.generation === generation) { requestRef.current.busy = false; requestRef.current.controller = null; setBusy(false); }
    }
  };
  const action = useProfileAction<'start' | 'continue'>({
    isOpen: true, profile, profileAvailable, scopeKey: binding, editRevision: draftKey,
    refresh: profileRefresh, readiness: readiness ?? (enabled ? 'ready' : 'blocked'),
    execute: (intent) => { void generate(intent === 'continue'); },
  });
  const working = busy || action.busy;
  const dirty = working || (!!run && (order || hasOrderAdvice || rewrites.some((item) => !dismissed.has(item.unit_id))));
  useEffect(() => { dirtyCallback.current?.(dirty); }, [dirty]);
  const cancel = () => {
    action.cancel();
    requestRef.current.generation += 1; requestRef.current.controller?.abort(); requestRef.current.busy = false;
    setBusy(false); setNotice('cancelled');
  };
  const apply = () => {
    if (!run || !ready || working || action.error || !currentContext) return;
    const result = applyTargetResumeAI(run.prepared, draft, run.responses,
      { rewriteUnitIds: [...selected], applyStructure: order, currentContext });
    if (!result.ok) { setError(result.code); return; }
    appliedKey.current = JSON.stringify(result.value);
    if (appliedKey.current === draftKey) { setNotice('applied'); setRun(null); runRef.current = null; setSelected(new Set()); setOrder(false); }
    onApply(run.prepared.canonical_draft, result.value);
  };
  const nextPreview = run && ready && !working && !action.error && currentContext && (selected.size > 0 || order)
    ? applyTargetResumeAI(run.prepared, draft, run.responses, { rewriteUnitIds: [...selected], applyStructure: order, currentContext }) : null;
  const canContinue = !!run && (review?.coverage.pending || review?.receipts.some((item) => item.status === 'skipped' && !permanent.has(item.reason_code ?? '')));
  const unitLabel = (id: string) => {
    const unit = run?.prepared.units.find((item) => item.unit_id === id);
    return unit?.label || (unit?.role === 'experience' ? copy('Experience', '经历') : unit?.role ?? id);
  };
  const fullPreview = (value: TargetResumeV1, title: string) => <section aria-label={title} className="min-w-0 rounded-lg border p-3">
    <h4 className="font-medium">{title}</h4>
    {value.document.sections.filter((section) => section.included).map((section) => <div key={section.id} className="mt-3">
      <h5 className="text-sm font-medium">{section.heading || ({ basics: copy('Contact', '基本信息'), education: copy('Education', '教育'), activities: copy('Experience and projects', '经历与项目'), publications: copy('Publications', '论文'), skills: copy('Skills', '技能'), other: copy('Other', '其他') } as Record<string, string>)[section.kind] || section.kind}</h5>
      {section.blocks.filter((block) => block.included).map((block) => <div key={block.id} className="mt-2 space-y-1">
        {block.lines.filter((line) => line.included).map((line) => <p key={line.id} className="whitespace-pre-wrap break-words text-sm">{line.text}</p>)}
      </div>)}
    </div>)}
  </section>;

  return <section aria-label="AI adaptation suggestions" className="my-5 min-w-0 rounded-xl border border-indigo-200 p-4">
    <h3 className="font-semibold">{copy('AI adaptation', 'AI 定向调整')}</h3>
    <p className="mt-1 text-sm text-gray-600">{copy('Review suggestions before applying them. Facts stay linked to your confirmed master. Reasons and rejected suggestions are kept only while this workspace is open.', '核对建议后再应用。事实仍关联已确认母版；修改理由和拒绝记录仅在本次打开期间保留。')}</p>
    {!ready && <p className="mt-2 text-sm text-amber-800">{copy('Use a draft based on your current confirmed profile and target to generate AI suggestions.', '请使用基于当前已确认资料及目标的文稿生成 AI 建议。')}</p>}
    <div className="mt-3 flex flex-wrap gap-2">
      <button type="button" className={button} disabled={!ready || working} onClick={() => action.request('start')}>{copy('Generate AI suggestions', '生成 AI 建议')}</button>
      {canContinue && <button type="button" className={button} disabled={!ready || working} onClick={() => action.request('continue')}>{copy('Continue remaining suggestions', '继续处理未完成项')}</button>}
      {working && <button type="button" className={button} onClick={cancel}>{copy('Cancel generation', '停止生成')}</button>}
    </div>
    {action.busy && <p role="status" className="mt-2 text-sm">{copy('Checking current profile before AI review…', 'AI 核对前正在检查最新资料…')}</p>}
    {action.error && <p role="alert" className="mt-2 text-sm text-amber-800">{action.error === 'changed' ? copy('Your draft, profile or target changed during the check. Review the current materials before trying again.', '核对期间文稿、资料或目标已变更，请核对当前材料后再试。') : copy('Current profile could not be verified. Your draft and completed suggestions are kept.', '未能核对当前资料。文稿及已完成建议保留。')}</p>}
    {busy && <p role="status" className="mt-2 text-sm">{copy('Reviewing your complete materials…', '正在核对完整材料…')}</p>}
    {error && <p role="alert" className="mt-3 rounded-lg bg-amber-50 p-3 text-sm">{reasonText(error)}</p>}
    {notice && <p role="status" className="mt-2 text-sm">{notice === 'applied'
      ? copy('Selected changes applied locally. Review the complete draft and save when ready.', '已将所选修改应用到本地稿。核对全文后再保存。')
      : notice === 'stale' ? copy('Your draft, profile or target changed. Earlier suggestions were discarded; your edits are kept.', '文稿、资料或目标已变更，旧建议已作废，手动编辑保留。')
        : copy('Generation stopped. Your draft and completed suggestions are kept.', '已停止生成，原稿及已完成建议保留。')}</p>}
    {review && <>
      <p role="status" className="mt-3 text-sm">{copy(`Reviewed ${review.coverage.processed} of ${review.coverage.total} items; ${review.coverage.pending} pending, ${review.coverage.skipped} unprocessed.`,
        `已核对 ${review.coverage.processed}/${review.coverage.total} 项；${review.coverage.pending} 项待处理，${review.coverage.skipped} 项未完成。`)}</p>
      {review.receipts.filter((item) => item.status === 'skipped').map((item) => <p key={item.unit_id} className="mt-2 break-words text-sm text-amber-800">{unitLabel(item.unit_id)}: {reasonText(item.reason_code)}</p>)}
      <details className="mt-3 rounded-lg border p-3"><summary className="cursor-pointer text-sm font-medium">{copy('Content priorities and target evidence', '内容优先级与目标依据')}</summary>
        {review.receipts.filter((item) => item.status !== 'skipped').map((item) => <div key={item.unit_id} className="mt-3 min-w-0 border-t pt-3 text-sm">
          <p className="whitespace-pre-wrap break-words">{run?.prepared.units.find((unit) => unit.unit_id === item.unit_id)?.original}</p>
          <p className="mt-1 text-xs font-medium">{copy('Content priority', '内容优先级')}: {item.suggestion?.priority === 'high' ? copy('High', '高') : item.suggestion?.priority === 'low' ? copy('Low', '低') : copy('Normal', '普通')}</p>
          <p className="mt-1 whitespace-pre-wrap break-words text-gray-600">{item.suggestion?.reason || reasonText(item.reason_code)}</p>
          {item.suggestion?.target_evidence.map((evidence, index) => <blockquote key={index} className="mt-1 whitespace-pre-wrap break-words border-l-2 border-indigo-200 pl-2">{evidence.quote}</blockquote>)}
        </div>)}
      </details>
      <label className="mt-3 flex items-start gap-2 text-sm"><input type="checkbox" checked={order} disabled={!ready || working || !!action.error || !review.structureReady}
        onChange={(event) => setOrder(event.target.checked)} />{copy('Use suggested section and block order', '使用建议的章节与内容块顺序')}</label>
      {!review.structureReady && <p className="mt-1 text-xs text-gray-500">{copy('Ordering is available after every content item has a usable review.', '所有内容项核对完成后，才能应用整稿排序。')}</p>}
      {rewrites.map((item) => <article key={item.unit_id} className="mt-4 min-w-0 rounded-lg border p-3" aria-label={`AI rewrite ${item.unit_id}`}>
        <label className="flex items-start gap-2 text-sm font-medium"><input type="checkbox" aria-label={`Use rewrite: ${item.unit_id}`}
          checked={selected.has(item.unit_id)} disabled={!ready || working || !!action.error || dismissed.has(item.unit_id)} onChange={(event) => setSelected((old) => {
            const next = new Set(old); if (event.target.checked) next.add(item.unit_id); else next.delete(item.unit_id); return next;
          })} />{unitLabel(item.unit_id)}</label>
        <div className="mt-3 grid min-w-0 gap-3 md:grid-cols-2">
          <div className="min-w-0"><h4 className="text-xs text-gray-500">{copy('Current wording', '当前表述')}</h4><p className="mt-1 whitespace-pre-wrap break-words text-sm">{item.before_text}</p></div>
          <div className="min-w-0"><h4 className="text-xs text-gray-500">{copy('Suggested wording — check the facts', '建议表述——请核对事实')}</h4><p className="mt-1 whitespace-pre-wrap break-words text-sm">{item.suggestion!.proposed_text}</p></div>
        </div>
        <p className="mt-2 whitespace-pre-wrap break-words text-sm text-gray-600">{item.suggestion!.reason}</p>
        {item.suggestion!.target_evidence.map((evidence, index) => <blockquote key={index} className="mt-2 whitespace-pre-wrap break-words border-l-2 border-indigo-200 pl-2 text-sm">{evidence.quote}</blockquote>)}
        <button type="button" className={`${button} mt-2`} disabled={working} aria-label={`Dismiss suggestion: ${item.unit_id}`} onClick={() => {
          setDismissed((old) => { const next = new Set(old); if (next.has(item.unit_id)) next.delete(item.unit_id); else next.add(item.unit_id); return next; });
          setSelected((old) => { const next = new Set(old); next.delete(item.unit_id); return next; });
        }}>{dismissed.has(item.unit_id) ? copy('Review again', '重新核对') : copy('Reject this wording', '拒绝此表述')}</button>
      </article>)}
      {nextPreview?.ok && <details className="mt-4"><summary className="cursor-pointer text-sm font-medium">{copy('Preview complete résumé before applying', '应用前对比完整简历')}</summary>
        <div className="mt-3 grid min-w-0 gap-3 lg:grid-cols-2">{fullPreview(draft, copy('Before AI changes', '应用前全文'))}{fullPreview(nextPreview.value, copy('After selected AI changes', '应用所选建议后全文'))}</div>
      </details>}
      <button type="button" className={`${button} mt-4 bg-indigo-600 text-white`} disabled={!ready || working || !!action.error || (!order && selected.size === 0)} onClick={apply}>{copy('Apply selected suggestions', '应用所选建议')}</button>
    </>}
  </section>;
}
