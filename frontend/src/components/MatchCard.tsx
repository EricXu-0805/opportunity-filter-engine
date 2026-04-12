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
} from 'lucide-react';
import Badge from './Badge';
import ScoreBar from './ScoreBar';
import type { MatchResult } from '@/lib/types';

interface MatchCardProps {
  match: MatchResult;
  onDraftEmail: (opportunityId: string) => void;
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

export default function MatchCard({ match, onDraftEmail }: MatchCardProps) {
  const [expanded, setExpanded] = useState(false);

  const { opportunity: opp } = match;
  const tier = getBucketLabel(match.bucket);
  const intl = getIntlBadge(opp.eligibility.international_friendly);
  const paid = getPaidBadge(opp.paid);

  return (
    <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] hover:shadow-[0_4px_20px_rgba(0,0,0,0.08)] transition-shadow duration-300 overflow-hidden">
      <div className="p-6">
        <div className="flex items-start justify-between gap-4 mb-3">
          <div className="flex-1 min-w-0">
            <h3 className="text-[17px] font-semibold text-gray-900 leading-snug line-clamp-2">
              {opp.title}
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
          <Badge variant={tier.variant} dot>
            {tier.label}
          </Badge>
        </div>

        <div className="flex flex-wrap items-center gap-1.5 mb-5">
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
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs font-medium text-gray-400 uppercase tracking-wider w-14 shrink-0">
            Match
          </span>
          <div className="flex-1">
            <ScoreBar score={match.final_score} size="md" />
          </div>
        </div>
      </div>

      <div className="border-t border-black/[0.04]">
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="flex items-center justify-between w-full px-6 py-3 text-[13px] font-medium text-gray-400 hover:text-gray-600 transition-colors duration-300"
        >
          <span>{expanded ? 'Hide details' : 'View details'}</span>
          <ChevronDown
            className={`w-4 h-4 transition-transform duration-300 ${expanded ? 'rotate-180' : ''}`}
          />
        </button>

        {expanded && (
          <div className="px-6 pb-6 space-y-5 animate-in">
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

            <div className="flex items-center gap-3 pt-1">
              {opp.url && (
                <a
                  href={opp.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 px-4 py-2.5 text-[13px] font-medium text-gray-600 bg-black/[0.03] rounded-xl hover:bg-black/[0.06] transition-colors duration-300"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  View Posting
                </a>
              )}
              <button
                type="button"
                onClick={() => onDraftEmail(opp.id)}
                className="inline-flex items-center gap-2 px-4 py-2.5 text-[13px] font-medium text-white bg-blue-600 rounded-xl hover:bg-blue-700 transition-colors duration-300"
              >
                <Mail className="w-3.5 h-3.5" />
                Draft Cold Email
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
