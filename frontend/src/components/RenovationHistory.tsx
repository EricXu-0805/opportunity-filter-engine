'use client';

import { useEffect, useRef, useState } from 'react';
import { listRenovationVersions, readRenovationVersion, type RenovationPayload, type RenovationVersion, type RenovationVersionPage } from '@/lib/supabase';
import { isOwnerTokenValid, type OwnerToken } from '@/lib/identity-owner';
import { shownHeading, shownText } from '@/lib/renovation-review';
import type { RenovationDoc } from '@/lib/types';

// A version saved before the faithfulness review (w13.x) can hold an unreviewed, other-language
// rewrite as a bullet's current wording; the preview shows that bullet's own text instead, as
// opening or restoring the version does (reviewedRenovation). A legacy_doc version is only read here.
// Its section headings show as the student wrote them, or as standard names (shownHeading).
function textOf(doc: Record<string, unknown>, resumeText: string) {
  return (doc as unknown as RenovationDoc).sections.map(s => [shownHeading(s, resumeText), ...s.bullets.map(shownText)].join('\n')).join('\n\n');
}

export default function RenovationHistory({ opportunityId, owner, locale, resumeText = '', disabled, onRestore, onClose }: {
  opportunityId: string; owner: OwnerToken; locale: string; resumeText?: string; disabled: boolean;
  onRestore: (payload: RenovationPayload) => void; onClose: () => void;
}) {
  const zh = locale === 'zh';
  const [page, setPage] = useState<RenovationVersionPage>({ items: [], next_cursor: null });
  const [selected, setSelected] = useState<RenovationVersion | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState(false);
  const alive = useRef(true);
  const request = useRef(0);
  const current = (id: number) => alive.current && request.current === id && isOwnerTokenValid(owner, owner.uid);
  async function load(more = false) {
    const id = ++request.current; setBusy(true); setError(false);
    try {
      const next = await listRenovationVersions(opportunityId, 20, owner, more ? page.next_cursor ?? undefined : undefined);
      if (current(id)) setPage(prev => ({ items: more ? [...prev.items, ...next.items] : next.items, next_cursor: next.next_cursor }));
    } catch { if (current(id)) setError(true); }
    finally { if (current(id)) setBusy(false); }
  }
  async function preview(id: string) {
    const requestId = ++request.current; setBusy(true); setError(false); setSelected(null);
    try {
      const version = await readRenovationVersion(opportunityId, id, owner);
      if (current(requestId)) { setSelected(version); if (!version) setError(true); }
    } catch { if (current(requestId)) setError(true); }
    finally { if (current(requestId)) setBusy(false); }
  }
  useEffect(() => {
    alive.current = true;
    const id = ++request.current;
    const usable = () => alive.current && request.current === id && isOwnerTokenValid(owner, owner.uid);
    void listRenovationVersions(opportunityId, 20, owner).then(next => {
      if (usable()) setPage(next);
    }).catch(() => { if (usable()) setError(true); })
      .finally(() => { if (usable()) setBusy(false); });
    return () => { alive.current = false; };
  }, [opportunityId, owner]);
  const complete = selected?.snapshot_kind === 'complete' && selected.payload.base_snapshot !== null && selected.payload.warnings !== null;
  return <section aria-label={zh ? '简历历史' : 'Résumé history'} className="mx-4 my-3 rounded-xl border border-indigo-200 p-4 space-y-3" data-testid="renovation-history">
    <div className="flex items-center justify-between gap-3"><h3 className="font-semibold">{zh ? '历史版本' : 'Version history'}</h3><button type="button" onClick={onClose} className="text-sm underline">{zh ? '关闭历史' : 'Close history'}</button></div>
    {busy && <p role="status">{zh ? '正在读取…' : 'Loading history…'}</p>}
    {error && <p role="alert">{zh ? '未能读取历史，当前稿已保留。' : 'Could not read history. Your current draft is kept.'} <button type="button" className="underline" onClick={() => void load()}>{zh ? '重试历史读取' : 'Retry history'}</button></p>}
    {!busy && !error && page.items.length === 0 && <p>{zh ? '还没有历史版本。' : 'No saved versions yet.'}</p>}
    <ul className="space-y-2">{page.items.map(v => <li key={v.id}><button type="button" disabled={busy} onClick={() => void preview(v.id)} className="text-sm text-indigo-700 underline">
      {v.revision !== null ? `${zh ? '版本' : 'Version'} ${v.revision}` : (zh ? '导入的旧版本' : 'Imported version')} · {new Date(v.created_at).toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US')}
      {v.snapshot_kind === 'legacy_doc' && (zh ? '（缺少原始来源）' : ' (source unavailable)')}
    </button></li>)}</ul>
    {page.next_cursor && <button type="button" disabled={busy} onClick={() => void load(true)} className="text-sm underline">{zh ? '更多历史' : 'More versions'}</button>}
    {selected && <div className="space-y-2 border-t pt-3">
      <p className="text-sm">{complete ? (zh ? '恢复会保存为新版本。当前稿与原历史都会保留。' : 'Restoring saves a new version. The current saved draft and earlier history stay in history.') : (zh ? '这份旧历史没有保存原始简历，只能查看；不能用当前来源补齐后恢复。' : 'This older version has no saved source résumé. You can read it, but it cannot be restored with the current source.')}</p>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-gray-50 p-3 text-sm" data-testid="renovation-history-preview">{textOf(selected.payload.doc, resumeText)}</pre>
      {complete && <button type="button" disabled={disabled || busy} className="text-sm font-semibold text-indigo-700 underline disabled:text-gray-400" onClick={() => onRestore(selected.payload as RenovationPayload)}>{zh ? '恢复为新版本' : 'Restore as new version'}</button>}
      {disabled && complete && <p className="text-sm text-amber-700">{zh ? '请先完成当前编辑或处理保存问题。' : 'Finish the current edit or resolve the save issue first.'}</p>}
    </div>}
  </section>;
}
