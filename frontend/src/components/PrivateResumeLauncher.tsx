'use client';

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Link from 'next/link';
import { useT } from '@/i18n/client';
import { useLocalStorageJSON } from '@/lib/use-local-storage-json';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { useCheckedWritingProfile } from '@/lib/use-checked-writing-profile';
import { useRetainedWritingProfile } from '@/lib/use-retained-writing-profile';
import { useProfileRefresh } from '@/lib/use-profile-refresh';
import { usePrivateResumeTarget } from '@/lib/use-private-resume-target';
import type { ProfileData } from '@/lib/types';
import FullTargetResumeModal from './FullTargetResumeModal';
import PrivateResumeStatus from './PrivateResumeStatus';

/** The detail page keys this launcher by account and target. A failed refresh
 * keeps an already-open editor; it never supplies a made-up public opportunity. */
export default function PrivateResumeLauncher({ id, scope, available }: { id: string; scope: string; available: boolean }) {
  const { locale } = useT(); const copy = (en: string, zh: string) => locale === 'zh' ? zh : en;
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const loadingClose = useRef<HTMLButtonElement>(null);
  const raw = useLocalStorageJSON<ProfileData>(STORAGE_KEYS.PROFILE);
  const { profile, acceptHydration } = useCheckedWritingProfile(raw, scope);
  // Only while the editor is open: a closed launcher adds no second profile poller to the page.
  const profileRefresh = useProfileRefresh(open, acceptHydration);
  const retained = useRetainedWritingProfile(profile, open, scope);
  const target = usePrivateResumeTarget(open, id);
  const loading = open && (!retained.profile || !target.target);
  const close = () => { setOpen(false); trigger.current?.focus(); };
  useEffect(() => {
    if (!loading) return;
    loadingClose.current?.focus();
    const previous = document.body.style.overflow; document.body.style.overflow = 'hidden';
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setOpen(false); trigger.current?.focus(); }
      if (event.key === 'Tab') {
        const buttons = Array.from(loadingClose.current?.parentElement?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? []);
        const first = buttons[0], last = buttons.at(-1);
        if (first && last && (event.shiftKey && document.activeElement === first || !event.shiftKey && document.activeElement === last)) {
          event.preventDefault(); (event.shiftKey ? last : first).focus();
        }
      }
    };
    document.addEventListener('keydown', key);
    return () => { document.body.style.overflow = previous; document.removeEventListener('keydown', key); };
  }, [loading]);
  return <>
    {available && <div className="space-y-2">
      <button ref={trigger} type="button" onClick={() => setOpen(true)} disabled={!profile}
        className="min-h-11 rounded-lg border border-indigo-600 px-4 py-2 text-indigo-700 disabled:opacity-50">{copy('Prepare résumé', '准备简历')}</button>
      {!profile && <p className="text-sm"><Link href="/#resume-master" className="underline text-indigo-700">{copy('Add your profile and confirmed résumé first', '先补充个人资料和已确认的简历')}</Link></p>}
    </div>}
    {open && createPortal(retained.profile && target.target
      ? <FullTargetResumeModal isOpen onClose={close} profile={retained.profile} profileAvailable={retained.profileAvailable}
          profileRefresh={profileRefresh} privateTarget={target.target} privateResumeRefresh={target}
          targetReady={available && target.status === 'ready'} targetMembershipReady={available} targetChecking={target.status === 'checking'} />
      : <div role="dialog" aria-modal="true" aria-label={copy('Prepare résumé', '准备简历')} className="fixed inset-0 z-[55] flex items-center justify-center bg-gray-900/60 p-4">
          <div className="w-full max-w-lg rounded-xl bg-white p-4">
            <button ref={loadingClose} type="button" className="mb-3 min-h-10 underline" onClick={close}>{copy('Close', '关闭')}</button>
            <PrivateResumeStatus state={target} available={available} />
            {!retained.profile && <p>{copy('Your profile is unavailable. Close and check your profile before continuing.', '个人资料暂不可用，请关闭后核对个人资料。')}</p>}
          </div>
        </div>, document.body)}
  </>;
}
