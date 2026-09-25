import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { WritingTargetState } from '@/lib/use-writing-target';
import ProfileRefreshBanner from './ProfileRefreshBanner';
afterEach(cleanup);
const target = (status: WritingTargetState['status']): WritingTargetState => ({ status, target: null, reason: 'internal-code-not-copy', refresh: vi.fn().mockResolvedValue(true), checkForAction: vi.fn() });
describe('writing target refresh explanations', () => {
  it.each(['checking', 'failed', 'missing', 'blocked'] as const)('explains %s without falsely claiming Results membership was lost', status => {
    const state = target(status); render(<ProfileRefreshBanner targetRefresh={state} />);
    expect(screen.getByTestId('writing-target-status')).toBeVisible();
    expect(screen.queryByText(/not confirmed in the current results/)).toBeNull();
    expect(screen.queryByText(/internal-code/)).toBeNull();
    if (status === 'checking') expect(screen.queryByRole('button')).toBeNull();
    else { fireEvent.click(screen.getByRole('button', { name: 'Check opportunity again' })); expect(state.refresh).toHaveBeenCalledOnce(); }
  });
  it.each([
    ['listing_closed', 'Applications for this opportunity are closed.', '此机会已停止接受申请。'],
    ['faculty_not_accepting', 'The professor is not accepting undergraduate inquiries.', '这位教授目前不接受本科生咨询。'],
    ['reference_only', 'This opportunity is available for reference only.', '此机会目前仅供参考。'],
    ['inactive', 'This opportunity is no longer active.', '此机会已不再活跃。'],
    ['timeout', 'The opportunity check timed out.', '机会信息核对超时。'],
    ['invalid_target', 'The opportunity information could not be verified.', '返回的机会信息无法确认。'],
  ])('explains %s in both languages without showing internal codes', (reason, en, zh) => {
    const state = { ...target(reason === 'timeout' || reason === 'invalid_target' ? 'failed' : 'blocked'), reason };
    const view = render(<ProfileRefreshBanner targetRefresh={state} />);
    expect(screen.getByTestId('writing-target-status')).toHaveTextContent(en);
    expect(screen.getByTestId('writing-target-status')).toHaveTextContent('Your draft is kept');
    view.rerender(<ProfileRefreshBanner targetRefresh={state} locale="zh" />);
    expect(screen.getByTestId('writing-target-status')).toHaveTextContent(zh);
  });
  it('retains Results membership warning even with a successful full detail read', () => {
    render(<ProfileRefreshBanner targetRefresh={target('ready')} targetReady={false} />);
    expect(screen.getByTestId('profile-refresh-status')).toHaveTextContent('not confirmed in the current results');
    expect(screen.queryByTestId('writing-target-status')).toBeNull();
  });
  it('keeps profile and target retries separate', () => {
    const state = target('failed'), refresh = vi.fn();
    render(<ProfileRefreshBanner targetRefresh={state} refresh={{ status: 'failed', refresh }} />);
    fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }));
    expect(refresh).toHaveBeenCalledOnce(); expect(state.refresh).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Check opportunity again' })); expect(state.refresh).toHaveBeenCalledOnce();
  });
  it('renders concise Chinese target failure and no banner after both checks are ready', () => {
    const view = render(<ProfileRefreshBanner targetRefresh={target('failed')} locale="zh" />);
    expect(screen.getByText('暂时无法核对这个机会。草稿仍保留，生成和邮件操作已暂停。')).toBeVisible();
    view.rerender(<ProfileRefreshBanner targetRefresh={target('ready')} />);
    expect(screen.queryByTestId('profile-refresh-status')).toBeNull();
  });
});
