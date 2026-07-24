'use client';

import Link from 'next/link';
import { ArrowRight, ExternalLink, Calendar, MapPin, Sparkles } from 'lucide-react';
import type { Opportunity } from '@/lib/types';
import { useT } from '@/i18n/client';

interface FellowshipCardProps {
  opp: Opportunity;
}

const VALID_GRADES = new Set(['Freshman', 'Sophomore', 'Junior', 'Senior', 'Masters', 'PhD']);
const VALID_SEEKING = new Set(['fellowship', 'summer_program']);

function buildPrefillHref(opp: Opportunity): string {
  const params = new URLSearchParams();
  const year = opp.eligibility?.preferred_year?.find((y) => VALID_GRADES.has(y));
  if (year) params.set('prefill_year', year);
  if (VALID_SEEKING.has(opp.opportunity_type)) {
    params.set('prefill_seeking', opp.opportunity_type);
  }
  const qs = params.toString();
  return qs ? `/?${qs}` : '/';
}

export default function FellowshipCard({ opp }: FellowshipCardProps) {
  const { t } = useT();
  const paid = opp.paid === 'yes' || opp.paid === 'stipend';
  const intl = opp.eligibility?.international_friendly === 'yes';
  const deadline = opp.deadline ?? null;
  // Only a positively estimated deadline gets the caveat. Absent precision
  // data stays silent — most of the catalog predates the flag, and wrapping
  // every card in warnings would drown the real ones.
  const deadlineIsEstimate = opp.deadline_is_estimate === true;
  const inactive = opp.metadata?.is_active === false;
  const linkHref = opp.url || opp.source_url || `/opportunities/${opp.id}`;
  const external = (opp.url || opp.source_url || '').startsWith('http');
  const prefillHref = buildPrefillHref(opp);

  return (
    <article className="rounded-2xl border border-gray-200 bg-white p-5 shadow-[0_1px_6px_rgba(0,0,0,0.04)] hover:border-indigo-300 hover:shadow-md transition-all flex flex-col">
      <div className="flex items-start justify-between gap-3 mb-2">
        <h3 className="text-base font-semibold text-gray-900 leading-snug">
          {external ? (
            <a
              href={linkHref}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-indigo-600 transition-colors"
            >
              {opp.title}
            </a>
          ) : (
            <Link href={linkHref} className="hover:text-indigo-600 transition-colors">
              {opp.title}
            </Link>
          )}
        </h3>
        {external && (
          <ExternalLink className="w-4 h-4 text-gray-300 shrink-0" aria-hidden="true" />
        )}
      </div>

      {opp.organization && (
        <p className="text-[13px] text-gray-500 mb-3">{opp.organization}</p>
      )}

      <div className="flex flex-wrap gap-1.5 mb-3">
        {paid && (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200">
            {t('fellowships.badges.paid')}
          </span>
        )}
        {intl && (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-indigo-50 text-indigo-700 ring-1 ring-inset ring-indigo-200">
            {t('fellowships.badges.intl')}
          </span>
        )}
        {opp.opportunity_type === 'summer_program' && (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-violet-50 text-violet-700 ring-1 ring-inset ring-violet-200">
            <Sparkles className="w-3 h-3" aria-hidden="true" />
            {t('fellowships.badges.summer')}
          </span>
        )}
        {opp.opportunity_type === 'fellowship' && (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-sky-50 text-sky-700 ring-1 ring-inset ring-sky-200">
            <Sparkles className="w-3 h-3" aria-hidden="true" />
            {t('fellowships.badges.fellowship')}
          </span>
        )}
      </div>

      {inactive && (
        <p
          className="mb-3 rounded-xl bg-red-50 px-3 py-2 text-[12px] leading-5 text-red-700 ring-1 ring-inset ring-red-100"
          data-testid="activity-status"
        >
          {t('fellowships.status.inactive')}
        </p>
      )}

      <div className="mt-auto flex items-center gap-3 text-[12px] text-gray-500">
        {deadline && (
          <span className="inline-flex items-center gap-1">
            <Calendar className="w-3 h-3" aria-hidden="true" />
            <span>{deadline}</span>
            {deadlineIsEstimate && (
              <span className="font-medium text-amber-700" data-testid="deadline-estimate">
                {t('fellowships.deadlineEstimate')}
              </span>
            )}
          </span>
        )}
        {typeof opp.on_campus === 'boolean' && (
          <span className="inline-flex items-center gap-1">
            <MapPin className="w-3 h-3" aria-hidden="true" />
            {opp.on_campus ? t('fellowships.location.onCampus') : t('fellowships.location.offCampus')}
          </span>
        )}
      </div>

      {!inactive && (
        <Link
          href={prefillHref}
          data-testid="match-like-this"
          className="mt-3 inline-flex items-center gap-1 text-[12px] font-medium text-indigo-600 hover:text-indigo-700 transition-colors self-start"
        >
          {t('fellowships.matchLikeThis')}
          <ArrowRight className="w-3 h-3" aria-hidden="true" />
        </Link>
      )}
    </article>
  );
}
