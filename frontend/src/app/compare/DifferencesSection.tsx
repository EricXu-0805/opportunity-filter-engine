'use client';

import { useMemo, useState } from 'react';
import { Check, X, ChevronDown } from 'lucide-react';
import type { Opportunity, ProfileData } from '@/lib/types';
import { FIELD_SCORERS, type OppScore } from './scores';
import { useT } from '@/i18n/client';

type Replier = (path: string, vars?: Record<string, string | number>) => string;

type ValueResolver = (opp: Opportunity) => string | string[] | undefined;

interface FieldSpec {
  key: string;
  labelKey: string;
  value: ValueResolver;
  kind?: 'skills';
}

const FIELDS: FieldSpec[] = [
  { key: 'compensation', labelKey: 'compare.fields.compensation', value: (o) => o.compensation_details || (o.paid && o.paid !== 'unknown' ? o.paid : undefined) },
  { key: 'paid', labelKey: 'compare.fields.paid', value: (o) => o.paid },
  { key: 'international', labelKey: 'compare.fields.international', value: (o) => o.eligibility?.international_friendly },
  { key: 'citizenship', labelKey: 'compare.fields.citizenship', value: (o) => (o.eligibility?.citizenship_required ? 'yes' : 'no') },
  { key: 'deadline', labelKey: 'compare.fields.deadline', value: (o) => (o.is_rolling ? 'rolling' : o.deadline) },
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
  { key: 'onCampus', labelKey: 'compare.fields.onCampus', value: (o) => (o.on_campus ? 'yes' : 'no') },
  { key: 'requiresResume', labelKey: 'compare.fields.requiresResume', value: (o) => o.application?.requires_resume },
  { key: 'requiresCoverLetter', labelKey: 'compare.fields.requiresCoverLetter', value: (o) => o.application?.requires_cover_letter },
  { key: 'requiresRecommendation', labelKey: 'compare.fields.requiresRecommendation', value: (o) => o.application?.requires_recommendation },
];

function formatType(s: string): string {
  return (s || '').replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
}

function normalizeForComparison(v: string | string[] | undefined): string {
  if (Array.isArray(v)) return [...v].map((s) => s.toLowerCase()).sort().join('|');
  return (v ?? '').toString().toLowerCase().trim();
}

interface Props {
  rows: Array<{ opp: Opportunity; score: OppScore }>;
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
      const norm = rows.map((r) => normalizeForComparison(f.value(r.opp)));
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
          {identical.map((field, idx) => (
            <Row
              key={field.key}
              field={field}
              rows={rows}
              profile={profile}
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
        {differing.map((field) => (
          <Row
            key={field.key}
            field={field}
            rows={rows}
            profile={profile}
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

function Row({
  field,
  rows,
  profile,
  gridStyle,
  t,
  userSkills,
  isFirst,
  isIdenticalSection,
}: {
  field: FieldSpec;
  rows: Array<{ opp: Opportunity; score: OppScore }>;
  profile: ProfileData | null;
  gridStyle: React.CSSProperties;
  t: Replier;
  userSkills: Set<string> | null;
  isFirst: boolean;
  isIdenticalSection: boolean;
}) {
  const values = rows.map((r) => field.value(r.opp));
  const scorer = FIELD_SCORERS[field.key];
  const fieldScores = (scorer && profile && !isIdenticalSection)
    ? rows.map((r) => scorer(r.opp, profile))
    : null;

  let bestVal = -Infinity;
  let worstVal = Infinity;
  if (fieldScores) {
    fieldScores.forEach((v) => {
      if (v > bestVal) bestVal = v;
      if (v < worstVal) worstVal = v;
    });
  }
  const gap = bestVal - worstVal;
  const meaningfulGap = gap >= 15;

  const wrapperClass = isIdenticalSection
    ? `grid gap-3 ${isFirst ? '' : 'border-t border-gray-100'}`
    : 'grid gap-2 bg-white rounded-xl border border-gray-200 overflow-hidden';

  return (
    <div className={wrapperClass} style={gridStyle}>
      <div className="px-4 py-3 text-[12px] font-medium text-gray-500 bg-gray-50 flex items-center">
        {t(field.labelKey)}
      </div>
      {values.map((v, i) => {
        let borderClass = 'border-l-4 border-transparent';
        let bgClass = '';
        if (!isIdenticalSection && fieldScores) {
          const score = fieldScores[i];
          const isBest = meaningfulGap && score === bestVal && score >= 60;
          const isWorst = meaningfulGap && score === worstVal && score < 50;
          if (isBest) {
            borderClass = 'border-l-4 border-emerald-400';
            bgClass = 'bg-emerald-50/30';
          } else if (isWorst) {
            borderClass = 'border-l-4 border-red-400';
            bgClass = 'bg-red-50/30';
          } else if (score < 60) {
            borderClass = 'border-l-4 border-amber-300';
            bgClass = 'bg-amber-50/20';
          }
        }
        return (
          <div key={rows[i].opp.id} className={`px-4 py-3 text-[13px] ${borderClass} ${bgClass}`}>
            <CellContent value={v} kind={field.kind} userSkills={userSkills} t={t} />
          </div>
        );
      })}
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
  return <span>{value}</span>;
}
