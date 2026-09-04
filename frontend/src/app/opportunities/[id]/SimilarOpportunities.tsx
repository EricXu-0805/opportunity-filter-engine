'use client';

import Link from 'next/link';
import { Building2 } from 'lucide-react';
import type { SimilarOpportunity } from '@/lib/api-server';
import { opportunityRecordKind } from '@/lib/record-kind';
import { targetPosture } from '@/lib/target-truth';
import { DetailBadge } from './DetailBadge';
import { typeLabel } from '@/app/results/types';
import type { TFunc } from './types';

export function SimilarOpportunities({
  similar,
  t,
}: {
  similar: SimilarOpportunity[];
  t: TFunc;
}) {
  // A rail of suggestions is a recommendation, so every card in it has to be
  // something the student can act on. Filtered here rather than trusted from
  // the server payload: this list comes from a separate endpoint that fails
  // open to [], and a stale or malformed row must not become a suggestion.
  const suggestions = similar.filter(
    (s) => targetPosture(s as Parameters<typeof targetPosture>[0]) === 'actionable',
  );
  if (suggestions.length === 0) return null;
  return (
    <section className="mt-8 mb-4" aria-labelledby="similar-heading">
      <h2 id="similar-heading" className="text-[14px] font-semibold text-gray-900 mb-4 tracking-tight">
        {t('detail.sections.similar')}
      </h2>
      <ul className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {suggestions.map((s) => {
          // Offer terms belong to a confirmed listing. A faculty profile and
          // an unreviewed row each get an honest label instead of the record's
          // own unchecked type claim.
          const kind = opportunityRecordKind(s as Parameters<typeof opportunityRecordKind>[0]);
          const isListing = kind === 'listing';
          return <li key={s.id}>
            <Link
              href={`/opportunities/${encodeURIComponent(s.id)}`}
              className="group block bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] hover:shadow-[0_4px_20px_rgba(0,0,0,0.08)] transition-shadow p-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
            >
              <div className="flex items-start gap-2 mb-2">
                <DetailBadge tone="blue">
                  {isListing
                    ? typeLabel(s.opportunity_type, t)
                    : t(kind === 'faculty_contact'
                      ? 'card.facultyContactUnconfirmed'
                      : 'card.recordTypeUnconfirmed')}
                </DetailBadge>
                {isListing && s.paid === 'yes' && <DetailBadge tone="emerald">{t('badges.paid')}</DetailBadge>}
                {isListing && s.paid === 'stipend' && <DetailBadge tone="emerald">{t('badges.stipend')}</DetailBadge>}
              </div>
              <h3 className="text-[14px] font-semibold text-gray-900 leading-snug line-clamp-2 group-hover:text-indigo-600 transition-colors">
                {s.title}
              </h3>
              {s.organization && (
                <p className="text-[12px] text-gray-400 mt-1.5 truncate">
                  <Building2 className="w-3 h-3 inline mr-1" aria-hidden="true" />
                  {s.organization}
                </p>
              )}
            </Link>
          </li>;
        })}
      </ul>
    </section>
  );
}
