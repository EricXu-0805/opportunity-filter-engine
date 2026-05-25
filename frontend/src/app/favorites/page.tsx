'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useLocalStorageJSON } from '@/lib/use-local-storage-json';
import { useCustomImports, removeCustomImport, type CustomImport } from '@/lib/custom-imports';
import {
  listSavedSearches,
  removeSavedSearch,
  savedSearchToUrl,
  type SavedSearch,
} from '@/lib/saved-searches';
import { humanizeTime } from '@/lib/humanize-time';
import {
  Star,
  ArrowLeft,
  Loader2,
  Mail,
  Globe,
  DollarSign,
  MapPin,
  Building2,
  BellRing,
  Clock,
  ChevronDown,
  FileText,
  GitCompare,
  Check,
  X,
  Bookmark,
  Cloud,
  Trash2,
  ExternalLink,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import dynamic from 'next/dynamic';
import { getFavorites, toggleFavorite } from '@/lib/supabase';
import { getOpportunitiesByIds, sendFavoritesEmail } from '@/lib/api';
import { getInteractionsFull } from '@/lib/supabase';
import Badge from '@/components/Badge';
import StorageStatusBanner from '@/components/StorageStatusBanner';
import EmailMeButton from '@/components/EmailMeButton';
import { useT } from '@/i18n/client';

const ColdEmailModal = dynamic(() => import('@/components/ColdEmailModal'), {
  ssr: false,
});
import type { ProfileData } from '@/lib/types';

interface Opp {
  id: string;
  title: string;
  organization?: string;
  department?: string;
  opportunity_type?: string;
  paid?: string;
  location?: string;
  url?: string;
  source?: string;
  on_campus?: boolean;
  deadline?: string;
  description_clean?: string;
  description_raw?: string;
  keywords?: string[];
  pi_name?: string;
  lab_or_program?: string;
  eligibility?: {
    international_friendly?: string;
    skills_required?: string[];
    years?: string[];
  };
  _customId?: string;
}

function customImportToOpp(c: CustomImport): Opp {
  const e = c.opportunity;
  const extra = (e.extra_fields ?? {}) as Record<string, unknown>;
  const oppType = typeof extra.opportunity_type === 'string' ? extra.opportunity_type : undefined;
  const paid = typeof extra.paid === 'string' ? extra.paid : undefined;
  const onCampus = typeof extra.on_campus === 'boolean' ? extra.on_campus : undefined;
  const intl = typeof extra.international_friendly === 'string' ? extra.international_friendly : undefined;
  const skills = Array.isArray(extra.skills_required) ? (extra.skills_required as string[]) : undefined;
  return {
    id: c.id,
    _customId: c.id,
    title: e.title || 'Untitled import',
    organization: e.organization || undefined,
    opportunity_type: oppType,
    paid,
    location: e.location || undefined,
    url: e.url || e.source_url || undefined,
    source: undefined,
    on_campus: onCampus,
    deadline: e.deadline || undefined,
    description_raw: e.description_raw || undefined,
    eligibility: skills || intl ? {
      international_friendly: intl,
      skills_required: skills,
    } : undefined,
  };
}

const MIN_COMPARE = 2;
const MAX_COMPARE = 3;

function summarizeSavedSearchFilters(
  search: SavedSearch,
  t: (key: string, vars?: Record<string, string | number>) => string,
): string {
  const parts: string[] = [];
  if (search.query) parts.push(`"${search.query}"`);
  if (search.filters.paid === 'yes') parts.push('paid');
  if (search.filters.paid === 'no') parts.push('unpaid');
  if (search.filters.intl === 'yes') parts.push('intl');
  if (search.filters.onCampus === 'yes') parts.push('on-campus');
  if (search.filters.deadline === 'passed') parts.push('past-due');
  else if (search.filters.deadline) parts.push(`≤${search.filters.deadline}d`);
  if (search.filters.minScore > 0) parts.push(`≥${search.filters.minScore}`);
  if (search.filters.source) parts.push(search.filters.source);
  if (search.tab && search.tab !== 'all') parts.push(search.tab);
  if (search.sort_by && search.sort_by !== 'score') parts.push(`by ${search.sort_by}`);
  return parts.length > 0 ? parts.join(' · ') : t('favorites.savedSearches.filtersFallback');
}

function formatSavedSearchTimestamp(
  iso: string | null,
  t: (key: string, vars?: Record<string, string | number>) => string,
): string {
  const result = humanizeTime(iso);
  if (!result) return t('favorites.savedSearches.pendingSync');
  let ago: string;
  switch (result.kind) {
    case 'just-now':
      ago = t('favorites.savedSearches.justNow');
      break;
    case 'minutes':
      ago = t('favorites.savedSearches.minutesAgo', { n: result.n });
      break;
    case 'hours':
      ago = t('favorites.savedSearches.hoursAgo', { n: result.n });
      break;
    case 'days':
      ago = t('favorites.savedSearches.daysAgo', { n: result.n });
      break;
    case 'date':
      ago = t('favorites.savedSearches.onDate', { date: result.iso });
      break;
  }
  return t('favorites.savedSearches.checkedAgo', { ago });
}

function DeadlineBadge({
  deadline,
  t,
}: {
  deadline?: string;
  t: (key: string, vars?: Record<string, string | number>) => string;
}) {
  if (!deadline) return null;
  const dl = new Date(deadline + 'T00:00:00');
  const now = new Date();
  const daysLeft = Math.ceil((dl.getTime() - now.getTime()) / 86400000);
  if (daysLeft < 0) return <Badge variant="red"><Clock className="w-3 h-3" />{t('badges.deadlinePassed')}</Badge>;
  if (daysLeft <= 14) return <Badge variant="orange"><Clock className="w-3 h-3" />{t('badges.dueInDays', { count: daysLeft })}</Badge>;
  return <Badge variant="gray"><Clock className="w-3 h-3" />{deadline}</Badge>;
}

export default function FavoritesPage() {
  const router = useRouter();
  const { t } = useT();
  const [serverOpportunities, setServerOpportunities] = useState<Opp[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectionMode, setSelectionMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const profile = useLocalStorageJSON<ProfileData>('ofe_profile');
  const customImports = useCustomImports();
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [emailModal, setEmailModal] = useState<{ open: boolean; id: string; title: string }>({
    open: false, id: '', title: '',
  });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const favSet = await getFavorites();
        if (cancelled) return;
        const ids = Array.from(favSet);
        if (ids.length === 0) {
          setLoading(false);
          return;
        }
        const opps = await getOpportunitiesByIds(ids);
        if (cancelled) return;
        setServerOpportunities(opps as unknown as Opp[]);
      } catch {}
      finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    listSavedSearches()
      .then((data) => {
        if (!cancelled) setSavedSearches(data);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const handleRemoveSavedSearch = useCallback(async (search: SavedSearch) => {
    if (!window.confirm(t('favorites.savedSearches.deleteConfirm', { name: search.name }))) return;
    const ok = await removeSavedSearch(search.id);
    if (ok) {
      setSavedSearches((prev) => prev.filter((s) => s.id !== search.id));
    }
  }, [t]);

  const opportunities = useMemo<Opp[]>(
    () => [...customImports.map(customImportToOpp), ...serverOpportunities],
    [customImports, serverOpportunities],
  );

  const handleRemove = useCallback(async (opp: Opp) => {
    if (opp._customId) {
      removeCustomImport(opp._customId);
      return;
    }
    await toggleFavorite(opp.id, true);
    setServerOpportunities(prev => prev.filter(o => o.id !== opp.id));
  }, []);

  const toggleExpand = useCallback((id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const enterSelectionMode = useCallback(() => {
    setSelectionMode(true);
    setSelected(new Set());
  }, []);

  const cancelSelection = useCallback(() => {
    setSelectionMode(false);
    setSelected(new Set());
  }, []);

  const toggleSelect = useCallback((opp: Opp) => {
    if (opp._customId) return;
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(opp.id)) {
        next.delete(opp.id);
      } else if (next.size < MAX_COMPARE) {
        next.add(opp.id);
      }
      return next;
    });
  }, []);

  const confirmCompare = useCallback(() => {
    if (selected.size < MIN_COMPARE) return;
    const ids = Array.from(selected).map(encodeURIComponent).join(',');
    router.push(`/compare?ids=${ids}`);
  }, [selected, router]);

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

      <div className="mb-10 flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-4xl font-bold text-gray-900 tracking-tight">{t('favorites.title')}</h1>
          <p className="mt-2 text-[15px] text-gray-400">
            {opportunities.length === 0 ? t('favorites.empty') : t('favorites.count', { count: opportunities.length })}
          </p>
          {selectionMode && (
            <p className="mt-1 text-[13px] text-blue-600 font-medium">
              {t('favorites.selectionHint', { min: MIN_COMPARE, max: MAX_COMPARE })}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0 flex-wrap">
          {!selectionMode && opportunities.length > 0 && (
            <EmailMeButton
              label={t('email.sendFavorites')}
              title={t('email.subtitle')}
              onSend={async (emailAddr) => {
                const interactions = await getInteractionsFull().catch(() => new Map());
                const items = opportunities
                  .filter((o) => !o._customId)
                  .slice(0, 50)
                  .map((o) => {
                    const rec = interactions.get(o.id);
                    return {
                      title: o.title,
                      url: o.url || '',
                      source: o.source || '',
                      deadline: o.deadline || null,
                      notes: rec?.notes || '',
                      status: rec?.type || '',
                    };
                  });
                return sendFavoritesEmail(emailAddr, items);
              }}
            />
          )}
          {!selectionMode && serverOpportunities.length >= MIN_COMPARE && (
            <button
              type="button"
              onClick={enterSelectionMode}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-blue-600 text-white text-[13px] font-semibold hover:bg-blue-700 transition-colors shadow-[0_2px_12px_rgba(37,99,235,0.25)]"
            >
              <GitCompare className="w-4 h-4" aria-hidden="true" />
              {t('favorites.compare')}
            </button>
          )}
          {selectionMode && (
            <button
              type="button"
              onClick={cancelSelection}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white border border-gray-300 text-gray-700 text-[13px] font-semibold hover:bg-gray-50 transition-colors"
            >
              <X className="w-4 h-4" aria-hidden="true" />
              {t('favorites.cancel')}
            </button>
          )}
        </div>
      </div>

      {!selectionMode && (savedSearches.length > 0 || opportunities.length > 0) && (
        <section className="mb-8" aria-labelledby="saved-searches-heading">
          <div className="flex items-baseline justify-between mb-3">
            <div>
              <h2 id="saved-searches-heading" className="text-[15px] font-semibold text-gray-900 inline-flex items-center gap-2">
                <Cloud className="w-4 h-4 text-indigo-500" aria-hidden="true" />
                {t('favorites.savedSearches.sectionTitle')}
              </h2>
              {savedSearches.length > 0 && (
                <p className="text-[12px] text-gray-400 mt-0.5">
                  {t('favorites.savedSearches.sectionHint')}
                </p>
              )}
            </div>
            {savedSearches.length > 0 && (
              <span className="text-[11px] text-gray-400 tabular-nums">
                {t('favorites.savedSearches.itemCount', { count: savedSearches.length })}
              </span>
            )}
          </div>
          {savedSearches.length === 0 ? (
            <div className="text-center py-6 px-4 rounded-xl bg-gray-50/80 border border-dashed border-gray-200">
              <p className="text-[13px] text-gray-500">
                {t('favorites.savedSearches.emptyHint')}
              </p>
            </div>
          ) : (
          <ul className="space-y-2">
            {savedSearches.map((search) => {
              const summary = summarizeSavedSearchFilters(search, t);
              const timestampLabel = formatSavedSearchTimestamp(search.last_run_at, t);
              const newCount = search.new_match_ids?.length ?? 0;
              const hasNew = newCount > 0;
              return (
                <li
                  key={search.id}
                  className="group bg-white rounded-xl shadow-[0_1px_6px_rgba(0,0,0,0.04)] hover:shadow-[0_2px_12px_rgba(0,0,0,0.06)] transition-shadow flex items-center"
                >
                  <Link
                    href={savedSearchToUrl(
                      search,
                      hasNew
                        ? { highlight: search.new_match_ids, savedSearchId: search.id }
                        : undefined,
                    )}
                    onClick={hasNew ? () => {
                      setSavedSearches((prev) =>
                        prev.map((s) =>
                          s.id === search.id ? { ...s, new_match_ids: [] } : s,
                        ),
                      );
                    } : undefined}
                    aria-label={t('favorites.savedSearches.applyAria', { name: search.name })}
                    className="flex-1 min-w-0 px-4 py-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded-l-xl"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-[14px] font-medium text-gray-900 truncate">
                        {search.name}
                      </span>
                      {hasNew && (
                        <span
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-amber-100/80 text-amber-700 text-[11px] font-semibold shrink-0"
                          aria-label={t('favorites.savedSearches.newMatchesAria', { count: newCount })}
                        >
                          <BellRing className="w-3 h-3" aria-hidden="true" />
                          {t('favorites.savedSearches.newBadge', { count: newCount })}
                        </span>
                      )}
                    </div>
                    <p className="text-[12px] text-gray-500 truncate mt-0.5">{summary}</p>
                    <p className="text-[11px] text-gray-400 truncate mt-0.5 tabular-nums">{timestampLabel}</p>
                  </Link>
                  <button
                    type="button"
                    onClick={() => handleRemoveSavedSearch(search)}
                    aria-label={t('favorites.savedSearches.deleteAria', { name: search.name })}
                    className="p-3 mr-1 rounded-lg text-gray-300 hover:text-red-500 hover:bg-red-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
                  >
                    <Trash2 className="w-4 h-4" aria-hidden="true" />
                  </button>
                </li>
              );
            })}
          </ul>
          )}
        </section>
      )}

      {opportunities.length === 0 ? (
        <div className="text-center py-20">
          <Star className="w-10 h-10 text-gray-200 mx-auto mb-4" />
          <p className="text-[15px] text-gray-400 mb-2">{t('favorites.emptyHint')}</p>
          <p className="text-[13px] text-gray-300 mb-6">{t('favorites.emptyHintImport')}</p>
          <div className="flex items-center justify-center gap-3 flex-wrap">
            <button
              type="button"
              onClick={() => router.push('/')}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-blue-600 text-white text-[13px] font-medium hover:bg-blue-700 transition-colors duration-300"
            >
              {t('favorites.browseMatches')}
            </button>
            <Link
              href="/import"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full border border-gray-200 text-gray-700 text-[13px] font-medium hover:bg-gray-50 transition-colors duration-300"
            >
              <Bookmark className="w-3.5 h-3.5" />
              {t('favorites.importLink')}
            </Link>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {opportunities.map((opp) => {
            const isExpanded = expanded.has(opp.id);
            const intlFriendly = opp.eligibility?.international_friendly;
            const desc = opp.description_clean || opp.description_raw || '';
            const isSelected = selected.has(opp.id);
            const canSelect = !isSelected && selected.size < MAX_COMPARE;

            return (
              <div key={opp.id} className="relative">
                <div
                  className={`bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] overflow-hidden transition-all ${
                    selectionMode
                      ? isSelected
                        ? 'ring-2 ring-blue-500 shadow-[0_4px_20px_rgba(37,99,235,0.15)]'
                        : canSelect
                        ? 'hover:shadow-[0_4px_20px_rgba(0,0,0,0.08)]'
                        : 'opacity-50'
                      : 'hover:shadow-[0_4px_20px_rgba(0,0,0,0.08)]'
                  }`}
                >
                  <div className="p-6">
                    <div className="flex items-start justify-between gap-4 mb-3">
                      <div className="flex-1 min-w-0">
                        <h3 className="text-[17px] font-semibold text-gray-900 leading-snug line-clamp-2">
                          {selectionMode || opp._customId ? (
                            <span>{opp.title}</span>
                          ) : (
                            <a
                              href={`/opportunities/${encodeURIComponent(opp.id)}`}
                              className="hover:text-blue-600 focus:outline-none focus-visible:underline decoration-blue-500 underline-offset-4 transition-colors"
                            >
                              {opp.title}
                            </a>
                          )}
                        </h3>
                        <div className="flex items-center gap-3 mt-2 text-[13px] text-gray-400">
                          {opp.organization && (
                            <span className="inline-flex items-center gap-1">
                              <Building2 className="w-3.5 h-3.5" />
                              {opp.organization}
                            </span>
                          )}
                          {opp.location && (
                            <span className="inline-flex items-center gap-1">
                              <MapPin className="w-3.5 h-3.5" />
                              {opp.location}
                            </span>
                          )}
                        </div>
                      </div>
                      {!selectionMode && (
                        <button
                          type="button"
                          onClick={() => handleRemove(opp)}
                          className="p-1.5 rounded-lg hover:bg-red-50 transition-colors shrink-0"
                          aria-label={opp._customId ? t('favorites.removeCustomAria') : t('favorites.removeAria')}
                        >
                          {opp._customId ? (
                            <Bookmark className="w-4.5 h-4.5 fill-blue-500 text-blue-500" />
                          ) : (
                            <Star className="w-4.5 h-4.5 fill-amber-400 text-amber-400" />
                          )}
                        </button>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center gap-1.5 mb-4">
                      {opp._customId && (
                        <Badge variant="indigo" dot>
                          <Bookmark className="w-3 h-3" />
                          {t('favorites.customBadge')}
                        </Badge>
                      )}
                      {opp.opportunity_type && <Badge variant="indigo">{opp.opportunity_type}</Badge>}
                      {intlFriendly && (
                        <Badge variant={intlFriendly === 'yes' ? 'green' : intlFriendly === 'no' ? 'red' : 'orange'} dot>
                          <Globe className="w-3 h-3" />
                          {intlFriendly === 'yes' ? 'Intl OK' : intlFriendly === 'no' ? 'US Only' : 'Verify'}
                        </Badge>
                      )}
                      {opp.paid && (
                        <Badge variant={opp.paid === 'yes' || opp.paid === 'stipend' ? 'green' : 'gray'} dot>
                          <DollarSign className="w-3 h-3" />
                          {opp.paid === 'yes' ? 'Paid' : opp.paid === 'stipend' ? 'Stipend' : 'Unpaid'}
                        </Badge>
                      )}
                      {opp.source && !opp._customId && <Badge variant="gray">{opp.source}</Badge>}
                      <DeadlineBadge deadline={opp.deadline} t={t} />
                    </div>

                    {!selectionMode && (
                      <div className="flex flex-wrap items-center gap-2">
                        {profile && !opp._customId && (
                          <button
                            type="button"
                            onClick={() => setEmailModal({ open: true, id: opp.id, title: opp.title })}
                            className="inline-flex items-center gap-2 px-5 py-2.5 text-[13px] font-semibold text-white bg-gradient-to-r from-blue-600 to-blue-500 rounded-xl hover:from-blue-700 hover:to-blue-600 shadow-sm hover:shadow transition-all duration-200"
                          >
                            <Mail className="w-3.5 h-3.5" />
                            Draft Email
                          </button>
                        )}
                        {opp.url && (
                          <a
                            href={opp.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-2 px-4 py-2 text-[13px] font-medium text-gray-600 bg-black/[0.04] rounded-xl hover:bg-black/[0.08] transition-colors duration-200"
                          >
                            {opp._customId ? <ExternalLink className="w-3.5 h-3.5" /> : <FileText className="w-3.5 h-3.5" />}
                            {opp._customId ? t('favorites.openSource') : 'View Details'}
                          </a>
                        )}
                      </div>
                    )}
                  </div>

                  {!selectionMode && (
                    <div className="border-t border-black/[0.04]">
                      <button
                        type="button"
                        onClick={() => toggleExpand(opp.id)}
                        className="flex items-center justify-between w-full px-6 py-3 text-[13px] font-medium text-gray-400 hover:text-gray-600 transition-colors"
                      >
                        <span>{isExpanded ? 'Hide details' : 'Show details'}</span>
                        <ChevronDown className={`w-4 h-4 transition-transform duration-300 ${isExpanded ? 'rotate-180' : ''}`} />
                      </button>

                      {isExpanded && (
                        <div className="px-6 pb-6 space-y-4 animate-in">
                          {(opp.pi_name || opp.lab_or_program || opp.department) && (
                            <div className="flex flex-wrap gap-x-6 gap-y-1 text-[13px]">
                              {opp.pi_name && (
                                <span className="text-gray-500"><span className="font-medium text-gray-700">PI:</span> {opp.pi_name}</span>
                              )}
                              {opp.lab_or_program && (
                                <span className="text-gray-500"><span className="font-medium text-gray-700">Lab:</span> {opp.lab_or_program}</span>
                              )}
                              {opp.department && (
                                <span className="text-gray-500"><span className="font-medium text-gray-700">Dept:</span> {opp.department}</span>
                              )}
                            </div>
                          )}

                          {desc && (
                            <p className="text-[13px] text-gray-500 leading-relaxed line-clamp-4">
                              {desc}
                            </p>
                          )}

                          {opp.eligibility?.skills_required && opp.eligibility.skills_required.length > 0 && (
                            <div>
                              <span className="text-[11px] font-semibold text-indigo-600 uppercase tracking-widest">{t('favorites.requiredSkills')}</span>
                              <div className="flex flex-wrap gap-1.5 mt-1.5">
                                {opp.eligibility.skills_required.map((s) => (
                                  <span key={s} className="px-2.5 py-1 rounded-lg bg-indigo-50 text-indigo-700 text-[12px] font-medium">{s}</span>
                                ))}
                              </div>
                            </div>
                          )}

                          {opp.keywords && opp.keywords.length > 0 && (
                            <div className="flex flex-wrap gap-1.5">
                              {opp.keywords.slice(0, 8).map((kw) => (
                                <span key={kw} className="px-2 py-0.5 rounded-md bg-gray-100 text-[11px] text-gray-500">{kw}</span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {selectionMode && (
                  <button
                    type="button"
                    onClick={() => toggleSelect(opp)}
                    disabled={!!opp._customId || (!isSelected && !canSelect)}
                    aria-pressed={isSelected}
                    aria-label={t('favorites.toggleSelectAria', { title: opp.title })}
                    className={`absolute inset-0 rounded-2xl focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 ${
                      opp._customId
                        ? 'bg-gray-500/[0.05] cursor-not-allowed'
                        : isSelected ? 'bg-blue-500/[0.05]' : canSelect ? 'hover:bg-blue-500/[0.03]' : 'cursor-not-allowed'
                    }`}
                  >
                    <span className={`absolute top-4 right-4 w-7 h-7 rounded-full flex items-center justify-center transition-all ${
                      isSelected
                        ? 'bg-blue-600 text-white'
                        : canSelect
                        ? 'bg-white border-2 border-gray-300'
                        : 'bg-gray-100 border-2 border-gray-200'
                    }`}>
                      {isSelected && <Check className="w-4 h-4" aria-hidden="true" />}
                    </span>
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {selectionMode && (
        <div className="fixed inset-x-0 bottom-0 z-30 bg-white/95 backdrop-blur-md border-t border-gray-200 shadow-[0_-4px_20px_rgba(0,0,0,0.08)]">
          <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center gap-4 flex-wrap">
            <div className="flex-1 min-w-0">
              <p className="text-[13px] font-semibold text-gray-900">
                {t('favorites.selectedCount', { current: selected.size, max: MAX_COMPARE })}
              </p>
              {selectedTitles.length > 0 && (
                <p className="text-[12px] text-gray-500 truncate mt-0.5">
                  {selectedTitles.join(' · ')}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={cancelSelection}
                className="inline-flex items-center justify-center px-4 py-2.5 rounded-xl bg-white border border-gray-300 text-gray-700 text-[13px] font-medium hover:bg-gray-50 transition-colors"
              >
                {t('favorites.cancel')}
              </button>
              <button
                type="button"
                onClick={confirmCompare}
                disabled={selected.size < MIN_COMPARE}
                className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-blue-600 text-white text-[13px] font-semibold hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-[0_2px_12px_rgba(37,99,235,0.25)]"
              >
                <GitCompare className="w-4 h-4" aria-hidden="true" />
                {t('favorites.confirmCompare')}
              </button>
            </div>
          </div>
        </div>
      )}

      {profile && (
        <ColdEmailModal
          isOpen={emailModal.open}
          onClose={() => setEmailModal({ open: false, id: '', title: '' })}
          profile={profile}
          opportunityId={emailModal.id}
          opportunityTitle={emailModal.title}
        />
      )}
    </div>
  );
}
