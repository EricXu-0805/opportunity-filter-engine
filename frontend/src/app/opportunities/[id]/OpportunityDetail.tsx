'use client';

import dynamic from 'next/dynamic';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import StorageStatusBanner from '@/components/StorageStatusBanner';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { useLocalStorageJSON } from '@/lib/use-local-storage-json';
import type { Opportunity, ProfileData } from '@/lib/types';
import type { SimilarOpportunity } from '@/lib/api-server';
import { useT } from '@/i18n/client';
import { RELEASE_SCOPE } from '@/lib/release-scope';
import { opportunityRecordKind } from '@/lib/match-utils';
import { canDeliverReminder } from '@/lib/reminders';
import { targetPosture } from '@/lib/target-truth';

import { ChatDrawer } from './ChatDrawer';
import { ContactRevealSection } from './ContactRevealSection';
import { ConciergeRequestSection } from './ConciergeRequestSection';
import {
  ApplicationSection,
  AtAGlanceSection,
  DescriptionSection,
  EligibilitySection,
  KeywordsSection,
  RecentWorksSection,
} from './DetailSections';
import { InteractionPills } from './InteractionPills';
import { OpportunityHeader } from './OpportunityHeader';
import { ProfessorFollowToggle } from './ProfessorFollowToggle';
import { SimilarOpportunities } from './SimilarOpportunities';
import { TrackerPanel } from './TrackerPanel';
import { useOpportunityDetail } from './use-opportunity-detail';

const ColdEmailModal = dynamic(() => import('@/components/ColdEmailModal'), { ssr: false });
// R71 PR-3: second entry point for the tailor modal (first was MatchCard).
// Keeping the same dynamic-ssr-off pattern so this leaf doesn't pull the
// modal bundle into the server render.
const TailorModal = dynamic(() => import('@/components/TailorModal'), { ssr: false });
const ResumeRenovationModal = dynamic(() => import('@/components/ResumeRenovationModal'), { ssr: false });
const OpportunityChatbot = dynamic(() => import('@/components/OpportunityChatbot'), { ssr: false });

export default function OpportunityDetail({
  opp,
  similar = [],
}: {
  opp: Opportunity;
  similar?: SimilarOpportunity[];
}) {
  const { t } = useT();
  const profile = useLocalStorageJSON<ProfileData>(STORAGE_KEYS.PROFILE);
  const {
    identityGeneration,
    ownerScopeKey,
    isFavorited,
    favoriteLoading,
    favoriteError,
    retryFavoriteHydration,
    favoriteSaving,
    favoriteSaveError,
    ownerReady,
    interactionDetail,
    noteContactConfirmed,
    interaction,
    interactionLoading,
    interactionError,
    retryInteractionHydration,
    statusSaving,
    statusError,
    retryTrack,
    emailModalOpen,
    setEmailModalOpen,
    shareCopied,
    chatDrawerOpen,
    setChatDrawerOpen,
    tailorOpen,
    setTailorOpen,
    renovationOpen,
    setRenovationOpen,
    suggestion,
    suggestionSaving,
    suggestionError,
    handleStar,
    handleTrack,
    saveDetails,
    handleUseSuggestion,
    handleDismissSuggestion,
    handleShare,
  } = useOpportunityDetail(opp);

  // One read, used by every action surface on this page. Historical and
  // unverified both resolve to false: the page stays readable either way,
  // but nothing on it may act on the target.
  const actionable = targetPosture(opp) === 'actionable';
  // Which body sections may exist at all. Each of the four gated below is a
  // block of offer terms — what it pays, when it closes, who may apply, what
  // to submit — and the sections themselves only knew `source_type`, so a
  // closed listing rendered its full application section under a banner
  // saying the application was closed.
  const recordKind = opportunityRecordKind(opp);
  const isCurrentListing = recordKind === 'listing' && actionable;
  // A profile, not a posting. It gets the profile-shaped variants the
  // sections already implement — a projected description, the faculty
  // at-a-glance, the outreach block — and none of the listing ones.
  const isActionableFaculty = recordKind === 'faculty_contact' && actionable;
  const showsProfileOrOffer = isCurrentListing || isActionableFaculty;

  const description = opp.description_raw || opp.description_clean || '';

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
      <Link
        href="/results"
        className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 mb-6 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded"
      >
        <ArrowLeft className="w-4 h-4" aria-hidden="true" />
        {t('detail.backToMatches')}
      </Link>

      <StorageStatusBanner />

      <div className="flex flex-col lg:flex-row lg:gap-6 lg:items-start">
        <main className="flex-1 min-w-0 lg:max-w-3xl">
          <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] overflow-hidden mb-6">
            <OpportunityHeader
              opp={opp}
              profile={profile}
              isFavorited={isFavorited}
              favoriteDisabled={!ownerReady || favoriteLoading || favoriteSaving || favoriteError}
              favoriteBusy={favoriteLoading || favoriteSaving}
              shareCopied={shareCopied}
              onStar={handleStar}
              // Undefined, not disabled: the header renders these controls
              // only when it has an opener, so withholding it removes them
              // from the accessibility tree and the tab order entirely. A
              // disabled button is still announced, still focusable, and still
              // says the action exists.
              onOpenEmailModal={actionable ? () => setEmailModalOpen(true) : undefined}
              onOpenTailorModal={actionable ? () => setTailorOpen(true) : undefined}
              tailorDisabled={!ownerReady}
              onOpenRenovationModal={RELEASE_SCOPE.resumeRenovate && actionable
                ? () => setRenovationOpen(true)
                : undefined}
              onShare={handleShare}
              t={t}
            />
            {(favoriteError || favoriteSaveError) && (
              <div className="px-5 sm:px-8 pb-3 -mt-2" role="alert">
                <p className="flex items-center gap-2 text-xs text-red-700">
                  {favoriteError ? t('detail.favorite.loadError') : t('detail.favorite.saveError')}
                  <button
                    type="button"
                    onClick={favoriteError ? retryFavoriteHydration : () => { void handleStar(); }}
                    className="font-semibold text-indigo-600 hover:text-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded"
                  >
                    {t('common.retry')}
                  </button>
                </p>
              </div>
            )}
            {interactionError && (
              <div className="px-5 sm:px-8 pb-3 -mt-2" role="alert">
                <p className="flex items-center gap-2 text-xs text-red-700">
                  {t('detail.tracker.loadError')}
                  <button
                    type="button"
                    onClick={retryInteractionHydration}
                    className="font-semibold text-indigo-600 hover:text-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded"
                  >
                    {t('common.retry')}
                  </button>
                </p>
              </div>
            )}
            <InteractionPills
              interaction={interaction}
              suggestion={suggestion}
              statusSaving={statusSaving}
              statusError={statusError}
              interactionUnready={!ownerReady || interactionLoading || interactionError}
              onTrack={handleTrack}
              onRetryTrack={retryTrack}
              onUseSuggestion={handleUseSuggestion}
              onDismissSuggestion={handleDismissSuggestion}
              suggestionSaving={suggestionSaving}
              suggestionError={suggestionError}
              t={t}
            />
            <TrackerPanel
              // Relying on interactionDetail merely passing through null
              // between identities is not a robust guarantee that React
              // unmounts this panel across a U1->U2 switch (same
              // opportunity, same mounted OpportunityDetail instance) — the
              // generation-qualified key forces a fresh instance (and
              // therefore a fresh, empty local notes/reminder draft)
              // explicitly, by construction (same fix as tracker/page.tsx).
              key={`${identityGeneration}:${opp.id}`}
              detail={interactionDetail}
              onSave={saveDetails}
              opportunityId={opp.id as string}
              hasInteraction={!!interaction}
              // A still-loading/failed/not-yet-owned read, or a status
              // write in flight, means notes/reminder edits must not be
              // typeable at all — otherwise a slow read landing later (or
              // a status change resolving) could auto-save a draft the
              // user typed against untrustworthy state, or silently drop
              // it into a permanently-unretried limbo.
              writeReady={ownerReady && !interactionLoading && !interactionError && !!interaction && !statusSaving}
              // Separate from writeReady on purpose — see the prop's comment.
              // Notes and status stay editable for a closed listing; only
              // scheduling a reminder the cron would skip is withheld.
              reminderEligible={canDeliverReminder(opp, interaction)}
              t={t}
            />
            {RELEASE_SCOPE.professorSignals && (
              <ProfessorFollowToggle
                professorId={opp.professor_id}
                professorName={opp.pi_name}
                school={opp.school}
              />
            )}
          </div>

          {showsProfileOrOffer && <DescriptionSection description={description} t={t} />}
          {/* Publications are the record's history and stay whatever its
              posture is — the section already refuses anything without
              verified attribution. */}
          <RecentWorksSection opp={opp} t={t} />
          {showsProfileOrOffer && <AtAGlanceSection opp={opp} t={t} />}
          {/* The faculty variant of this section is deliberately narrow — it
              hides year, major and required skills, and shows only the
              fail-closed international answer plus an explicit citizenship
              restriction. Those are evidenced negatives and verify-this
              prompts, not terms of an offer, so a live profile keeps them. */}
          {showsProfileOrOffer && <EligibilitySection opp={opp} t={t} />}
          {showsProfileOrOffer && <ApplicationSection opp={opp} t={t} />}
          {/* Revealing a contact is a direct action, not a display detail: it
              re-fetches the record to obtain the address, can raise the sign-in
              modal, and ends in a mailto. None of that belongs on a target the
              server would refuse to draft an email about. */}
          {actionable && <ContactRevealSection opp={opp} t={t} />}
          {/* Placed after the address, where the size of the job becomes
              concrete. Bound to this record, because the work being asked for
              is: read this lab, tailor to this lab, write to this person. */}
          {actionable && <ConciergeRequestSection opportunityId={opp.id} t={t} />}
          <KeywordsSection opp={opp} t={t} />
          <SimilarOpportunities similar={similar} t={t} />

          <div className="mt-8 pt-6 border-t border-gray-100 text-[11px] text-gray-400 space-y-1">
            {opp.source && <p>{t('detail.source', { source: opp.source })}</p>}
            {/* From the truth envelope, not metadata: the server stopped
                serving metadata.last_verified once target_truth carried it,
                and one timestamp cannot disagree with itself. */}
            {opp.target_truth?.verified_at && (
              <p>{t('detail.lastVerified', { date: opp.target_truth.verified_at })}</p>
            )}
          </div>
        </main>

        {RELEASE_SCOPE.askAi && actionable && (
          <aside className="hidden lg:block lg:w-[360px] xl:w-[400px] lg:sticky lg:top-[4.5rem] lg:self-start lg:shrink-0">
            <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] border border-gray-100 overflow-hidden h-[calc(100vh-6rem)] max-h-[760px]">
              <OpportunityChatbot opportunity={opp} profile={profile} />
            </div>
          </aside>
        )}
      </div>

      {RELEASE_SCOPE.askAi && actionable && (
        <ChatDrawer
          opp={opp}
          profile={profile}
          open={chatDrawerOpen}
          onOpen={() => setChatDrawerOpen(true)}
          onClose={() => setChatDrawerOpen(false)}
          t={t}
        />
      )}

      {/* Historical and unverified targets mount none of these. A closed
          listing stays readable; drafting an email about it, tailoring a
          résumé to it, or asking an AI how to approach it are the actions
          that must not exist — including as a closed modal one state change
          from opening. */}
      {profile && actionable && (
        <ColdEmailModal
          isOpen={emailModalOpen}
          onClose={() => setEmailModalOpen(false)}
          profile={profile}
          opportunityId={opp.id}
          opportunityTitle={opp.title}
          opportunitySchool={opp.school ?? null}
          reminderTarget={opp}
          onContactConfirmed={noteContactConfirmed}
        />
      )}

      {profile && actionable && (
        <TailorModal
          // Generation-qualified key (same fix as TrackerPanel above): a
          // real identity transition forces a full remount, destroying
          // this modal's own local state (draft, in-flight request)
          // outright rather than relying solely on hydrate()'s
          // setTailorOpen(false) to close it — belt-and-suspenders, not
          // either/or.
          key={`${identityGeneration}:${opp.id}`}
          isOpen={tailorOpen}
          onClose={() => setTailorOpen(false)}
          profile={profile}
          opportunityId={opp.id}
          opportunityTitle={opp.title}
          ownerReady={ownerReady}
          ownerScopeKey={ownerScopeKey}
        />
      )}

      {/* `actionable` is stated explicitly rather than left to the release
          flag. A test that passes only because resumeRenovate is false proves
          nothing about the day it is turned on. */}
      {RELEASE_SCOPE.resumeRenovate && profile && actionable && (
        <ResumeRenovationModal
          isOpen={renovationOpen}
          onClose={() => setRenovationOpen(false)}
          profile={profile}
          opportunityId={opp.id}
          opportunityTitle={opp.title}
        />
      )}
    </div>
  );
}
