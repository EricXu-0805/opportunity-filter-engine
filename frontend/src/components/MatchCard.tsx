'use client';

import { useState } from 'react';
import {
  ChevronDown,
  ExternalLink,
  Mail,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  MapPin,
  Building2,
  Globe,
  DollarSign,
  Star,
  FileText,
  Clock,
  BookOpen,
  Loader2,
} from 'lucide-react';
import Badge from './Badge';
import ScoreBar from './ScoreBar';
import { getGapAnalysis } from '@/lib/api';
import type { GapAnalysis } from '@/lib/api';
import type { MatchResult, ProfileData } from '@/lib/types';
import type { InteractionType } from '@/lib/supabase';

interface MatchCardProps {
  match: MatchResult;
  profile?: ProfileData | null;
  onDraftEmail: (opportunityId: string) => void;
  isFavorited?: boolean;
  onToggleFavorite?: (opportunityId: string) => void;
  interaction?: InteractionType;
  onTrackInteraction?: (opportunityId: string, type: InteractionType) => void;
}

function getBucketLabel(bucket: string): { label: string; variant: 'green' | 'blue' | 'yellow' | 'gray' } {
  switch (bucket) {
    case 'high_priority':
      return { label: 'High Priority', variant: 'green' };
    case 'good_match':
      return { label: 'Good Match', variant: 'blue' };
    case 'reach':
      return { label: 'Reach', variant: 'yellow' };
    default:
      return { label: 'Low Fit', variant: 'gray' };
  }
}

function getIntlBadge(
  friendly: string,
): { label: string; variant: 'green' | 'red' | 'orange' } {
  if (friendly === 'yes') return { label: 'Intl OK', variant: 'green' };
  if (friendly === 'no') return { label: 'US Only', variant: 'red' };
  return { label: 'Verify', variant: 'orange' };
}

function getPaidBadge(
  paid: string,
): { label: string; variant: 'green' | 'blue' | 'gray' } {
  if (paid === 'stipend') return { label: 'Stipend', variant: 'blue' };
  if (paid === 'yes') return { label: 'Paid', variant: 'green' };
  return { label: 'Unpaid', variant: 'gray' };
}

const INTERACTION_LABELS: Record<InteractionType, { label: string; color: string }> = {
  applied: { label: 'Applied', color: 'bg-blue-50 text-blue-700 border-blue-200' },
  replied: { label: 'Got Reply', color: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  interviewing: { label: 'Interviewing', color: 'bg-violet-50 text-violet-700 border-violet-200' },
  rejected: { label: 'Rejected', color: 'bg-gray-100 text-gray-500 border-gray-200' },
  dismissed: { label: 'Not interested', color: 'bg-gray-100 text-gray-400 border-gray-200' },
};

const INTERACTION_OPTIONS: InteractionType[] = ['applied', 'replied', 'interviewing', 'rejected', 'dismissed'];

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

const URGENCY_BORDER: Record<string, string> = {
  urgent: 'before:absolute before:inset-y-0 before:left-0 before:w-1 before:bg-red-400 before:rounded-l-2xl',
  soon: 'before:absolute before:inset-y-0 before:left-0 before:w-1 before:bg-amber-400 before:rounded-l-2xl',
  passed: 'before:absolute before:inset-y-0 before:left-0 before:w-1 before:bg-gray-300 before:rounded-l-2xl',
};

export default function MatchCard({ match, profile, onDraftEmail, isFavorited, onToggleFavorite, interaction, onTrackInteraction }: MatchCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [gaps, setGaps] = useState<GapAnalysis | null>(null);
  const [gapLoading, setGapLoading] = useState(false);

  const { opportunity: opp } = match;
  const tier = getBucketLabel(match.bucket);
  const intl = getIntlBadge(opp.eligibility?.international_friendly ?? 'unknown');
  const paid = getPaidBadge(opp.paid);
  const urgency = getDeadlineUrgency(opp.deadline);
  const urgencyBorder = urgency ? URGENCY_BORDER[urgency] ?? '' : '';

  return (
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
                  className="hover:text-blue-600 focus:outline-none focus-visible:underline decoration-blue-500 underline-offset-4 transition-colors"
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
          {isNewPosting(opp) && <Badge variant="green" dot>New</Badge>}
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
          {opp.deadline && (() => {
            const dl = new Date(opp.deadline + 'T00:00:00');
            const now = new Date();
            const daysLeft = Math.ceil((dl.getTime() - now.getTime()) / 86400000);
            if (daysLeft < 0) return <Badge variant="red"><Clock className="w-3 h-3" />Deadline passed</Badge>;
            if (daysLeft <= 14) return <Badge variant="orange"><Clock className="w-3 h-3" />Due in {daysLeft}d</Badge>;
            return <Badge variant="gray"><Clock className="w-3 h-3" />{opp.deadline}</Badge>;
          })()}
        </div>

        {(opp.compensation_details || opp.duration || opp.application?.requires_resume === 'yes' || opp.application?.requires_recommendation === 'yes') && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-gray-400 mb-4">
            {opp.compensation_details && (
              <span className="inline-flex items-center gap-1">
                <DollarSign className="w-3 h-3 text-emerald-400" />
                {opp.compensation_details}
              </span>
            )}
            {opp.duration && (
              <span className="inline-flex items-center gap-1">
                <Clock className="w-3 h-3 text-blue-400" />
                {opp.duration}
              </span>
            )}
            {opp.application?.requires_resume === 'yes' && (
              <span className="inline-flex items-center gap-1">
                <FileText className="w-3 h-3 text-orange-400" />
                Resume required
              </span>
            )}
            {opp.application?.requires_recommendation === 'yes' && (
              <span className="inline-flex items-center gap-1">
                <Mail className="w-3 h-3 text-violet-400" />
                Rec. letter needed
              </span>
            )}
          </div>
        )}

        <div className="flex items-center gap-3 mb-4">
          <span className="text-xs font-medium text-gray-400 uppercase tracking-wider w-14 shrink-0">
            Match
          </span>
          <div className="flex-1">
            <ScoreBar score={match.final_score} size="md" />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {opp.application?.application_url ? (
            <a
              href={opp.application.application_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-5 py-2.5 text-[13px] font-semibold text-white bg-gradient-to-r from-emerald-600 to-emerald-500 rounded-xl hover:from-emerald-700 hover:to-emerald-600 shadow-sm hover:shadow transition-all duration-200"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              Apply Now
            </a>
          ) : null}
          <button
            type="button"
            onClick={() => onDraftEmail(opp.id)}
            className={`inline-flex items-center gap-2 px-4 py-2 text-[13px] font-semibold rounded-xl transition-all duration-200 ${
              opp.application?.application_url
                ? 'text-gray-600 bg-black/[0.04] hover:bg-black/[0.08]'
                : 'text-white bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600 shadow-sm hover:shadow px-5 py-2.5'
            }`}
          >
            <Mail className="w-3.5 h-3.5" />
            Draft Email
          </button>
          {opp.url && !opp.application?.application_url && (
            <a
              href={opp.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-4 py-2 text-[13px] font-medium text-gray-600 bg-black/[0.04] rounded-xl hover:bg-black/[0.08] transition-colors duration-200"
            >
              <FileText className="w-3.5 h-3.5" />
              View Details
            </a>
          )}
          {onTrackInteraction && (
            <div
              className="flex items-center gap-1 w-full sm:w-auto sm:ml-auto overflow-x-auto no-scrollbar -mx-1 px-1 sm:mx-0 sm:px-0"
              role="group"
              aria-label={`Track status for ${opp.title}`}
            >
              {INTERACTION_OPTIONS.map((type) => {
                const cfg = INTERACTION_LABELS[type];
                const isActive = interaction === type;
                return (
                  <button
                    key={type}
                    type="button"
                    aria-pressed={isActive}
                    onClick={(e) => { e.stopPropagation(); onTrackInteraction(opp.id, type); }}
                    className={`px-2.5 py-1 rounded-lg text-[11px] font-medium border whitespace-nowrap transition-all duration-200 shrink-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                      isActive ? cfg.color : 'bg-white border-gray-200 text-gray-400 hover:border-gray-300'
                    }`}
                  >
                    {cfg.label}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-black/[0.04]">
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="flex items-center justify-between w-full px-4 sm:px-6 py-3 text-[13px] font-medium text-gray-400 hover:text-gray-600 transition-colors duration-300"
        >
          <span>{expanded ? 'Hide details' : 'View details'}</span>
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
                <h4 className="text-xs font-semibold text-blue-600 uppercase tracking-widest mb-2.5">
                  Next steps
                </h4>
                <ul className="space-y-2">
                  {match.next_steps.map((n, i) => (
                    <li key={i} className="flex items-start gap-2.5 text-[13px] text-gray-600 leading-relaxed">
                      <ArrowRight className="w-4 h-4 text-blue-400 mt-0.5 shrink-0" />
                      <span>{n}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {opp.eligibility?.skills_required?.length > 0 && (
              <div className="pt-1">
                <h4 className="text-xs font-semibold text-indigo-600 uppercase tracking-widest mb-2">
                  Required skills
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
                      Recommended UIUC courses
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
  );
}
