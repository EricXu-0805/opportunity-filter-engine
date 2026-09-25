'use client';

import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { useLocale } from '@/i18n/client';
import type { OwnerToken } from '@/lib/identity-owner';
import type { ProfileViewSnapshot } from '@/lib/profile-sync';
import { SUPPLEMENT_ANSWER_KEYS, previewSupplement, type SupplementAnswers, type SupplementAnswerKey, type SupplementDraft } from '@/lib/resume-supplement';
import { useResumeSupplement } from './use-resume-supplement';

export interface ResumeSupplementPanelProps {
  owner: OwnerToken;
  targetKey: string;
  profileAvailable?: boolean;
  onDirtyChange?: (dirty: boolean) => void;
  onAcceptedProfile?: (view: ProfileViewSnapshot, againstView: ProfileViewSnapshot) => void;
  onOpenProfile?: () => void;
}
const emptyAnswers = (): SupplementAnswers => ({ task: '', method: '', personalRole: '', outcome: '', outcomeBasis: '' });
const button = 'rounded-lg border border-gray-300 px-3 py-2 text-sm disabled:opacity-40';

/** A real identity change clears private answers synchronously. A target-content
 * change keeps them for explicit review; changing opportunity IDs remounts the
 * parent workspace. Folding this panel should hide it, not unmount its draft. */
export default function ResumeSupplementPanel(props: ResumeSupplementPanelProps) {
  const ownerKey = JSON.stringify([props.owner.uid, props.owner.epoch, props.owner.generation]);
  return <SupplementSession key={ownerKey} {...props} />;
}

function SupplementSession({ owner, targetKey, profileAvailable = true, onDirtyChange, onAcceptedProfile, onOpenProfile }: ResumeSupplementPanelProps) {
  const locale = useLocale();
  const copy = (en: string, zh: string) => locale === 'zh' ? zh : en;
  const id = useId();
  const controller = useResumeSupplement({ enabled: true, profileAvailable, owner, targetKey, onAcceptedProfile });
  const [entryId, setEntryId] = useState(() => crypto.randomUUID());
  const [activityId, setActivityId] = useState('');
  const [answers, setAnswers] = useState<SupplementAnswers>(emptyAnswers);
  const [selected, setSelected] = useState<SupplementAnswerKey[]>([]);
  const [confirmedFor, setConfirmedFor] = useState<string | null>(null);
  const [busyFor, setBusyFor] = useState<string | null>(null);
  const [localError, setLocalError] = useState(false);
  const [nextRound, setNextRound] = useState<{ target: string; entry: string } | null>(null);
  const active = useRef(true);
  const currentTarget = useRef(targetKey);
  useLayoutEffect(() => { currentTarget.current = targetKey; }, [targetKey]);
  const request = useRef<{ target: string; number: number } | null>(null);
  const callbacks = useRef({ onDirtyChange });
  useLayoutEffect(() => { callbacks.current = { onDirtyChange }; }, [onDirtyChange]);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; callbacks.current.onDirtyChange?.(false); };
  }, []);
  const draft: SupplementDraft = { entryId, activityId, answers, selected };
  const preview = previewSupplement(draft);
  const view = controller.view;
  const master = view?.renderedProfile.resume_master;
  const activities = master?.activities ?? [];
  const activity = activities.find((item) => item.id === activityId);
  const saved = profileAvailable && controller.phase === 'saved' && controller.confirmedEntryId === entryId;
  const hasInput = Object.values(answers).some((value) => value.length > 0);
  const hasUnselectedInput = SUPPLEMENT_ANSWER_KEYS.some((key) => !selected.includes(key) && answers[key].length > 0);
  const dirty = controller.phase !== 'retired' && hasInput && (!saved || hasUnselectedInput);
  useLayoutEffect(() => { callbacks.current.onDirtyChange?.(dirty); }, [dirty]);
  const busy = busyFor === targetKey;
  const locked = busy || !!nextRound || controller.operationLocked || ['saving', 'recorded', 'conflict', 'save-unknown', 'saved', 'retired'].includes(controller.phase);
  const fingerprint = JSON.stringify([targetKey, view?.viewId, draft]);
  const confirmed = confirmedFor === fingerprint;
  const ready = profileAvailable && (controller.phase === 'ready' || controller.phase === 'save-error');
  const canConfirm = ready && !!activity && preview.ok && confirmed && !locked;
  const questions: Record<SupplementAnswerKey, { question: string; include: string; label: string }> = {
    task: { question: copy('What was the task?', '当时要完成什么任务？'), include: copy('Include task', '纳入任务'), label: copy('Task', '任务') },
    method: { question: copy('What methods or tools did you use?', '用了哪些方法或工具？'), include: copy('Include method', '纳入方法'), label: copy('Method', '方法') },
    personalRole: { question: copy('What did you personally do?', '你本人具体做了什么？'), include: copy('Include my role', '纳入本人职责'), label: copy('My role', '本人职责') },
    outcome: { question: copy('What was the outcome, if known?', '已知的结果是什么？'), include: copy('Include outcome', '纳入结果'), label: copy('Outcome', '结果') },
    outcomeBasis: { question: copy('What supports that outcome? (optional)', '有什么可以支持这个结果？（选填）'), include: copy('Include outcome basis', '纳入结果依据'), label: copy('Outcome basis', '结果依据') },
  };
  const run = async (action: () => Promise<unknown>) => {
    if (request.current?.target === targetKey) return;
    const marker = { target: targetKey, number: (request.current?.number ?? 0) + 1 };
    request.current = marker; setBusyFor(targetKey); setLocalError(false);
    try { await action(); }
    catch { if (active.current && request.current === marker && currentTarget.current === marker.target) setLocalError(true); }
    finally {
      if (active.current && request.current === marker) { request.current = null; setBusyFor(null); }
    }
  };
  const refresh = () => { setConfirmedFor(null); void run(() => controller.acceptCurrent()); };
  useEffect(() => {
    if (!nextRound) return;
    if (nextRound.target !== targetKey || nextRound.entry !== entryId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setNextRound(null); return;
    }
    if (controller.phase === 'ready' && profileAvailable) {
      // The user explicitly requested another supplement; only discard this
      // already-saved answer round after accepting a fresh profile view.
      setEntryId(crypto.randomUUID()); setAnswers(emptyAnswers()); setSelected([]);
      setConfirmedFor(null); setNextRound(null); setLocalError(false);
    } else if (controller.phase === 'retired' || !profileAvailable) setNextRound(null);
  }, [nextRound, controller.phase, entryId, targetKey, profileAvailable]);
  const messages: Partial<Record<typeof controller.phase, string>> = {
    loading: copy('Loading your saved profile…', '正在读取已保存的资料…'),
    'load-error': copy('Your profile could not be read. Your answers are still here. Retry before confirming.', '暂时无法读取资料，填写内容仍保留。请重试后再确认。'),
    'profile-unavailable': copy('Your saved profile is unavailable. Your answers are kept; adding information and retrying saves are paused.', '已保存的个人资料不可用。答案仍保留，补充与重试保存已暂停。'),
    'not-saved': copy('Save your profile first, then return to add this information.', '请先保存个人资料，再回来补充。'),
    stale: copy('Your profile or target changed. Your answers are kept; review the current materials before confirming.', '资料或目标已更新。答案仍保留，请重新核对当前材料后再确认。'),
    saving: copy('Recording your confirmed information…', '正在保存你确认的信息…'),
    'save-unknown': copy('The save result is not confirmed. Your answers are kept; retry this submission before making changes.', '保存结果尚未确认。答案仍保留，请先重试本次提交，再作修改。'),
    recorded: copy('Recorded on this device; cloud saving is not confirmed. Retry the same submission.', '已在本机记录，云端保存尚未确认。请重试这次提交。'),
    conflict: copy('Another edit needs your attention. Your answers are kept. Review your profile, then check it again here.', '另一处资料修改需要处理。答案仍保留，请先核对个人资料，再回来重新检查。'),
    'save-error': copy('This information was not saved. Your answers are kept; retry when ready.', '补充信息尚未保存，答案仍保留，可以重试。'),
    saved: copy('Added to your master résumé. The current target draft is unchanged. Rebuild it only when you choose.', '已加入简历母版，当前目标稿保持原样。需要时再明确选择重新创建。'),
    retired: copy('This session changed. Reopen the workspace to continue.', '当前会话已变化，请重新打开工作区。'),
  };
  const noMaster = !!view && !master;
  const noActivities = !!master && activities.length === 0;
  if (controller.phase === 'retired') return <section aria-label={copy('Add experience details', '补充经历信息')} data-testid="resume-supplement-panel"><p role="status">{messages.retired}</p></section>;
  return <section aria-labelledby={`${id}-title`} className="min-w-0 rounded-xl border border-indigo-100 bg-indigo-50/20 p-4" data-testid="resume-supplement-panel">
    <h3 id={`${id}-title`} className="font-semibold">{copy('Add experience details', '补充经历信息')}</h3>
    <p className="mt-2 text-sm text-gray-600">{copy('Answer what you know, choose what to include, then confirm it is accurate. Numbers and outcomes are optional. Nothing is inferred or added automatically.', '填写你知道的内容，选择要纳入的部分，再确认属实。不必写数字或结果，也不会自动推测或补写。')}</p>
    {messages[controller.phase] && <p role={['load-error', 'conflict', 'save-error'].includes(controller.phase) ? 'alert' : 'status'} className="mt-3 whitespace-pre-wrap text-sm text-indigo-900">{messages[controller.phase]}</p>}
    {localError && <p role="alert" className="mt-3 text-sm text-red-700">{copy('That action could not finish. Your answers are kept; please retry.', '操作未能完成，答案仍保留，请重试。')}</p>}
    {(noMaster || noActivities) && <p className="mt-3 text-sm text-amber-900">{noMaster ? copy('Create your master résumé before adding details here.', '请先建立简历母版，再在这里补充。') : copy('Add a project or experience to your master résumé first.', '请先在简历母版中添加一项项目或经历。')}</p>}
    {(noMaster || noActivities || ['not-saved', 'conflict', 'save-error', 'profile-unavailable'].includes(controller.phase)) && onOpenProfile && <button type="button" className={`${button} mt-2`} onClick={onOpenProfile}>{copy('Review my profile', '核对个人资料')}</button>}
    {['load-error', 'not-saved', 'stale', 'conflict'].includes(controller.phase) && <button type="button" className={`${button} mt-2`} disabled={busy || !profileAvailable} onClick={refresh}>{controller.phase === 'load-error' ? copy('Retry reading profile', '重试读取资料') : copy('Review current materials', '重新核对当前材料')}</button>}
    {['recorded', 'save-unknown'].includes(controller.phase) && <button type="button" className={`${button} mt-2`} disabled={busy || !profileAvailable} onClick={() => { if (profileAvailable) void run(() => controller.retryRecorded()); }}>{copy('Retry cloud save', '重试云端保存')}</button>}
    <div className="mt-4">
      <label htmlFor={`${id}-activity`} className="text-sm font-medium">{copy('Project or experience in your master résumé', '母版中的项目或经历')}</label>
      <select id={`${id}-activity`} value={activityId} disabled={locked || !activities.length} className="mt-1 w-full rounded-lg border p-2 text-sm"
        onChange={(event) => { setActivityId(event.target.value); setConfirmedFor(null); }}>
        <option value="">{copy('Choose an existing activity', '选择已有项目或经历')}</option>
        {activities.map((item, index) => <option key={item.id} value={item.id}>{item.title?.value || item.organization?.value || `${copy('Activity', '经历')} ${index + 1}`}</option>)}
      </select>
    </div>
    {activity && <details className="mt-3 rounded-lg border bg-white p-3"><summary className="cursor-pointer text-sm font-medium">{copy('Current activity materials', '当前经历材料')}</summary>
      {[activity.title, activity.organization, activity.location, activity.start, activity.end].filter((item) => !!item).map((item) => <p key={item!.id} className="mt-2 whitespace-pre-wrap break-words text-sm">{item!.value}</p>)}
      {activity.details.map((ref) => {
        const entry = view?.renderedProfile.experience_entries?.find((item) => item.id === ref.id && item.revision === ref.revision);
        return <div key={`${ref.id}:${ref.revision}`} className="mt-2 border-t pt-2 text-sm"><p className="whitespace-pre-wrap break-words">{entry?.text ?? copy('This linked experience needs review in your profile.', '这条关联经历需要在个人资料中重新核对。')}</p><p className="mt-1 text-xs text-gray-500">{copy('Existing material, shown for reference. It is not part of this new submission.', '已有材料仅供对照，不会混入本次补充。')}</p></div>;
      })}
    </details>}
    <fieldset disabled={locked} className="mt-4 min-w-0 space-y-4">
      <legend className="sr-only">{copy('Your answers', '填写答案')}</legend>
      {SUPPLEMENT_ANSWER_KEYS.map((key) => <div key={key} className="min-w-0">
        <label htmlFor={`${id}-${key}`} className="text-sm font-medium">{questions[key].question}</label>
        <textarea id={`${id}-${key}`} rows={3} value={answers[key]} className="mt-1 w-full rounded-lg border bg-white p-2 text-sm"
          onChange={(event) => { setAnswers((previous) => ({ ...previous, [key]: event.target.value })); setConfirmedFor(null); }} />
        <label className="mt-1 flex items-center gap-2 text-sm"><input type="checkbox" checked={selected.includes(key)} onChange={(event) => {
          setSelected((previous) => event.target.checked ? [...previous, key] : previous.filter((item) => item !== key)); setConfirmedFor(null);
        }} />{questions[key].include}</label>
      </div>)}
    </fieldset>
    <section aria-label={copy('Information to confirm', '待确认内容')} className="mt-4 min-w-0 rounded-lg border bg-white p-3">
      <h4 className="text-sm font-semibold">{copy('Information to confirm', '待确认内容')}</h4>
      {preview.ok ? <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words font-sans text-sm">{preview.previewText}</pre> : <>
        <p className="mt-2 text-sm text-amber-900">{preview.reason === 'empty' ? copy('Select at least one answer with content.', '请选择至少一项已填写的答案。') : preview.reason === 'limit' ? copy('The selected answers are too long for one entry. Keep the full text here and choose less to include.', '选中内容超过单条经历上限。全文仍保留，请减少本次纳入的内容。') : copy('Check the selected answers before confirming. Your full input is kept.', '请核对所选答案。输入全文仍保留。')}</p>
        {SUPPLEMENT_ANSWER_KEYS.filter((key) => selected.includes(key) && answers[key].length > 0).map((key) => <div key={key} className="mt-3"><p className="text-xs font-medium">{questions[key].label}</p><pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words font-sans text-sm">{answers[key]}</pre></div>)}
      </>}
    </section>
    <p className="mt-2 text-xs text-gray-600">{copy('This records your own confirmation, not an independent verification. Unselected answers are not saved.', '这里记录的是你本人的确认，不代表独立核验。未选答案不会保存。')}</p>
    <label className="mt-3 flex items-start gap-2 text-sm"><input type="checkbox" checked={saved || confirmed} disabled={locked || !preview.ok || !activity || !ready} onChange={(event) => setConfirmedFor(event.target.checked ? fingerprint : null)} />{copy('I confirm the selected information is accurate.', '我确认所选内容属实。')}</label>
    <button type="button" className={`${button} mt-3 bg-indigo-600 text-white`} disabled={!canConfirm} onClick={() => {
      if (!canConfirm) return;
      const baseline = controller.baseline(activityId);
      if (baseline) void run(() => controller.confirm(draft, baseline));
      else setLocalError(true);
    }}>{saved ? copy('Added to master résumé', '已加入母版简历') : copy('Confirm and add to my master résumé', '确认并加入简历母版')}</button>
    {saved && <button type="button" className={`${button} mt-3 ml-2`} disabled={busy} onClick={() => {
      if (hasUnselectedInput && !window.confirm(copy('Start another detail? Answers you did not include will be discarded.', '开始补充另一条？未纳入的答案将被丢弃。'))) return;
      setNextRound({ target: targetKey, entry: entryId }); void run(() => controller.acceptCurrent());
    }}>{copy('Add another detail', '继续补充另一条')}</button>}
  </section>;
}
