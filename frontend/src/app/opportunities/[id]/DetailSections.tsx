'use client';

import type { ReactNode } from 'react';
import {
  AlertTriangle,
  Briefcase,
  Calendar,
  Clock,
  DollarSign,
  Globe,
  GraduationCap,
  Mail,
  Users,
} from 'lucide-react';
import type { Opportunity } from '@/lib/types';
import { cleanCompensation, friendlyLabel } from './detail-utils';
import type { TFunc } from './types';

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-5 sm:p-7 mb-4">
      <h2 className="text-[14px] font-semibold text-gray-900 mb-4 tracking-tight">{title}</h2>
      {children}
    </section>
  );
}

export function DetailRow({
  icon,
  label,
  value,
  warn,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div className="flex items-start gap-3">
      <span className={`shrink-0 mt-0.5 text-gray-400 ${warn ? 'text-amber-500' : ''}`} aria-hidden="true">
        {icon}
      </span>
      <div className="min-w-0">
        <dt className="text-[11px] text-gray-400 uppercase tracking-wider mb-0.5">{label}</dt>
        <dd className={`text-[14px] break-words ${warn ? 'text-amber-700' : 'text-gray-800'}`}>{value}</dd>
      </div>
    </div>
  );
}

export function DescriptionSection({ description, t }: { description: string; t: TFunc }) {
  if (!description) return null;
  return (
    <Section title={t('detail.sections.description')}>
      <p className="text-[14px] sm:text-[15px] text-gray-700 leading-relaxed whitespace-pre-wrap">
        {description}
      </p>
    </Section>
  );
}

export function AtAGlanceSection({ opp, t }: { opp: Opportunity; t: TFunc }) {
  const compensation = cleanCompensation(opp.compensation_details);
  return (
    <Section title={t('detail.sections.atGlance')}>
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-y-4 gap-x-6">
        {opp.deadline && (
          <DetailRow
            icon={<Calendar />}
            label={t('detail.fields.deadline')}
            value={opp.deadline_is_estimate
              ? `${opp.deadline} ${t('detail.fields.deadlineEstimate')}`
              : opp.deadline}
          />
        )}
        {!opp.deadline && opp.is_rolling && (
          <DetailRow
            icon={<Calendar />}
            label={t('detail.fields.deadline')}
            value={t('detail.fields.rollingBasis')}
          />
        )}
        {opp.start_date && (
          <DetailRow icon={<Calendar />} label={t('detail.fields.startDate')} value={opp.start_date} />
        )}
        {opp.duration && (
          <DetailRow icon={<Clock />} label={t('detail.fields.duration')} value={opp.duration} />
        )}
        {compensation && (
          <DetailRow icon={<DollarSign />} label={t('detail.fields.compensation')} value={compensation} />
        )}
        {opp.posted_date && (
          <DetailRow icon={<Calendar />} label={t('detail.fields.posted')} value={opp.posted_date} />
        )}
        {opp.lab_or_program && (
          <DetailRow icon={<Briefcase />} label={t('detail.fields.lab')} value={opp.lab_or_program} />
        )}
        {opp.pi_name && (
          <DetailRow icon={<Users />} label={t('detail.fields.pi')} value={opp.pi_name} />
        )}
      </dl>
    </Section>
  );
}

export function EligibilitySection({ opp, t }: { opp: Opportunity; t: TFunc }) {
  if (!opp.eligibility) return null;
  const e = opp.eligibility;
  return (
    <Section title={t('detail.sections.eligibility')}>
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-y-4 gap-x-6">
        {e.preferred_year?.length > 0 && (
          <DetailRow
            icon={<GraduationCap />}
            label={t('detail.fields.preferredYear')}
            value={e.preferred_year.join(', ')}
          />
        )}
        {e.majors?.length > 0 && (
          <DetailRow
            icon={<GraduationCap />}
            label={t('detail.fields.majors')}
            value={e.majors.join(', ')}
          />
        )}
        {e.skills_required?.length > 0 && (
          <DetailRow
            icon={<Briefcase />}
            label={t('detail.fields.skills')}
            value={e.skills_required.join(', ')}
          />
        )}
        <DetailRow
          icon={<Globe />}
          label={t('detail.fields.international')}
          value={friendlyLabel(e.international_friendly, t)}
        />
        {e.citizenship_required && (
          <DetailRow
            icon={<AlertTriangle />}
            label={t('detail.fields.citizenship')}
            value={t('detail.fields.citizenshipNote')}
            warn
          />
        )}
      </dl>
    </Section>
  );
}

export function ApplicationSection({ opp, t }: { opp: Opportunity; t: TFunc }) {
  if (!opp.application) return null;
  const a = opp.application;
  return (
    <Section title={t('detail.sections.application')}>
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-y-4 gap-x-6">
        {a.contact_method && (
          <DetailRow icon={<Mail />} label={t('detail.fields.contactMethod')} value={a.contact_method} />
        )}
        {a.requires_resume && (
          <DetailRow icon={<Briefcase />} label={t('detail.fields.resume')} value={friendlyLabel(a.requires_resume, t)} />
        )}
        {a.requires_cover_letter && (
          <DetailRow icon={<Briefcase />} label={t('detail.fields.coverLetter')} value={friendlyLabel(a.requires_cover_letter, t)} />
        )}
        {a.requires_recommendation && (
          <DetailRow icon={<Users />} label={t('detail.fields.recommendation')} value={friendlyLabel(a.requires_recommendation, t)} />
        )}
        {a.application_effort && (
          <DetailRow icon={<Clock />} label={t('detail.fields.effort')} value={a.application_effort} />
        )}
      </dl>
    </Section>
  );
}

export function RecentWorksSection({ opp, t }: { opp: Opportunity; t: TFunc }) {
  const works = opp.metadata?.recent_works;
  if (!works?.length) return null;
  return (
    <Section title={t('detail.sections.recentWorks')}>
      <ul className="space-y-2.5">
        {works.slice(0, 5).map((w) => (
          <li key={w.title} className="flex items-baseline gap-2.5 text-[13px] leading-snug">
            {w.year != null && (
              <span className="shrink-0 font-mono text-[11px] text-gray-400 tabular-nums">{w.year}</span>
            )}
            <a
              href={`https://scholar.google.com/scholar?q=${encodeURIComponent(`"${w.title}"`)}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-gray-700 hover:text-indigo-600 hover:underline transition-colors"
            >
              {w.title}
            </a>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-[11px] text-gray-400">{t('detail.recentWorksNote')}</p>
    </Section>
  );
}

export function KeywordsSection({ opp, t }: { opp: Opportunity; t: TFunc }) {
  if (!opp.keywords?.length) return null;
  return (
    <Section title={t('detail.sections.keywords')}>
      <div className="flex flex-wrap gap-1.5">
        {opp.keywords.map((k) => (
          <span key={k} className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-gray-100 text-gray-600">
            {k}
          </span>
        ))}
      </div>
    </Section>
  );
}
