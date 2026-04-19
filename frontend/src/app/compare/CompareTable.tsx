'use client';

import { useMemo, useEffect, useState } from 'react';
import Link from 'next/link';
import { ExternalLink, Check, X } from 'lucide-react';
import type { Opportunity, ProfileData } from '@/lib/types';
import { useT } from '@/i18n/client';

type ValueResolver = (opp: Opportunity) => string | string[] | undefined;

interface FieldSpec {
  key: string;
  labelKey: string;
  value: ValueResolver;
  kind?: 'skills';
}

const BASICS: FieldSpec[] = [
  { key: 'type', labelKey: 'compare.fields.type', value: (o) => formatType(o.opportunity_type) },
  { key: 'organization', labelKey: 'compare.fields.organization', value: (o) => o.organization },
  { key: 'deadline', labelKey: 'compare.fields.deadline', value: (o) => o.deadline },
  { key: 'startDate', labelKey: 'compare.fields.startDate', value: (o) => o.start_date },
  { key: 'duration', labelKey: 'compare.fields.duration', value: (o) => o.duration },
  { key: 'location', labelKey: 'compare.fields.location', value: (o) => o.location },
  { key: 'paid', labelKey: 'compare.fields.paid', value: (o) => o.paid },
  { key: 'compensation', labelKey: 'compare.fields.compensation', value: (o) => o.compensation_details },
  { key: 'remote', labelKey: 'compare.fields.remote', value: (o) => o.remote_option },
  { key: 'onCampus', labelKey: 'compare.fields.onCampus', value: (o) => (o.on_campus ? 'yes' : 'no') },
];

const ELIGIBILITY: FieldSpec[] = [
  { key: 'preferredYear', labelKey: 'compare.fields.preferredYear', value: (o) => o.eligibility?.preferred_year },
  { key: 'majors', labelKey: 'compare.fields.majors', value: (o) => o.eligibility?.majors },
  { key: 'skills', labelKey: 'compare.fields.skills', value: (o) => o.eligibility?.skills_required, kind: 'skills' },
  { key: 'international', labelKey: 'compare.fields.international', value: (o) => o.eligibility?.international_friendly },
  { key: 'citizenship', labelKey: 'compare.fields.citizenship', value: (o) => (o.eligibility?.citizenship_required ? 'yes' : 'no') },
];

const APPLICATION: FieldSpec[] = [
  { key: 'resume', labelKey: 'compare.fields.requiresResume', value: (o) => o.application?.requires_resume },
  { key: 'cover', labelKey: 'compare.fields.requiresCoverLetter', value: (o) => o.application?.requires_cover_letter },
  { key: 'rec', labelKey: 'compare.fields.requiresRecommendation', value: (o) => o.application?.requires_recommendation },
  { key: 'effort', labelKey: 'compare.fields.applicationEffort', value: (o) => o.application?.application_effort },
];

export default function CompareTable({ opps }: { opps: Opportunity[] }) {
  const { t } = useT();
  const [userSkills, setUserSkills] = useState<Set<string> | null>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem('ofe_profile');
      if (!raw) return;
      const profile = JSON.parse(raw) as ProfileData;
      setUserSkills(new Set(profile.skills.map((s) => s.name.toLowerCase())));
    } catch { /* malformed */ }
  }, []);

  const cols = `grid-cols-[minmax(140px,180px)_repeat(${opps.length},minmax(0,1fr))]`;

  return (
    <div className="space-y-6">
      <div className="overflow-x-auto -mx-4 sm:mx-0">
        <div className="min-w-[640px] sm:min-w-0 px-4 sm:px-0">
          <HeaderRow opps={opps} cols={cols} />
          <SectionGroup title={t('compare.sections.basics')} fields={BASICS} opps={opps} cols={cols} t={t} userSkills={userSkills} />
          <SectionGroup title={t('compare.sections.eligibility')} fields={ELIGIBILITY} opps={opps} cols={cols} t={t} userSkills={userSkills} />
          <SectionGroup title={t('compare.sections.application')} fields={APPLICATION} opps={opps} cols={cols} t={t} userSkills={userSkills} />
          <TagsRow opps={opps} cols={cols} t={t} />
        </div>
      </div>
    </div>
  );
}

function HeaderRow({ opps, cols }: { opps: Opportunity[]; cols: string }) {
  return (
    <div className={`grid ${cols} gap-3 mb-4 items-stretch`}>
      <div />
      {opps.map((opp) => {
        const applyUrl = opp.application?.application_url || opp.url || opp.source_url;
        return (
          <div key={opp.id} className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-4 flex flex-col">
            <Link
              href={`/opportunities/${encodeURIComponent(opp.id)}`}
              className="text-[14px] font-semibold text-gray-900 leading-snug line-clamp-3 hover:text-blue-600 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
            >
              {opp.title}
            </Link>
            {opp.organization && (
              <p className="text-[11px] text-gray-400 mt-2 truncate">{opp.organization}</p>
            )}
            {applyUrl && (
              <a
                href={applyUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-3 inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-50 text-blue-700 text-[11px] font-medium hover:bg-blue-100 transition-colors"
              >
                <ExternalLink className="w-3 h-3" aria-hidden="true" />
                Apply
              </a>
            )}
          </div>
        );
      })}
    </div>
  );
}

function SectionGroup({
  title,
  fields,
  opps,
  cols,
  t,
  userSkills,
}: {
  title: string;
  fields: FieldSpec[];
  opps: Opportunity[];
  cols: string;
  t: (p: string, vars?: Record<string, string | number>) => string;
  userSkills: Set<string> | null;
}) {
  return (
    <section className="mb-6">
      <h2 className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2 px-1">{title}</h2>
      <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] overflow-hidden">
        {fields.map((field, idx) => (
          <Row
            key={field.key}
            field={field}
            opps={opps}
            cols={cols}
            t={t}
            userSkills={userSkills}
            isFirst={idx === 0}
          />
        ))}
      </div>
    </section>
  );
}

function Row({
  field,
  opps,
  cols,
  t,
  userSkills,
  isFirst,
}: {
  field: FieldSpec;
  opps: Opportunity[];
  cols: string;
  t: (p: string, vars?: Record<string, string | number>) => string;
  userSkills: Set<string> | null;
  isFirst: boolean;
}) {
  const values = opps.map(field.value);
  const allSame = useMemo(() => {
    const norm = values.map((v) => (Array.isArray(v) ? [...v].sort().join('|') : v ?? ''));
    return norm.every((v) => v === norm[0]) && norm[0] !== '';
  }, [values]);

  return (
    <div className={`grid ${cols} gap-3 ${isFirst ? '' : 'border-t border-gray-100'}`}>
      <div className="px-4 py-3 text-[12px] font-medium text-gray-500 bg-gray-50/50 flex items-center">
        {t(field.labelKey)}
      </div>
      {values.map((v, i) => (
        <div
          key={opps[i].id}
          className={`px-4 py-3 text-[13px] ${allSame ? 'text-gray-400' : 'text-gray-800'}`}
        >
          <CellContent value={v} kind={field.kind} userSkills={userSkills} t={t} />
        </div>
      ))}
    </div>
  );
}

function CellContent({
  value,
  kind,
  userSkills,
  t,
}: {
  value: string | string[] | undefined;
  kind?: 'skills';
  userSkills: Set<string> | null;
  t: (p: string, vars?: Record<string, string | number>) => string;
}) {
  if (value === undefined || value === null || value === '' || (Array.isArray(value) && value.length === 0)) {
    return <span className="text-gray-300">—</span>;
  }

  if (kind === 'skills' && Array.isArray(value)) {
    return (
      <div className="flex flex-wrap gap-1">
        {value.map((skill) => {
          const has = userSkills?.has(skill.toLowerCase());
          const cls =
            userSkills === null
              ? 'bg-gray-100 text-gray-600'
              : has
              ? 'bg-emerald-50 text-emerald-700'
              : 'bg-red-50 text-red-700';
          return (
            <span key={skill} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${cls}`}>
              {userSkills !== null && (has ? <Check className="w-2.5 h-2.5" aria-hidden="true" /> : <X className="w-2.5 h-2.5" aria-hidden="true" />)}
              {skill}
            </span>
          );
        })}
      </div>
    );
  }

  if (Array.isArray(value)) {
    return <span>{value.join(', ')}</span>;
  }

  if (value === 'yes') return <span>{t('common.yes')}</span>;
  if (value === 'no') return <span>{t('common.no')}</span>;
  if (value === 'unknown') return <span className="text-gray-400">{t('common.notSpecified')}</span>;

  return <span>{value}</span>;
}

function TagsRow({ opps, cols, t }: { opps: Opportunity[]; cols: string; t: (p: string) => string }) {
  const hasAny = opps.some((o) => o.keywords && o.keywords.length > 0);
  if (!hasAny) return null;
  return (
    <section className="mb-6">
      <h2 className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2 px-1">{t('compare.sections.tags')}</h2>
      <div className={`grid ${cols} gap-3 bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-4`}>
        <div className="text-[12px] font-medium text-gray-500">{t('compare.fields.keywords')}</div>
        {opps.map((o) => (
          <div key={o.id} className="flex flex-wrap gap-1">
            {(o.keywords ?? []).slice(0, 12).map((k) => (
              <span key={k} className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 text-gray-600">
                {k}
              </span>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

function formatType(t: string): string {
  return t.replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
}
