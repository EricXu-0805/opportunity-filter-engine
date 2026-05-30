'use client';

import { LAB_TYPES, TIP_BULLET_ORDER, type LabType } from './types';
import { useT } from '@/i18n/client';

interface ContactTipsCardProps {
  labType: LabType;
}

export default function ContactTipsCard({ labType }: ContactTipsCardProps) {
  const { t } = useT();
  const meta = LAB_TYPES.find((m) => m.key === labType)!;
  const Icon = meta.icon;

  const whatPoints = TIP_BULLET_ORDER
    .map((k) => t(`resources.tips.${labType}.differentiators.${k}`))
    .filter(Boolean);
  const skillsPoints = TIP_BULLET_ORDER
    .map((k) => t(`resources.tips.${labType}.skills.${k}`))
    .filter(Boolean);
  const mistakesPoints = TIP_BULLET_ORDER
    .slice(0, 3)
    .map((k) => t(`resources.tips.${labType}.mistakes.${k}`))
    .filter(Boolean);

  return (
    <article
      className={`rounded-2xl border border-gray-200 bg-white p-6 shadow-[0_1px_6px_rgba(0,0,0,0.04)] flex flex-col`}
      aria-labelledby={`tips-${labType}-heading`}
    >
      <div className={`inline-flex items-center gap-2 self-start px-3 py-1 rounded-full ring-1 ring-inset ${meta.bgClass} ${meta.textClass} ${meta.ringClass} text-xs font-semibold mb-4`}>
        <Icon className="w-3.5 h-3.5" aria-hidden="true" />
        {t(`resources.labType.${labType}`)}
      </div>

      <h2 id={`tips-${labType}-heading`} className="text-lg font-bold text-gray-900 tracking-tight">
        {t(`resources.tips.${labType}.heading`)}
      </h2>
      <p className="mt-1 text-sm text-gray-500">
        {t(`resources.tips.${labType}.subtitle`)}
      </p>

      <section className="mt-5">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-gray-500">
          {t('resources.tips.whatHeading')}
        </h3>
        <ul className="mt-2 space-y-1.5 text-[13px] leading-snug text-gray-700">
          {whatPoints.map((p, i) => (
            <li key={i} className="flex gap-2"><span aria-hidden="true">•</span><span>{p}</span></li>
          ))}
        </ul>
      </section>

      <section className="mt-5">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-emerald-700">
          {t('resources.tips.skillsHeading')}
        </h3>
        <ul className="mt-2 space-y-1.5 text-[13px] leading-snug text-gray-700">
          {skillsPoints.map((p, i) => (
            <li key={i} className="flex gap-2"><span aria-hidden="true">•</span><span>{p}</span></li>
          ))}
        </ul>
      </section>

      <section className="mt-5">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-amber-700">
          {t('resources.tips.mistakesHeading')}
        </h3>
        <ul className="mt-2 space-y-1.5 text-[13px] leading-snug text-gray-700">
          {mistakesPoints.map((p, i) => (
            <li key={i} className="flex gap-2"><span aria-hidden="true">•</span><span>{p}</span></li>
          ))}
        </ul>
      </section>
    </article>
  );
}
