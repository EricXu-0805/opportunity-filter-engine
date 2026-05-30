import { TABS, type Tab, type TFunc } from './types';

export interface ResultsTabsProps {
  activeTab: Tab;
  onChange: (tab: Tab) => void;
  counts: Record<Tab, number>;
  t: TFunc;
}

/**
 * R69-B: the tab row scrolls horizontally on viewports < sm. On a 375x812
 * mobile viewport the rightmost tabs (Reach, Starred) clip off the edge of
 * the screen, but the original layout gave no visual cue that scroll was
 * possible. Adding a `mask-image` linear gradient fades the right edge
 * into transparency so the clipped tabs read as "more content here, swipe
 * left" rather than as broken UI. The mask is removed at `sm:` because the
 * 5 tabs fit comfortably in the desktop container.
 */
export function ResultsTabs({ activeTab, onChange, counts, t }: ResultsTabsProps) {
  return (
    <div
      className="overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0 mb-8 sm:mb-10 no-scrollbar [mask-image:linear-gradient(to_right,black_calc(100%-24px),transparent)] sm:[mask-image:none]"
    >
      <div className="inline-flex items-center bg-black/[0.04] rounded-full p-1" role="tablist" aria-label={t('results.matchCategoryAria')}>
        {TABS.map(({ key, labelKey, icon: Icon, color }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={activeTab === key}
            onClick={() => onChange(key)}
            className={`inline-flex items-center gap-1.5 px-3 sm:px-4 py-2 rounded-full text-[12px] sm:text-[13px] font-medium whitespace-nowrap transition-all duration-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
              ${
                activeTab === key
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
          >
            <Icon className={`w-3.5 h-3.5 ${activeTab === key ? color : ''}`} aria-hidden="true" />
            {t(labelKey)}
            <span className="text-[11px] font-semibold tabular-nums text-gray-400" aria-label={t('results.countResultsAria', { count: counts[key] })}>
              {counts[key]}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
