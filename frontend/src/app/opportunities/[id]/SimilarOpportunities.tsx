'use client';

import Link from 'next/link';
import { Building2 } from 'lucide-react';
import type { SimilarOpportunity } from '@/lib/api-server';
import { DetailBadge } from './DetailBadge';
import { formatType } from './detail-utils';
import type { TFunc } from './types';

export function SimilarOpportunities({
  similar,
  t,
}: {
  similar: SimilarOpportunity[];
  t: TFunc;
}) {
  if (similar.length === 0) return null;
  return (
    <section className="mt-8 mb-4" aria-labelledby="similar-heading">
      <h2 id="similar-heading" className="text-[14px] font-semibold text-gray-900 mb-4 tracking-tight">
        {t('detail.sections.similar')}
      </h2>
      <ul className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {similar.map((s) => (
          <li key={s.id}>
            <Link
              href={`/opportunities/${encodeURIComponent(s.id)}`}
              className="group block bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] hover:shadow-[0_4px_20px_rgba(0,0,0,0.08)] transition-shadow p-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              <div className="flex items-start gap-2 mb-2">
                <DetailBadge tone="blue">{formatType(s.opportunity_type)}</DetailBadge>
                {s.paid === 'yes' && <DetailBadge tone="emerald">{t('badges.paid')}</DetailBadge>}
                {s.paid === 'stipend' && <DetailBadge tone="emerald">{t('badges.stipend')}</DetailBadge>}
              </div>
              <h3 className="text-[14px] font-semibold text-gray-900 leading-snug line-clamp-2 group-hover:text-blue-600 transition-colors">
                {s.title}
              </h3>
              {s.organization && (
                <p className="text-[12px] text-gray-400 mt-1.5 truncate">
                  <Building2 className="w-3 h-3 inline mr-1" aria-hidden="true" />
                  {s.organization}
                </p>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
