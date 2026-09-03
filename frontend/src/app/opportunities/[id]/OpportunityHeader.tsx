'use client';

import { useMemo } from 'react';
import {
  AlertTriangle,
  Building2,
  Check,
  Clock,
  DollarSign,
  ExternalLink,
  FileText,
  Globe,
  Mail,
  MapPin,
  Share2,
  Sparkles,
  Star,
} from 'lucide-react';
import type { Opportunity, ProfileData } from '@/lib/types';
import {
  facultySafeInternational,
  getDeadlineUrgency,
  daysUntil,
  opportunityRecordKind,
} from '@/lib/match-utils';
import {
  opportunityApplicationUrl,
  opportunitySourceUrl,
  targetPosture,
  targetStatusReason,
  type TargetStatusReason,
} from '@/lib/target-truth';
import { RELEASE_SCOPE } from '@/lib/release-scope';
import ResponsivenessBadge from '@/components/ResponsivenessBadge';
import { DetailBadge } from './DetailBadge';
import { typeLabel } from '@/app/results/types';
import type { TFunc } from './types';

/**
 * One sentence per reason, complete over the contract.
 *
 * The chain this replaces ended in `closedBanner` for anything it did not
 * recognise, so `record_kind_unverified` — a record nobody has reviewed —
 * told the student an application window had shut. Nobody said that. A map
 * keyed by the reason type is exhaustive by construction: a new reason in
 * target-truth.ts stops this file compiling instead of silently landing on
 * "closed" again.
 */
const STATUS_BANNER_KEY: Record<TargetStatusReason, string> = {
  listing_closed: 'detail.closedBanner',
  reference_only: 'detail.referenceBanner',
  faculty_not_accepting: 'detail.notAcceptingBanner',
  inactive: 'detail.inactiveBanner',
  record_kind_unverified: 'detail.kindUnverifiedBanner',
  status_unverified: 'detail.unverifiedBanner',
};

export function OpportunityHeader({
  opp,
  profile,
  isFavorited,
  favoriteDisabled,
  favoriteBusy,
  shareCopied,
  onStar,
  onOpenEmailModal,
  onOpenTailorModal,
  tailorDisabled,
  onOpenRenovationModal,
  onShare,
  t,
}: {
  opp: Opportunity;
  profile: ProfileData | null;
  isFavorited: boolean;
  /**
   * True whenever the star control must not be clicked: hydration/save in
   * flight, OR a hydration failure (isFavorited is a fabricated default
   * then, not a fact — Retry is the only recovery path).
   */
  favoriteDisabled: boolean;
  /** True only while hydration/save is actually in flight — an error is not "busy". */
  favoriteBusy: boolean;
  shareCopied: boolean;
  onStar: () => void;
  // Optional for the same reason onOpenTailorModal is: withholding the opener
  // is how the control leaves the accessibility tree rather than merely going
  // grey. Absent = this target has no draft-email action.
  onOpenEmailModal?: () => void;
  /**
   * Optional — when omitted the "Tailor Resume" CTA is hidden. R71 PR-3
   * passes it from `OpportunityDetail`; leaving it optional keeps the
   * existing call sites (none today, but a defensive API surface) from
   * breaking when this header is reused.
   */
  onOpenTailorModal?: () => void;
  /** True while the owner identity for this target isn't confirmed yet —
   *  fail-closed gate for the Tailor CTA (see ownerReady in
   *  use-opportunity-detail.ts): opening it before an owner is known would
   *  let Generate/Extract capture an unprimed token, and the draft would
   *  have no safe scope to persist under. REQUIRED (no default) so a
   *  caller can never forget it and end up silently fail-OPEN — every
   *  call site must make an explicit, considered choice. */
  tailorDisabled: boolean;
  /** Optional — when omitted the "Renovate Resume" CTA is hidden. */
  onOpenRenovationModal?: () => void;
  onShare: () => void;
  t: TFunc;
}) {
  // The shared allowlist, not a raw string compare. `source_type` is scraped
  // metadata; the allowlist is what this build has actually reviewed, and the
  // rest of the product decides kind through it.
  const recordKind = opportunityRecordKind(opp);
  const isFaculty = recordKind === 'faculty_contact';
  const facultyUnavailable = isFaculty
    && opp.faculty_availability_status === 'not_accepting_undergraduates';
  // Apply and "read the source" are different links now. The old resolver fell
  // back from application_url through url/source_url, so a closed listing's
  // reference page was rendered under an Apply label.
  const posture = targetPosture(opp);
  // Both halves. `!isFaculty` treated a closed listing and an unreviewed row
  // as things with terms — a pay badge, an audience badge, a countdown — and
  // the header is the largest surface those claims appear on.
  const isCurrentListing = recordKind === 'listing' && posture === 'actionable';
  const statusReason = targetStatusReason(opp);
  const applyUrl = opportunityApplicationUrl(opp);
  const sourceUrl = opportunitySourceUrl(opp);
  const effectiveIntl = facultySafeInternational(opp);
  const urgency = getDeadlineUrgency(
    opp.deadline,
    undefined,
    opp.deadline_is_estimate ?? undefined,
  );
  const days = daysUntil(opp.deadline);

  const deadlineBadge = useMemo(() => {
    if (!isCurrentListing || !opp.deadline || days === null) return null;
    if (urgency === 'passed') {
      return <DetailBadge tone="gray" icon={<AlertTriangle className="w-3 h-3" />}>{t('badges.pastDeadline')}</DetailBadge>;
    }
    if (urgency === 'urgent') {
      return <DetailBadge tone="red" icon={<Clock className="w-3 h-3" />}>{days === 1 ? t('deadline.urgentSingle') : t('deadline.urgent', { days })}</DetailBadge>;
    }
    if (urgency === 'soon') {
      return <DetailBadge tone="amber" icon={<Clock className="w-3 h-3" />}>{t('deadline.soon', { days })}</DetailBadge>;
    }
    return null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isCurrentListing, opp.deadline, urgency, days]);

  return (
    <div className="p-5 sm:p-8">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-3">
            {/* The record's own claim about what it is, published only where
                it still describes something on offer. */}
            {isCurrentListing && (
              <DetailBadge tone="blue">{typeLabel(opp.opportunity_type, t)}</DetailBadge>
            )}
            {isFaculty && !facultyUnavailable && opp.faculty_availability_status !== 'research_inactive' && (
              <DetailBadge tone="amber">{t('card.facultyContactUnconfirmed')}</DetailBadge>
            )}
            {isFaculty && opp.faculty_availability_status === 'not_accepting_undergraduates' && (
              <DetailBadge tone="red">{t('card.facultyNotAcceptingUndergraduates')}</DetailBadge>
            )}
            {isFaculty && opp.faculty_availability_status === 'research_inactive' && (
              <DetailBadge tone="red">{t('card.facultyResearchInactive')}</DetailBadge>
            )}
            {/* A green "Paid" is a student planning a summer around the money.
                220 records carry a pay value read off page prose — one says
                only "in many cases, funding or a stipend" — so those say what
                we actually saw. NSF Sites keep the plain badge: the
                solicitation requires a stipend. */}
            {isCurrentListing && opp.paid === 'yes' && (
              opp.paid_attribution === 'inferred'
                ? <DetailBadge tone="gray" icon={<DollarSign className="w-3 h-3" />}>{t('badges.fundingMentioned')}</DetailBadge>
                : <DetailBadge tone="emerald" icon={<DollarSign className="w-3 h-3" />}>{t('badges.paid')}</DetailBadge>
            )}
            {isCurrentListing && opp.paid === 'stipend' && <DetailBadge tone="emerald">{t('badges.stipend')}</DetailBadge>}
            {isCurrentListing && opp.paid === 'no' && <DetailBadge tone="gray">{t('badges.unpaid')}</DetailBadge>}
            {isCurrentListing && opp.on_campus && <DetailBadge tone="gray">{t('badges.onCampus')}</DetailBadge>}
            {isCurrentListing && opp.remote_option === 'yes' && <DetailBadge tone="gray">{t('badges.remoteOk')}</DetailBadge>}
            {isCurrentListing && effectiveIntl === 'yes' && (
              <DetailBadge tone="indigo" icon={<Globe className="w-3 h-3" />}>{t('badges.internationalFriendly')}</DetailBadge>
            )}
            {deadlineBadge}
            {RELEASE_SCOPE.professorSignals && (
              <ResponsivenessBadge opportunityId={opp.id} size="detail" />
            )}
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 leading-tight tracking-tight">
            {opp.title}
          </h1>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-3 text-[13px] sm:text-sm text-gray-500">
            {opp.organization && (
              <span className="inline-flex items-center gap-1.5">
                <Building2 className="w-3.5 h-3.5" aria-hidden="true" />
                {opp.organization}
              </span>
            )}
            {opp.department && <span>· {opp.department}</span>}
            {/* Two different facts wearing one pin. A faculty row's location
                is where the person works — identity, true whether or not
                they are taking students. A listing's location is where the
                work would happen, which is a term of an offer, so it goes
                when the offer does. */}
            {opp.location && (isFaculty || isCurrentListing) && (
              <span className="inline-flex items-center gap-1.5">
                <MapPin className="w-3.5 h-3.5" aria-hidden="true" />
                {isFaculty
                  ? t('detail.fields.facultyAffiliationLocation', { location: opp.location })
                  : opp.location}
              </span>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={onStar}
          disabled={favoriteDisabled}
          aria-busy={favoriteBusy}
          className="shrink-0 p-2 -mr-2 rounded-xl hover:bg-amber-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 disabled:cursor-wait disabled:opacity-60"
          aria-label={isFavorited ? t('detail.favoriteRemove') : t('detail.favoriteAdd')}
          aria-pressed={isFavorited}
        >
          <Star className={`w-6 h-6 ${isFavorited ? 'fill-amber-400 text-amber-400' : 'text-gray-300'}`} />
        </button>
      </div>

      {/* `targetStatusReason` returns null exactly when the target is
          actionable, and it reads the truth through the same parser every
          other surface uses — so a payload this build cannot read lands on
          "we could not confirm" rather than on the raw `reason_code` field,
          which the old chain read straight off the wire. */}
      {statusReason && (
        <div
          role="status"
          className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-[13px] text-amber-900"
        >
          {t(STATUS_BANNER_KEY[statusReason])}
        </div>
      )}

      <div className="flex flex-wrap gap-2 mt-4">
        {applyUrl && (
          <a
            href={applyUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-indigo-600 text-white text-[14px] font-semibold hover:bg-indigo-700 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          >
            <ExternalLink className="w-4 h-4" aria-hidden="true" />
            {t('detail.apply')}
          </a>
        )}
        {/* Reading the source is always allowed — that is what "kept as a
            reference" means. Rendered as a secondary control so it can never
            be mistaken for the Apply action it replaces. */}
        {!applyUrl && sourceUrl && (
          <a
            href={sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white border border-gray-200 text-gray-700 text-[14px] font-medium hover:bg-gray-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          >
            <ExternalLink className="w-4 h-4" aria-hidden="true" />
            {t(isFaculty ? 'detail.viewFacultyProfile' : 'detail.viewSource')}
          </a>
        )}
        {profile && onOpenEmailModal && posture === 'actionable' && !facultyUnavailable && (
          <button
            type="button"
            onClick={onOpenEmailModal}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white border border-gray-200 text-gray-700 text-[14px] font-medium hover:bg-gray-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          >
            <Mail className="w-4 h-4" aria-hidden="true" />
            {t('detail.draftEmail')}
          </button>
        )}
        {/* Same gate as Draft Email. Both post to /api/tailor, which refuses a
            non-actionable target with a 409 — so without this the page offers
            two buttons whose only possible outcome is an error. */}
        {profile && onOpenTailorModal && posture === 'actionable' && (
          <button
            type="button"
            onClick={onOpenTailorModal}
            disabled={tailorDisabled}
            aria-busy={tailorDisabled}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-indigo-50 text-indigo-700 text-[14px] font-medium hover:bg-indigo-100 disabled:opacity-50 disabled:cursor-wait transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          >
            <Sparkles className="w-4 h-4" aria-hidden="true" />
            {t('card.tailorResume')}
          </button>
        )}
        {profile && onOpenRenovationModal && posture === 'actionable' && (
          <button
            type="button"
            onClick={onOpenRenovationModal}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-fuchsia-50 text-fuchsia-700 text-[14px] font-medium hover:bg-fuchsia-100 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-fuchsia-500"
          >
            <FileText className="w-4 h-4" aria-hidden="true" />
            {t('card.renovateResume')}
          </button>
        )}
        <button
          type="button"
          onClick={onShare}
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white border border-gray-200 text-gray-700 text-[14px] font-medium hover:bg-gray-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
        >
          {shareCopied ? <Check className="w-4 h-4 text-emerald-500" aria-hidden="true" /> : <Share2 className="w-4 h-4" aria-hidden="true" />}
          {shareCopied ? t('detail.shareCopied') : t('detail.share')}
        </button>
      </div>
    </div>
  );
}
