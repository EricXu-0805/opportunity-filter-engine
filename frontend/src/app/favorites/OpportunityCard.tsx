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
import { facultySafeInternational, opportunityRecordKind } from '@/lib/match-utils';
import {
  opportunitySourceUrl,
  targetPosture,
  targetStatusReason,
  type TargetStatusReason,
} from '@/lib/target-truth';
import { DeadlineBadge } from './DeadlineBadge';
import { MAX_COMPARE, type Opp, type TFunc } from './types';

/**
 * Why a saved target is no longer one to act on — one sentence per reason.
 *
 * A shortlist is read weeks after it was built, so "this is not open any
 * more" is not enough: the student needs to know whether a window closed,
 * whether it was ever a listing, or whether we simply never reviewed it.
 *
 * The `compare.` keys are shared vocabulary, already written and translated,
 * and MatchCard borrows the same set. Worth renaming once, for both, in a
 * batch that owns the dictionaries.
 */
const SAVED_STATUS_KEY: Record<TargetStatusReason, string> = {
  listing_closed: 'compare.status.closed',
  reference_only: 'compare.status.reference',
  faculty_not_accepting: 'compare.status.notAccepting',
  inactive: 'compare.status.inactive',
  record_kind_unverified: 'compare.status.kindUnverified',
  status_unverified: 'compare.status.unverified',
};

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
  /** True while the owner identity isn't confirmed yet — fail-closed gate
   *  for the Tailor CTA (see ownerReady in use-favorites-data.ts).
   *  REQUIRED (no default) so a caller can never forget it and end up
   *  silently fail-OPEN — every call site must make an explicit,
   *  considered choice. */
  tailorDisabled: boolean;
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
  tailorDisabled,
  t,
}: OpportunityCardProps) {
  const recordKind = opportunityRecordKind(opp);
  const isFaculty = recordKind === 'faculty_contact';
  // Two different questions. `serverActionable` is what the corpus says about
  // a canonical record; `actionable` additionally lets a user's own custom
  // import keep today's behaviour, since we never claimed a truth for it.
  // Comparison uses the stricter one — see canSelect.
  const isCustom = !!opp._customId;
  const serverActionable = targetPosture(opp) === 'actionable';
  const actionable = isCustom || serverActionable;
  // A custom entry is the user's own note about their own target. No
  // collector ever saw it, so we neither vouch for it nor contradict it:
  // it keeps exactly today's rendering, and it never receives a server
  // status label — a "status unconfirmed" badge on something typed in by
  // hand is us reporting on our own silence as if it were a finding.
  const showsOfferTerms = isCustom
    || (recordKind === 'listing' && serverActionable);
  const isActionableFaculty = !isCustom && isFaculty && serverActionable;
  const statusReason = isCustom ? null : targetStatusReason(opp);
  const sourceUrl = opportunitySourceUrl(opp);
  const facultyUnavailable = isFaculty
    && opp.faculty_availability_status === 'not_accepting_undergraduates';
  // R70-E: switched from inline ternaries to the shared badge-utils
  // helpers so this card stays in sync with MatchCard. The inline paid
  // ternary that used to live here had the same R70-D bug — labelling
  // paid='unknown' (1262 records) as the misleading "Unpaid".
  // `facultySafeInternational` fails closed to "unknown" for any record whose
  // source type this build has not reviewed — a rule about what a COLLECTOR
  // scraped, and a good one. A custom entry was never scraped: the field is
  // what its owner typed, so routing it through that rule answered "not
  // disclosed" about something the student had just disclosed to themselves.
  const intlFriendly = isCustom
    ? opp.eligibility?.international_friendly
    : facultySafeInternational(opp);
  const intlBadge = showsOfferTerms && intlFriendly ? getIntlBadge(intlFriendly, t, opp.international_attribution) : null;
  const paidBadge = showsOfferTerms && opp.paid ? getPaidBadge(opp.paid, t, opp.paid_attribution) : null;
  // A faculty profile's description is profile text, already projected
  // server-side; a listing's is a pitch for something on offer. Both are
  // withheld once we can no longer vouch for the target.
  const desc = showsOfferTerms || isActionableFaculty
    ? (opp.description_clean || opp.description_raw || '')
    : '';
  // Comparing is a decision aid for targets you could still choose between, so
  // it uses the server's answer and NOT the custom-import escape: a record we
  // never verified must not reach an AI comparison just because the user typed
  // it in themselves.
  const canSelect = serverActionable && !isSelected && selectedSize < MAX_COMPARE;

  return (
    <div className="relative">
      <div
        className={`bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] overflow-hidden transition-all ${
          selectionMode
            ? isSelected
              ? 'ring-2 ring-indigo-500 shadow-[0_4px_20px_rgba(79,70,229,0.15)]'
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
                    className="hover:text-indigo-600 focus:outline-none focus-visible:underline decoration-indigo-500 underline-offset-4 transition-colors"
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
                {/* Same split as the detail header. A faculty row's location
                    is where the person works — identity. A listing's is where
                    the work would happen — a term of an offer, gone when the
                    offer is. `showsOfferTerms` already covers a custom entry,
                    which keeps the location its owner typed. */}
                {opp.location && (isFaculty || showsOfferTerms) && (
                  <span className="inline-flex items-center gap-1">
                    <MapPin className="w-3.5 h-3.5" />
                    {isFaculty
                      ? t('favorites.facultyAffiliationLocation', { location: opp.location })
                      : opp.location}
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
                  <Bookmark className="w-4.5 h-4.5 fill-indigo-500 text-indigo-500" />
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
            {isFaculty && !facultyUnavailable && opp.faculty_availability_status !== 'research_inactive' && (
              <Badge variant="orange">{t('card.facultyContactUnconfirmed')}</Badge>
            )}
            {isFaculty && opp.faculty_availability_status === 'not_accepting_undergraduates' && (
              <Badge variant="red">{t('card.facultyNotAcceptingUndergraduates')}</Badge>
            )}
            {isFaculty && opp.faculty_availability_status === 'research_inactive' && (
              <Badge variant="red">{t('card.facultyResearchInactive')}</Badge>
            )}
            {/* Why this one is no longer a target to act on. Skipped for the
                faculty stop, which the red badge above already states in the
                source's own words. */}
            {statusReason && !(statusReason === 'faculty_not_accepting' && facultyUnavailable) && (
              <Badge variant="red">{t(SAVED_STATUS_KEY[statusReason])}</Badge>
            )}
            {showsOfferTerms && opp.opportunity_type && (
              <Badge variant="indigo">{opp.opportunity_type}</Badge>
            )}
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
            {opp.source && !isCustom && <Badge variant="gray">{opp.source}</Badge>}
            {showsOfferTerms && (
              <DeadlineBadge
                deadline={opp.deadline}
                isEstimate={opp.deadline_is_estimate ?? undefined}
                t={t}
              />
            )}
          </div>

          {!selectionMode && (
            <div className="flex flex-wrap items-center gap-2">
              {/* A saved target can close after it was saved. The card stays —
                  that is the point of a shortlist — but drafting an email or
                  tailoring a résumé to it are actions the server now refuses,
                  so they leave the card entirely rather than turning grey. */}
              {hasProfile && !opp._customId && actionable && !facultyUnavailable && (
                <button
                  type="button"
                  onClick={() => { if (actionable) onOpenEmailModal(opp); }}
                  className="inline-flex items-center gap-2 px-5 py-2.5 text-[13px] font-semibold text-white bg-gradient-to-r from-indigo-600 to-indigo-500 rounded-xl hover:from-indigo-700 hover:to-indigo-600 shadow-sm hover:shadow transition-all duration-200"
                >
                  <Mail className="w-3.5 h-3.5" />
                  {t('card.draftEmail')}
                </button>
              )}
              {hasProfile && !opp._customId && actionable && onOpenTailorModal && (
                <button
                  type="button"
                  onClick={() => { if (actionable) onOpenTailorModal(opp); }}
                  disabled={tailorDisabled}
                  aria-busy={tailorDisabled}
                  className="inline-flex items-center gap-2 px-4 py-2 text-[13px] font-medium text-indigo-600 bg-indigo-50 rounded-xl hover:bg-indigo-100 disabled:opacity-50 disabled:cursor-wait transition-colors duration-200"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  {t('card.tailorResume')}
                </button>
              )}
              {sourceUrl && (
                <a
                  href={sourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 px-4 py-2 text-[13px] font-medium text-gray-600 bg-black/[0.04] rounded-xl hover:bg-black/[0.08] transition-colors duration-200"
                >
                  {isCustom ? <ExternalLink className="w-3.5 h-3.5" /> : <FileText className="w-3.5 h-3.5" />}
                  {/* "View Details" promises the current details of an
                      opening. For a target we can no longer vouch for, the
                      link goes to a source page and says so. A faculty page
                      is a faculty page whatever the posture. */}
                  {isCustom
                    ? t('favorites.openSource')
                    : isFaculty
                      ? t('card.viewFacultyPage')
                      : statusReason
                        ? t('favorites.viewSourceRecord')
                        : t('card.viewDetails')}
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
                      <span className="text-gray-500">
                        <span className="font-medium text-gray-700">
                          {isFaculty ? t('card.facultyMember') : 'PI:'}
                        </span>{' '}
                        {opp.pi_name}
                      </span>
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

                {showsOfferTerms && opp.eligibility?.skills_required && opp.eligibility.skills_required.length > 0 && (
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
          className={`absolute inset-0 rounded-2xl focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-600 ${
            opp._customId
              ? 'bg-gray-500/[0.05] cursor-not-allowed'
              : isSelected ? 'bg-indigo-500/[0.05]' : canSelect ? 'hover:bg-indigo-500/[0.03]' : 'cursor-not-allowed'
          }`}
        >
          <span className={`absolute top-4 right-4 w-7 h-7 rounded-full flex items-center justify-center transition-all ${
            isSelected
              ? 'bg-indigo-600 text-white'
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
