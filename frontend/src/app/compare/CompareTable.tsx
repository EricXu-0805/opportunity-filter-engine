'use client';

import { useEffect, useMemo, useState } from 'react';
import type { Opportunity, ProfileData } from '@/lib/types';
import { rankAndBucket } from './scores';
import BucketCards from './BucketCards';
import DifferencesSection from './DifferencesSection';
import RadarChart from './RadarChart';

export default function CompareTable({ opps }: { opps: Opportunity[] }) {
  const [profile, setProfile] = useState<ProfileData | null>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem('ofe_profile');
      if (raw) setProfile(JSON.parse(raw) as ProfileData);
    } catch {}
  }, []);

  const ranked = useMemo(() => {
    if (!profile) return null;
    return rankAndBucket(opps, profile);
  }, [opps, profile]);

  if (!ranked) {
    return (
      <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8 text-center">
        <p className="text-sm text-gray-500">Loading your profile…</p>
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
