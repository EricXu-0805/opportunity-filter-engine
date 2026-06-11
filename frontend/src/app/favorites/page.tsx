'use client';

import { useCallback, useMemo, useState } from 'react';
import { ArrowLeft, Loader2 } from 'lucide-react';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/navigation';

import SaveFavoritesAnchor from '@/components/SaveFavoritesAnchor';
import StorageStatusBanner from '@/components/StorageStatusBanner';
import { useCustomImports } from '@/lib/custom-imports';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { useLocalStorageJSON } from '@/lib/use-local-storage-json';
import type { ProfileData } from '@/lib/types';
import { useT } from '@/i18n/client';

import { FavoritesEmptyState } from './FavoritesEmptyState';
import { FavoritesHeader } from './FavoritesHeader';
import { OpportunityCard } from './OpportunityCard';
import { SavedSearchesSection } from './SavedSearchesSection';
import { SelectionFooter } from './SelectionFooter';
import { customImportToOpp, type Opp } from './types';
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

export default function FavoritesPage() {
  const router = useRouter();
  const { t } = useT();

  const profile = useLocalStorageJSON<ProfileData>(STORAGE_KEYS.PROFILE);
  const customImports = useCustomImports();
  const { serverOpportunities, loading, handleRemove } = useFavoritesData();
  const {
    savedSearches,
    digests,
    handleRemove: handleRemoveSavedSearch,
    handleApplyOptimisticClear,
    handleDigestSave,
  } = useSavedSearches(t);
  const {
    selectionMode,
    selected,
    enterSelection,
    cancelSelection,
    toggleSelect,
    confirmCompare,
  } = useCompareSelection();

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [emailModal, setEmailModal] = useState<{ open: boolean; id: string; title: string }>({
    open: false, id: '', title: '',
  });
  // R71 PR-3: mirror emailModal state. We model open/closed + opp metadata
  // together (rather than separate booleans) so closing the modal doesn't
  // race with re-opening for a different opp.
  const [tailorModal, setTailorModal] = useState<{ open: boolean; id: string; title: string }>({
    open: false, id: '', title: '',
  });

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
    setEmailModal({ open: true, id: opp.id, title: opp.title });
  }, []);

  const closeEmailModal = useCallback(() => {
    setEmailModal({ open: false, id: '', title: '' });
  }, []);

  const openTailorModal = useCallback((opp: Opp) => {
    setTailorModal({ open: true, id: opp.id, title: opp.title });
  }, []);

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
          flag persists across sessions on this device). */}
      <SaveFavoritesAnchor favoriteCount={opportunities.length} />

      <FavoritesHeader
        opportunities={opportunities}
        serverOpportunitiesCount={serverOpportunities.length}
        selectionMode={selectionMode}
        onEnterSelection={enterSelection}
        onCancelSelection={cancelSelection}
        t={t}
      />

      {!selectionMode && (savedSearches.length > 0 || opportunities.length > 0) && (
        <SavedSearchesSection
          savedSearches={savedSearches}
          digests={digests}
          onApplyOptimisticClear={handleApplyOptimisticClear}
          onRemove={handleRemoveSavedSearch}
          onDigestSave={handleDigestSave}
          t={t}
        />
      )}

      {opportunities.length === 0 ? (
        <FavoritesEmptyState t={t} />
      ) : (
        <div className="space-y-4">
          {opportunities.map((opp) => (
            <OpportunityCard
              key={opp.id}
              opp={opp}
              selectionMode={selectionMode}
              isSelected={selected.has(opp.id)}
              selectedSize={selected.size}
              isExpanded={expanded.has(opp.id)}
              hasProfile={!!profile}
              onToggleExpand={toggleExpand}
              onToggleSelect={toggleSelect}
              onRemove={handleRemove}
              onOpenEmailModal={openEmailModal}
              onOpenTailorModal={openTailorModal}
              t={t}
            />
          ))}
        </div>
      )}

      {selectionMode && (
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
        />
      )}

      {profile && (
        <TailorModal
          isOpen={tailorModal.open}
          onClose={closeTailorModal}
          profile={profile}
          opportunityId={tailorModal.id}
          opportunityTitle={tailorModal.title}
        />
      )}
    </div>
  );
}
