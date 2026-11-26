'use client';

import { useState } from 'react';
import { alreadyImported, authorIdentifier, studentWorks } from '@/lib/student-publications';
import type { StudentWork } from '@/lib/student-publications';
import type { ResumePublicationItem } from '@/lib/types';

const button = 'rounded-lg border border-gray-300 px-3 py-2 text-sm disabled:opacity-40';
const field = 'w-full rounded-lg border border-gray-300 p-2 text-sm';

export function StudentPublicationImport({ scholar, items, disabled, copy, onConfirm }: {
  scholar: string | null; items: ResumePublicationItem[]; disabled: boolean;
  copy: (en: string, zh: string) => string; onConfirm: (work: StudentWork) => void;
}) {
  const [author, setAuthor] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [json, setJson] = useState('');
  const [result, setResult] = useState<ReturnType<typeof studentWorks> | null>(null);
  const [error, setError] = useState(false);
  const identifier = authorIdentifier(author);
  return <details className="mt-3 rounded-lg border p-3">
    <summary id="student-publication-import" className="scroll-mt-24 cursor-pointer font-medium">{copy('Import my publications from OpenAlex', '从 OpenAlex 导入我的论文')}</summary>
    {!scholar ? <p className="mt-2 text-sm"><a className="underline" href="#scholar_url">{copy('Add your Google Scholar profile in Online Profiles first.', '请先在在线资料中填写本人的 Google Scholar 主页。')}</a></p> :
      <fieldset disabled={disabled} className="mt-3 space-y-3 text-sm">
        <p>{copy('Check that both public profiles identify you.', '请核对这两个公开作者主页是否都属于你。')} <a className="underline" target="_blank" rel="noreferrer" href={'https://scholar.google.com/citations?user=' + scholar}>Google Scholar · {scholar}</a></p>
        <label className="block">{copy('Your OpenAlex author ID or ORCID', '你的 OpenAlex 作者 ID 或 ORCID')}
          <input className={field} value={author} onChange={(event) => {
            setAuthor(event.target.value); setConfirmed(false); setResult(null); setError(false);
          }} placeholder="A… / 0000-0000-0000-000X" />
        </label>
        {identifier && <a className="block underline" rel="noreferrer" target="_blank"
          href={(identifier.startsWith('A') ? 'https://openalex.org/' : 'https://orcid.org/') + identifier}>{identifier}</a>}
        <label className="flex items-center gap-2"><input type="checkbox" checked={confirmed} disabled={!identifier}
          onChange={(event) => { setConfirmed(event.target.checked); setResult(null); setError(false); }} />
          {copy('I confirm that these author profiles are mine.', '我确认这两个作者主页都是我本人的。')}
        </label>
        {confirmed && identifier && <>
          <label className="block">{copy('Paste your public OpenAlex Works JSON export (up to 200 works).', '粘贴你的公开 OpenAlex 作品 JSON 导出（最多 200 篇）。')}
            <textarea className={field} rows={3} value={json} maxLength={2_000_000}
              onChange={(event) => { setJson(event.target.value); setResult(null); setError(false); }} />
          </label>
          <button type="button" className={button} disabled={!json.trim()} onClick={() => {
            try { setResult(studentWorks(json, scholar, identifier)); setError(false); }
            catch { setError(true); setResult(null); }
          }}>{copy('Check authorships', '核对署名')}</button>
        </>}
        {error && <p role="alert">{copy('Use a public OpenAlex Works JSON export containing IDs and authorships, up to 200 works and 2 million characters.', '请使用包含作品 ID 与署名的公开 OpenAlex 作品 JSON，最多 200 篇、200 万字符。')}</p>}
        {result && <div aria-live="polite"><p>{copy('Matching works', '匹配作品')} · {result.works.length} / {copy('Skipped', '已略过')} · {result.skipped}</p>
          {result.works.length > 0 && <p>{copy('Open each work and check your byline before confirming.', '请打开作品来源，核对自己的署名后再确认。')}</p>}
          <ul>{result.works.map((work) => <li className="mt-3" key={work.source.work_id}>
            <a className="font-medium underline" href={'https://openalex.org/' + work.source.work_id} target="_blank" rel="noreferrer">{work.title}</a>
            <p>{copy('Listed author', '作品署名')} · {work.authorName} · {work.source.author_id}{work.doi && <> · DOI {work.doi}</>}</p>
            <button type="button" className={button} disabled={alreadyImported(items, work)}
              onClick={() => onConfirm(work)}>{alreadyImported(items, work)
                ? copy('Already in résumé', '已在简历中') : copy('Confirm this is my publication', '确认这是我的论文')}</button>
          </li>)}</ul>
        </div>}
      </fieldset>}
  </details>;
}
