'use client';

import { ExternalLink } from 'lucide-react';
import type { DatabaseLink } from './types';
import { useT } from '@/i18n/client';

interface DatabaseLinkCardProps {
  link: DatabaseLink;
}

export default function DatabaseLinkCard({ link }: DatabaseLinkCardProps) {
  const { t } = useT();
  return (
    <a
      href={link.href}
      target="_blank"
      rel="noopener noreferrer"
      className="group block rounded-2xl border border-gray-200 bg-white p-5 shadow-[0_1px_6px_rgba(0,0,0,0.04)] hover:border-blue-300 hover:shadow-md transition-all"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-600 to-blue-500 text-white flex items-center justify-center text-sm font-bold tracking-tight shrink-0">
            {link.short}
          </div>
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-gray-900 truncate">
              {t(`resources.databases.${link.key}.name`)}
            </h3>
            <p className="text-[11px] text-gray-400 truncate">{link.domain}</p>
          </div>
        </div>
        <ExternalLink className="w-4 h-4 text-gray-300 group-hover:text-blue-500 shrink-0 transition-colors" aria-hidden="true" />
      </div>
      <p className="mt-3 text-sm text-gray-600 leading-relaxed">
        {t(`resources.databases.${link.key}.description`)}
      </p>
    </a>
  );
}
