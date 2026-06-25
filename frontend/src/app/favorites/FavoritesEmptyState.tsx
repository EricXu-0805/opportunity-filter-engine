'use client';

import { Bookmark, Star } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { TFunc } from './types';

export function FavoritesEmptyState({ t }: { t: TFunc }) {
  const router = useRouter();
  return (
    <div className="text-center py-20">
      <Star className="w-10 h-10 text-gray-200 mx-auto mb-4" />
      <p className="text-[15px] text-gray-400 mb-2">{t('favorites.emptyHint')}</p>
      <p className="text-[13px] text-gray-300 mb-6">{t('favorites.emptyHintImport')}</p>
      <div className="flex items-center justify-center gap-3 flex-wrap">
        <button
          type="button"
          onClick={() => router.push('/')}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-indigo-600 text-white text-[13px] font-medium hover:bg-indigo-700 transition-colors duration-300"
        >
          {t('favorites.browseMatches')}
        </button>
        <Link
          href="/import"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full border border-gray-200 text-gray-700 text-[13px] font-medium hover:bg-gray-50 transition-colors duration-300"
        >
          <Bookmark className="w-3.5 h-3.5" />
          {t('favorites.importLink')}
        </Link>
      </div>
    </div>
  );
}
