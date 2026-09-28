/**
 * M03 detail-field truth — the client half of backend/lib/opportunity_detail.py.
 *
 * The server classifies every facet of the ten detail fields as `source`
 * (read off the page), `inferred` (produced by us, with a named basis) or
 * `unknown` (nobody said). This module only READS that classification. It
 * never re-derives one from the flat record, because the flat record is
 * exactly what cannot tell them apart: `citizenship_required: false` is the
 * template most collectors write when the page is silent.
 *
 * Fail-closed in one direction only: anything malformed — a missing bucket, a
 * value of the wrong shape, an unrecognised basis — becomes `unknown`. Nothing
 * malformed can become `source`, and no unknown can become false, unpaid,
 * ineligible or "no deadline".
 */

export const DETAIL_FIELDS_VERSION = 'm03-v1';

export const DETAIL_FIELD_NAMES = [
  'school',
  'department',
  'professor_or_lab',
  'research_content',
  'eligibility',
  'required_skills',
  'timing',
  'funding',
  'location',
  'application_method',
] as const;
export type DetailFieldName = typeof DETAIL_FIELD_NAMES[number];

// Mirrors FIELD_FACETS in backend/lib/opportunity_detail.py. The contract test
// (detail-fields.contract.test.tsx) fails if the two drift.
export const FIELD_FACETS: Record<DetailFieldName, readonly string[]> = {
  school: ['institution'],
  department: ['department'],
  professor_or_lab: ['principal_investigator', 'faculty_rank', 'lab_or_program'],
  research_content: ['research_areas'],
  eligibility: [
    'class_year',
    'majors',
    'min_gpa',
    'international_students',
    'citizenship',
    'work_authorization_notes',
  ],
  required_skills: ['required', 'preferred', 'mentioned'],
  timing: ['deadline', 'rolling', 'application_window', 'start_date', 'duration', 'posted_date'],
  funding: ['paid', 'compensation'],
  location: ['location', 'remote_option'],
  application_method: ['application_url', 'contact_method', 'requirements', 'effort'],
};

export const INFERENCE_BASES = [
  'text_scan',
  'model_extraction',
  'external_enrichment',
  'estimate',
  'program_policy',
  'collector_default',
  'derived_from_source',
] as const;
export type InferenceBasis = typeof INFERENCE_BASES[number];

export type FacetValue = string | number | boolean | string[];

export type FacetTruth =
  | { state: 'source'; value: FacetValue }
  | { state: 'inferred'; value: FacetValue; basis: InferenceBasis }
  | { state: 'unknown' };

export interface FieldTruth {
  state: 'source' | 'inferred' | 'unknown';
  facets: { facet: string; truth: FacetTruth }[];
  sourceUrl: string | null;
  observedAt: string | null;
}

export type DetailFields = Record<DetailFieldName, FieldTruth>;

const UNKNOWN: FacetTruth = { state: 'unknown' };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asFacetValue(value: unknown): FacetValue | null {
  if (typeof value === 'string') return value.trim() ? value : null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'boolean') return value;
  if (Array.isArray(value)) {
    const items = value.filter((v): v is string => typeof v === 'string' && v.trim() !== '');
    return items.length > 0 && items.length === value.length ? items : null;
  }
  return null;
}

/** An http(s) URL string, or null. The server already ran the public URL
 *  boundary; this is the client's belt for a stale or hand-built payload. */
export function safeHttpUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.toString() : null;
  } catch {
    return null;
  }
}

/**
 * Every truth the server reports for one facet: a source row, an inference
 * row, both (a professor's stated research text beside topic tags we derived
 * from a matched publication record), or a single unknown row.
 */
function readFacet(raw: Record<string, unknown>, facet: string): FacetTruth[] {
  const explicit = isRecord(raw.explicit) ? raw.explicit : {};
  const inferred = isRecord(raw.inferred) ? raw.inferred : {};
  const out: FacetTruth[] = [];
  if (facet in explicit) {
    // A facet the server put in `explicit` with an unreadable value is not
    // quietly demoted to an inference: we cannot say what it is.
    const value = asFacetValue(explicit[facet]);
    if (value !== null) out.push({ state: 'source', value });
  }
  if (facet in inferred) {
    const entry = inferred[facet];
    if (isRecord(entry)) {
      const value = asFacetValue(entry.value);
      const basis = entry.basis;
      if (value !== null && INFERENCE_BASES.includes(basis as InferenceBasis)) {
        out.push({ state: 'inferred', value, basis: basis as InferenceBasis });
      }
    }
  }
  return out.length > 0 ? out : [UNKNOWN];
}

function readField(raw: unknown, name: DetailFieldName): FieldTruth {
  const field = isRecord(raw) ? raw : {};
  const facets = FIELD_FACETS[name].flatMap((facet) =>
    readFacet(field, facet).map((truth) => ({ facet, truth })),
  );
  // Recomputed from the facets rather than trusted from `state`: a payload
  // whose summary says `source` while every facet reads unknown would
  // otherwise render a confirmed badge over nothing.
  const state = facets.some((f) => f.truth.state === 'source')
    ? 'source'
    : facets.some((f) => f.truth.state === 'inferred')
      ? 'inferred'
      : 'unknown';
  const provenance = isRecord(field.provenance) ? field.provenance : {};
  const observed = provenance.observed_at;
  return {
    state,
    facets,
    sourceUrl: safeHttpUrl(provenance.source_url),
    observedAt: typeof observed === 'string' && /^\d{4}-\d{2}-\d{2}/.test(observed)
      ? observed.slice(0, 10)
      : null,
  };
}

/**
 * The detail-field truth on a payload, or null when there is none to read.
 *
 * Null (older backend, cached payload, unknown version) means "this client
 * has no per-field classification" — callers fall back to the legacy
 * sections, which carry their own hedges. It never means "everything is
 * confirmed".
 */
export function readDetailFields(payload: { detail_fields?: unknown } | null | undefined): DetailFields | null {
  const envelope = payload?.detail_fields;
  if (!isRecord(envelope) || envelope.version !== DETAIL_FIELDS_VERSION) return null;
  const fields = isRecord(envelope.fields) ? envelope.fields : {};
  const out = {} as DetailFields;
  for (const name of DETAIL_FIELD_NAMES) out[name] = readField(fields[name], name);
  return out;
}
