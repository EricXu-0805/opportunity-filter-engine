'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { useLocalStorageJSON } from '@/lib/use-local-storage-json';
import type { Opportunity, ProfileData } from '@/lib/types';
import type { SimilarOpportunity } from '@/lib/api-server';
import { useT } from '@/i18n/client';

import { ChatDrawer } from './ChatDrawer';
import {
  ApplicationSection,
  AtAGlanceSection,
  DescriptionSection,
  EligibilitySection,
  KeywordsSection,
} from './DetailSections';
import { InteractionPills } from './InteractionPills';
import { OpportunityHeader } from './OpportunityHeader';
import { SimilarOpportunities } from './SimilarOpportunities';
import { TrackerPanel } from './TrackerPanel';
import { useOpportunityDetail } from './use-opportunity-detail';

const ColdEmailModal = dynamic(() => import('@/components/ColdEmailModal'), { ssr: false });
// R71 PR-3: second entry point for the tailor modal (first was MatchCard).
// Keeping the same dynamic-ssr-off pattern so this leaf doesn't pull the
// modal bundle into the server render.
const TailorModal = dynamic(() => import('@/components/TailorModal'), { ssr: false });
const OpportunityChatbot = dynamic(() => import('@/components/OpportunityChatbot'), { ssr: false });

export default function OpportunityDetail({
  opp,
  similar = [],
}: {
  opp: Opportunity;
  similar?: SimilarOpportunity[];
}) {
  const { t } = useT();
  const profile = useLocalStorageJSON<ProfileData>('ofe_profile');
  // R71 PR-3: tailor modal is local to this page — it has no callers
  // outside OpportunityDetail, so we keep state here rather than bloat
  // useOpportunityDetail. Matches PR-2's MatchCard-local pattern.
  const [tailorOpen, setTailorOpen] = useState(false);
  const {
    isFavorited,
    interactionDetail,
    interaction,
    emailModalOpen,
    setEmailModalOpen,
    shareCopied,
    chatDrawerOpen,
    setChatDrawerOpen,
    suggestion,
    handleStar,
    handleTrack,
    saveDetails,
    handleUseSuggestion,
    handleDismissSuggestion,
    handleShare,
  } = useOpportunityDetail(opp);

  const description = opp.description_raw || opp.description_clean || '';

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
      <Link
        href="/results"
        className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 mb-6 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
      >
        <ArrowLeft className="w-4 h-4" aria-hidden="true" />
        {t('detail.backToMatches')}
      </Link>

      <div className="flex flex-col lg:flex-row lg:gap-6 lg:items-start">
        <main className="flex-1 min-w-0 lg:max-w-3xl">
          <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] overflow-hidden mb-6">
            <OpportunityHeader
              opp={opp}
              profile={profile}
              isFavorited={isFavorited}
              shareCopied={shareCopied}
              onStar={handleStar}
              onOpenEmailModal={() => setEmailModalOpen(true)}
              onOpenTailorModal={() => setTailorOpen(true)}
              onShare={handleShare}
              t={t}
            />
            <InteractionPills
              interaction={interaction}
              suggestion={suggestion}
              onTrack={handleTrack}
              onUseSuggestion={handleUseSuggestion}
              onDismissSuggestion={handleDismissSuggestion}
              t={t}
            />
            <TrackerPanel
              detail={interactionDetail}
              onSave={saveDetails}
              opportunityId={opp.id as string}
              hasInteraction={!!interaction}
              t={t}
            />
          </div>

          <DescriptionSection description={description} t={t} />
          <AtAGlanceSection opp={opp} t={t} />
          <EligibilitySection opp={opp} t={t} />
          <ApplicationSection opp={opp} t={t} />
          <KeywordsSection opp={opp} t={t} />
          <SimilarOpportunities similar={similar} t={t} />

          <div className="mt-8 pt-6 border-t border-gray-100 text-[11px] text-gray-400 space-y-1">
            {opp.source && <p>{t('detail.source', { source: opp.source })}</p>}
            {(opp.metadata as { last_verified?: string } | undefined)?.last_verified && (
              <p>{t('detail.lastVerified', { date: (opp.metadata as { last_verified?: string }).last_verified ?? '' })}</p>
            )}
          </div>
        </main>

        <aside className="hidden lg:block lg:w-[360px] xl:w-[400px] lg:sticky lg:top-6 lg:self-start lg:shrink-0">
          <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] border border-gray-100 overflow-hidden h-[calc(100vh-6rem)] max-h-[760px]">
            <OpportunityChatbot opportunity={opp} profile={profile} />
          </div>
        </aside>
      </div>

      <ChatDrawer
        opp={opp}
        profile={profile}
        open={chatDrawerOpen}
        onOpen={() => setChatDrawerOpen(true)}
        onClose={() => setChatDrawerOpen(false)}
        t={t}
      />

      {profile && (
        <ColdEmailModal
          isOpen={emailModalOpen}
          onClose={() => setEmailModalOpen(false)}
          profile={profile}
          opportunityId={opp.id}
          opportunityTitle={opp.title}
        />
      )}

      {profile && (
        <TailorModal
          isOpen={tailorOpen}
          onClose={() => setTailorOpen(false)}
          profile={profile}
          opportunityId={opp.id}
          opportunityTitle={opp.title}
        />
      )}
    </div>
  );
}
