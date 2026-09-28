'use client';

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useLocale } from '@/i18n/client';
import type { ExperienceEntry } from '@/lib/types';
import { sourceDigest, isActiveExperience } from '@/lib/experience-evidence';
import { isActiveResumeFact } from '@/lib/resume-master';
import { unassignedConfirmedExperiences } from '@/lib/resume-experience-assignment';
import { useResumeSupplement, type ResumeSupplementOptions } from './use-resume-supplement';

type Props = ResumeSupplementOptions & { onDirtyChange?: (dirty: boolean) => void };
const button = 'rounded-lg border border-gray-300 px-3 py-2 text-sm disabled:opacity-40';
export default function ResumeExperienceAssignmentPanel(props: Props) {
  const locale = useLocale(), copy = (en: string, zh: string) => locale === 'zh' ? zh : en;
  const controller = useResumeSupplement(props);
  const [candidates, setCandidates] = useState<{ key: string; entries: ExperienceEntry[]; digest: string } | null>(null);
  const [entryId, setEntryId] = useState('');
  const [activityId, setActivityId] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmedFor, setConfirmedFor] = useState<string | null>(null);
  const dirtyCallback = useRef(props.onDirtyChange);
  useLayoutEffect(() => { dirtyCallback.current = props.onDirtyChange; }, [props.onDirtyChange]);
  const view = controller.view, viewKey = view?.viewId ?? '';
  useEffect(() => {
    let active = true;
    if (view) void Promise.all([unassignedConfirmedExperiences(view.renderedProfile), sourceDigest(view.renderedProfile.resume_text ?? '')]).then(([entries,digest]) => { if (active) setCandidates({ key: viewKey, entries, digest }); });
    return () => { active = false; };
  }, [view, viewKey]);
  const entries = candidates?.key === viewKey ? candidates.entries : [];
  const entry = entries.find(item => item.id === entryId);
  const activities = view?.renderedProfile.resume_master?.activities ?? [];
  const factContext = { rawText: view?.renderedProfile.resume_text ?? '', expectedDigest: candidates?.key === viewKey ? candidates.digest : '' };
  const activeFact = (fact: typeof activities[number]['title']) => fact && isActiveResumeFact(fact, factContext) ? fact : undefined;
  const activity = activities.find(item => item.id === activityId);
  const key = JSON.stringify([props.targetKey, viewKey, entry, activity]);
  const saved = controller.phase === 'saved' && controller.confirmedEntryId === entryId;
  const dirty = !!entryId && !saved;
  useEffect(() => { dirtyCallback.current?.(dirty); }, [dirty]);
  useEffect(() => () => dirtyCallback.current?.(false), []);
  const ready = props.profileAvailable !== false && ['ready', 'save-error'].includes(controller.phase) && !busy && !controller.operationLocked;
  const locked = busy || controller.operationLocked || saved;
  const refresh = async () => { setConfirmedFor(null); setBusy(true); try { await controller.acceptCurrent(); } finally { setBusy(false); } };
  const confirm = async () => {
    if (!ready || !entry || !activity || confirmedFor !== key) return;
    const against = controller.baseline(activityId); if (!against) return;
    setBusy(true); try { await controller.assign({entryId, entryRevision:entry.revision, activityId}, against); } finally { setBusy(false); }
  };
  return <section className="mb-5 rounded-xl border border-indigo-100 bg-white p-4" aria-label={copy('Assign experience to a project', '归入项目/经历')} data-testid="resume-experience-assignment">
    <h3 className="font-semibold">{copy('Assign experience to a project', '归入项目/经历')}</h3>
    <p className="mt-2 text-sm text-gray-600">{copy('Choose an existing confirmed entry and the project it belongs to. The original wording is kept. Create a new target draft after saving to include it.', '选择已确认的原文和所属项目。原文保持不变；保存后创建目标新稿，才能加入选材。')}</p>
    {controller.phase === 'loading' && <p role="status">{copy('Reading current materials…', '正在读取当前资料…')}</p>}
    {['stale', 'conflict', 'load-error', 'profile-unavailable', 'not-saved'].includes(controller.phase) && <p role="status" className="mt-2 text-sm">{copy('Review current profile materials before confirming. Your selection is kept.', '请先重新读取当前资料，再核对归属。当前选择保留。')}</p>}
    {['stale', 'conflict', 'load-error', 'not-saved'].includes(controller.phase) && <button type="button" className={button} disabled={busy || props.profileAvailable === false} onClick={() => void refresh()}>{copy('Review current materials', '重新读取当前资料')}</button>}
    {saved && <p role="status" className="mt-2 text-sm">{copy('Assigned to your master résumé. Your existing target draft is kept; create a new draft when ready.', '已归入母版。原有目标稿保持不变，需要时再创建新稿。')}</p>}
    {controller.phase === 'save-error' && <p role="alert" className="mt-2 text-sm">{copy('The assignment was not saved. Your selection is kept; review and retry.', '归属未能保存。当前选择保留，请核对后重试。')}</p>}
    {['recorded', 'save-unknown'].includes(controller.phase) && <><p role="status" className="mt-2 text-sm">{copy('Saving is not yet confirmed. Retry the same assignment.', '尚未确认保存完成，请重试同一次归属保存。')}</p><button type="button" className={button} disabled={busy || props.profileAvailable === false} onClick={() => void controller.retryRecorded()}>{copy('Retry saving', '重试保存')}</button></>}
    {ready && !entries.length && <p className="mt-2 text-sm">{copy('No current confirmed entries need a project assignment.', '没有需要归类的有效已确认经历。')}</p>}
    <fieldset disabled={locked} className="mt-3 min-w-0 space-y-3"><legend className="text-sm font-medium">{copy('Confirmed original entries', '已确认原文')}</legend>
      {entries.map(item => <label key={item.id} className="block rounded-lg border p-3 text-sm"><input type="radio" name="experience-assignment" checked={item.id === entryId} onChange={() => { setEntryId(item.id); setConfirmedFor(null); }} /> <span>{copy('Use this entry', '选择这条')}</span><pre className="mt-2 whitespace-pre-wrap break-words font-sans">{item.text}</pre><span className="mt-2 block text-xs text-gray-500">{item.source.kind === 'resume' ? copy('From résumé', '来自简历原文') : copy('Your confirmed description', '本人确认的描述')}</span></label>)}
      <label className="block text-sm">{copy('Project or experience', '所属项目或经历')}<select className="mt-1 w-full rounded-lg border p-2" value={activityId} onChange={event => {setActivityId(event.target.value);setConfirmedFor(null);}}><option value="">{copy('Choose an existing activity', '选择已有项目或经历')}</option>{activities.map((item,index) => <option key={item.id} value={item.id}>{activeFact(item.title)?.value || activeFact(item.organization)?.value || copy(`Activity ${index+1} — review its name`, `经历 ${index+1}：请先核对名称`)}</option>)}</select></label>
    </fieldset>
    {activity && <div className="mt-2 whitespace-pre-wrap break-words text-sm">{[activity.title,activity.organization,activity.start,activity.end].map(activeFact).filter(Boolean).map(fact=><p key={fact!.id}>{fact!.value}</p>)}{activity.details.flatMap(ref => { const current = view?.renderedProfile.experience_entries?.find(item => item.id === ref.id && item.revision === ref.revision); return current && isActiveExperience(current, factContext) ? [<pre key={current.id} className="mt-2 whitespace-pre-wrap break-words rounded-lg border p-2 font-sans">{current.text}</pre>] : []; })}</div>}
    <label className="mt-3 flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmedFor === key} disabled={!ready || !entry || !activity} onChange={event=>setConfirmedFor(event.target.checked ? key : null)}/>{copy('I checked the original entry and confirm it belongs to this activity.', '我已核对原文，确认它属于这项项目或经历。')}</label>
    <button type="button" className={`${button} mt-3`} disabled={!ready || !entry || !activity || confirmedFor !== key} onClick={()=>void confirm()}>{copy('Save assignment', '保存归属')}</button>
  </section>;
}
