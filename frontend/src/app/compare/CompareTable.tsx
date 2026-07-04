'use client';

import { useMemo } from 'react';
import Link from 'next/link';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import type { Opportunity, ProfileData } from '@/lib/types';
import { useHasLocalStorageKey, useLocalStorageJSON } from '@/lib/use-local-storage-json';
import { useT } from '@/i18n/client';
import { rankAndBucket } from './scores';
import BucketCards from './BucketCards';
import DifferencesSection from './DifferencesSection';
import RadarChart from './RadarChart';

export default function CompareTable({ opps }: { opps: Opportunity[] }) {
  const { t } = useT();
  // Tri-state: useLocalStorageJSON alone returns null both while hydrating
  // and when no profile exists, which used to leave visitors without a
  // profile stuck on a permanent loading card.
  const hasProfile = useHasLocalStorageKey(STORAGE_KEYS.PROFILE);
  const profile = useLocalStorageJSON<ProfileData>(STORAGE_KEYS.PROFILE);

  const ranked = useMemo(() => {
    if (!profile) return null;
    return rankAndBucket(opps, profile);
  }, [opps, profile]);

  if (hasProfile === undefined) {
    return (
      <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8 text-center">
        <p className="text-sm text-gray-500">{t('compare.loadingProfile')}</p>
      </div>
    );
  }

  if (!ranked) {
    return (
      <div>
        <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8 text-center mb-8">
          <p className="text-sm text-gray-500 mb-4">{t('compare.noProfile')}</p>
          <Link
            href="/"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 text-white text-[13px] font-medium hover:bg-indigo-700 transition-colors"
          >
            {t('compare.createProfile')}
          </Link>
        </div>
        <DifferencesSection rows={opps.map((opp) => ({ opp }))} profile={null} />
      </div>
    );
  }

  return (
    <div>
      <BucketCards rows={ranked} profile={profile} />
      <DifferencesSection rows={ranked} profile={profile} />
      <RadarChart rows={ranked} />
    </div>
  );
}
