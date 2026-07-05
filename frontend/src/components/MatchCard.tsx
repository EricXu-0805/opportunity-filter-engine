'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';
import {
  ChevronDown,
  ExternalLink,
  Mail,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  MapPin,
  Building2,
  BellRing,
  Globe,
  DollarSign,
  Star,
  FileText,
  Clock,
  BookOpen,
  Loader2,
  Sparkles,
  ThumbsUp,
  ThumbsDown,
} from 'lucide-react';
import Badge from './Badge';
import ScoreBar from './ScoreBar';
import { InteractionStatusMenu } from './InteractionStatusMenu';
import { getGapAnalysis } from '@/lib/api';
import type { GapAnalysis } from '@/lib/api';
import type { MatchResult, ProfileData } from '@/lib/types';
import type { InteractionType } from '@/lib/supabase';
import type { MatchVerdict, MatchFeedbackContext } from '@/lib/match-feedback';
import { useT } from '@/i18n/client';
import { getIntlBadge, getPaidBadge } from '@/lib/badge-utils';
import { homeSchoolOf, scopeChipFor, type ScopeChip } from '@/lib/discovery-scope';
import { cleanCompensation } from '@/app/opportunities/[id]/detail-utils';

// R71 PR-2: client-only modal (matches ColdEmailModal SSR-disabled pattern
// to keep this card a server-cheap leaf until the user opens the panel).
const TailorModal = dynamic(() => import('./TailorModal'), { ssr: false });

export interface MatchCardProps {
  match: MatchResult;
  profile?: ProfileData | null;
  onDraftEmail: (opportunityId: string) => void;
  isFavorited?: boolean;
  onToggleFavorite?: (opportunityId: string) => void;
  interaction?: InteractionType;
  onTrackInteraction?: (opportunityId: string, type: InteractionType) => void;
  isNew?: boolean;
  feedbackVerdict?: MatchVerdict | null;
  onFeedback?: (opportunityId: string, verdict: MatchVerdict | null, context: MatchFeedbackContext) => void;
  // 1-based rank in the full results list — persisted with each vote so the
  // offline feedback analysis can measure position bias.
  position?: number;
}

function getBucketLabel(
  bucket: string,
  t: (key: string) => string,
): { label: string; variant: 'green' | 'blue' | 'yellow' | 'gray' } {
  switch (bucket) {
    case 'high_priority':
      return { label: t('results.tabs.highPriority'), variant: 'green' };
    case 'good_match':
      return { label: t('results.tabs.goodMatch'), variant: 'blue' };
    case 'reach':
      return { label: t('results.tabs.reach'), variant: 'yellow' };
    default:
      return { label: t('results.tabs.lowFit'), variant: 'gray' };
  }
}

// R70-E: getIntlBadge + getPaidBadge moved to `lib/badge-utils.ts` so
// `OpportunityCard.tsx` can reuse the same logic (it previously duplicated
// the ternary inline, complete with the R70-D paid='unknown' mislabel).

// R69-C: the inline INTERACTION_COLORS map and INTERACTION_OPTIONS list moved
// into ./InteractionStatusMenu.tsx together with the disclosure UI they fed
// into. MatchCard now delegates the entire status-tracker surface to that
// menu component (single trigger + 5 menuitem options + Clear), which
// collapses ~5 status pills × 608 cards = ~3000 inline buttons in the worst
// case down to one trigger per card.

function isNewPosting(opp: MatchResult['opportunity']): boolean {
  const posted = opp.posted_date;
  if (!posted) return false;
  const diff = Date.now() - new Date(posted).getTime();
  return diff < 14 * 86400000;
}

function getDeadlineUrgency(deadline: string | undefined): 'passed' | 'urgent' | 'soon' | 'later' | null {
  if (!deadline) return null;
  const dl = new Date(deadline + 'T00:00:00');
  if (isNaN(dl.getTime())) return null;
  const days = Math.ceil((dl.getTime() - Date.now()) / 86400000);
  if (days < 0) return 'passed';
  if (days <= 7) return 'urgent';
  if (days <= 30) return 'soon';
  return 'later';
}

function scopeChipText(chip: ScopeChip, t: (key: string, vars?: Record<string, string | number>) => string): string {
  if (chip.kind === 'foreignCampus') return t('card.scope.campusOnly', { host: chip.host! });
  if (chip.kind === 'unknown') {
    return chip.host ? t('card.scope.unknownWithHost', { host: chip.host }) : t('card.scope.unknown');
  }
  return chip.host ? t('card.scope.openWithHost', { host: chip.host }) : t('card.scope.open');
}

const URGENCY_BORDER: Record<string, string> = {
  urgent: 'before:absolute before:inset-y-0 before:left-0 before:w-1 before:bg-red-400 before:rounded-l-2xl',
  soon: 'before:absolute before:inset-y-0 before:left-0 before:w-1 before:bg-amber-400 before:rounded-l-2xl',
  passed: 'before:absolute before:inset-y-0 before:left-0 before:w-1 before:bg-gray-300 before:rounded-l-2xl',
};

export default function MatchCard({ match, profile, onDraftEmail, isFavorited, onToggleFavorite, interaction, onTrackInteraction, isNew, feedbackVerdict, onFeedback, position }: MatchCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [gaps, setGaps] = useState<GapAnalysis | null>(null);
  const [gapLoading, setGapLoading] = useState(false);
  // R71 PR-2: local tailor-modal state — parent doesn't need to know.
  // We only mount the heavy modal once the user clicks the CTA, and
  // the button itself only renders when a profile exists (the route
  // would still work without one, but the tailor UX without a profile
  // is empty).
  const [tailorOpen, setTailorOpen] = useState(false);
  const { t } = useT();

  const { opportunity: opp } = match;
  const compensation = cleanCompensation(opp.compensation_details);
  const tier = getBucketLabel(match.bucket, t);
  const intl = getIntlBadge(opp.eligibility?.international_friendly ?? 'unknown', t);
  const paid = getPaidBadge(opp.paid, t);
  // Home-campus records get no chip (the majority — avoid noise); only
  // open/unknown/foreign-campus records carry the host+audience chip.
  const scopeChip = scopeChipFor(opp, homeSchoolOf(profile ?? null));
  const urgency = getDeadlineUrgency(opp.deadline);
  const urgencyBorder = urgency ? URGENCY_BORDER[urgency] ?? '' : '';

  // Faculty "Research with Prof. X" records set application_url to the
  // professor's directory page (not an application form), and you actually
  // apply by emailing the PI. So for them the honest primary CTA is "Email
  // Professor", with the directory link demoted to a secondary "Faculty Page"
  // — never "Apply Now", which dead-ends on a bio page.
  const isFaculty = opp.source_type === 'faculty_research';
  const applyUrl = opp.application?.application_url;
  const facultyPageUrl = applyUrl || opp.url;
  const showApplyNow = !!applyUrl && !isFaculty;
  const emailIsPrimary = isFaculty || !showApplyNow;

  return (
    <>
    <div className={`relative bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] hover:shadow-[0_4px_20px_rgba(0,0,0,0.08)] transition-shadow duration-300 overflow-hidden ${urgencyBorder}`}>
      <div className="p-4 sm:p-6">
          <div className="flex items-start justify-between gap-4 mb-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-start gap-2">
              {onToggleFavorite && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); onToggleFavorite(opp.id); }}
                  className="mt-0.5 shrink-0 p-1 -ml-1 rounded-lg hover:bg-amber-50 transition-colors duration-200"
                  aria-label={isFavorited ? 'Remove from favorites' : 'Add to favorites'}
                >
                  <Star className={`w-4 h-4 transition-colors duration-200 ${isFavorited ? 'fill-amber-400 text-amber-400' : 'text-gray-300 hover:text-amber-300'}`} />
                </button>
              )}
              <h3 className="text-[17px] font-semibold text-gray-900 leading-snug line-clamp-2">
                <a
                  href={`/opportunities/${encodeURIComponent(opp.id)}`}
                  onClick={e => e.stopPropagation()}
                  className="hover:text-indigo-600 focus:outline-none focus-visible:underline decoration-indigo-500 underline-offset-4 transition-colors"
                >
                  {opp.title}
                </a>
              </h3>
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-[12px] sm:text-[13px] text-gray-400">
              {opp.organization && (
                <span className="inline-flex items-center gap-1 min-w-0">
                  <Building2 className="w-3.5 h-3.5 shrink-0" />
                  <span className="truncate max-w-[180px] sm:max-w-none">{opp.organization}</span>
                </span>
              )}
              {opp.location && (
                <span className="inline-flex items-center gap-1 min-w-0">
                  <MapPin className="w-3.5 h-3.5 shrink-0" />
                  <span className="truncate max-w-[160px] sm:max-w-none">{opp.location}</span>
                </span>
              )}
            </div>
          </div>
          <Badge variant={tier.variant} dot>
            {tier.label}
          </Badge>
        </div>

        <div className="flex flex-wrap items-center gap-1.5 mb-5">
          {isNew && (
            <Badge variant="orange" dot>
              <BellRing className="w-3 h-3" />
              {t('results.newMatchBadge')}
            </Badge>
          )}
          {isNewPosting(opp) && <Badge variant="green" dot>{t('badges.new')}</Badge>}
          <Badge variant="indigo">{opp.opportunity_type}</Badge>
          <Badge variant={intl.variant} dot>
            <Globe className="w-3 h-3" />
            {intl.label}
          </Badge>
          <Badge variant={paid.variant} dot>
            <DollarSign className="w-3 h-3" />
            {paid.label}
          </Badge>
          {opp.source && <Badge variant="gray">{opp.source}</Badge>}
          {scopeChip && (
            <Badge variant={scopeChip.kind === 'open' ? 'green' : 'gray'} dot>
              {scopeChipText(scopeChip, t)}
            </Badge>
          )}
          {opp.deadline && (() => {
            const dl = new Date(opp.deadline + 'T00:00:00');
            const now = new Date();
            const daysLeft = Math.ceil((dl.getTime() - now.getTime()) / 86400000);
            if (daysLeft < 0) return <Badge variant="red"><Clock className="w-3 h-3" />{t('badges.deadlinePassed')}</Badge>;
            if (daysLeft <= 14) return <Badge variant="orange"><Clock className="w-3 h-3" />{t('badges.dueInDays', { count: daysLeft })}</Badge>;
            return <Badge variant="gray"><Clock className="w-3 h-3" />{opp.deadline}</Badge>;
          })()}
        </div>

        {(compensation || opp.duration || opp.application?.requires_resume === 'yes' || opp.application?.requires_recommendation === 'yes') && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-gray-400 mb-4">
            {compensation && (
              <span className="inline-flex items-center gap-1">
                <DollarSign className="w-3 h-3 text-emerald-400" />
                {compensation}
              </span>
            )}
            {opp.duration && (
              <span className="inline-flex items-center gap-1">
                <Clock className="w-3 h-3 text-indigo-400" />
                {opp.duration}
              </span>
            )}
            {opp.application?.requires_resume === 'yes' && (
              <span className="inline-flex items-center gap-1">
                <FileText className="w-3 h-3 text-orange-400" />
                {t('card.resumeRequired')}
              </span>
            )}
            {opp.application?.requires_recommendation === 'yes' && (
              <span className="inline-flex items-center gap-1">
                <Mail className="w-3 h-3 text-violet-400" />
                {t('card.recLetterNeeded')}
              </span>
            )}
          </div>
        )}

        <div className="flex items-center gap-3 mb-4">
          <span className="text-xs font-medium text-gray-400 uppercase tracking-wider w-14 shrink-0">
            Match
          </span>
          <div className="flex-1">
            <ScoreBar score={match.final_score} size="md" bucket={match.bucket} />
          </div>
          {onFeedback && (
            <div className="flex items-center gap-0.5 shrink-0">
              <span className="hidden sm:inline text-[11px] text-gray-400 mr-1">
                {t('card.feedback.prompt')}
              </span>
              <button
                type="button"
                onClick={() => onFeedback(opp.id, feedbackVerdict === 'up' ? null : 'up', { bucket: match.bucket, finalScore: match.final_score, position })}
                aria-label={t('card.feedback.up')}
                aria-pressed={feedbackVerdict === 'up'}
                className={`p-1 rounded-lg transition-colors duration-200 ${feedbackVerdict === 'up' ? 'text-emerald-500 bg-emerald-50' : 'text-gray-300 hover:text-emerald-400 hover:bg-emerald-50'}`}
              >
                <ThumbsUp className={`w-3.5 h-3.5 ${feedbackVerdict === 'up' ? 'fill-emerald-200' : ''}`} />
              </button>
              <button
                type="button"
                onClick={() => onFeedback(opp.id, feedbackVerdict === 'down' ? null : 'down', { bucket: match.bucket, finalScore: match.final_score, position })}
                aria-label={t('card.feedback.down')}
                aria-pressed={feedbackVerdict === 'down'}
                className={`p-1 rounded-lg transition-colors duration-200 ${feedbackVerdict === 'down' ? 'text-red-500 bg-red-50' : 'text-gray-300 hover:text-red-400 hover:bg-red-50'}`}
              >
                <ThumbsDown className={`w-3.5 h-3.5 ${feedbackVerdict === 'down' ? 'fill-red-200' : ''}`} />
              </button>
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {showApplyNow ? (
            <a
              href={applyUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-5 py-2.5 text-[13px] font-semibold text-white bg-gradient-to-r from-emerald-600 to-emerald-500 rounded-xl hover:from-emerald-700 hover:to-emerald-600 shadow-sm hover:shadow transition-all duration-200"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              {t('card.applyNow')}
            </a>
          ) : null}
          <button
            type="button"
            onClick={() => onDraftEmail(opp.id)}
            className={`inline-flex items-center gap-2 px-4 py-2 text-[13px] font-semibold rounded-xl transition-all duration-200 ${
              emailIsPrimary
                ? 'text-white bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-700 hover:to-indigo-600 shadow-sm hover:shadow px-5 py-2.5'
                : 'text-gray-600 bg-black/[0.04] hover:bg-black/[0.08]'
            }`}
          >
            <Mail className="w-3.5 h-3.5" />
            {isFaculty ? t('card.emailProfessor') : t('card.draftEmail')}
          </button>
          {profile && (
            <button
              type="button"
              onClick={() => setTailorOpen(true)}
              className="inline-flex items-center gap-2 px-4 py-2 text-[13px] font-medium text-indigo-600 bg-indigo-50 rounded-xl hover:bg-indigo-100 transition-colors duration-200"
            >
              <Sparkles className="w-3.5 h-3.5" />
              {t('card.tailorResume')}
            </button>
          )}
          {/* Faculty: the directory page is a secondary "Faculty Page", not the
              primary CTA. Non-faculty with no apply portal: source "Details". */}
          {isFaculty && facultyPageUrl ? (
            <a
              href={facultyPageUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-4 py-2 text-[13px] font-medium text-gray-600 bg-black/[0.04] rounded-xl hover:bg-black/[0.08] transition-colors duration-200"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              {t('card.viewFacultyPage')}
            </a>
          ) : opp.url && !applyUrl ? (
            <a
              href={opp.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-4 py-2 text-[13px] font-medium text-gray-600 bg-black/[0.04] rounded-xl hover:bg-black/[0.08] transition-colors duration-200"
            >
              <FileText className="w-3.5 h-3.5" />
              {t('card.viewDetails')}
            </a>
          ) : null}
          {onTrackInteraction && (
            <InteractionStatusMenu
              opportunityId={opp.id}
              opportunityTitle={opp.title}
              interaction={interaction}
              onTrackInteraction={onTrackInteraction}
            />
          )}
        </div>
      </div>

      <div className="border-t border-black/[0.04]">
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="flex items-center justify-between w-full px-4 sm:px-6 py-3 text-[13px] font-medium text-gray-400 hover:text-gray-600 transition-colors duration-300"
        >
          <span>{expanded ? t('card.hideDetails') : t('card.showDetails')}</span>
          <ChevronDown
            className={`w-4 h-4 transition-transform duration-300 ${expanded ? 'rotate-180' : ''}`}
          />
        </button>

        {expanded && (
          <div className="px-4 sm:px-6 pb-5 sm:pb-6 space-y-5 animate-in">
            {match.reasons_fit.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-emerald-600 uppercase tracking-widest mb-2.5">
                  Why it fits
                </h4>
                <ul className="space-y-2">
                  {match.reasons_fit.map((s, i) => (
                    <li key={i} className="flex items-start gap-2.5 text-[13px] text-gray-600 leading-relaxed">
                      <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
                      <span>{s}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {match.reasons_gap.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-amber-600 uppercase tracking-widest mb-2.5">
                  Potential concerns
                </h4>
                <ul className="space-y-2">
                  {match.reasons_gap.map((c, i) => (
                    <li key={i} className="flex items-start gap-2.5 text-[13px] text-gray-600 leading-relaxed">
                      <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" />
                      <span>{c}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {match.next_steps.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-indigo-600 uppercase tracking-widest mb-2.5">
                  Next steps
                </h4>
                <ul className="space-y-2">
                  {match.next_steps.map((n, i) => (
                    <li key={i} className="flex items-start gap-2.5 text-[13px] text-gray-600 leading-relaxed">
                      <ArrowRight className="w-4 h-4 text-indigo-400 mt-0.5 shrink-0" />
                      <span>{n}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {opp.eligibility?.skills_required?.length > 0 && (
              <div className="pt-1">
                <h4 className="text-xs font-semibold text-indigo-600 uppercase tracking-widest mb-2">
                  {t('favorites.requiredSkills')}
                </h4>
                <div className="flex flex-wrap gap-1.5">
                  {opp.eligibility?.skills_required?.map((skill) => (
                    <span key={skill} className="px-2.5 py-1 rounded-lg bg-indigo-50 text-indigo-700 text-[12px] font-medium">
                      {skill}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {profile && !gaps && (
              <button
                type="button"
                disabled={gapLoading}
                onClick={async () => {
                  setGapLoading(true);
                  try {
                    const data = await getGapAnalysis(profile, opp.id);
                    setGaps(data);
                  } catch { /* best effort */ }
                  finally { setGapLoading(false); }
                }}
                className="inline-flex items-center gap-2 px-4 py-2 text-[12px] font-medium text-teal-700 bg-teal-50 rounded-xl hover:bg-teal-100 transition-colors"
              >
                {gapLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <BookOpen className="w-3.5 h-3.5" />}
                {gapLoading ? 'Analyzing...' : 'Show preparation plan'}
              </button>
            )}

            {gaps && (
              <div className="space-y-4 pt-1">
                {gaps.missing_skills.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-red-500 uppercase tracking-widest mb-2">
                      Skills to learn
                    </h4>
                    <div className="flex flex-wrap gap-1.5">
                      {gaps.missing_skills.map((s) => (
                        <span key={s} className="px-2.5 py-1 rounded-lg bg-red-50 text-red-600 text-[12px] font-medium">{s}</span>
                      ))}
                    </div>
                  </div>
                )}

                {gaps.suggested_coursework.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-teal-600 uppercase tracking-widest mb-2">
                      Recommended courses
                    </h4>
                    <div className="flex flex-wrap gap-1.5">
                      {gaps.suggested_coursework.map((c) => (
                        <span key={c} className="px-2.5 py-1 rounded-lg bg-teal-50 text-teal-700 text-[12px] font-medium">{c}</span>
                      ))}
                    </div>
                  </div>
                )}

                {gaps.preparation_timeline.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-violet-600 uppercase tracking-widest mb-2">
                      Preparation timeline
                    </h4>
                    <div className="space-y-1.5">
                      {gaps.preparation_timeline.map((item) => (
                        <div key={item.skill} className="flex items-center gap-3 text-[13px]">
                          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${item.priority === 'high' ? 'bg-red-400' : 'bg-amber-400'}`} />
                          <span className="font-medium text-gray-700">{item.skill}</span>
                          <span className="text-gray-400">—</span>
                          <span className="text-gray-500">{item.estimated_time}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {gaps.resume_tips.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-orange-600 uppercase tracking-widest mb-2">
                      Resume tips
                    </h4>
                    <ul className="space-y-1.5">
                      {gaps.resume_tips.map((tip, i) => (
                        <li key={i} className="text-[13px] text-gray-600 leading-relaxed pl-4 relative before:content-['•'] before:absolute before:left-0 before:text-orange-400">
                          {tip}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {gaps.missing_skills.length === 0 && gaps.suggested_coursework.length === 0 && (
                  <p className="text-[13px] text-emerald-600 flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4" />
                    Your profile already covers the requirements for this position.
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
    {profile && (
      <TailorModal
        isOpen={tailorOpen}
        onClose={() => setTailorOpen(false)}
        profile={profile}
        opportunityId={opp.id}
        opportunityTitle={opp.title}
      />
    )}
    </>
  );
}
