'use client';

import { ExternalLink } from 'lucide-react';
import {
  DETAIL_FIELD_NAMES,
  type DetailFields,
  type FacetTruth,
  type FacetValue,
  safeHttpUrl,
} from '@/lib/detail-fields';
import { Section } from './DetailSections';
import type { TFunc } from './types';

// Three tones for three states, each with its own words — never colour alone.
// "Not provided" is deliberately the quietest: it is a statement that nobody
// said, not a warning that something is wrong.
const STATE_STYLE: Record<FacetTruth['state'], string> = {
  source: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  inferred: 'bg-amber-50 text-amber-800 border-amber-200 border-dashed',
  unknown: 'bg-gray-50 text-gray-500 border-gray-200',
};

// Enumerated wire values → display keys. Anything not listed renders as the
// raw string: it is source text (a department, a duration), not a code.
const VALUE_KEYS: Record<string, Record<string, string>> = {
  paid: { yes: 'paidYes', stipend: 'paidStipend', no: 'paidNo' },
  international_students: { yes: 'intlYes', no: 'intlNo' },
  citizenship: { required: 'citizenshipRequired', not_required: 'citizenshipNotRequired' },
  remote_option: { remote: 'remote', hybrid: 'hybrid', no: 'onsite' },
  effort: { low: 'low', high: 'high' },
};
const LIST_VALUE_KEYS: Record<string, Record<string, string>> = {
  requirements: {
    resume: 'resume',
    cover_letter: 'cover_letter',
    transcript: 'transcript',
    recommendation: 'recommendation',
  },
};

function formatValue(facet: string, value: FacetValue, t: TFunc): string {
  if (typeof value === 'boolean') {
    // The only boolean facet is `rolling`, and the server sends it only as
    // true. A false here would be a claim the server never makes.
    return facet === 'rolling' && value ? t('detail.facts.values.rolling') : '';
  }
  if (Array.isArray(value)) {
    const keys = LIST_VALUE_KEYS[facet];
    return value.map((v) => (keys?.[v] ? t(`detail.facts.values.${keys[v]}`) : v)).join(', ');
  }
  const key = VALUE_KEYS[facet]?.[String(value)];
  return key ? t(`detail.facts.values.${key}`) : String(value);
}

export function StateTag({ truth, t }: { truth: FacetTruth; t: TFunc }) {
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] font-semibold uppercase tracking-wide ${STATE_STYLE[truth.state]}`}
      data-state={truth.state}
    >
      {t(`detail.facts.state.${truth.state}`)}
    </span>
  );
}

const UNKNOWN_HINT_FACETS = new Set([
  'international_students',
  'citizenship',
  'paid',
  'deadline',
  'location',
]);

function FacetRow({ field, facet, truth, t }: {
  field: string;
  facet: string;
  truth: FacetTruth;
  t: TFunc;
}) {
  const label = t(`detail.facts.facets.${facet}`);
  const isLink = facet === 'application_url' && truth.state !== 'unknown';
  const href = isLink && typeof truth.value === 'string' ? safeHttpUrl(truth.value) : null;
  const text = truth.state === 'unknown' ? null : formatValue(facet, truth.value, t);
  const quote = truth.state === 'source' ? truth.quote : undefined;
  const quoteHref = quote?.sourceUrl ? safeHttpUrl(quote.sourceUrl) : null;
  return (
    <div
      className="flex flex-col gap-1 py-2 border-b border-gray-50 last:border-b-0"
      data-testid={`fact-${field}-${facet}`}
      data-state={truth.state}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <dt className="text-[11px] text-gray-400 uppercase tracking-wider">{label}</dt>
        <StateTag truth={truth} t={t} />
      </div>
      <dd className={`text-[14px] break-words ${truth.state === 'unknown' ? 'text-gray-400 italic' : 'text-gray-800'}`}>
        {truth.state === 'unknown'
          ? (UNKNOWN_HINT_FACETS.has(facet)
            ? t(`detail.facts.unknownHint.${facet}`)
            : t('detail.facts.state.unknown'))
          : href
            ? (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-indigo-600 hover:underline"
              >
                {t('detail.facts.values.openLink')}
                <ExternalLink className="w-3 h-3" aria-hidden="true" />
              </a>
            )
            : text}
      </dd>
      {quote && (
        <dd className="text-[12px] text-gray-500">
          <q data-testid={`fact-${field}-${facet}-quote`}>{quote.text}</q>
          {(quoteHref || quote.observedAt) && (
            <span
              className="ml-2 text-[11px] text-gray-400 inline-flex flex-wrap gap-x-2"
              data-testid={`fact-${field}-${facet}-quote-source`}
            >
              {quoteHref && (
                <a href={quoteHref} target="_blank" rel="noopener noreferrer" className="hover:underline">
                  {t('detail.facts.sourceLink')}
                </a>
              )}
              {quote.observedAt && <span>{t('detail.facts.observed', { date: quote.observedAt })}</span>}
            </span>
          )}
        </dd>
      )}
      {truth.state === 'inferred' && (
        <dd className="text-[11px] text-amber-700" data-testid={`fact-${field}-${facet}-basis`}>
          {t(`detail.facts.basis.${truth.basis}`)}
        </dd>
      )}
    </div>
  );
}

/**
 * Every detail field, each facet tagged Source says / System inference / Not
 * provided, with the page's own sentence (and where and when it was read)
 * under a source value the server checked against page text. Renders what
 * the server classified and nothing else — see `readDetailFields` for why
 * this never re-derives a state from the flat record.
 */
export function DetailFactsSection({
  fields,
  isFaculty,
  t,
}: {
  fields: DetailFields;
  isFaculty: boolean;
  t: TFunc;
}) {
  return (
    <Section title={t('detail.facts.title')}>
      <p className="text-[12px] text-gray-500 mb-2">{t('detail.facts.legend')}</p>
      {isFaculty && (
        <p className="text-[12px] text-gray-500 mb-4" data-testid="facts-faculty-note">
          {t('detail.facts.facultyNote')}
        </p>
      )}
      <div className="space-y-5">
        {DETAIL_FIELD_NAMES.map((name) => {
          const field = fields[name];
          const sourceHref = field.sourceUrl ? safeHttpUrl(field.sourceUrl) : null;
          return (
            <div key={name} data-testid={`fact-field-${name}`} data-state={field.state}>
              <h3 className="text-[12px] font-semibold text-gray-700 mb-1">
                {t(`detail.facts.fields.${name}`)}
              </h3>
              <dl>
                {field.facets.map(({ facet, truth }) => (
                  <FacetRow
                    key={`${facet}:${truth.state}`}
                    field={name}
                    facet={facet}
                    truth={truth}
                    t={t}
                  />
                ))}
              </dl>
              {field.state !== 'unknown' && (sourceHref || field.observedAt) && (
                <p className="mt-1 text-[11px] text-gray-400 flex flex-wrap gap-x-3">
                  {sourceHref && (
                    <a href={sourceHref} target="_blank" rel="noopener noreferrer" className="hover:underline">
                      {t('detail.facts.sourceLink')}
                    </a>
                  )}
                  {field.observedAt && <span>{t('detail.facts.observed', { date: field.observedAt })}</span>}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </Section>
  );
}
