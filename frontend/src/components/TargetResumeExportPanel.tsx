'use client';

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useLocale } from '@/i18n/client';
import { ApiError } from '@/lib/api';
import { isOwnerTokenValid, onLocalOwnerStateChange, type OwnerToken } from '@/lib/identity-owner';
import { prepareTargetResumeExport, isPreparedTargetResumeExportCurrent } from '@/lib/target-resume-export';
import { fetchTargetResumeExport, downloadTargetResumeExport } from '@/lib/target-resume-export-api';
import type { TargetResumeV1 } from '@/lib/target-resume';
import type { TargetResumeExportFormat, TargetResumeExportLocale, TargetResumeExportPageSize } from '@/lib/target-resume-export-protocol';

export interface TargetResumeExportPanelProps {
  draft: TargetResumeV1; owner: OwnerToken; contextKey: string;
  enabled: boolean; unsaved: boolean; outdated: boolean;
}
const control = 'rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm disabled:opacity-40';
export default function TargetResumeExportPanel({ draft, owner, contextKey, enabled, unsaved, outdated }: TargetResumeExportPanelProps) {
  const uiLocale = useLocale(); const copy = (en: string, zh: string) => uiLocale === 'zh' ? zh : en;
  const [locale, setLocale] = useState<TargetResumeExportLocale>(uiLocale === 'zh' ? 'zh' : 'en');
  const [pageSize, setPageSize] = useState<TargetResumeExportPageSize>('letter');
  const [busy, setBusy] = useState<TargetResumeExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const draftKey = useMemo(() => JSON.stringify(draft), [draft]);
  const binding = `${owner.uid}:${owner.epoch}:${owner.generation}\n${contextKey}\n${locale}:${pageSize}\n${draftKey}`;
  const state = useRef({ binding, owner, draft, enabled });
  const operation = useRef({ generation: 0, controller: null as AbortController | null, busy: false });
  useLayoutEffect(() => {
    const changed = state.current.binding !== binding || (state.current.enabled && !enabled);
    state.current = { binding, owner, draft, enabled };
    if (!changed) return;
    operation.current.generation += 1; operation.current.controller?.abort(); operation.current.busy = false;
    setBusy(null); setError(null); setDone(false);
  }, [binding, owner, draft, enabled]);
  useEffect(() => {
    const current = operation.current;
    const unsubscribe = onLocalOwnerStateChange(() => {
      if (isOwnerTokenValid(state.current.owner, state.current.owner.uid)) return;
      current.generation += 1; current.controller?.abort(); current.busy = false;
      setBusy(null); setDone(false); setError(null);
    });
    return () => { current.generation += 1; current.controller?.abort(); current.busy = false; unsubscribe(); };
  }, []);
  const ready = enabled && isOwnerTokenValid(owner, owner.uid);
  const generate = async (format: TargetResumeExportFormat) => {
    if (!ready || operation.current.busy) return;
    const expected = binding, generation = ++operation.current.generation;
    const controller = new AbortController(); operation.current.controller = controller; operation.current.busy = true;
    const live = () => operation.current.generation === generation && state.current.binding === expected
      && state.current.enabled && isOwnerTokenValid(state.current.owner, state.current.owner.uid);
    setBusy(format); setError(null); setDone(false);
    try {
      const result = await prepareTargetResumeExport(draft, { locale, page_size: pageSize });
      if (!live()) return;
      if (!result.ok) { setError(result.code); return; }
      const prepared = result.value;
      const file = await fetchTargetResumeExport({ version: 1, request_id: crypto.randomUUID(), format,
        document_signature: prepared.document_signature, export_signature: prepared.export_signature,
        projection: prepared.projection }, { owner, signal: controller.signal });
      if (!live() || !isPreparedTargetResumeExportCurrent(prepared, state.current.draft)) return;
      downloadTargetResumeExport(file); setDone(true);
    } catch (caught) { if (live()) setError(caught instanceof ApiError ? caught.code : 'export_failed'); }
    finally { if (operation.current.generation === generation) { operation.current.busy = false; operation.current.controller = null; setBusy(null); } }
  };
  const reasons: Record<string, string> = {
    empty_document: copy('Select at least one non-empty field before exporting.', '请先选择至少一项非空内容。'),
    unsupported_character: copy('The selected text contains a character this format cannot store. Your text is kept.', '所选内容含文件格式无法保存的字符，原文仍保留。'),
    invalid_export_text: copy('The selected text contains a character this format cannot store. Your text is kept.', '所选内容含文件格式无法保存的字符，原文仍保留。'),
    unsupported_glyph: copy('The export fonts cannot render part of the selected text. Your complete draft is kept.', '导出字体无法显示部分所选字符，完整文稿保留。'),
    document_too_large: copy('This complete draft exceeds the export limit. No text was removed.', '完整文稿超过导出容量，内容未删减。'),
    export_too_large: copy('This complete draft exceeds the export limit. No text was removed.', '完整文稿超过导出容量，内容未删减。'),
    export_timeout: copy('Export did not finish in time. Your draft is kept; you can try again.', '导出未及时完成，原稿保留，可重试。'),
    fonts_unavailable: copy('The export fonts are temporarily unavailable. Your draft is kept.', '导出字体暂不可用，原稿保留。'),
  };
  return <section aria-label="Export current résumé" className="my-4 min-w-0 rounded-xl border p-4">
    <h3 className="font-semibold">{copy('Export current draft', '导出当前稿')}</h3>
    <p className="mt-1 text-sm text-gray-600">{copy('Exports the selected content shown in your current draft. Section headings change language; your wording stays as written.', '导出当前稿中已勾选的内容。语言选项只改变章节及字段标签，正文保持原文。')}</p>
    {unsaved && <p className="mt-2 text-sm text-amber-800">{copy('Includes unsaved edits. Exporting does not save this version to your account.', '包含未保存的修改；导出不会将此版本保存到账户。')}</p>}
    {outdated && <p className="mt-2 text-sm text-amber-800">{copy('This draft uses earlier source materials. Exporting keeps that version.', '此稿使用较早的来源材料，导出保留该版本。')}</p>}
    <div className="mt-3 flex flex-wrap items-end gap-3">
      <label className="text-sm">{copy('Section headings', '章节标签语言')}<select aria-label={copy('Section headings language', '章节标签语言')} className={`${control} ml-2`} value={locale} disabled={!!busy} onChange={(event) => setLocale(event.target.value as TargetResumeExportLocale)}><option value="en">English</option><option value="zh">中文</option></select></label>
      <label className="text-sm">{copy('Paper size', '纸张')}<select aria-label={copy('Paper size', '纸张')} className={`${control} ml-2`} value={pageSize} disabled={!!busy} onChange={(event) => setPageSize(event.target.value as TargetResumeExportPageSize)}><option value="letter">Letter</option><option value="a4">A4</option></select></label>
      <button type="button" className={control} disabled={!ready || !!busy} onClick={() => void generate('pdf')}>{copy('Export PDF', '导出 PDF')}</button>
      <button type="button" className={control} disabled={!ready || !!busy} onClick={() => void generate('docx')}>{copy('Export Word', '导出 Word')}</button>
      {busy && <button type="button" className={control} onClick={() => { operation.current.generation += 1; operation.current.controller?.abort(); operation.current.busy = false; setBusy(null); }}>{copy('Cancel export', '取消导出')}</button>}
    </div>
    {busy && <p role="status" className="mt-2 text-sm">{copy('Preparing your file…', '正在生成文件…')}</p>}
    {done && <p role="status" className="mt-2 text-sm">{copy('Download started. Open the file to review text, links and page breaks.', '已开始下载。请打开文件检查文字、链接和分页。')}</p>}
    {error && <p role="alert" className="mt-2 text-sm text-red-700">{reasons[error] ?? copy('The export could not be completed. Your draft is kept; you can try again.', '导出未完成，原稿保留，可重试。')}</p>}
  </section>;
}
