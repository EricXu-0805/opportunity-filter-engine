'use client';

import Link from 'next/link';
import type { ProfileRefreshState } from '@/lib/use-profile-refresh';

export function profileRefreshReady(refresh?: ProfileRefreshState): boolean {
  return !refresh || refresh.status === 'ready' || refresh.status === 'local-only';
}

/** Refreshing never owns the editor buffer. It only suspends derived actions. */
export default function ProfileRefreshBanner({ refresh, targetReady = true, profileAvailable = true, locale = 'en', onBeforeReview }: {
  refresh?: ProfileRefreshState; targetReady?: boolean; profileAvailable?: boolean; locale?: 'en' | 'zh';
  onBeforeReview?: () => boolean;
}) {
  if (profileAvailable && targetReady && (!refresh || refresh.status === 'ready')) return null;
  const copy = (en: string, zh: string) => locale === 'zh' ? zh : en;
  const status = refresh?.status;
  return <div role={status === 'failed' || status === 'conflict' ? 'alert' : 'status'}
    className="max-h-[25vh] shrink-0 overflow-y-auto border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-950"
    data-testid="profile-refresh-status">
    {!profileAvailable && <p>{copy('Your profile is no longer available. Your draft is kept; generation and outreach are paused.', '个人资料已不可用。草稿仍保留，生成和邮件操作已暂停。')}</p>}
    {status === 'checking' && <p>{copy('Checking for profile updates…', '正在核对最新资料…')}</p>}
    {status === 'failed' && <p>{copy('Could not check for profile updates. Your draft is kept.', '资料核对失败，草稿仍保留。')}</p>}
    {status === 'conflict' && <p>{copy('Your profile has conflicting edits. Review them before generating.', '资料存在冲突，请先确认要保留的改动。')}</p>}
    {profileAvailable && status === 'local-only' && <p>{copy('Using this device’s profile. Cloud updates are unavailable.', '正在使用本机资料，暂不能读取云端更新。')}</p>}
    {profileAvailable && !targetReady && <p>{copy('This target is not confirmed in the current results. Your draft is kept; generation and outreach are paused.', '当前结果暂未确认此目标。草稿仍保留，生成和邮件操作已暂停。')}</p>}
    {status === 'failed' && <button type="button" className="mt-1 font-semibold underline" onClick={() => { void refresh?.refresh(); }}>{copy('Retry', '重试')}</button>}
    {status === 'conflict' && <Link className="mt-1 inline-block font-semibold underline" href="/" onClick={(event) => { if (onBeforeReview && !onBeforeReview()) event.preventDefault(); }}>{copy('Review profile', '核对资料')}</Link>}
  </div>;
}
