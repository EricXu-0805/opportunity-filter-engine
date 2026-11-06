import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import golden from '../../../tests/fixtures/private-resume-context-v5-golden.json';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { DEFAULT_PROFILE } from '@/app/home/types';
import type { ProfileData } from '@/lib/types';
import PrivateResumeLauncher from './PrivateResumeLauncher';
const mocks = vi.hoisted(() => ({ read: vi.fn(), refresh: vi.fn(), profile: null as ProfileData | null, props: null as Record<string, unknown> | null, locale: 'en' as 'en' | 'zh' }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ locale: mocks.locale }), useLocale: () => mocks.locale }));
vi.mock('@/lib/private-resume', () => ({ getPrivateResumeContext: mocks.read }));
vi.mock('@/lib/use-local-storage-json', () => ({ useLocalStorageJSON: () => mocks.profile }));
vi.mock('@/lib/use-profile-refresh', () => ({ PROFILE_REFRESH_DEADLINE_MS: 15000, useProfileRefresh: mocks.refresh }));
vi.mock('./FullTargetResumeModal', () => ({ default: (props: Record<string, unknown>) => {
  mocks.props = props;
  return <div role="dialog" aria-label="Private editor"><button onClick={props.onClose as () => void}>Close private editor</button></div>;
} }));
const id=golden.receipt.context.opportunity_id;
beforeEach(async () => {
  localStorage.clear(); advanceOwnerEpoch(golden.receipt.context.private_source.owner_id); await syncLocalIdentityOwner(golden.receipt.context.private_source.owner_id);
  mocks.profile={...DEFAULT_PROFILE,...golden.draft.base_snapshot} as ProfileData; mocks.props=null; mocks.locale='en';
  mocks.read.mockReset().mockResolvedValue(structuredClone(golden.receipt.context));
  mocks.refresh.mockReset().mockReturnValue({ status: 'local-only' });
});
afterEach(() => vi.restoreAllMocks());

it('renders the loading dialog in the body and cancels its read on Escape, restoring focus', async () => {
  mocks.read.mockReturnValue(new Promise(() => {}));
  const { container }=render(<PrivateResumeLauncher id={id} scope={id} available />);
  const open=screen.getByRole('button',{name:'Prepare résumé'}); fireEvent.click(open);
  await waitFor(()=>expect(mocks.read).toHaveBeenCalledOnce());
  const dialog=screen.getByRole('dialog'); expect(container.contains(dialog)).toBe(false); expect(dialog.parentElement).toBe(document.body);
  expect(screen.getByRole('button',{name:'Close'})).toHaveFocus();
  const signal=mocks.read.mock.calls[0][1].signal;
  fireEvent.keyDown(document,{key:'Escape'});
  expect(screen.queryByRole('dialog')).toBeNull(); expect(signal.aborted).toBe(true); expect(open).toHaveFocus();
});

it('retries a source read into the full editor without constructing a public opportunity', async () => {
  mocks.read.mockRejectedValueOnce({code:'unavailable'});
  render(<PrivateResumeLauncher id={id} scope={id} available />); fireEvent.click(screen.getByRole('button',{name:'Prepare résumé'}));
  await screen.findByText(/Could not check this private source/);
  fireEvent.click(screen.getByRole('button',{name:'Check private source again'})); await screen.findByRole('dialog',{name:'Private editor'});
  expect(mocks.props?.privateTarget).toEqual(golden.receipt.context); expect(mocks.props).not.toHaveProperty('opportunity');
  fireEvent.click(screen.getByRole('button',{name:'Close private editor'})); expect(screen.queryByRole('dialog')).toBeNull();
  expect(screen.getByRole('button',{name:'Prepare résumé'})).toHaveFocus();
});

it('keeps an open editor when page membership or live profile disappears', async () => {
  const view=render(<PrivateResumeLauncher id={id} scope={id} available />);fireEvent.click(screen.getByRole('button',{name:'Prepare résumé'}));
  await screen.findByRole('dialog',{name:'Private editor'}); const profile=mocks.props?.profile;
  mocks.profile=null; view.rerender(<PrivateResumeLauncher id={id} scope={id} available={false} />);
  expect(screen.getByRole('dialog',{name:'Private editor'})).toBeInTheDocument();
  expect(mocks.props).toMatchObject({profileAvailable:false,targetMembershipReady:false,targetReady:false,profile});
});

it('does not show the previous account editor after an owner change', async () => {
  render(<PrivateResumeLauncher id={id} scope={id} available />);fireEvent.click(screen.getByRole('button',{name:'Prepare résumé'}));
  await screen.findByRole('dialog',{name:'Private editor'});
  await act(async()=>{advanceOwnerEpoch('b1000000-0000-4000-8000-000000000001');await syncLocalIdentityOwner('b1000000-0000-4000-8000-000000000001');});
  expect(screen.queryByRole('dialog',{name:'Private editor'})).toBeNull();
});

it('checks the profile only while the editor is open', async () => {
  render(<PrivateResumeLauncher id={id} scope={id} available />);
  expect(mocks.refresh.mock.calls.length).toBeGreaterThan(0); expect(mocks.refresh.mock.calls.every(([enabled]) => enabled === false)).toBe(true);
  fireEvent.click(screen.getByRole('button',{name:'Prepare résumé'})); await screen.findByRole('dialog',{name:'Private editor'});
  expect(mocks.refresh).toHaveBeenLastCalledWith(true, expect.any(Function));
  fireEvent.click(screen.getByRole('button',{name:'Close private editor'}));
  expect(mocks.refresh).toHaveBeenLastCalledWith(false, expect.any(Function));
});

it('says a source over the draft limit is too large instead of offering the editor', async () => {
  mocks.read.mockRejectedValue({code:'too_large'});
  render(<PrivateResumeLauncher id={id} scope={id} available />); fireEvent.click(screen.getByRole('button',{name:'Prepare résumé'}));
  expect(await screen.findByText(/complete source exceeds the résumé draft limit/)).toBeInTheDocument();
  expect(screen.queryByRole('dialog',{name:'Private editor'})).toBeNull();
});

it.each([
  ['a failed read', 'en', () => mocks.read.mockRejectedValue({code:'unavailable'}), 'Could not check this private source. Try again.'],
  ['a failed read', 'zh', () => mocks.read.mockRejectedValue({code:'unavailable'}), '暂时无法核对私有来源，可重试。'],
  ['a missing import', 'en', () => mocks.read.mockRejectedValue({code:'not_found'}), 'This private import is no longer available.'],
  ['a missing import', 'zh', () => mocks.read.mockRejectedValue({code:'not_found'}), '这条私有导入已不可用。'],
  ['offline', 'en', () => { vi.spyOn(navigator,'onLine','get').mockReturnValue(false); }, 'You are offline. Reconnect to check the source.'],
  ['offline', 'zh', () => { vi.spyOn(navigator,'onLine','get').mockReturnValue(false); }, '当前离线，联网后重新核对来源。'],
] as const)('promises no kept draft before any draft is read or created (%s, %s)', async (_case, locale, arrange, message) => {
  mocks.locale=locale; arrange();
  render(<PrivateResumeLauncher id={id} scope={id} available />); fireEvent.click(screen.getByRole('button',{name:locale==='zh'?'准备简历':'Prepare résumé'}));
  expect(await screen.findByText(message)).toBeInTheDocument();
  expect(screen.queryByText(/draft is kept|文稿仍保留/)).toBeNull();
});
