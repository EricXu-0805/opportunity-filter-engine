'use client';

import { useEffect, useRef, useState } from 'react';
import { useLocale } from '@/i18n/client';
import {
  commitWorkReview, emptyWorkRecord, MAX_WORK_FILE_BYTES, parseWorkCsv, parseWorkPaste,
  prepareWorkReview, validWorkRecord, workText,
} from '@/lib/linkedin-experience-import';
import type { ImportAction, WorkField, WorkRecord, WorkReview } from '@/lib/linkedin-experience-import';
import type { ExperienceEntry } from '@/lib/types';

const copy = {
  en: {
    title: 'Import LinkedIn experience', hint: 'Use your own Positions.csv, paste experience text, or enter a role. A profile link alone does not import work history.',
    method: 'Input method', file: 'Positions.csv', paste: 'Paste text', manual: 'Enter a role', text: 'Experience text',
    company: 'Company', role: 'Role', start: 'Start date', end: 'End date', duties: 'Responsibilities', results: 'Results',
    review: 'Preview experiences', edit: 'Back to input', confirm: 'Confirm selected experiences',
    owner: 'Check the employer, dates, responsibilities and results. Leave unstated information blank.',
    target: 'Compare with an existing experience or résumé passage', none: 'Choose a record', decision: 'Choose what to save',
    add: 'Save as a separate experience', keep: 'Keep the existing wording', combine: 'Use my combined wording', skip: 'Skip this row',
    combined: 'Final wording to keep', imported: 'Imported wording', existing: 'Existing wording',
    mergeHint: 'Your combined wording replaces the active entry. The original stays in the library as withdrawn.',
    choose: 'Choose an action', saved: 'Confirmed experiences saved to your profile', unchanged: 'No experiences changed.',
    csv: 'Select a readable Positions.csv with company and title columns. Check that rows and quotes are complete.',
    limit: 'This import exceeds the experience limit. Review fewer roles or shorten the text.',
    fields: 'Each saved role needs a company and a role, responsibility or result.',
    targetError: 'Choose an existing record and check the final wording.',
    decisionError: 'Choose an action for each role before confirming.',
    duplicate: 'This role was already imported or selected more than once. Keep the existing record, choose combined wording, or skip the repeated row.',
    stale: 'Your profile changed. Return to input and preview it again before saving.',
    textError: 'Paste your experience text. A profile link alone has no work history.',
    failed: 'The import could not be read. Your existing experience is safe. Try again.',
  },
  zh: {
    title: '导入 LinkedIn 经历', hint: '使用本人的 Positions.csv、粘贴经历文字或手工填写职位。单独保存个人主页链接不会导入经历。',
    method: '输入方式', file: 'Positions.csv', paste: '粘贴文字', manual: '手工填写', text: '经历文字',
    company: '公司', role: '职位', start: '开始日期', end: '结束日期', duties: '职责', results: '成果',
    review: '预览经历', edit: '返回输入', confirm: '确认选中的经历',
    owner: '请核对公司、时间、职责和成果。未提及的内容可以留空。',
    target: '选择对照的已有经历或简历段落', none: '选择记录', decision: '选择保存方式',
    add: '另存为独立经历', keep: '保留已有表述', combine: '使用我合并后的表述', skip: '跳过此条',
    combined: '最终保留的表述', imported: '导入的表述', existing: '已有表述',
    mergeHint: '合并后使用你确认的文字，原始条目以已撤回状态保留在经历库中。',
    choose: '选择处理方式', saved: '选中的经历已确认并加入资料', unchanged: '经历未变更。',
    csv: '请选择包含公司和职位列的 Positions.csv，并检查行和引号是否完整。',
    limit: '已超出经历容量，请减少本次导入条数或缩短文字。', fields: '每条要保存的经历都需要公司，以及职位、职责或成果中的至少一项。',
    targetError: '请选择对照记录，并检查最终保留的表述。', decisionError: '请为每条经历选择保存方式。',
    duplicate: '同一条经历已导入或被选中多次。可以保留原记录、选择合并文字，或跳过重复行。',
    stale: '资料已有更新，请返回输入并重新预览后保存。', textError: '请粘贴经历文字。仅有主页链接无法导入工作经历。',
    failed: '本次导入未能读完，已有经历保留。请重试。',
  },
} as const;

type Labels = typeof copy.en | typeof copy.zh;
type Snapshot = { resumeText: string; entriesJson: string };
const fields: WorkField[] = ['company', 'role', 'start', 'end', 'duties', 'results'];
const control = 'mt-1 block w-full rounded-lg border border-gray-300 p-2 text-sm';
const button = 'mt-3 rounded-lg border border-indigo-300 px-3 py-2 text-sm text-indigo-700 disabled:opacity-40';

function WorkFields({ value, change, labels, disabled }: {
  value: WorkRecord; change: (v: WorkRecord) => void; labels: Labels; disabled: boolean;
}) {
  return <div className="grid gap-2 sm:grid-cols-2">{fields.map(key =>
    <label key={key} className={'block text-sm ' + (key === 'duties' || key === 'results' ? 'sm:col-span-2' : '')}>
      {labels[key]}
      {key === 'duties' || key === 'results'
        ? <textarea className={control} rows={3} value={value[key]} disabled={disabled}
            onChange={e => change({ ...value, [key]: e.target.value })} />
        : <input className={control} value={value[key]} disabled={disabled}
            onChange={e => change({ ...value, [key]: e.target.value })} />}
    </label>)}</div>;
}

export function LinkedInExperienceImport({ entries, raw, disabled, onSave }: {
  entries: ExperienceEntry[]; raw: string; disabled: boolean;
  onSave: (next: ExperienceEntry[], snapshot: Snapshot) => boolean;
}) {
  const labels = copy[useLocale()];
  const [mode, setMode] = useState<'file' | 'paste' | 'manual'>('file');
  const [file, setFile] = useState<File>();
  const [paste, setPaste] = useState('');
  const [manual, setManual] = useState(emptyWorkRecord);
  const [review, setReview] = useState<{ rows: WorkReview[]; targets: ExperienceEntry[]; base: Snapshot }>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  const report = (caught: unknown) => {
    const code = caught instanceof Error ? caught.message : '';
    const known = { csv: labels.csv, limit: labels.limit, fields: labels.fields, target: labels.targetError,
      decision: labels.decisionError, duplicate: labels.duplicate, text: labels.textError };
    setError(known[code as keyof typeof known] ?? labels.failed);
  };
  const preview = async () => {
    const run = ++generation.current;
    const base = { resumeText: raw, entriesJson: JSON.stringify(entries) };
    setError(''); setNotice(''); setBusy(true);
    try {
      let values: WorkRecord[];
      if (mode === 'file') {
        if (!file) throw Error('csv');
        if (file.size > MAX_WORK_FILE_BYTES) throw Error('limit');
        values = parseWorkCsv(await file.text());
      } else if (mode === 'paste') {
        values = parseWorkPaste(paste);
      } else {
        if (!validWorkRecord(manual)) throw Error('fields');
        values = [{ ...manual }];
      }
      const prepared = await prepareWorkReview(values, entries, raw);
      if (generation.current === run) setReview({ ...prepared, base });
    } catch (caught) {
      if (generation.current === run) report(caught);
    } finally {
      if (generation.current === run) setBusy(false);
    }
  };
  const update = (index: number, next: Partial<WorkReview>) =>
    setReview(r => r && ({ ...r, rows: r.rows.map((item, i) => i === index ? { ...item, ...next } : item) }));
  const confirm = () => {
    if (!review || disabled) return;
    setError('');
    if (review.base.resumeText !== raw || review.base.entriesJson !== JSON.stringify(entries)) { setError(labels.stale); return; }
    try {
      const next = commitWorkReview(review.rows, entries, review.targets);
      const changed = JSON.stringify(next) !== review.base.entriesJson;
      if (changed && !onSave(next, review.base)) { setError(labels.stale); return; }
      setReview(undefined); setNotice(changed ? labels.saved : labels.unchanged);
      if (changed) { setFile(undefined); setPaste(''); setManual(emptyWorkRecord()); }
    } catch (caught) { report(caught); }
  };
  return <details className="mt-4">
    <summary className="cursor-pointer text-sm font-medium text-indigo-700">{labels.title}</summary>
    {!review ? <>
      <p className="my-2 text-xs text-gray-600">{labels.hint}</p>
      <label className="block text-sm">{labels.method}
        <select value={mode} disabled={disabled || busy} className={control} onChange={e => {
          setMode(e.target.value as typeof mode); setError(''); setNotice('');
        }}>
          {(['file', 'paste', 'manual'] as const).map(m => <option key={m} value={m}>{labels[m]}</option>)}
        </select>
      </label>
      {mode === 'file' && <label className="mt-2 block text-sm">{labels.file}
        <input type="file" accept=".csv,text/csv" disabled={disabled || busy} className="mt-1 block w-full"
          onChange={e => { setFile(e.target.files?.[0]); setNotice(''); }} /></label>}
      {mode === 'paste' && <label className="mt-2 block text-sm">{labels.text}
        <textarea className={control} rows={5} value={paste} disabled={disabled || busy} onChange={e => setPaste(e.target.value)} /></label>}
      {mode === 'manual' && <WorkFields value={manual} labels={labels} disabled={disabled || busy} change={setManual} />}
      <button type="button" className={button} disabled={disabled || busy || (mode === 'file' && !file)} onClick={preview}>{labels.review}</button>
    </> : <>
      <p className="my-2 text-sm">{labels.owner}</p>
      {review.rows.map((row, i) => {
        const other = review.targets.find(e => e.id === row.target);
        return <fieldset key={i} className="my-3 space-y-2 rounded-lg border p-3" disabled={disabled}>
          <legend className="px-1 text-sm font-medium">{row.fields.company || labels.company} · {i + 1}/{review.rows.length}</legend>
          <WorkFields value={row.fields} change={fields => update(i, { fields })} labels={labels} disabled={disabled} />
          <label className="block text-sm">{labels.target}
            <select className={control} value={row.target} onChange={e => {
              const selected = review.targets.find(t => t.id === e.target.value);
              update(i, { target: e.target.value, action: '', combined: selected?.text ?? '' });
            }}>
              <option value="">{labels.none}</option>
              {review.targets.map(t => <option key={t.id} value={t.id}>{t.text.slice(0, 110)}</option>)}
            </select>
          </label>
          {other && <p className="whitespace-pre-wrap break-words text-sm"><strong>{labels.existing}</strong>{'\n'}{other.text}</p>}
          <label className="block text-sm">{labels.decision}
            <select className={control} value={row.action} onChange={e => update(i, { action: e.target.value as ImportAction })}>
              <option value="">{labels.choose}</option><option value="new">{labels.add}</option>
              {other && <><option value="keep">{labels.keep}</option><option value="combine">{labels.combine}</option></>}
              <option value="skip">{labels.skip}</option>
            </select>
          </label>
          {row.action === 'combine' && <>
            <p className="whitespace-pre-wrap break-words text-sm"><strong>{labels.imported}</strong>{'\n'}{workText(row.fields)}</p>
            <label className="block text-sm">{labels.combined}
              <textarea className={control} rows={4} value={row.combined} onChange={e => update(i, { combined: e.target.value })} /></label>
            <p className="text-xs">{labels.mergeHint}</p>
          </>}
        </fieldset>;
      })}
      <button type="button" className={button} disabled={disabled} onClick={confirm}>{labels.confirm}</button>
      <button type="button" className="ml-3 text-sm underline" onClick={() => { setReview(undefined); setError(''); }}>{labels.edit}</button>
    </>}
    {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
    {notice && <p role="status" className="mt-2 text-sm">{notice}</p>}
  </details>;
}
