import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ArrowLeft } from 'lucide-react';
import { fetchOpportunityServer } from '@/lib/api-server';
import type { Opportunity } from '@/lib/types';
import { getServerT } from '@/i18n/server';
import { RELEASE_SCOPE } from '@/lib/release-scope';
import CompareTable from './CompareTable';

const MAX_COMPARE = 4;
const MIN_COMPARE = 2;

export async function generateMetadata(): Promise<Metadata> {
  return {
    title: 'Compare opportunities — JoinALab',
    robots: { index: false },
  };
}

function parseIds(raw: string | string[] | undefined): string[] {
  if (!raw) return [];
  const flat = Array.isArray(raw) ? raw.join(',') : raw;
  const unique = new Set(
    flat
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
  );
  return [...unique].slice(0, MAX_COMPARE);
}

export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<{ ids?: string | string[] }>;
}) {
  if (!RELEASE_SCOPE.compare) notFound();

  const { ids: rawIds } = await searchParams;
  const ids = parseIds(rawIds);
  const [opps, t] = await Promise.all([
    Promise.all(ids.map((id) => fetchOpportunityServer(id))).then((rs) =>
      rs.filter((o): o is Opportunity => !!o),
    ),
    getServerT(),
  ]);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
      <Link
        href="/favorites"
        className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 mb-6 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded"
      >
        <ArrowLeft className="w-4 h-4" aria-hidden="true" />
        {t('compare.backToFavorites')}
      </Link>

      <header className="mb-6">
        <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 tracking-tight">
          {t('compare.title')}
        </h1>
        {opps.length > 0 && (
          <p className="text-[13px] text-gray-500 mt-1.5">
            {t('compare.subtitle', { count: opps.length })}
          </p>
        )}
      </header>

      {ids.length < MIN_COMPARE ? (
        <EmptyState message={t('compare.tooFew')} ctaLabel={t('compare.addMore')} />
      ) : opps.length < MIN_COMPARE ? (
        <EmptyState
          message={t(opps.length === 0 ? 'compare.notFound' : 'compare.notEnoughFound')}
          ctaLabel={t('compare.addMore')}
        />
      ) : (
        <CompareTable opps={opps} />
      )}
    </div>
  );
}

function EmptyState({ message, ctaLabel }: { message: string; ctaLabel: string }) {
  return (
    <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8 text-center">
      <p className="text-sm text-gray-500 mb-4">{message}</p>
      <Link
        href="/favorites"
        className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 text-white text-[13px] font-medium hover:bg-indigo-700 transition-colors"
      >
        {ctaLabel}
      </Link>
    </div>
  );
}
