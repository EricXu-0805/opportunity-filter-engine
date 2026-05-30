'use client';

import Link from 'next/link';
import { Lightbulb, AlertTriangle, ArrowRight } from 'lucide-react';
import type { LabType } from '@/lib/types';
import { useT } from '@/i18n/client';

interface EmailTipsPanelProps {
  labType: LabType | null | undefined;
}

const TIP_KEY_ORDER = ['skill1', 'skill2', 'skill3', 'skill4'] as const;
const MISTAKE_KEY_ORDER = ['mistake1', 'mistake2', 'mistake3'] as const;

export default function EmailTipsPanel({ labType }: EmailTipsPanelProps) {
  const { t } = useT();
  if (!labType) return null;

  const skills = TIP_KEY_ORDER.map((k) => t(`coldEmail.tips.${labType}.skills.${k}`)).filter(Boolean);
  const mistakes = MISTAKE_KEY_ORDER.map((k) => t(`coldEmail.tips.${labType}.mistakes.${k}`)).filter(Boolean);

  return (
    <div className="space-y-3">
      <section className="rounded-xl border border-emerald-100 bg-emerald-50/60 p-3">
        <h4 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-emerald-700">
          <Lightbulb className="w-3 h-3" aria-hidden="true" />
          {t('coldEmail.tips.skillsHeading')}
        </h4>
        <ul className="mt-2 space-y-1.5 text-[12px] leading-snug text-emerald-900/90">
          {skills.map((tip, i) => (
            <li key={i} className="flex gap-1.5">
              <span aria-hidden="true">•</span>
              <span>{tip}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-xl border border-amber-100 bg-amber-50/60 p-3">
        <h4 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-amber-700">
          <AlertTriangle className="w-3 h-3" aria-hidden="true" />
          {t('coldEmail.tips.mistakesHeading')}
        </h4>
        <ul className="mt-2 space-y-1.5 text-[12px] leading-snug text-amber-900/90">
          {mistakes.map((tip, i) => (
            <li key={i} className="flex gap-1.5">
              <span aria-hidden="true">•</span>
              <span>{tip}</span>
            </li>
          ))}
        </ul>
      </section>

      <Link
        href={`/resources?lab=${labType}#tips-card-${labType}`}
        data-testid="tips-read-more"
        className="inline-flex items-center gap-1 text-[12px] font-medium text-blue-600 hover:text-blue-700 transition-colors px-3 py-1.5 rounded-lg hover:bg-blue-50/60"
      >
        {t('coldEmail.tips.readMore')}
        <ArrowRight className="w-3 h-3" aria-hidden="true" />
      </Link>
    </div>
  );
}
