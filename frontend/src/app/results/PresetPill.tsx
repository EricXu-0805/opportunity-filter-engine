import { Bookmark, Trash2 } from 'lucide-react';
import type { FilterPreset } from '@/lib/filter-presets';
import type { TFunc } from './types';

export function PresetPill({
  preset,
  active,
  onApply,
  onDelete,
  t,
}: {
  preset: FilterPreset;
  active: boolean;
  onApply: (p: FilterPreset) => void;
  onDelete: (id: string) => void;
  t: TFunc;
}) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full text-[11px] font-medium border transition-colors ${
      active
        ? 'bg-blue-600 border-blue-600 text-white'
        : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300'
    }`}>
      <button
        type="button"
        onClick={() => onApply(preset)}
        className="inline-flex items-center gap-1 pl-2.5 pr-1.5 py-1"
        aria-label={t('results.presets.applyLabel', { name: preset.name })}
      >
        <Bookmark className={`w-2.5 h-2.5 ${active ? 'fill-white' : ''}`} aria-hidden="true" />
        {preset.name}
      </button>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          if (window.confirm(t('results.presets.deleteConfirm', { name: preset.name }))) onDelete(preset.id);
        }}
        className={`pr-2 py-1 ${active ? 'text-white/70 hover:text-white' : 'text-gray-300 hover:text-red-500'}`}
        aria-label={t('results.presets.deleteLabel', { name: preset.name })}
      >
        <Trash2 className="w-2.5 h-2.5" />
      </button>
    </span>
  );
}
