import type { ColdEmailDraftVersion } from '@/lib/cold-email-draft';

type Props = {
  locale: string; versions: ColdEmailDraftVersion[]; busy: boolean; error: string | null;
  /** Comparing and restoring wait, e.g. while an AI draft is being generated. */
  restoreDisabled: boolean;
  comparison: { version: ColdEmailDraftVersion; subject: string; body: string } | null;
  onCompare: (version: ColdEmailDraftVersion) => void;
  onRestore: () => void; onCancel: () => void; onDelete: (id: string) => void;
};

export default function EmailVersionHistory({ locale, versions, busy, restoreDisabled, error, comparison, onCompare, onRestore, onCancel, onDelete }: Props) {
  const zh = locale === 'zh';
  const reasons = zh ? { accepted_edit: '接受修改前', regenerated: '重新生成前', restored: '恢复旧版前', undo: '撤销修改前', variant: '切换稿件前' }
    : { accepted_edit: 'Before accepting an edit', regenerated: 'Before regeneration', restored: 'Before restoring a version', undo: 'Before undo', variant: 'Before switching drafts' };
  return <details className="rounded-xl border border-gray-200 px-3.5 py-3 text-sm text-gray-700" data-testid="cold-email-history">
    <summary className="cursor-pointer font-semibold">{zh ? '版本历史' : 'Version history'} ({versions.length}/10)</summary>
    <p className="mt-2 text-xs text-gray-600">{zh ? '只保存在此浏览器，最多 10 个版本。容量不足时不会替换当前稿，也不会自动删除旧版。' : 'Saved only on this browser, up to 10 versions. If storage is full, your draft stays unchanged and no versions are removed automatically.'}</p>
    {error && <p role="alert" className="mt-2 text-amber-900">{error}</p>}
    {busy && <p role="status" className="mt-2">{zh ? '正在保存版本…' : 'Saving version…'}</p>}
    {versions.length === 0 && <p className="mt-3 text-xs">{zh ? '接受修改、重生成或切换稿件后，原稿会出现在这里。' : 'Previous drafts appear here after accepting an edit, regenerating, or switching drafts.'}</p>}
    <ul className="mt-3 space-y-3">
      {[...versions].reverse().map(version => <li key={version.id} data-testid="cold-email-history-item" data-version-id={version.id} className="rounded-lg bg-gray-50 p-3 space-y-2">
        <p className="font-medium">{reasons[version.reason]}</p>
        <time dateTime={version.createdAt} className="block text-xs text-gray-600">{new Date(version.createdAt).toLocaleString(zh ? 'zh-CN' : 'en-US')}</time>
        <p className="break-words">{version.subject || (zh ? '（无主题）' : '(No subject)')}</p>
        <p className="whitespace-pre-wrap break-words text-xs text-gray-600">{version.body.slice(0, 120)}{version.body.length > 120 ? '…' : ''}</p>
        <div className="flex flex-wrap gap-3">
          <button type="button" disabled={busy || restoreDisabled} onClick={() => onCompare(version)} className="underline text-indigo-700 disabled:opacity-50">{zh ? '比较并恢复' : 'Compare and restore'}</button>
          <button type="button" disabled={busy} onClick={() => onDelete(version.id)} className="underline disabled:opacity-50">{zh ? '删除此版本' : 'Delete this version'}</button>
        </div>
      </li>)}
    </ul>
    {comparison && <section aria-label={zh ? '比较邮件版本' : 'Compare email versions'} className="mt-4 space-y-3 rounded-lg border border-indigo-200 bg-white p-3">
      <p className="text-xs text-gray-600">{zh ? '恢复前先保存当前稿。仅恢复主题、正文和语气；不会恢复收件人、阅读确认或已发送状态。旧版仍按原资料核对。' : 'Your current draft is saved first. Only the subject, body, and tone are restored; recipient, reading confirmations, and sent status are not restored. The version keeps its original source references.'}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div><h4 className="font-semibold">{zh ? '当前草稿' : 'Current draft'}</h4><p className="mt-2 whitespace-pre-wrap break-words font-medium">{comparison.subject}</p><p className="mt-2 whitespace-pre-wrap break-words">{comparison.body}</p></div>
        <div><h4 className="font-semibold">{zh ? '已保存版本' : 'Saved version'}</h4><p className="mt-2 whitespace-pre-wrap break-words font-medium">{comparison.version.subject}</p><p className="mt-2 whitespace-pre-wrap break-words">{comparison.version.body}</p></div>
      </div>
      <div className="flex flex-wrap gap-3">
        <button type="button" disabled={busy || restoreDisabled} onClick={onRestore} className="rounded-lg bg-indigo-600 px-3 py-2 text-white disabled:opacity-50">{zh ? '恢复此版本' : 'Restore this version'}</button>
        <button type="button" disabled={busy} onClick={onCancel} className="rounded-lg border border-gray-300 px-3 py-2 disabled:opacity-50">{zh ? '取消' : 'Cancel'}</button>
      </div>
    </section>}
  </details>;
}
