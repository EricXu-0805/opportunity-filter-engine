import type { ImportedOpportunity } from '@/lib/api';
import { importSourceInfo, type ImportSourceInfo } from '@/lib/import-source';
import { importSuggestions } from '@/lib/import-suggestions';
import ImportSourceText from './ImportSourceText';
import ImportSuggestions from './ImportSuggestions';

export default function ImportOpportunityDetails({ opportunity, sourceInfo, t }: {
  opportunity: ImportedOpportunity;
  sourceInfo?: ImportSourceInfo;
  t: (path: string, vars?: Record<string, string | number>) => string;
}) {
  const extra = opportunity.extra_fields ?? {};
  const oppType = typeof extra.opportunity_type === 'string' ? extra.opportunity_type : null;
  const onCampus = typeof extra.on_campus === 'boolean' ? extra.on_campus : null;
  const paid = typeof extra.paid === 'string' ? extra.paid : null;
  const suggestions = importSuggestions(extra);
  const preferredYear = Array.isArray(extra.preferred_year) ? (extra.preferred_year as string[]) : [];
  const intlFriendly = typeof extra.international_friendly === 'string'
    ? extra.international_friendly
    : null;

  return <>
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4 text-[13px] mb-6">
        <Field label={t('import.fieldOrg')} value={opportunity.organization} t={t} />
        <Field label={t('import.fieldType')} value={oppType} t={t} capitalize />
        <Field label={t('import.fieldLocation')} value={opportunity.location} t={t} />
        <Field
          label={t('import.fieldOnCampus')}
          value={onCampus === null ? null : (onCampus ? 'yes' : 'no')}
          t={t}
          capitalize
        />
        <Field label={t('import.fieldPaid')} value={paid} t={t} capitalize />
        <Field label={t('import.fieldDeadline')} value={opportunity.deadline} t={t} />
        <Field label={t('import.fieldIntl')} value={intlFriendly} t={t} capitalize />
        <Field
          label={t('import.fieldYear')}
          value={preferredYear.length > 0 ? preferredYear.join(', ') : null}
          t={t}
          capitalize
        />
      </dl>

      {opportunity.description_raw && (
        <div className="mb-6">
          <ImportSourceText text={opportunity.description_raw} info={sourceInfo ?? importSourceInfo(extra, opportunity.description_raw)} t={t} />
        </div>
      )}

      <ImportSuggestions skills={suggestions.skills} summary={suggestions.summary} t={t} />
  </>;
}

function Field({
  label,
  value,
  t,
  capitalize,
}: {
  label: string;
  value: string | null | undefined;
  t: (path: string, vars?: Record<string, string | number>) => string;
  capitalize?: boolean;
}) {
  const display = value && value.trim() ? value : t('import.notProvided');
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wide text-gray-400 font-semibold mb-0.5">
        {label}
      </dt>
      <dd className={`text-gray-800 ${capitalize ? 'capitalize' : ''}`}>{display}</dd>
    </div>
  );
}
