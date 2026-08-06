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
import { getDeadlineUrgency, daysUntil } from '@/lib/match-utils';
import { RELEASE_SCOPE } from '@/lib/release-scope';
import ResponsivenessBadge from '@/components/ResponsivenessBadge';
import { DetailBadge } from './DetailBadge';
import { formatType } from './detail-utils';
import type { TFunc } from './types';

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
  onOpenEmailModal: () => void;
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
  const applyUrl = opp.application?.application_url || opp.url || opp.source_url;
  const urgency = getDeadlineUrgency(opp.deadline, undefined, opp.deadline_is_estimate);
  const days = daysUntil(opp.deadline);

  const deadlineBadge = useMemo(() => {
    if (!opp.deadline || days === null) return null;
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
  }, [opp.deadline, urgency, days]);

  return (
    <div className="p-5 sm:p-8">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-3">
            <DetailBadge tone="blue">{formatType(opp.opportunity_type)}</DetailBadge>
            {opp.paid === 'yes' && <DetailBadge tone="emerald" icon={<DollarSign className="w-3 h-3" />}>{t('badges.paid')}</DetailBadge>}
            {opp.paid === 'stipend' && <DetailBadge tone="emerald">{t('badges.stipend')}</DetailBadge>}
            {opp.paid === 'no' && <DetailBadge tone="gray">{t('badges.unpaid')}</DetailBadge>}
            {opp.on_campus && <DetailBadge tone="gray">{t('badges.onCampus')}</DetailBadge>}
            {opp.remote_option === 'yes' && <DetailBadge tone="gray">{t('badges.remoteOk')}</DetailBadge>}
            {opp.eligibility?.international_friendly === 'yes' && (
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
            {opp.location && (
              <span className="inline-flex items-center gap-1.5">
                <MapPin className="w-3.5 h-3.5" aria-hidden="true" />
                {opp.location}
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
        {profile && (
          <button
            type="button"
            onClick={onOpenEmailModal}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white border border-gray-200 text-gray-700 text-[14px] font-medium hover:bg-gray-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          >
            <Mail className="w-4 h-4" aria-hidden="true" />
            {t('detail.draftEmail')}
          </button>
        )}
        {profile && onOpenTailorModal && (
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
        {profile && onOpenRenovationModal && (
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
