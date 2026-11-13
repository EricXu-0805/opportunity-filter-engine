import Link from 'next/link';
import { Search } from 'lucide-react';
import { getServerT } from '@/i18n/server';

export default async function OpportunityNotFound() {
  const t = await getServerT();
  return (
    <div className="max-w-xl mx-auto px-4 sm:px-6 lg:px-8 py-16 text-center">
      <div className="w-12 h-12 mx-auto mb-4 rounded-2xl bg-gray-100 flex items-center justify-center">
        <Search className="w-6 h-6 text-gray-400" aria-hidden="true" />
      </div>
      <h1 className="text-2xl font-bold text-gray-900 mb-2 tracking-tight">
        {t('detail.notFound.title')}
      </h1>
      <p className="text-[14px] text-gray-600 mb-6 max-w-md mx-auto leading-relaxed">
        {t('detail.notFound.message')}
      </p>
      <Link
        href="/results"
        className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-indigo-600 text-white text-[14px] font-semibold hover:bg-indigo-700 transition-colors"
      >
        {t('detail.notFound.browse')}
      </Link>
    </div>
  );
}
