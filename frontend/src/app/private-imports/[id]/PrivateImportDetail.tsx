'use client';

import { useEffect, useState, useSyncExternalStore } from 'react';
import Link from 'next/link';
import { useT } from '@/i18n/client';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange } from '@/lib/identity-owner';
import { getPrivateImportTarget, getResolvedPrivateImportTarget, PrivateTargetError, type PrivateResolvedTarget } from '@/lib/private-import-target-api';
import ContactHistory from '@/components/ContactHistory';
import ApplicationRecordForm from '@/components/ApplicationRecordForm';
import ApplicationHistory from '@/components/ApplicationHistory';

const copy = {
  en: { back: 'Back to saved opportunities', title: 'Private import', checking: 'Loading your saved import…',
    error: 'This import could not be loaded. Your history has not been removed.', missing: 'This import is not available in this account.',
    signIn: 'Sign in to open an account import.', retry: 'Try again', deleted: 'This account copy was deleted. Your recorded contact and application history remains below.',
    unverified: 'Imported content — not independently verified. It does not establish an opening, eligibility, or permission to contact.',
    source: 'View source page', original: 'Full imported text', history: 'Your recorded history', writes: 'Email and résumé preparation for private imports is not connected yet.' },
  zh: { back: '返回已保存机会', title: '账户中的导入', checking: '正在读取账户中的导入…',
    error: '暂时无法读取这条导入，历史记录没有删除。', missing: '当前账户无法查看这条导入。',
    signIn: '登录后可查看账户中的导入。', retry: '重试', deleted: '这条账户副本已删除；已记录的联系和申请历史仍保留在下方。',
    unverified: '导入内容尚未独立核对，不代表存在空缺、符合资格或允许联系。',
    source: '查看来源网页', original: '完整导入原文', history: '已记录的历史', writes: '私有机会的邮件和简历准备尚未接通。' },
};
function snapshot() { const token = captureOwnerToken(); return JSON.stringify([token.uid, token.epoch, token.generation, isOwnerTokenValid(token, token.uid)]); }
function subscribe(fn: () => void) { const off = onLocalOwnerStateChange(fn); window.addEventListener('storage', fn); return () => { off(); window.removeEventListener('storage', fn); }; }
type Result = { scope: string; status: 'ready'; target: PrivateResolvedTarget } | { scope: string; status: 'deleted' | 'missing' | 'error' | 'sign_in' };

export default function PrivateImportDetail({ id }: { id: string }) {
  const { locale } = useT(); const text = locale === 'zh' ? copy.zh : copy.en;
  const owner = useSyncExternalStore(subscribe, snapshot, () => 'server');
  const [historyEpoch, setHistoryEpoch] = useState(0);
  const [retry, setRetry] = useState(0); const scope = JSON.stringify([id, owner, retry]);
  const [result, setResult] = useState<Result | null>(null);
  const view = result?.scope === scope ? result : null;
  useEffect(() => {
    let active = true; const controller = new AbortController(); const origin = captureOwnerToken();
    const current = () => active && !controller.signal.aborted && isOwnerTokenValid(origin, origin.uid);
    void Promise.resolve().then(async () => {
      if (!current()) return;
      const raw = await getPrivateImportTarget(id, { owner: origin, signal: controller.signal });
      if (!current()) return;
      if (raw === null) { setResult({ scope, status: 'missing' }); return; }
      if (raw.target.deleted_at !== null) { setResult({ scope, status: 'deleted' }); return; }
      const target = await getResolvedPrivateImportTarget(id, { owner: origin, signal: controller.signal, expectedVersion: raw.target.target_version });
      if (current()) setResult({ scope, status: 'ready', target });
    }).catch(error => {
      if (current()) setResult({ scope, status: error instanceof PrivateTargetError && error.code === 'sign_in_required' ? 'sign_in'
        : error instanceof PrivateTargetError && error.code === 'deleted' ? 'deleted' : 'error' });
    });
    return () => { active = false; controller.abort(); };
  }, [id, scope]);
  const unreadyOwner = owner === 'server' || !JSON.parse(owner)[0] || JSON.parse(owner)[3] !== true;
  const content = view?.status === 'ready' ? view.target.detail : null;
  const history = !unreadyOwner && (view?.status === 'ready' || view?.status === 'deleted');
  return <main className="mx-auto max-w-4xl space-y-6 px-4 py-8">
    <Link href="/favorites" className="inline-flex min-h-10 items-center text-sm text-indigo-700 underline">{text.back}</Link>
    <h1 className="break-words text-2xl font-semibold">{content?.title || text.title}</h1>
    {unreadyOwner || view?.status === 'sign_in' ? <p role="status">{text.signIn}</p>
      : !view ? <p role="status">{text.checking}</p>
      : view.status === 'missing' ? <p role="status">{text.missing}</p>
      : view.status === 'error' ? <div role="alert"><p>{text.error}</p><button type="button" className="min-h-10 underline" onClick={() => setRetry(n => n + 1)}>{text.retry}</button></div>
      : view.status === 'deleted' ? <p role="status">{text.deleted}</p> : null}
    {content && <section className="space-y-3">
      {content.organization && <p className="break-words">{content.organization}</p>}
      <p className="text-sm text-amber-800">{text.unverified}</p>
      {(content.source_url || content.url) && <a href={content.source_url || content.url || undefined} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-10 items-center text-indigo-700 underline">{text.source}</a>}
      <details className="rounded-xl border p-4"><summary className="min-h-10 cursor-pointer font-medium">{text.original}</summary><p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{content.description_raw}</p></details>
      <p className="text-sm text-gray-600">{text.writes}</p>
    </section>}
    {history && <section key={scope} id="tracker-records" className="space-y-6 border-t pt-6">
      <h2 className="text-lg font-semibold">{text.history}</h2>
      {view?.status === 'ready' && <ApplicationRecordForm opportunityId={id} ownerReady={true} onConfirmed={() => setHistoryEpoch(n => n + 1)} />}
      <ContactHistory opportunityId={id} refreshKey={String(historyEpoch)} />
      <ApplicationHistory opportunityId={id} refreshKey={String(historyEpoch)} />
    </section>}
  </main>;
}
