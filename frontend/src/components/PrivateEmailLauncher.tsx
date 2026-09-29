'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useT } from '@/i18n/client';
import { useLocalStorageJSON } from '@/lib/use-local-storage-json';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { useCheckedWritingProfile } from '@/lib/use-checked-writing-profile';
import { useRetainedWritingProfile } from '@/lib/use-retained-writing-profile';
import { useProfileRefresh } from '@/lib/use-profile-refresh';
import { usePrivateEmailTarget } from '@/lib/use-private-email-target';
import type { ProfileData } from '@/lib/types';
import ColdEmailModal from './ColdEmailModal';

/** Mounted within the detail's account scope. Temporary reads keep an open
 * editor, while membership and owner changes withdraw action authority. */
export default function PrivateEmailLauncher({ id, scope, title, available, onContactConfirmed }: {
  id: string; scope: string; title: string; available: boolean; onContactConfirmed: () => void;
}) {
  const { locale } = useT();
  const [open, setOpen] = useState(false);
  const raw = useLocalStorageJSON<ProfileData>(STORAGE_KEYS.PROFILE);
  const { profile, acceptHydration } = useCheckedWritingProfile(raw, scope);
  const profileRefresh = useProfileRefresh(true, acceptHydration);
  const retained = useRetainedWritingProfile(profile, open, scope);
  const privateTargetRefresh = usePrivateEmailTarget(open, id);
  return <>
    {available && <div className="space-y-2">
      <button type="button" onClick={() => setOpen(true)} disabled={!profile}
        className="min-h-11 rounded-lg bg-indigo-600 px-4 py-2 text-white disabled:opacity-50">{locale === 'zh' ? '准备邮件' : 'Prepare email'}</button>
      {!profile && <p className="text-sm"><Link href="/" className="underline text-indigo-700">{locale === 'zh' ? '先补充个人资料和姓名' : 'Add your profile and name first'}</Link></p>}
    </div>}
    {open && retained.profile && <ColdEmailModal isOpen={open} onClose={() => setOpen(false)} profile={retained.profile}
      profileAvailable={retained.profileAvailable} profileRefresh={profileRefresh} privateTargetRefresh={privateTargetRefresh}
      targetReady={available && privateTargetRefresh.status === 'ready'} targetMembershipReady={available}
      targetChecking={privateTargetRefresh.status === 'checking'} opportunityId={id} opportunityTitle={privateTargetRefresh.target?.title ?? title}
      onContactConfirmed={onContactConfirmed} />}
  </>;
}
