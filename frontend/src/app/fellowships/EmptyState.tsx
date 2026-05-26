'use client';

import { Search } from 'lucide-react';
import { useT } from '@/i18n/client';

interface EmptyStateProps {
  hasFilters: boolean;
  onClearFilters: () => void;
}

export default function EmptyState({ hasFilters, onClearFilters }: EmptyStateProps) {
  const { t } = useT();
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-12 h-12 rounded-2xl bg-gray-100 flex items-center justify-center mb-4">
        <Search className="w-5 h-5 text-gray-400" aria-hidden="true" />
      </div>
      <p className="text-base font-semibold text-gray-900">
        {t('fellowships.empty.title')}
      </p>
      <p className="mt-2 text-sm text-gray-500 max-w-sm">
        {hasFilters ? t('fellowships.empty.withFilters') : t('fellowships.empty.noResults')}
      </p>
      {hasFilters && (
        <button
          type="button"
          onClick={onClearFilters}
          className="mt-4 px-4 py-2 text-sm font-medium text-blue-600 hover:text-blue-700 rounded-xl border border-blue-200 hover:bg-blue-50 transition-colors"
        >
          {t('fellowships.empty.clear')}
        </button>
      )}
    </div>
  );
}
