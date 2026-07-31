'use client';

import { useMemo, useState } from 'react';
import { Check, X, ChevronDown } from 'lucide-react';
import type { Opportunity, ProfileData } from '@/lib/types';
import { useT } from '@/i18n/client';
import { cleanCompensation, noDeadlineKind } from '@/app/opportunities/[id]/detail-utils';

type Replier = (path: string, vars?: Record<string, string | number>) => string;

type ComparisonValue = string | string[] | null | undefined;
type ValueResolver = (opp: Opportunity) => ComparisonValue;

function truthValue(value: boolean | null | undefined): 'yes' | 'no' | 'unknown' {
  if (value === true) return 'yes';
  if (value === false) return 'no';
  return 'unknown';
}

interface FieldSpec {
  key: string;
  labelKey: string;
  value: ValueResolver;
  kind?: 'skills' | 'deadline';
}

const FIELDS: FieldSpec[] = [
  { key: 'compensation', labelKey: 'compare.fields.compensation', value: (o) => cleanCompensation(o.compensation_details) || (o.paid && o.paid !== 'unknown' ? o.paid : undefined) },
  { key: 'paid', labelKey: 'compare.fields.paid', value: (o) => o.paid },
  { key: 'international', labelKey: 'compare.fields.international', value: (o) => o.eligibility?.international_friendly },
  { key: 'citizenship', labelKey: 'compare.fields.citizenship', value: (o) => truthValue(o.eligibility?.citizenship_required) },
  // A listed date beats the `is_rolling` flag (a blanket collector default,
  // not scraped evidence); the 'rolling' sentinel is emitted only on actual
  // rolling evidence, otherwise the honest 'no_deadline' sentinel.
  { key: 'deadline', labelKey: 'compare.fields.deadline', value: (o) => o.deadline ?? (o.is_rolling ? (noDeadlineKind(o) === 'rolling' ? 'rolling' : 'no_deadline') : undefined), kind: 'deadline' },
  { key: 'effort', labelKey: 'compare.fields.applicationEffort', value: (o) => o.application?.application_effort },
  { key: 'skills', labelKey: 'compare.fields.skills', value: (o) => o.eligibility?.skills_required, kind: 'skills' },
  { key: 'majors', labelKey: 'compare.fields.majors', value: (o) => o.eligibility?.majors },
  { key: 'preferredYear', labelKey: 'compare.fields.preferredYear', value: (o) => o.eligibility?.preferred_year },
  { key: 'type', labelKey: 'compare.fields.type', value: (o) => formatType(o.opportunity_type) },
  { key: 'organization', labelKey: 'compare.fields.organization', value: (o) => o.organization },
  { key: 'duration', labelKey: 'compare.fields.duration', value: (o) => o.duration },
  { key: 'startDate', labelKey: 'compare.fields.startDate', value: (o) => o.start_date },
  { key: 'location', labelKey: 'compare.fields.location', value: (o) => o.location },
  { key: 'remote', labelKey: 'compare.fields.remote', value: (o) => o.remote_option },
  { key: 'onCampus', labelKey: 'compare.fields.onCampus', value: (o) => truthValue(o.on_campus) },
  { key: 'requiresResume', labelKey: 'compare.fields.requiresResume', value: (o) => o.application?.requires_resume },
  { key: 'requiresCoverLetter', labelKey: 'compare.fields.requiresCoverLetter', value: (o) => o.application?.requires_cover_letter },
  { key: 'requiresRecommendation', labelKey: 'compare.fields.requiresRecommendation', value: (o) => o.application?.requires_recommendation },
];

function formatType(s: string): string {
  return (s || '').replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
}

function normalizeForComparison(v: ComparisonValue): string {
  if (Array.isArray(v)) return [...v].map((s) => s.toLowerCase()).sort().join('|');
  return (v ?? '').toString().toLowerCase().trim();
}

function normalizeFieldForComparison(field: FieldSpec, opp: Opportunity): string {
  const value = normalizeForComparison(field.value(opp));
  if (field.kind !== 'deadline' || !value || value === 'rolling' || value === 'no_deadline') return value;
  const precision = opp.deadline_is_estimate === false
    ? 'confirmed'
    : opp.deadline_is_estimate === true
      ? 'estimated'
      : 'unknown';
  return `${value}|${precision}`;
}

interface Props {
  rows: Array<{ opp: Opportunity }>;
  profile: ProfileData | null;
}

export default function DifferencesSection({ rows, profile }: Props) {
  const { t } = useT();
  const [showSame, setShowSame] = useState(false);

  const userSkills = useMemo(() => {
    if (!profile) return null;
    return new Set(profile.skills.map((s) => s.name.toLowerCase()));
  }, [profile]);

  const { differing, identical } = useMemo(() => {
    const diff: FieldSpec[] = [];
    const same: FieldSpec[] = [];
    for (const f of FIELDS) {
      const norm = rows.map((r) => normalizeFieldForComparison(f, r.opp));
      const allEmpty = norm.every((n) => !n);
      if (allEmpty) continue;
      const allSame = norm.every((n) => n === norm[0]);
      if (allSame) same.push(f); else diff.push(f);
    }
    return { differing: diff, identical: same };
  }, [rows]);

  const oppCount = rows.length;
  const gridStyle = { gridTemplateColumns: `180px repeat(${oppCount}, minmax(0, 1fr))` };

  return (
    <section className="mb-8">
      <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3 px-1">
        {t('compare.sections.differences')}
      </h2>

      {identical.length > 0 && (
        <button
          type="button"
          onClick={() => setShowSame((s) => !s)}
          className="w-full mb-3 px-4 py-2.5 rounded-xl bg-gray-100 border border-gray-200 flex items-center justify-between text-[12px] text-gray-500 hover:bg-gray-200/70 transition-colors"
        >
          <span>{t('compare.identicalCount', { count: identical.length })}</span>
          <span className="inline-flex items-center gap-1 text-gray-700 font-medium">
            {showSame ? t('compare.hide') : t('compare.show')}
            <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showSame ? 'rotate-180' : ''}`} aria-hidden="true" />
          </span>
        </button>
      )}

      {showSame && identical.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden mb-4">
          <OpportunityColumnHeaders rows={rows} gridStyle={gridStyle} t={t} />
          {identical.map((field, idx) => (
            <Row
              key={field.key}
              field={field}
              rows={rows}
              gridStyle={gridStyle}
              t={t}
              userSkills={userSkills}
              isFirst={idx === 0}
              isIdenticalSection
            />
          ))}
        </div>
      )}

      <div className="space-y-2">
        {differing.length > 0 && (
          <OpportunityColumnHeaders rows={rows} gridStyle={gridStyle} t={t} />
        )}
        {differing.map((field) => (
          <Row
            key={field.key}
            field={field}
            rows={rows}
            gridStyle={gridStyle}
            t={t}
            userSkills={userSkills}
            isFirst={false}
            isIdenticalSection={false}
          />
        ))}
        {differing.length === 0 && (
          <p className="text-[13px] text-gray-400 px-4 py-3">{t('compare.noDifferences')}</p>
        )}
      </div>
    </section>
  );
}

function OpportunityColumnHeaders({
  rows,
  gridStyle,
  t,
}: {
  rows: Array<{ opp: Opportunity }>;
  gridStyle: React.CSSProperties;
  t: Replier;
}) {
  return (
    <div
      data-testid="compare-opportunity-column-headers"
      className="hidden gap-2 border-b border-gray-100 bg-gray-50/70 md:grid"
      style={gridStyle}
      aria-label={t('compare.subtitle', { count: rows.length })}
    >
      <div aria-hidden="true" />
      {rows.map(({ opp }) => (
        <div
          key={opp.id}
          className="min-w-0 px-4 py-2.5 text-[11px] font-semibold leading-snug text-gray-600"
          title={opp.title}
        >
          <span className="line-clamp-2">{opp.title}</span>
        </div>
      ))}
    </div>
  );
}

function Row({
  field,
  rows,
  gridStyle,
  t,
  userSkills,
  isFirst,
  isIdenticalSection,
}: {
  field: FieldSpec;
  rows: Array<{ opp: Opportunity }>;
  gridStyle: React.CSSProperties;
  t: Replier;
  userSkills: Set<string> | null;
  isFirst: boolean;
  isIdenticalSection: boolean;
}) {
  const values = rows.map((r) => field.value(r.opp));

  const wrapperClass = isIdenticalSection
    ? `flex flex-col md:grid md:gap-3 ${isFirst ? '' : 'border-t border-gray-100'}`
    : 'flex flex-col bg-white rounded-xl border border-gray-200 overflow-hidden md:grid md:gap-2';

  return (
    <div className={wrapperClass} style={gridStyle}>
      <div className="flex items-center bg-gray-50 px-4 py-3 text-[12px] font-semibold text-gray-600">
        {t(field.labelKey)}
      </div>
      {values.map((v, i) => {
        return (
          <div
            key={rows[i].opp.id}
            data-testid={`compare-value-${field.key}-${rows[i].opp.id}`}
            className="min-w-0 border-t border-gray-100 px-4 py-3 text-[13px] md:border-l md:border-t-0"
          >
            <p className="mb-1.5 text-[11px] font-semibold leading-snug text-indigo-700 md:hidden">
              {rows[i].opp.title}
            </p>
            <CellContent
              value={v}
              kind={field.kind}
              deadlineIsEstimate={rows[i].opp.deadline_is_estimate}
              userSkills={userSkills}
              t={t}
            />
          </div>
        );
      })}
    </div>
  );
}

function CellContent({
  value,
  kind,
  deadlineIsEstimate,
  userSkills,
  t,
}: {
  value: ComparisonValue;
  kind?: 'skills' | 'deadline';
  deadlineIsEstimate?: boolean | null;
  userSkills: Set<string> | null;
  t: Replier;
}) {
  if (value === undefined || value === null || value === '' || (Array.isArray(value) && value.length === 0)) {
    return <span className="text-gray-300">—</span>;
  }
  if (kind === 'skills' && Array.isArray(value)) {
    const haveCount = userSkills ? value.filter((s) => userSkills.has(s.toLowerCase())).length : 0;
    return (
      <div>
        {userSkills && (
          <div className="text-[11px] text-gray-500 mb-1">
            {t('compare.skillMatch', { have: haveCount, total: value.length })}
          </div>
        )}
        <div className="flex flex-wrap gap-1">
          {value.map((skill) => {
            const has = userSkills?.has(skill.toLowerCase());
            const cls = userSkills === null
              ? 'bg-gray-100 text-gray-600'
              : has
              ? 'bg-emerald-100 text-emerald-700'
              : 'bg-red-100 text-red-700';
            return (
              <span key={skill} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${cls}`}>
                {userSkills !== null && (has ? <Check className="w-2.5 h-2.5" /> : <X className="w-2.5 h-2.5" />)}
                {skill}
              </span>
            );
          })}
        </div>
      </div>
    );
  }
  if (Array.isArray(value)) return <span>{value.join(', ')}</span>;
  if (value === 'yes') return <span>{t('common.yes')}</span>;
  if (value === 'no') return <span>{t('common.no')}</span>;
  if (value === 'unknown') return <span className="text-gray-400">{t('common.notSpecified')}</span>;
  if (value === 'rolling') return <span>{t('compare.rolling')}</span>;
  if (value === 'no_deadline') return <span className="text-gray-400">{t('compare.noDeadline')}</span>;
  if (kind === 'deadline' && deadlineIsEstimate !== false) {
    return (
      <span>
        {value} · <span className="text-amber-700">
          {t(deadlineIsEstimate === true
            ? 'compare.deadlineEstimated'
            : 'compare.deadlineVerify')}
        </span>
      </span>
    );
  }
  return <span>{value}</span>;
}
