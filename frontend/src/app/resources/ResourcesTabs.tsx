'use client';

import { useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useT } from '@/i18n/client';
import type { ResourcesTab } from '@/lib/resources-tab';

const TABS: { key: ResourcesTab; labelKey: string }[] = [
  { key: 'guides', labelKey: 'resources.tabGuides' },
  { key: 'import', labelKey: 'resources.tabImport' },
];

/**
 * Guides and Import as two tabs of one page. The selected tab is mirrored to
 * `?tab=` with replaceState (no history entry per click, other params and the
 * hash kept). Import mounts when first opened and then stays mounted, so
 * switching back to the guides never discards a half-finished extraction.
 */
export default function ResourcesTabs({
  initialTab,
  guides,
  importPanel,
}: {
  initialTab: ResourcesTab;
  guides: ReactNode;
  importPanel: ReactNode;
}) {
  const { t } = useT();
  const [active, setActive] = useState<ResourcesTab>(initialTab);
  const [importOpened, setImportOpened] = useState(initialTab === 'import');
  const tabRefs = useRef<Record<ResourcesTab, HTMLButtonElement | null>>({ guides: null, import: null });

  function select(next: ResourcesTab) {
    setActive(next);
    if (next === 'import') setImportOpened(true);
    const url = new URL(window.location.href);
    if (next === 'import') url.searchParams.set('tab', 'import');
    else url.searchParams.delete('tab');
    window.history.replaceState(window.history.state, '', url);
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = TABS.length - 1;
    const target = event.key === 'ArrowRight' ? (index === last ? 0 : index + 1)
      : event.key === 'ArrowLeft' ? (index === 0 ? last : index - 1)
      : event.key === 'Home' ? 0
      : event.key === 'End' ? last
      : null;
    if (target === null) return;
    event.preventDefault();
    const next = TABS[target].key;
    select(next);
    tabRefs.current[next]?.focus();
  }

  return (
    <>
      <div role="tablist" aria-label={t('resources.tabsAria')} className="mb-10 flex w-fit gap-1 rounded-xl bg-gray-100 p-1">
        {TABS.map(({ key, labelKey }, index) => (
          <button
            key={key}
            ref={(node) => { tabRefs.current[key] = node; }}
            type="button"
            role="tab"
            id={`resources-tab-${key}`}
            aria-selected={active === key}
            aria-controls={`resources-panel-${key}`}
            tabIndex={active === key ? 0 : -1}
            onClick={() => select(key)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={`rounded-lg px-4 py-1.5 text-[13px] font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
              active === key ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-600 hover:text-gray-800'
            }`}
          >
            {t(labelKey)}
          </button>
        ))}
      </div>

      <div role="tabpanel" id="resources-panel-guides" aria-labelledby="resources-tab-guides" hidden={active !== 'guides'}>
        {guides}
      </div>
      <div role="tabpanel" id="resources-panel-import" aria-labelledby="resources-tab-import" hidden={active !== 'import'}>
        {importOpened && importPanel}
      </div>
    </>
  );
}
