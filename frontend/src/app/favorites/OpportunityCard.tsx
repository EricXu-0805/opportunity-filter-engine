'use client';

import {
  Bookmark,
  Building2,
  Check,
  ChevronDown,
  DollarSign,
  ExternalLink,
  FileText,
  Globe,
  Mail,
  MapPin,
  Sparkles,
  Star,
} from 'lucide-react';
import Badge from '@/components/Badge';
import { getIntlBadge, getPaidBadge } from '@/lib/badge-utils';
import { DeadlineBadge } from './DeadlineBadge';
import { MAX_COMPARE, type Opp, type TFunc } from './types';

export interface OpportunityCardProps {
  opp: Opp;
  selectionMode: boolean;
  isSelected: boolean;
  selectedSize: number;
  isExpanded: boolean;
  hasProfile: boolean;
  onToggleExpand: (id: string) => void;
  onToggleSelect: (opp: Opp) => void;
  onRemove: (opp: Opp) => void;
  onOpenEmailModal: (opp: Opp) => void;
  /**
   * Optional — when omitted the "Tailor Resume" CTA is hidden. R71 PR-3
   * adds this entry point for the favorites page; the modal itself is
   * mounted at the parent so we don't pay the dynamic-import cost N
   * times across the saved list.
   */
  onOpenTailorModal?: (opp: Opp) => void;
  t: TFunc;
}

export function OpportunityCard({
  opp,
  selectionMode,
  isSelected,
  selectedSize,
  isExpanded,
  hasProfile,
  onToggleExpand,
  onToggleSelect,
  onRemove,
  onOpenEmailModal,
  onOpenTailorModal,
  t,
}: OpportunityCardProps) {
  // R70-E: switched from inline ternaries to the shared badge-utils
  // helpers so this card stays in sync with MatchCard. The inline paid
  // ternary that used to live here had the same R70-D bug — labelling
  // paid='unknown' (1262 records) as the misleading "Unpaid".
  const intlFriendly = opp.eligibility?.international_friendly;
  const intlBadge = intlFriendly ? getIntlBadge(intlFriendly, t) : null;
  const paidBadge = opp.paid ? getPaidBadge(opp.paid, t) : null;
  const desc = opp.description_clean || opp.description_raw || '';
  const canSelect = !isSelected && selectedSize < MAX_COMPARE;

  return (
    <div className="relative">
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
                onClick={() => onRemove(opp)}
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
            {intlBadge && (
              <Badge variant={intlBadge.variant} dot>
                <Globe className="w-3 h-3" />
                {intlBadge.label}
              </Badge>
            )}
            {paidBadge && (
              <Badge variant={paidBadge.variant} dot>
                <DollarSign className="w-3 h-3" />
                {paidBadge.label}
              </Badge>
            )}
            {opp.source && !opp._customId && <Badge variant="gray">{opp.source}</Badge>}
            <DeadlineBadge deadline={opp.deadline} t={t} />
          </div>

          {!selectionMode && (
            <div className="flex flex-wrap items-center gap-2">
              {hasProfile && !opp._customId && (
                <button
                  type="button"
                  onClick={() => onOpenEmailModal(opp)}
                  className="inline-flex items-center gap-2 px-5 py-2.5 text-[13px] font-semibold text-white bg-gradient-to-r from-blue-600 to-blue-500 rounded-xl hover:from-blue-700 hover:to-blue-600 shadow-sm hover:shadow transition-all duration-200"
                >
                  <Mail className="w-3.5 h-3.5" />
                  {t('card.draftEmail')}
                </button>
              )}
              {hasProfile && !opp._customId && onOpenTailorModal && (
                <button
                  type="button"
                  onClick={() => onOpenTailorModal(opp)}
                  className="inline-flex items-center gap-2 px-4 py-2 text-[13px] font-medium text-indigo-600 bg-indigo-50 rounded-xl hover:bg-indigo-100 transition-colors duration-200"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  {t('card.tailorResume')}
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
                  {opp._customId ? t('favorites.openSource') : t('card.viewDetails')}
                </a>
              )}
            </div>
          )}
        </div>

        {!selectionMode && (
          <div className="border-t border-black/[0.04]">
            <button
              type="button"
              onClick={() => onToggleExpand(opp.id)}
              className="flex items-center justify-between w-full px-6 py-3 text-[13px] font-medium text-gray-400 hover:text-gray-600 transition-colors"
            >
              <span>{isExpanded ? t('card.hideDetails') : t('card.showDetails')}</span>
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
          onClick={() => onToggleSelect(opp)}
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
}
