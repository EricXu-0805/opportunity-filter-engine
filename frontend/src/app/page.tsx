'use client';

import { Suspense, useEffect } from 'react';
import FeaturedFellowships from '@/components/FeaturedFellowships';
import { trackOnce } from '@/lib/analytics';
import { useT } from '@/i18n/client';

import { AcademicProfileCard } from './home/AcademicProfileCard';
import { DocumentsCard } from './home/DocumentsCard';
import { HeroSection } from './home/HeroSection';
import { LiveDatabaseCard } from './home/LiveDatabaseCard';
import { OnlineProfilesCard } from './home/OnlineProfilesCard';
import { ProfileStrength } from './home/ProfileStrength';
import { SaveCta } from './home/SaveCta';
import { SearchFocusCard } from './home/SearchFocusCard';
import { SharedBanner } from './home/SharedBanner';
import { SubmitRow } from './home/SubmitRow';
import { WalkthroughSection } from './home/WalkthroughSection';
import { useProfileForm } from './home/use-profile-form';

export default function HomePage() {
  return (
    <Suspense fallback={null}>
      <HomePageInner />
    </Suspense>
  );
}

function HomePageInner() {
  const { t } = useT();
  const {
    profile,
    searchWeight,
    setSearchWeight,
    oppCount,
    lastUpdated,
    ghLoading,
    ghStatus,
    sharedBanner,
    dismissSharedBanner,
    shareCopied,
    saveStatus,
    isValid,
    update,
    handleSubmit,
    handleShare,
    handleResumeParsed,
    handleGitHubImport,
  } = useProfileForm(t);

  useEffect(() => {
    trackOnce('landing_view');
  }, []);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
      <SharedBanner message={sharedBanner} onDismiss={dismissSharedBanner} t={t} />

      <HeroSection t={t} />

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        <div className="lg:col-span-7">
          <AcademicProfileCard profile={profile} update={update} t={t} />
        </div>

        <div className="lg:col-span-5 space-y-8">
          <DocumentsCard profile={profile} onResumeParsed={handleResumeParsed} t={t} />
          <OnlineProfilesCard
            profile={profile}
            update={update}
            ghLoading={ghLoading}
            ghStatus={ghStatus}
            onGitHubImport={handleGitHubImport}
            t={t}
          />
          <SearchFocusCard
            searchWeight={searchWeight}
            setSearchWeight={setSearchWeight}
            exploring={profile.exploring ?? false}
            setExploring={(v) => update('exploring', v)}
            t={t}
          />
          <LiveDatabaseCard oppCount={oppCount} lastUpdated={lastUpdated} t={t} />
        </div>
      </div>

      {isValid && (
        <ProfileStrength profile={profile} hasResume={!!profile.resume_text} t={t} />
      )}

      <SubmitRow
        isValid={isValid}
        shareCopied={shareCopied}
        saveStatus={saveStatus}
        onSubmit={handleSubmit}
        onShare={handleShare}
        t={t}
      />

      <SaveCta t={t} />

      <WalkthroughSection t={t} />

      <FeaturedFellowships />
    </div>
  );
}
