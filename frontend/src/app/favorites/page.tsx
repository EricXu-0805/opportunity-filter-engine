'use client';

import { useCallback, useMemo, useState } from 'react';
import { AlertTriangle, ArrowLeft, Loader2 } from 'lucide-react';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/navigation';

import SaveFavoritesAnchor from '@/components/SaveFavoritesAnchor';
import StorageStatusBanner from '@/components/StorageStatusBanner';
import { useCustomImports } from '@/lib/custom-imports';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { RELEASE_SCOPE } from '@/lib/release-scope';
import { useLocalStorageJSON } from '@/lib/use-local-storage-json';
import type { ProfileData } from '@/lib/types';
import { useT } from '@/i18n/client';

import { FavoritesEmptyState } from './FavoritesEmptyState';
import { FavoritesHeader } from './FavoritesHeader';
import { OpportunityCard } from './OpportunityCard';
import { SavedSearchesSection } from './SavedSearchesSection';
import { SelectionFooter } from './SelectionFooter';
import { customImportToOpp, type Opp, type TFunc } from './types';
import { useCompareSelection } from './use-compare-selection';
import { useFavoritesData } from './use-favorites-data';
import { useSavedSearches } from './use-saved-searches';

const ColdEmailModal = dynamic(() => import('@/components/ColdEmailModal'), {
  ssr: false,
});
// R71 PR-3: third entry point for the tailor modal. Same shape as the
// email modal — favorites/page owns the open/close state, OpportunityCard
// gets a callback prop, and the modal is mounted once at the page level
// (not per-card) so we don't pay the dynamic-import cost N times.
const TailorModal = dynamic(() => import('@/components/TailorModal'), {
  ssr: false,
});

// useSavedSearches fetches once on mount and has no identity awareness of
// its own (out of allowlist scope to change). Isolating it in its own
// component lets the parent force a fresh mount — cancelling any in-flight
// fetch for the old identity and loading the new one — by changing this
// component's `key` on a real account switch, instead of ever showing the
// previous account's saved searches/digests after the new one loads.
function SavedSearchesPanel({
  t,
  selectionMode,
  hasOpportunities,
}: {
  t: TFunc;
  selectionMode: boolean;
  hasOpportunities: boolean;
}) {
  const {
    savedSearches,
    digests,
    handleRemove,
    handleApplyOptimisticClear,
    handleDigestSave,
  } = useSavedSearches(t);

  if (selectionMode || (savedSearches.length === 0 && !hasOpportunities)) return null;

  return (
    <SavedSearchesSection
      savedSearches={savedSearches}
      digests={digests}
      onApplyOptimisticClear={handleApplyOptimisticClear}
      onRemove={handleRemove}
      onDigestSave={handleDigestSave}
      t={t}
    />
  );
}

export default function FavoritesPage() {
  const router = useRouter();
  const { t } = useT();

  const profile = useLocalStorageJSON<ProfileData>(STORAGE_KEYS.PROFILE);
  const customImports = useCustomImports();
  const [savedSearchesEpoch, setSavedSearchesEpoch] = useState(0);
  const {
    selectionMode,
    selected,
    enterSelection,
    cancelSelection,
    toggleSelect,
    confirmCompare,
  } = useCompareSelection();

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [emailModal, setEmailModal] = useState<{ open: boolean; id: string; title: string; school: string | null }>({
    open: false, id: '', title: '', school: null,
  });
  // R71 PR-3: mirror emailModal state. We model open/closed + opp metadata
  // together (rather than separate booleans) so closing the modal doesn't
  // race with re-opening for a different opp.
  const [tailorModal, setTailorModal] = useState<{ open: boolean; id: string; title: string }>({
    open: false, id: '', title: '',
  });

  // The previous account's expanded cards / open modals / compare selection
  // / saved searches are page-local UI that useFavoritesData has no way to
  // reach — clear it (and remount SavedSearchesPanel via the epoch bump) on
  // a real identity transition so none of it can leak into the next account.
  const resetPageLocalState = useCallback(() => {
    setExpanded(new Set());
    setEmailModal({ open: false, id: '', title: '', school: null });
    setTailorModal({ open: false, id: '', title: '' });
    cancelSelection();
    setSavedSearchesEpoch((e) => e + 1);
  }, [cancelSelection]);

  const {
    serverOpportunities, loading, error, retry, unavailableCount,
    identityGeneration, ownerReady, ownerScopeKey,
    handleRemove,
  } = useFavoritesData(resetPageLocalState);

  const opportunities = useMemo<Opp[]>(
    () => [...customImports.map(customImportToOpp), ...serverOpportunities],
    [customImports, serverOpportunities],
  );

  const toggleExpand = useCallback((id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const openEmailModal = useCallback((opp: Opp) => {
    setEmailModal({ open: true, id: opp.id, title: opp.title, school: opp.school ?? null });
  }, []);

  const closeEmailModal = useCallback(() => {
    setEmailModal({ open: false, id: '', title: '', school: null });
  }, []);

  const openTailorModal = useCallback((opp: Opp) => {
    if (!ownerReady) return; // fail-closed — the CTA is disabled too, this is defense-in-depth
    setTailorModal({ open: true, id: opp.id, title: opp.title });
  }, [ownerReady]);

  const closeTailorModal = useCallback(() => {
    setTailorModal({ open: false, id: '', title: '' });
  }, []);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <Loader2 className="w-6 h-6 text-gray-400 animate-spin" />
        <p className="text-[13px] text-gray-400">{t('favorites.loading')}</p>
      </div>
    );
  }

  const selectedTitles = Array.from(selected)
    .map((id) => opportunities.find((o) => o.id === id)?.title || '')
    .filter(Boolean);

  return (
    <div className={`max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-16 ${selectionMode ? 'pb-32' : ''}`}>
      <button
        type="button"
        onClick={() => router.back()}
        className="inline-flex items-center gap-2 text-[13px] text-gray-400 hover:text-gray-600 mb-8 transition-colors duration-300"
      >
        <ArrowLeft className="w-4 h-4" />
        Back
      </button>

      <StorageStatusBanner />

      {/* R66: the lone anchor prompt — only renders when an anonymous
          user has 3+ favorites AND has not dismissed it (localStorage
          flag persists across sessions on this device). unavailableCount
          is included so a partial load doesn't undercount the real total. */}
      <SaveFavoritesAnchor favoriteCount={opportunities.length + unavailableCount} />

      {error || unavailableCount > 0 ? (
        // FavoritesHeader's own count text (opportunities.length === 0 ?
        // "empty" : count) can't tell a degraded load apart from a true
        // empty shortlist — it would claim "you have no favorites" during
        // an error, or undercount the total during a partial load. A safe,
        // simplified title stands in until accounting is complete and
        // clean; Email/Compare are omitted rather than acting on it.
        <div className="mb-10">
          <h1 className="text-4xl font-bold text-gray-900 tracking-tight">{t('favorites.title')}</h1>
          {!error && (
            <p className="mt-2 text-[15px] text-gray-400">
              {t('favorites.count', { count: opportunities.length + unavailableCount })}
            </p>
          )}
        </div>
      ) : (
        <FavoritesHeader
          opportunities={opportunities}
          serverOpportunitiesCount={serverOpportunities.length}
          selectionMode={RELEASE_SCOPE.compare && selectionMode}
          onEnterSelection={enterSelection}
          onCancelSelection={cancelSelection}
          t={t}
        />
      )}

      <SavedSearchesPanel
        key={savedSearchesEpoch}
        t={t}
        selectionMode={selectionMode}
        hasOpportunities={opportunities.length > 0}
      />

      {opportunities.length === 0 && !error && unavailableCount === 0 ? (
        <FavoritesEmptyState t={t} />
      ) : (
        <div className="space-y-4">
          {error && (
            <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3">
              <p className="flex items-center gap-2 text-[13px] text-red-700">
                <AlertTriangle className="w-4 h-4 shrink-0" aria-hidden="true" />
                {t('favorites.loadError')}
              </p>
              <button
                type="button"
                onClick={retry}
                className="shrink-0 text-[13px] font-semibold text-indigo-600 hover:text-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded"
              >
                {t('common.retry')}
              </button>
            </div>
          )}
          {!error && unavailableCount > 0 && (
            <div className="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-[13px] text-amber-800">
              <AlertTriangle className="w-4 h-4 shrink-0" aria-hidden="true" />
              {t('favorites.unavailableWarning', { count: unavailableCount })}
            </div>
          )}
          {opportunities.map((opp) => (
            <OpportunityCard
              key={opp.id}
              opp={opp}
              selectionMode={RELEASE_SCOPE.compare && selectionMode}
              isSelected={selected.has(opp.id)}
              selectedSize={selected.size}
              isExpanded={expanded.has(opp.id)}
              hasProfile={!!profile}
              onToggleExpand={toggleExpand}
              onToggleSelect={toggleSelect}
              onRemove={handleRemove}
              onOpenEmailModal={openEmailModal}
              onOpenTailorModal={openTailorModal}
              tailorDisabled={!ownerReady}
              t={t}
            />
          ))}
        </div>
      )}

      {RELEASE_SCOPE.compare && selectionMode && (
        <SelectionFooter
          selectedCount={selected.size}
          selectedTitles={selectedTitles}
          onCancel={cancelSelection}
          onConfirm={confirmCompare}
          t={t}
        />
      )}

      {profile && (
        <ColdEmailModal
          isOpen={emailModal.open}
          onClose={closeEmailModal}
          profile={profile}
          opportunityId={emailModal.id}
          opportunityTitle={emailModal.title}
          opportunitySchool={emailModal.school}
        />
      )}

      {profile && (
        <TailorModal
          // Generation-qualified key: a real identity transition forces a
          // full remount, destroying this modal's own local state (draft,
          // in-flight request) outright — belt-and-suspenders alongside
          // resetPageLocalState's setTailorModal({open:false,...}), not
          // either/or. Also remounts on a target-opportunity change (this
          // is a single page-level modal instance reused across cards),
          // which is already the existing behavior via tailorModal.id
          // changing what's displayed — the key just makes it explicit.
          key={`${identityGeneration}:${tailorModal.id}`}
          isOpen={tailorModal.open}
          onClose={closeTailorModal}
          profile={profile}
          opportunityId={tailorModal.id}
          opportunityTitle={tailorModal.title}
          ownerReady={ownerReady}
          ownerScopeKey={ownerScopeKey}
        />
      )}
    </div>
  );
}
