'use client';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useLocale } from '@/i18n/client';
import type { TargetResumeV1 } from '@/lib/target-resume';
import { parseTargetResumeSupportGroups, targetResumeSupportActivities, type TargetResumeSupportGroup } from '@/lib/target-resume-support';

interface Props { draft: TargetResumeV1; groups: TargetResumeSupportGroup[]; enabled: boolean; onChange: (groups: TargetResumeSupportGroup[]) => void; onDirtyChange?: (dirty: boolean) => void }
const button = 'rounded-lg border border-gray-300 px-3 py-2 text-sm disabled:opacity-40';
export default function TargetResumeSupportPanel({draft,groups,enabled,onChange,onDirtyChange}:Props) {
  const locale=useLocale(), copy=(en:string,zh:string)=>locale==='zh'?zh:en;
  const activities=targetResumeSupportActivities(draft);
  const [unit,setUnit]=useState(''),[selected,setSelected]=useState<string[]>([]);
  const activity=activities.find(item=>item.lines.some(line=>line.id===unit));
  const original=activity?.lines.find(line=>line.id===unit);
  const dirty=!!unit || groups.length>0;
  const callback=useRef(onDirtyChange);
  useLayoutEffect(()=>{callback.current=onDirtyChange;},[onDirtyChange]);
  useEffect(()=>{callback.current?.(dirty);},[dirty]);useEffect(()=>()=>callback.current?.(false),[]);
  const options=groups.filter(item=>item.unit_id!==unit);
  const candidate=selected.length ? parseTargetResumeSupportGroups(draft,[...options,{unit_id:unit,support_unit_ids:selected,confirmed:true}]) : null;
  return <details className="my-5 min-w-0 rounded-xl border p-4" data-testid="target-resume-support">
    <summary className="cursor-pointer font-semibold">{copy('Choose supporting details', '选择补充依据')}</summary>
    <p className="mt-2 text-sm text-gray-600">{copy('Choose the original sentence and confirmed details from the same activity. Read them together before allowing a suggested rewrite to use them. Original entries stay unchanged.', '选择要改写的原句和同一经历中的已确认补充。核对完整原文后，才允许这条改写使用补充；原始条目保持不变。')}</p>
    <p className="mt-2 text-sm text-gray-600">{copy('Supporting details remain separate entries. After applying a rewrite, check for repetition and deselect entries if needed.', '补充仍保留为独立条目。采用改写后，请检查是否重复，并按需取消选用。')}</p>
    {!enabled && <p className="mt-2 text-sm text-amber-900">{copy('Use a draft based on the current profile and opportunity before selecting sources.', '请先使用基于当前资料和机会的新稿，再选择依据。')}</p>}
    {!activities.length && <p className="mt-2 text-sm">{copy('No activity in this draft has multiple confirmed experience entries. Add or assign details, then create a new draft.', '本稿还没有包含多条已确认经历的项目。补充或归类后，再创建新稿。')}</p>}
    <label className="mt-3 block text-sm">{copy('Original sentence to adapt', '要改写的原句')}<select className="mt-1 w-full rounded-lg border p-2" disabled={!enabled} value={unit} onChange={event=>{const id=event.target.value;setUnit(id);setSelected(groups.find(group=>group.unit_id===id)?.support_unit_ids ?? []);}}><option value="">{copy('Choose a sentence', '选择原句')}</option>{activities.map((block,index)=><optgroup key={block.id} label={block.label || copy(`Activity ${index+1}`,`经历 ${index+1}`)}>{block.lines.map(line=><option key={line.id} value={line.id}>{line.original.slice(0,100)}</option>)}</optgroup>)}</select></label>
    {original && <><p className="mt-3 text-sm font-medium">{copy('Complete original sentence', '完整原句')}</p><pre className="mt-1 whitespace-pre-wrap break-words rounded-lg border bg-gray-50 p-3 font-sans text-sm">{original.original}</pre>
      <fieldset className="mt-3 space-y-2" disabled={!enabled}><legend className="text-sm font-medium">{copy('Confirmed details from this activity', '同一经历的已确认补充')}</legend>{activity!.lines.filter(line=>line.id!==unit).map(line=><label key={line.id} className="block rounded-lg border p-3 text-sm"><input type="checkbox" checked={selected.includes(line.id)} onChange={event=>{setSelected(old=>event.target.checked?[...old,line.id]:old.filter(id=>id!==line.id));onChange(options);}}/> {copy('Use this detail', '使用这条补充')}<pre className="mt-2 whitespace-pre-wrap break-words font-sans">{line.original}</pre></label>)}</fieldset>
      <button type="button" className={`${button} mt-3`} disabled={!enabled || !candidate} onClick={()=>{if(candidate)onChange(candidate);}}>{copy('Reviewed: use these sources for this rewrite', '核对后用于这条修改')}</button>
      {groups.some(group=>group.unit_id===unit) && <p role="status" className="mt-2 text-sm text-indigo-800">{copy('These sources may now support this sentence. Generate new suggestions to use them.', '这些原文已允许用于这句改写。请生成新建议。')}</p>}
    </>}
    {groups.length>0 && <div className="mt-4 space-y-3">{groups.map(group=>{const block=activities.find(item=>item.lines.some(line=>line.id===group.unit_id))!;return <div key={group.unit_id} className="rounded-lg border p-3 text-sm"><p className="font-medium">{copy('Confirmed source combination', '已确认的原文组合')}</p>{[group.unit_id,...group.support_unit_ids].map(id=><pre key={id} className="mt-2 whitespace-pre-wrap break-words font-sans">{block.lines.find(line=>line.id===id)?.original}</pre>)}<button type="button" className={`${button} mt-2`} onClick={()=>{onChange(groups.filter(item=>item.unit_id!==group.unit_id));if(unit===group.unit_id)setSelected([]);}}>{copy('Remove this source choice', '取消这条依据')}</button></div>;})}</div>}
  </details>;
}
