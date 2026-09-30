'use client';

import { useId, useState } from 'react';
import type { ImportSourceInfo } from '@/lib/import-source';

const SOURCE_LABEL: Record<ImportSourceInfo['source'], string> = {
  page_text: 'import.pageText',
  pasted_text: 'import.pastedSource',
  page_excerpt: 'import.pageExcerpt',
  unknown: 'import.fieldDescription',
};

/** Collapse only the display. Never shorten the source stored or sent by the caller. */
export default function ImportSourceText({ text, info, t }: {
  text: string;
  info: ImportSourceInfo;
  t: (key: string) => string;
}) {
  const id = useId();
  const [expandedText, setExpandedText] = useState<string | null>(null);
  const expanded = expandedText === text;
  return (
    <section aria-label={t(SOURCE_LABEL[info.source])} className="min-w-0 space-y-2">
      <h3 className="text-[12px] text-gray-500 font-semibold">{t(SOURCE_LABEL[info.source])}</h3>
      <p className="text-[12px] text-gray-500 leading-relaxed">
        {t(info.aiInputScope === 'full_source' ? 'import.fullAiInput' : info.aiInputScope === 'source_excerpt' ? 'import.excerptAiInput' : 'import.aiInputUnknown')}
      </p>
      {info.source === 'page_text' && <p className="text-[12px] text-gray-500 leading-relaxed">{t('import.pageTextScope')}</p>}
      <p id={id} className={`text-[13px] text-gray-600 leading-relaxed whitespace-pre-wrap break-words [overflow-wrap:anywhere] ${expanded ? '' : 'line-clamp-4'}`}>
        {text}
      </p>
      <button type="button" aria-expanded={expanded} aria-controls={id}
        className="text-[13px] font-medium text-indigo-600 hover:text-indigo-800"
        onClick={() => setExpandedText(expanded ? null : text)}>
        {t(expanded ? 'import.collapseSource' : 'import.expandSource')}
      </button>
    </section>
  );
}
