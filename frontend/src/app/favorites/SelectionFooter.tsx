import { GitCompare } from 'lucide-react';
import { MAX_COMPARE, MIN_COMPARE, type TFunc } from './types';

export interface SelectionFooterProps {
  selectedCount: number;
  selectedTitles: string[];
  onCancel: () => void;
  onConfirm: () => void;
  t: TFunc;
}

export function SelectionFooter({
  selectedCount,
  selectedTitles,
  onCancel,
  onConfirm,
  t,
}: SelectionFooterProps) {
  return (
    <div className="fixed inset-x-0 bottom-0 z-30 bg-white/95 backdrop-blur-md border-t border-gray-200 shadow-[0_-4px_20px_rgba(0,0,0,0.08)]">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-semibold text-gray-900">
            {t('favorites.selectedCount', { current: selectedCount, max: MAX_COMPARE })}
          </p>
          {selectedTitles.length > 0 && (
            <p className="text-[12px] text-gray-500 truncate mt-0.5">
              {selectedTitles.join(' · ')}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={onCancel}
            className="inline-flex items-center justify-center px-4 py-2.5 rounded-xl bg-white border border-gray-300 text-gray-700 text-[13px] font-medium hover:bg-gray-50 transition-colors"
          >
            {t('favorites.cancel')}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={selectedCount < MIN_COMPARE}
            className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-blue-600 text-white text-[13px] font-semibold hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-[0_2px_12px_rgba(37,99,235,0.25)]"
          >
            <GitCompare className="w-4 h-4" aria-hidden="true" />
            {t('favorites.confirmCompare')}
          </button>
        </div>
      </div>
    </div>
  );
}
