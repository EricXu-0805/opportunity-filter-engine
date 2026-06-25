import { Sparkles } from 'lucide-react';
import type { TFunc } from './types';

export function SemanticToggle({
  value,
  onChange,
  disabled,
  t,
}: {
  value: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  t: TFunc;
}) {
  return (
    <button
      type="button"
      role="switch"
      data-testid="semantic-toggle"
      aria-checked={value}
      aria-label={t('results.semantic.aria')}
      disabled={disabled}
      onClick={() => onChange(!value)}
      title={value ? t('results.semantic.titleOn') : t('results.semantic.titleOff')}
      className={`inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-[12px] font-medium border transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed ${
        value
          ? 'bg-gradient-to-r from-indigo-600 to-violet-600 text-white border-transparent shadow-sm'
          : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300'
      }`}
    >
      <Sparkles className={`w-3.5 h-3.5 ${value ? 'text-white' : 'text-gray-400'}`} aria-hidden="true" />
      <span className="hidden sm:inline">{t('results.semantic.label')}</span>
      <span className={`text-[10px] font-semibold tracking-wider uppercase ${value ? 'opacity-90' : 'opacity-60'}`}>
        {value ? t('results.semantic.on') : t('results.semantic.off')}
      </span>
    </button>
  );
}
