'use client';

import Link from 'next/link';
import type { MouseEvent } from 'react';
import type { ProfileRefreshState } from '@/lib/use-profile-refresh';
import type { WritingTargetState } from '@/lib/use-writing-target';

export function profileRefreshReady(refresh?: ProfileRefreshState): boolean {
  return !refresh || refresh.status === 'ready' || refresh.status === 'local-only';
}

/** Refreshing never owns the editor buffer. It only suspends derived actions. */
export default function ProfileRefreshBanner({ refresh, targetRefresh, targetReady = true, profileAvailable = true, locale = 'en', onBeforeReview }: {
  refresh?: ProfileRefreshState; targetRefresh?: WritingTargetState; targetReady?: boolean; profileAvailable?: boolean; locale?: 'en' | 'zh';
  onBeforeReview?: (event: MouseEvent<HTMLAnchorElement>) => boolean;
}) {
  const offline = refresh?.status === 'offline' || targetRefresh?.status === 'offline';
  if (!offline && profileAvailable && targetReady && (!refresh || refresh.status === 'ready') && (!targetRefresh || targetRefresh.status === 'ready')) return null;
  const copy = (en: string, zh: string) => locale === 'zh' ? zh : en;
  const status = refresh?.status;
  const targetStatus = targetRefresh?.status;
  const targetReason = targetRefresh?.reason;
  if (offline) return <div role="status"
    className="max-h-[25vh] shrink-0 overflow-y-auto border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-950"
    data-testid="profile-refresh-status">
    <p>{copy("You're offline. Your draft is kept; generation and email actions are paused. We'll check the sources again when you're online.", '当前离线。草稿仍保留，生成和邮件操作已暂停；联网后会自动重新核对资料。')}</p>
  </div>;
  const targetExplanation = targetReason === 'listing_closed'
    ? copy('Applications for this opportunity are closed.', '此机会已停止接受申请。')
    : targetReason === 'faculty_not_accepting'
      ? copy('The professor is not accepting undergraduate inquiries.', '这位教授目前不接受本科生咨询。')
      : targetReason === 'reference_only'
        ? copy('This opportunity is available for reference only.', '此机会目前仅供参考。')
        : targetReason === 'inactive'
          ? copy('This opportunity is no longer active.', '此机会已不再活跃。')
          : targetReason === 'timeout'
            ? copy('The opportunity check timed out.', '机会信息核对超时。')
            : targetReason === 'invalid_target'
              ? copy('The opportunity information could not be verified.', '返回的机会信息无法确认。')
              : targetReason === 'record_kind_unverified' || targetReason === 'status_unverified'
                ? copy('This opportunity’s current availability is unconfirmed.', '此机会目前是否可申请或联系尚未确认。')
                : null;
  return <div role={status === 'failed' || status === 'conflict' || targetStatus === 'failed' ? 'alert' : 'status'}
    className="max-h-[25vh] shrink-0 overflow-y-auto border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-950"
    data-testid="profile-refresh-status">
    {!profileAvailable && <p>{copy('Your profile is no longer available. Your draft is kept; generation and outreach are paused.', '个人资料已不可用。草稿仍保留，生成和邮件操作已暂停。')}</p>}
    {status === 'checking' && <p>{copy('Checking for profile updates…', '正在核对最新资料…')}</p>}
    {status === 'failed' && <p>{copy('Could not check for profile updates. Your draft is kept.', '资料核对失败，草稿仍保留。')}</p>}
    {status === 'conflict' && <p>{copy('Your profile has conflicting edits. Review them before generating.', '资料存在冲突，请先确认要保留的改动。')}</p>}
    {profileAvailable && status === 'local-only' && <p>{copy('Using this device’s profile. Cloud updates are unavailable.', '正在使用本机资料，暂不能读取云端更新。')}</p>}
    {profileAvailable && !targetReady && (!targetRefresh || targetStatus === 'ready') && <p>{copy('This target is not confirmed in the current results. Your draft is kept; generation and outreach are paused.', '当前结果暂未确认此目标。草稿仍保留，生成和邮件操作已暂停。')}</p>}
    {targetStatus && targetStatus !== 'ready' && <div data-testid="writing-target-status">
      {targetStatus === 'checking' && <p>{copy('Checking current opportunity information…', '正在核对最新机会信息…')}</p>}
      {targetStatus === 'failed' && <p>{targetExplanation ? <>{targetExplanation} {copy('Your draft is kept; generation and outreach are paused.', '草稿仍保留，生成和邮件操作已暂停。')}</> : copy('Could not verify this opportunity. Your draft is kept; generation and outreach are paused.', '暂时无法核对这个机会。草稿仍保留，生成和邮件操作已暂停。')}</p>}
      {targetStatus === 'missing' && <p>{copy('This opportunity could not be found. Your draft is kept; generation and outreach are paused.', '暂未找到这个机会。草稿仍保留，生成和邮件操作已暂停。')}</p>}
      {targetStatus === 'blocked' && <p>{targetExplanation ? <>{targetExplanation} {copy('Your draft is kept; generation and outreach are paused.', '草稿仍保留，生成和邮件操作已暂停。')}</> : copy('This opportunity is not currently available for applications or outreach. Your draft is kept.', '此机会目前不支持申请或联系。草稿仍保留。')}</p>}
      {targetStatus !== 'checking' && <button type="button" className="mt-1 font-semibold underline" onClick={() => { void targetRefresh?.refresh(); }}>{copy('Check opportunity again', '重新核对机会')}</button>}
    </div>}
    {status === 'failed' && <button type="button" className="mt-1 font-semibold underline" onClick={() => { void refresh?.refresh(); }}>{copy('Retry', '重试')}</button>}
    {status === 'conflict' && <Link className="mt-1 inline-block font-semibold underline" href="/" onClick={(event) => { if (onBeforeReview && !onBeforeReview(event)) event.preventDefault(); }}>{copy('Review profile', '核对资料')}</Link>}
  </div>;
}
