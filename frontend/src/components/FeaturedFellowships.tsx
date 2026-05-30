'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { ArrowRight, Globe, GraduationCap, Sparkles } from 'lucide-react';
import { useT } from '@/i18n/client';
import { getFeaturedFellowships } from '@/lib/api';
import type { Opportunity } from '@/lib/types';

const PREVIEW_LIMIT = 3;

function formatDeadline(iso?: string): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function FellowshipPreviewCard({
  opp,
  labelDeadline,
  labelPaid,
  labelIntl,
}: {
  opp: Opportunity;
  labelDeadline: string;
  labelPaid: string;
  labelIntl: string;
}) {
  const isExternal = typeof opp.url === 'string' && /^https?:\/\//i.test(opp.url);
  const href = isExternal ? (opp.url as string) : `/opportunities/${opp.id}`;
  const deadline = formatDeadline(opp.deadline);
  const paid = opp.paid === 'yes';
  const intl = opp.eligibility?.international_friendly === 'yes';

  const cardClasses = 'group block rounded-2xl bg-white border border-gray-100 shadow-[0_1px_6px_rgba(0,0,0,0.04)] hover:shadow-[0_4px_16px_rgba(0,0,0,0.08)] transition-all duration-300 p-4 h-full';

  const body = (
    <>
      <div className="flex items-start justify-between gap-2 mb-2">
        <h3 className="text-[14px] font-semibold text-gray-900 line-clamp-2 group-hover:text-blue-600 transition-colors">
          {opp.title}
        </h3>
        <Sparkles className="w-3.5 h-3.5 text-blue-500 shrink-0 mt-1" aria-hidden="true" />
      </div>
      {opp.organization && (
        <p className="text-[12px] text-gray-500 mb-3 line-clamp-1">{opp.organization}</p>
      )}
      <div className="flex flex-wrap gap-1.5 mb-2">
        {paid && (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 text-[10px] font-medium">
            {labelPaid}
          </span>
        )}
        {intl && (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 text-[10px] font-medium">
            <Globe className="w-2.5 h-2.5" aria-hidden="true" />
            {labelIntl}
          </span>
        )}
      </div>
      {deadline && (
        <p className="text-[11px] text-gray-400">
          {labelDeadline}: <span className="text-gray-600 font-medium">{deadline}</span>
        </p>
      )}
    </>
  );

  if (isExternal) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={cardClasses}>
        {body}
      </a>
    );
  }
  return (
    <Link href={href} className={cardClasses}>
      {body}
    </Link>
  );
}

export default function FeaturedFellowships() {
  const { t } = useT();
  const [items, setItems] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getFeaturedFellowships(PREVIEW_LIMIT)
      .then((res) => {
        if (cancelled) return;
        setItems((res.opportunities ?? []).slice(0, PREVIEW_LIMIT));
      })
      .catch(() => {
        if (!cancelled) setErrored(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (errored || (!loading && items.length === 0)) return null;

  return (
    <section
      aria-labelledby="featured-fellowships-heading"
      data-testid="featured-fellowships"
      className="max-w-5xl mx-auto mt-12 px-4 sm:px-6"
    >
      <div className="flex items-end justify-between mb-4 gap-3">
        <div>
          <h2 id="featured-fellowships-heading" className="flex items-center gap-2 text-[15px] font-semibold text-gray-900 tracking-tight">
            <GraduationCap className="w-4 h-4 text-blue-600" aria-hidden="true" />
            {t('home.featured.title')}
          </h2>
          <p className="mt-1 text-[12px] text-gray-500">{t('home.featured.subtitle')}</p>
        </div>
        <Link
          href="/fellowships"
          className="inline-flex items-center gap-1 text-[12px] font-medium text-blue-600 hover:text-blue-700 transition-colors shrink-0"
        >
          {t('home.featured.cta')}
          <ArrowRight className="w-3 h-3" aria-hidden="true" />
        </Link>
      </div>
      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3" aria-busy="true" aria-live="polite">
          {Array.from({ length: PREVIEW_LIMIT }).map((_, i) => (
            <div key={i} className="rounded-2xl bg-white border border-gray-100 p-4 animate-pulse">
              <div className="h-3 bg-gray-100 rounded mb-2" />
              <div className="h-3 bg-gray-100 rounded w-2/3 mb-3" />
              <div className="h-2 bg-gray-100 rounded w-1/2" />
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {items.map((opp) => (
            <FellowshipPreviewCard
              key={opp.id}
              opp={opp}
              labelDeadline={t('home.featured.deadlineLabel')}
              labelPaid={t('home.featured.paid')}
              labelIntl={t('home.featured.intl')}
            />
          ))}
        </div>
      )}
    </section>
  );
}
