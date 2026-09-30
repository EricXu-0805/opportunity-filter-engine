'use client';

import { useEffect, useState } from 'react';
import Card from '@/components/Card';
import { useLocale } from '@/i18n/client';
import { isActiveExperience, sourceDigest, validateExperienceEntries } from '@/lib/experience-evidence';
import {
  buildResumeMasterPreview, createEmptyResumeMaster, isActiveResumeFact, resumeMasterEditBase, validateResumeMaster,
} from '@/lib/resume-master';
import type { ExperienceSourceContext } from '@/lib/experience-evidence';
import type {
  ExperienceEntry, ProfileData, ResumeActivityItem, ResumeExperienceRef, ResumeFact, ResumeMasterV1,
} from '@/lib/types';

type EditBase = { resumeText: string; entriesJson: string; masterJson: string };
type Draft = { master: ResumeMasterV1; base: EditBase; dirty: boolean };
type Copy = (en: string, zh: string) => string;
const button = 'rounded-lg border border-gray-300 px-3 py-2 text-sm disabled:opacity-40';
const input = 'mt-1 w-full rounded-lg border border-gray-300 p-2 text-sm disabled:opacity-50';
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const sameBase = (a: EditBase, b: EditBase) => a.resumeText === b.resumeText
  && a.entriesJson === b.entriesJson && a.masterJson === b.masterJson;

function FactField({ label, fact, disabled, context, onChange, copy }: {
  label: string; fact?: ResumeFact; disabled: boolean; context: ExperienceSourceContext;
  onChange: (fact: ResumeFact | undefined) => void; copy: Copy;
}) {
  const current = !!fact && isActiveResumeFact({ ...fact, status: 'confirmed' }, context);
  const status = fact && ({
    candidate: copy('Needs confirmation', '待确认'), confirmed: copy('Confirmed', '已确认'),
    rejected: copy('Excluded', '已排除'), withdrawn: copy('Withdrawn', '已撤回'),
  })[fact.status];
  return <div className="min-w-0 rounded-xl border border-gray-100 p-3">
    <label className="block text-sm font-medium text-gray-800">{label}
      <textarea className={input} rows={2} value={fact?.value ?? ''} disabled={disabled}
        onChange={(event) => {
          const value = event.target.value;
          onChange(value === '' ? undefined : {
            id: fact?.id ?? crypto.randomUUID(), revision: (fact?.revision ?? 0) + 1,
            status: 'candidate', value, source: fact?.source ?? { kind: 'manual' },
          });
        }} />
    </label>
    {fact && <>
      <p className="mt-1 text-xs text-gray-500">{status} · {fact.source.kind === 'manual'
        ? copy('Entered by you', '手动录入') : copy('Résumé source', '简历原文')}
        {!current && fact.source.kind === 'resume' && ` · ${copy('Source not verified against the current résumé', '来源尚未通过当前简历核对')}`}</p>
      {fact.source.kind === 'resume' && <details className="mt-2 text-xs text-gray-600">
        <summary className="cursor-pointer">{copy('View original source', '查看原始出处')}</summary>
        <p className="mt-2 whitespace-pre-wrap break-words rounded-lg bg-gray-50 p-3">{fact.source.quote}</p>
      </details>}
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" className={button} disabled={disabled || !current || fact.status === 'confirmed'}
          aria-label={`${copy('Confirm', '确认')} ${label}`}
          onClick={() => onChange({ ...fact, status: 'confirmed', revision: fact.revision + 1 })}>{copy('Confirm', '确认')}</button>
        <button type="button" className={button} disabled={disabled || fact.status === 'rejected'}
          aria-label={`${copy('Exclude', '排除')} ${label}`}
          onClick={() => onChange({ ...fact, status: 'rejected', revision: fact.revision + 1 })}>{copy('Exclude', '排除')}</button>
      </div>
    </>}
  </div>;
}

function ExperienceReferences({ refs, entries, context, disabled, onChange, copy }: {
  refs: ResumeExperienceRef[]; entries: ExperienceEntry[]; context: ExperienceSourceContext;
  disabled: boolean; onChange: (refs: ResumeExperienceRef[]) => void; copy: Copy;
}) {
  const active = entries.filter((entry) => isActiveExperience(entry, context));
  const unresolved = refs.filter((ref) => !active.some((entry) => entry.id === ref.id && entry.revision === ref.revision));
  return <fieldset className="mt-3 rounded-xl bg-gray-50 p-3" disabled={disabled}>
    <legend className="text-sm font-medium">{copy('Confirmed experience details', '已确认的经历详情')}</legend>
    <p className="text-xs text-gray-600">{copy('Choose exact confirmed versions from your experience library. Candidate or changed versions are excluded from the preview.', '选择经历库中已确认的具体版本。候选或已变更版本不会进入预览。')}</p>
    {active.length === 0 && <p className="mt-2 text-sm text-gray-500">{copy('No eligible confirmed experience yet.', '暂无可引用的已确认经历。')}</p>}
    {active.map((entry) => <label key={entry.id} className="mt-2 flex items-start gap-2 text-sm">
      <input type="checkbox" className="mt-1 shrink-0" checked={refs.some((ref) => ref.id === entry.id && ref.revision === entry.revision)}
        onChange={(event) => onChange(event.target.checked
          ? [...refs.filter((ref) => ref.id !== entry.id), { id: entry.id, revision: entry.revision }]
          : refs.filter((ref) => ref.id !== entry.id))} />
      <span className="whitespace-pre-wrap break-words">{entry.text}</span>
    </label>)}
    {unresolved.map((ref) => <div key={`${ref.id}:${ref.revision}`} className="mt-2 flex flex-wrap items-center gap-2 text-sm text-amber-800">
      <span>{copy('A referenced experience is no longer eligible. Review it in the experience library.', '某条引用经历已失效，请回经历库核对。')}</span>
      <button type="button" className={button} onClick={() => onChange(refs.filter((item) => item !== ref))}>{copy('Remove unavailable reference', '移除失效引用')}</button>
    </div>)}
    <a href="#experience-library" className="mt-3 inline-block text-sm text-indigo-700 underline">{copy('Review experience library', '核对经历库')}</a>
  </fieldset>;
}

export function ResumeMasterCard({ profile, ready, onChange }: {
  profile: ProfileData; ready: boolean;
  onChange: (master: ResumeMasterV1, expected: EditBase) => boolean;
}) {
  const locale = useLocale();
  const copy: Copy = (en, zh) => locale === 'zh' ? zh : en;
  const base = resumeMasterEditBase(profile);
  const { resumeText: raw, entriesJson, masterJson } = base;
  const checked = validateResumeMaster(profile.resume_master);
  const checkedEntries = validateExperienceEntries(profile.experience_entries);
  const [draft, setDraft] = useState<Draft | null>(() => ready && checked.ok
    ? { master: clone(checked.value ?? createEmptyResumeMaster()), base, dirty: false } : null);
  const [error, setError] = useState<'invalid' | 'stale' | null>(null);
  const [digest, setDigest] = useState<{ raw: string; value: string } | null>(null);
  useEffect(() => {
    if (!ready) return;
    const parsed = validateResumeMaster(JSON.parse(masterJson));
    if (!parsed.ok) return;
    const nextBase = { resumeText: raw, entriesJson, masterJson };
    // Only a clean editor follows external updates. Unsaved buffers stay intact.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft((old) => old?.dirty || (old && sameBase(old.base, nextBase)) ? old
      : { master: clone(parsed.value ?? createEmptyResumeMaster()), base: nextBase, dirty: false });
  }, [ready, raw, entriesJson, masterJson]);
  useEffect(() => {
    let active = true;
    sourceDigest(raw).then((value) => { if (active) setDigest({ raw, value }); })
      .catch(() => { if (active) setDigest(null); });
    return () => { active = false; };
  }, [raw]);
  const context = { rawText: raw, expectedDigest: digest?.raw === raw ? digest.value : '' };
  const entries = checkedEntries.ok ? checkedEntries.value : [];
  const conflict = !!draft && !sameBase(draft.base, base);
  const blocked = !ready || !checked.ok || !checkedEntries.ok;
  const edit = (change: (next: ResumeMasterV1) => void) => {
    if (blocked) return;
    setDraft((old) => {
      if (!old) return old;
      const next = clone(old.master); change(next);
      return { ...old, master: clone(next), dirty: true };
    });
    setError(null);
  };
  const field = (label: string, fact: ResumeFact | undefined, update: (next: ResumeMasterV1, fact: ResumeFact | undefined) => void) =>
    <FactField key={label} label={label} fact={fact} disabled={blocked} context={context} copy={copy}
      onChange={(value) => edit((next) => update(next, value))} />;
  const references = (refs: ResumeExperienceRef[], update: (next: ResumeMasterV1, refs: ResumeExperienceRef[]) => void) =>
    <ExperienceReferences refs={refs} entries={entries} context={context} disabled={blocked} copy={copy}
      onChange={(value) => edit((next) => update(next, value))} />;
  const headings: Record<string, string> = {
    basics: copy('Contact and identity', '姓名与联系方式'), education: copy('Education', '教育'),
    activities: copy('Experience and projects', '经历与项目'), publications: copy('Publications', '论文与出版物'),
    skills: copy('Skills', '技能'),
  };
  const headingFor = (id: string) => headings[id] ?? draft?.master.other_sections.find((section) => section.id === id)?.heading ?? '';
  const master = draft?.master;
  const previewReady = validateResumeMaster(master ?? null).ok;
  const preview = buildResumeMasterPreview(previewReady ? master ?? null : null, entries, context);
  const previewBlocks = preview.sections.reduce((count, section) => count + section.blocks.length, 0);
  const previewLabels = (sectionId: string, blockId: string): string[] => {
    if (!master) return [];
    const labels = (item: object, fields: ReadonlyArray<readonly [string, string]>): string[] => fields.flatMap(([key, label]) => {
      const fact = (item as Record<string, ResumeFact | undefined>)[key];
      return fact && isActiveResumeFact(fact, context) ? [label] : [];
    });
    const detailLabels = (refs: ResumeExperienceRef[]) => refs.flatMap((ref) => entries.some((entry) => entry.id === ref.id
      && entry.revision === ref.revision && isActiveExperience(entry, context)) ? [copy('Experience detail', '经历详情')] : []);
    if (sectionId === 'basics') {
      if (blockId === master.id) return labels(master.basics, [['name', copy('Full name', '姓名')], ['email', copy('Email', '邮箱')], ['phone', copy('Phone', '电话')], ['location', copy('Location', '所在地')]]);
      const link = master.basics.links.find((item) => item.id === blockId);
      return link ? [link.label] : [];
    }
    const education = master.education.find((item) => item.id === blockId);
    if (sectionId === 'education' && education) return [...labels(education, [['school', copy('School', '学校')], ['degree', copy('Degree', '学位')], ['field', copy('Field of study', '专业')], ['start', copy('Start date', '开始日期')], ['end', copy('End date / expected date', '结束／预计日期')]]), ...detailLabels(education.details)];
    const activity = master.activities.find((item) => item.id === blockId);
    if (sectionId === 'activities' && activity) return [...labels(activity, [['title', copy('Role / project title', '职位／项目名称')], ['organization', copy('Organization', '组织')], ['location', copy('Activity location', '经历地点')], ['start', copy('Start date', '开始日期')], ['end', copy('End date / present', '结束日期／至今')], ['url', copy('Project URL', '项目链接')]]), ...detailLabels(activity.details)];
    const publication = master.publications.find((item) => item.id === blockId);
    if (sectionId === 'publications' && publication) return [...labels(publication, [['title', copy('Publication title', '论文标题')], ['authors', copy('Authors in exact order', '作者及准确顺序')], ['venue', copy('Journal / conference', '期刊／会议')], ['date', copy('Publication date', '发表日期')], ['publication_status', copy('Publication status', '发表状态')], ['url', copy('Publication URL', '论文链接')], ['doi', 'DOI']]), ...detailLabels(publication.details)];
    return [];
  };

  const apply = () => {
    if (!draft || blocked || conflict || !draft.dirty) return;
    const next = { ...draft.master, revision: draft.master.revision + 1 };
    const validated = validateResumeMaster(next);
    if (!validated.ok || !validated.value) { setError('invalid'); return; }
    if (!onChange(validated.value, draft.base)) { setError('stale'); return; }
    setDraft({ master: validated.value, base: resumeMasterEditBase({ ...profile, resume_master: validated.value }), dirty: false });
    setError(null);
  };
  const reload = () => {
    if (blocked || !checked.ok) return;
    setDraft({ master: clone(checked.value ?? createEmptyResumeMaster()), base, dirty: false });
    setError(null);
  };
  return <section id="resume-master" aria-labelledby="resume-master-title" className="scroll-mt-24">
    <Card>
      <h2 id="resume-master-title" className="text-xl font-bold text-gray-900">{copy('Complete résumé master', '完整简历母版')}</h2>
      <p className="mt-2 text-sm text-gray-600">{copy('Keep your exact contact details, education, experience, publications and skills together. New or edited facts need your confirmation before appearing in the preview. Nothing is inferred from your profile.', '统一保留准确的联系方式、教育、经历、论文与技能。新增或修改的事实需逐项确认后才进入预览，不会从资料中猜测补全。')}</p>
      <p className="mt-2 text-xs text-gray-500">{copy('Changes stay in this editor until you apply them. Applying updates your profile; check the profile save indicator for storage status. Preview is not a PDF or DOCX export.', '修改先保留在编辑器内，应用后更新资料；实际保存状态以资料保存提示为准。此处预览不是 PDF 或 DOCX 导出。')}</p>
      <a href="#profile-save-status" className="mt-2 inline-block text-sm text-indigo-700 underline">{copy('View profile save status', '查看资料保存状态')}</a>
      {!ready && <p role="status" className="mt-3 text-sm text-gray-600">{copy('Loading your profile. Editing is unavailable until it is ready.', '正在读取资料，准备完成后才能编辑。')}</p>}
      {(!checked.ok || !checkedEntries.ok) && <p role="alert" className="mt-3 text-sm text-red-700">{copy('Saved résumé data could not be read safely. It has not been replaced.', '已保存的简历资料无法安全读取，未用空内容替换。')}</p>}
      {conflict && draft?.dirty && <div role="alert" className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
        <p>{copy('Your résumé source or saved materials changed. Your unsaved edits are still here. Applying is blocked until you review the current version.', '简历来源或已保存材料已变更。未保存编辑仍保留在此，核对当前版本前不能应用。')}</p>
        <button type="button" className={`${button} mt-2`} disabled={blocked} onClick={reload}>{copy('Discard unsaved edits and load current version', '放弃未保存编辑并载入当前版本')}</button>
      </div>}
      {error && <p role="alert" className="mt-3 text-sm text-red-700">{error === 'stale'
        ? copy('These edits were not accepted because your profile changed. Your input is still here.', '资料已变更，本次修改未被接纳，输入仍保留在此。')
        : copy('These edits could not be applied. Check empty fields, references and size limits; your full input is preserved.', '修改暂未应用，请检查空字段、引用和篇幅限制；输入全文仍已保留。')}</p>}
      {raw && <details className="mt-4 rounded-xl border border-gray-200 p-3">
        <summary className="cursor-pointer text-sm font-medium">{copy('View complete current résumé source', '查看当前简历原文全文')}</summary>
        <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words text-sm font-sans">{raw}</pre>
      </details>}
      {ready && master && checked.ok && checkedEntries.ok && <details data-testid="resume-master-editor" className="mt-4">
        <summary className="cursor-pointer text-sm font-semibold text-indigo-700">{copy('Open full résumé editor', '展开完整简历编辑器')}</summary>
        <div className="mt-5 space-y-4">
          {master.section_order.map((sectionId, position) => <details open key={sectionId} className="rounded-xl border border-gray-200 p-4">
            <summary className="cursor-pointer font-semibold text-gray-900">{headingFor(sectionId) || copy('Untitled section', '未命名章节')}</summary>
            <div className="my-3 flex flex-wrap gap-2">
              {[-1, 1].map((direction) => <button key={direction} type="button" className={button}
                disabled={blocked || position + direction < 0 || position + direction >= master.section_order.length}
                aria-label={`${direction < 0 ? copy('Move up', '上移') : copy('Move down', '下移')} ${headingFor(sectionId)}`}
                onClick={() => edit((next) => { const order = next.section_order; [order[position], order[position + direction]] = [order[position + direction], order[position]]; })}>
                {direction < 0 ? copy('Move up', '上移') : copy('Move down', '下移')}</button>)}
            </div>
            {sectionId === 'basics' && <>
              <div className="grid gap-2 sm:grid-cols-2">
                {field(copy('Full name', '姓名'), master.basics.name, (next, value) => { next.basics.name = value; })}
                {field(copy('Email', '邮箱'), master.basics.email, (next, value) => { next.basics.email = value; })}
                {field(copy('Phone', '电话'), master.basics.phone, (next, value) => { next.basics.phone = value; })}
                {field(copy('Location', '所在地'), master.basics.location, (next, value) => { next.basics.location = value; })}
              </div>
              {master.basics.links.map((link, index) => <div key={link.id} className="mt-3 rounded-lg border p-3">
                <label className="block text-sm">{copy('Link label', '链接名称')}<input className={input} value={link.label} disabled={blocked}
                  onChange={(event) => edit((next) => { next.basics.links[index].label = event.target.value; })} /></label>
                {field(copy('Link URL', '链接地址'), link.url, (next, value) => { if (value) next.basics.links[index].url = value; else next.basics.links[index].url = { ...next.basics.links[index].url, value: '', status: 'candidate' }; })}
                <button type="button" className={`${button} mt-2`} onClick={() => edit((next) => { next.basics.links.splice(index, 1); })}>{copy('Remove link', '删除链接')}</button>
              </div>)}
              <button type="button" className={`${button} mt-3`} onClick={() => edit((next) => { next.basics.links.push({ id: crypto.randomUUID(), label: '', url: { id: crypto.randomUUID(), revision: 1, status: 'candidate', value: '', source: { kind: 'manual' } } }); })}>{copy('Add link', '添加链接')}</button>
            </>}
            {sectionId === 'education' && <>
              {master.education.map((item, index) => <fieldset key={item.id} className="mb-3 rounded-xl border p-3"><legend className="text-sm font-medium">{copy('Education', '教育')} {index + 1}</legend>
                <div className="grid gap-2 sm:grid-cols-2">{([
                  ['school', copy('School', '学校')], ['degree', copy('Degree', '学位')], ['field', copy('Field of study', '专业')], ['start', copy('Start date', '开始日期')], ['end', copy('End date / expected date', '结束／预计日期')],
                ] as const).map(([key, label]) => field(label, item[key], (next, value) => { next.education[index][key] = value; }))}</div>
                {references(item.details, (next, value) => { next.education[index].details = value; })}
                <button type="button" className={`${button} mt-2`} onClick={() => edit((next) => { next.education.splice(index, 1); })}>{copy('Remove education', '删除教育项')}</button>
              </fieldset>)}
              <button type="button" className={button} onClick={() => edit((next) => { next.education.push({ id: crypto.randomUUID(), details: [] }); })}>{copy('Add education', '添加教育')}</button>
            </>}
            {sectionId === 'activities' && <>
              {master.activities.map((item, index) => <fieldset key={item.id} className="mb-3 rounded-xl border p-3"><legend className="text-sm font-medium">{copy('Activity', '经历')} {index + 1}</legend>
                <label className="block text-sm">{copy('Activity type', '经历类型')}<select className={input} value={item.kind} disabled={blocked}
                  onChange={(event) => edit((next) => { next.activities[index].kind = event.target.value as ResumeActivityItem['kind']; })}>
                  {([['employment', copy('Employment', '工作')], ['research', copy('Research', '研究')], ['project', copy('Project', '项目')], ['volunteer', copy('Volunteering', '志愿活动')], ['other', copy('Other', '其他')]] as const).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select></label>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">{([
                  ['title', copy('Role / project title', '职位／项目名称')], ['organization', copy('Organization', '组织')], ['location', copy('Activity location', '经历地点')], ['start', copy('Start date', '开始日期')], ['end', copy('End date / present', '结束日期／至今')], ['url', copy('Project URL', '项目链接')],
                ] as const).map(([key, label]) => field(label, item[key], (next, value) => { next.activities[index][key] = value; }))}</div>
                {references(item.details, (next, value) => { next.activities[index].details = value; })}
                <button type="button" className={`${button} mt-2`} onClick={() => edit((next) => { next.activities.splice(index, 1); })}>{copy('Remove activity', '删除经历项')}</button>
              </fieldset>)}
              <button type="button" className={button} onClick={() => edit((next) => { next.activities.push({ id: crypto.randomUUID(), kind: 'project', details: [] }); })}>{copy('Add experience or project', '添加经历或项目')}</button>
            </>}
            {sectionId === 'publications' && <>
              {master.publications.map((item, index) => <fieldset key={item.id} className="mb-3 rounded-xl border p-3"><legend className="text-sm font-medium">{copy('Publication', '论文')} {index + 1}</legend>
                <div className="grid gap-2 sm:grid-cols-2">{([
                  ['title', copy('Publication title', '论文标题')], ['authors', copy('Authors in exact order', '作者及准确顺序')], ['venue', copy('Journal / conference', '期刊／会议')], ['date', copy('Publication date', '发表日期')], ['publication_status', copy('Publication status', '发表状态')], ['url', copy('Publication URL', '论文链接')], ['doi', 'DOI'],
                ] as const).map(([key, label]) => field(label, item[key], (next, value) => { next.publications[index][key] = value; }))}</div>
                {references(item.details, (next, value) => { next.publications[index].details = value; })}
                <button type="button" className={`${button} mt-2`} onClick={() => edit((next) => { next.publications.splice(index, 1); })}>{copy('Remove publication', '删除论文项')}</button>
              </fieldset>)}
              <button type="button" className={button} onClick={() => edit((next) => { next.publications.push({ id: crypto.randomUUID(), details: [] }); })}>{copy('Add publication', '添加论文')}</button>
            </>}
            {sectionId === 'skills' && <>
              <p className="mb-2 text-xs text-gray-500">{copy('Use your exact wording. These display entries do not change your matching skill levels.', '按事实准确填写。这里的展示条目不会修改匹配资料中的技能等级。')}</p>
              {master.skills.map((fact, index) => <div key={fact.id} className="mb-3">
                {field(`${copy('Skill', '技能')} ${index + 1}`, fact, (next, value) => { if (value) next.skills[index] = value; else next.skills[index] = { ...next.skills[index], value: '', status: 'candidate' }; })}
                <button type="button" className={`${button} mt-1`} onClick={() => edit((next) => { next.skills.splice(index, 1); })}>{copy('Remove skill', '删除技能项')}</button>
              </div>)}
              <button type="button" className={button} onClick={() => edit((next) => { next.skills.push({ id: crypto.randomUUID(), revision: 1, status: 'candidate', value: '', source: { kind: 'manual' } }); })}>{copy('Add skill', '添加技能')}</button>
            </>}
            {master.other_sections.filter((section) => section.id === sectionId).map((section) => {
              const index = master.other_sections.findIndex((item) => item.id === sectionId);
              return <div key={section.id}>
                <label className="block text-sm">{copy('Section heading', '章节标题')}<input className={input} value={section.heading} disabled={blocked}
                  onChange={(event) => edit((next) => { next.other_sections[index].heading = event.target.value; })} /></label>
                {section.items.map((fact, itemIndex) => <div key={fact.id} className="mt-3">
                  {field(`${copy('Additional detail', '补充内容')} ${itemIndex + 1}`, fact, (next, value) => { if (value) next.other_sections[index].items[itemIndex] = value; else next.other_sections[index].items[itemIndex] = { ...fact, value: '', status: 'candidate' }; })}
                  <button type="button" className={`${button} mt-1`} onClick={() => edit((next) => { next.other_sections[index].items.splice(itemIndex, 1); })}>{copy('Remove detail', '删除补充内容')}</button>
                </div>)}
                <div className="mt-3 flex flex-wrap gap-2">
                  <button type="button" className={button} onClick={() => edit((next) => { next.other_sections[index].items.push({ id: crypto.randomUUID(), revision: 1, status: 'candidate', value: '', source: { kind: 'manual' } }); })}>{copy('Add detail', '添加补充内容')}</button>
                  <button type="button" className={button} onClick={() => edit((next) => { next.other_sections.splice(index, 1); next.section_order = next.section_order.filter((id) => id !== sectionId); })}>{copy('Remove section', '删除章节')}</button>
                </div>
              </div>;
            })}
          </details>)}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" className={button} onClick={() => edit((next) => { const id = crypto.randomUUID(); next.other_sections.push({ id, heading: '', items: [] }); next.section_order.push(id); })}>{copy('Add another section', '添加其他章节')}</button>
          <button type="button" className={`${button} bg-indigo-600 text-white`} disabled={blocked || conflict || !draft?.dirty} onClick={apply}>{copy('Apply changes', '应用修改')}</button>
        </div>
        <section aria-label={copy('Résumé preview', '简历预览')} className="mt-6 rounded-xl border border-indigo-100 bg-indigo-50/30 p-4">
          <h3 className="font-semibold">{copy('Confirmed content preview', '已确认内容预览')}</h3>
          <p className="mt-1 text-xs text-gray-600">{copy('This previews the current editor, including changes you have not applied yet. Only confirmed facts and eligible experience versions appear.', '这里预览当前编辑内容，也包含尚未应用的修改。只展示已确认事实与有效经历版本。')}</p>
          {!previewReady && <p role="status" className="mt-3 text-sm text-amber-800">{copy('Complete or remove empty added fields and check size limits to preview this draft. All input remains in the editor.', '请填写或删除新增的空字段，并检查篇幅限制后再预览。所有输入仍保留在编辑器中。')}</p>}
          {previewReady && previewBlocks === 0 && <p className="mt-3 text-sm text-gray-500">{copy('No confirmed content to preview yet.', '暂无已确认内容可预览。')}</p>}
          {preview.sections.filter((section) => section.blocks.length > 0).map((section) => <section key={section.id} className="mt-4">
            <h4 className="font-medium text-gray-900">{headingFor(section.id) || section.heading}</h4>
            {section.blocks.map((block) => {
              const labels = previewLabels(section.id, block.id);
              return <dl key={block.id} className="mt-3 space-y-2">{block.lines.map((line, index) => <div key={index}>
                {labels[index] && <dt className="text-xs font-medium text-gray-500">{labels[index]}</dt>}
                <dd className="whitespace-pre-wrap break-words text-sm">{line}</dd>
              </div>)}</dl>;
            })}
          </section>)}
          {(preview.excludedFactCount > 0 || preview.unresolvedExperienceRefs.length > 0) && <p className="mt-3 text-xs text-amber-800">{copy('Unconfirmed, excluded or outdated material is omitted. Review the fields and experience references above.', '未确认、已排除或已失效的材料不会展示，请核对上方字段与经历引用。')}</p>}
        </section>
      </details>}
    </Card>
  </section>;
}
