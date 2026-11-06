'use client';

import { useLocale } from '@/i18n/client';
import type { PrivateResumeTargetState } from '@/lib/use-private-resume-target';

export default function PrivateResumeStatus({ state, available = true, draft = false }: { state: PrivateResumeTargetState; available?: boolean; draft?: boolean }) {
  const locale = useLocale();
  if (state.status === 'ready' && available) return null;
  const copy = (en: string, zh: string) => locale === 'zh' ? zh : en;
  // Only an open draft can be kept; the launcher's loading dialog has none yet.
  const kept = (withDraft: [string, string], without: [string, string]) => copy(...(draft ? withDraft : without));
  const message = !available || state.status === 'missing'
    ? kept(['This private import is no longer available. Your draft is kept.', '这条私有导入已不可用，文稿仍保留。'], ['This private import is no longer available.', '这条私有导入已不可用。'])
    : state.status === 'offline' ? kept(['You are offline. Your draft is kept; reconnect to check the source.', '当前离线，文稿仍保留；联网后重新核对来源。'], ['You are offline. Reconnect to check the source.', '当前离线，联网后重新核对来源。'])
    : state.status === 'checking' ? copy('Checking your saved private source…', '正在核对已保存的私有来源…')
    : state.reason === 'too_large' ? copy('The complete source exceeds the résumé draft limit. No text was removed; your saved import is unchanged.', '完整来源超过简历文稿容量，内容未截断，已保存的导入保持原样。')
    : kept(['Could not check this private source. Your draft is kept; try again.', '暂时无法核对私有来源，文稿仍保留，可重试。'], ['Could not check this private source. Try again.', '暂时无法核对私有来源，可重试。']);
  return <div role={state.status === 'failed' ? 'alert' : 'status'} className="max-h-[20vh] shrink-0 overflow-y-auto border-b bg-amber-50 px-4 py-2 text-sm text-amber-900">
    <p>{message}</p>
    {state.status !== 'checking' && <button type="button" className="mt-1 min-h-10 underline" onClick={() => void state.refresh()}>{copy('Check private source again', '重新核对私有来源')}</button>}
  </div>;
}
