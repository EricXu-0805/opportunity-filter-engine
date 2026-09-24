import type {
  ExperienceEntry, ExperienceSource, ProfileData, ResumeFact, ResumeMasterV1,
  ResumeExperienceRef, ResumeMasterSectionKind,
} from './types';
import { isActiveExperience, validateExperienceEntries, type ExperienceSourceContext } from './experience-evidence';
import { MAX_RESUME_TEXT_CHARACTERS, resumeTextCharacters } from './resume-input';

export const MAX_RESUME_MASTER_FACTS = 300;
export const MAX_RESUME_MASTER_CHARACTERS = 60_000;
export const MAX_RESUME_MASTER_RECORDS = 300;
export const RESUME_MASTER_SECTIONS = ['basics', 'education', 'activities', 'publications', 'skills'] as const;
const DIGEST = /^[a-f0-9]{64}$/;
const STATUSES = new Set(['candidate', 'confirmed', 'rejected', 'withdrawn']);
const ACTIVITY_KINDS = new Set(['employment', 'research', 'project', 'volunteer', 'other']);
const BASIC_FIELDS = ['name', 'email', 'phone', 'location'] as const;
const EDUCATION_FIELDS = ['school', 'degree', 'field', 'start', 'end'] as const;
const ACTIVITY_FIELDS = ['title', 'organization', 'location', 'start', 'end', 'url'] as const;
const PUBLICATION_FIELDS = ['title', 'authors', 'venue', 'date', 'publication_status', 'url', 'doi'] as const;

export type ResumeMasterValidationCode =
  | 'invalid_master' | 'invalid_fact' | 'invalid_source' | 'invalid_unicode' | 'duplicate_id'
  | 'too_many_facts' | 'too_many_records' | 'value_limit' | 'quote_limit' | 'invalid_reference'
  | 'invalid_order' | 'invalid_range' | 'revision_limit';
export type ResumeMasterValidation =
  | { ok: true; value: ResumeMasterV1 | null }
  | { ok: false; code: ResumeMasterValidationCode };

export class ResumeMasterError extends Error {
  constructor(public readonly code: ResumeMasterValidationCode) {
    super(code); // Never include a rejected value, quote, or stored document.
    this.name = 'ResumeMasterError';
  }
}
function fail(code: ResumeMasterValidationCode): never { throw new ResumeMasterError(code); }
function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
function shape(value: unknown, required: readonly string[], optional: readonly string[] = []): asserts value is Record<string, unknown> {
  if (!record(value) || required.some((key) => !Object.hasOwn(value, key))
    || Object.keys(value).some((key) => !required.includes(key) && !optional.includes(key))) fail('invalid_master');
}
function unicode(value: string): boolean {
  for (const character of value) {
    const point = character.codePointAt(0)!;
    if (point >= 0xd800 && point <= 0xdfff) return false;
  }
  return true;
}
function text(value: unknown, max: number, code: ResumeMasterValidationCode): asserts value is string {
  if (typeof value !== 'string' || !value.trim()) fail(code);
  if (!unicode(value)) fail('invalid_unicode');
  if (resumeTextCharacters(value) > max) fail(code);
}
function positive(value: unknown): value is number { return Number.isSafeInteger(value) && (value as number) > 0; }
function sourceValid(value: unknown): asserts value is ExperienceSource {
  if (!record(value)) fail('invalid_source');
  if (value.kind === 'manual') {
    if (Object.keys(value).length !== 1) fail('invalid_source');
    return;
  }
  if (value.kind !== 'resume' || Object.keys(value).length !== 5
    || !['kind', 'signature', 'quote', 'start', 'end'].every((key) => Object.hasOwn(value, key))
    || typeof value.signature !== 'string' || !DIGEST.test(value.signature)) fail('invalid_source');
  text(value.quote, MAX_RESUME_MASTER_CHARACTERS, 'quote_limit');
  if (!Number.isSafeInteger(value.start) || (value.start as number) < 0
    || !Number.isSafeInteger(value.end) || (value.end as number) <= (value.start as number)
    || (value.end as number) > MAX_RESUME_TEXT_CHARACTERS
    || (value.end as number) - (value.start as number) !== resumeTextCharacters(value.quote)) fail('invalid_source');
}
function factValid(value: unknown): asserts value is ResumeFact {
  if (!record(value) || Object.keys(value).length !== 5
    || !['id', 'revision', 'status', 'value', 'source'].every((key) => Object.hasOwn(value, key))) fail('invalid_fact');
  text(value.id, 80, 'invalid_fact');
  if (!positive(value.revision) || typeof value.status !== 'string' || !STATUSES.has(value.status)) fail('invalid_fact');
  text(value.value, MAX_RESUME_MASTER_CHARACTERS, 'value_limit');
  sourceValid(value.source);
}

/** Structural validation preserves historical facts/references. Eligibility is a
 *  separate check against the caller's accepted, current source and entries. */
export function validateResumeMaster(value: unknown): ResumeMasterValidation {
  if (value === undefined || value === null) return { ok: true, value: null };
  try {
    shape(value, ['version', 'id', 'revision', 'source_signature', 'basics', 'education', 'activities',
      'publications', 'skills', 'other_sections', 'section_order', 'unmapped_ranges']);
    if (value.version !== 1 || !positive(value.revision)
      || (value.source_signature !== null && (typeof value.source_signature !== 'string' || !DIGEST.test(value.source_signature)))) fail('invalid_master');
    const ids = new Set<string>();
    let facts = 0;
    let values = 0;
    let quotes = 0;
    let records = 0;
    let refs = 0;
    const id = (candidate: unknown) => {
      text(candidate, 80, 'invalid_master');
      if (ids.has(candidate)) fail('duplicate_id');
      ids.add(candidate);
    };
    id(value.id);
    const list = (candidate: unknown): unknown[] => {
      if (!Array.isArray(candidate)) fail('invalid_master');
      if (candidate.length > MAX_RESUME_MASTER_RECORDS) fail('too_many_records');
      return candidate;
    };
    const addRecord = (candidate: unknown) => {
      id(candidate);
      if (++records > MAX_RESUME_MASTER_RECORDS) fail('too_many_records');
    };
    const addFact = (candidate: unknown) => {
      factValid(candidate);
      id(candidate.id);
      if (++facts > MAX_RESUME_MASTER_FACTS) fail('too_many_facts');
      values += resumeTextCharacters(candidate.value);
      if (candidate.source.kind === 'resume') quotes += resumeTextCharacters(candidate.source.quote);
      if (values > MAX_RESUME_MASTER_CHARACTERS) fail('value_limit');
      if (quotes > MAX_RESUME_MASTER_CHARACTERS) fail('quote_limit');
    };
    const fields = (item: Record<string, unknown>, keys: readonly string[]) => {
      for (const key of keys) if (Object.hasOwn(item, key)) addFact(item[key]);
    };
    const references = (candidate: unknown) => {
      const seen = new Set<string>();
      for (const ref of list(candidate)) {
        if (!record(ref) || Object.keys(ref).length !== 2 || !Object.hasOwn(ref, 'id')
          || !Object.hasOwn(ref, 'revision') || !positive(ref.revision)) fail('invalid_reference');
        text(ref.id, 80, 'invalid_reference');
        if (seen.has(ref.id)) fail('invalid_reference');
        seen.add(ref.id);
        if (++refs > MAX_RESUME_MASTER_RECORDS) fail('too_many_records');
      }
    };
    shape(value.basics, ['links'], BASIC_FIELDS);
    fields(value.basics, BASIC_FIELDS);
    for (const link of list(value.basics.links)) {
      shape(link, ['id', 'label', 'url']);
      addRecord(link.id);
      text(link.label, 120, 'invalid_master');
      addFact(link.url);
    }
    for (const item of list(value.education)) {
      shape(item, ['id', 'details'], EDUCATION_FIELDS);
      addRecord(item.id); fields(item, EDUCATION_FIELDS); references(item.details);
    }
    for (const item of list(value.activities)) {
      shape(item, ['id', 'kind', 'details'], ACTIVITY_FIELDS);
      addRecord(item.id);
      if (typeof item.kind !== 'string' || !ACTIVITY_KINDS.has(item.kind)) fail('invalid_master');
      fields(item, ACTIVITY_FIELDS); references(item.details);
    }
    for (const item of list(value.publications)) {
      shape(item, ['id', 'details'], PUBLICATION_FIELDS);
      addRecord(item.id); fields(item, PUBLICATION_FIELDS); references(item.details);
    }
    for (const fact of list(value.skills)) addFact(fact);
    const sectionIds = new Set<string>(RESUME_MASTER_SECTIONS);
    for (const section of list(value.other_sections)) {
      shape(section, ['id', 'heading', 'items']);
      addRecord(section.id);
      if (sectionIds.has(section.id as string)) fail('invalid_order');
      sectionIds.add(section.id as string);
      text(section.heading, 120, 'invalid_master');
      for (const fact of list(section.items)) addFact(fact);
    }
    if (!Array.isArray(value.section_order) || value.section_order.length !== sectionIds.size
      || new Set(value.section_order).size !== sectionIds.size
      || value.section_order.some((key) => typeof key !== 'string' || !sectionIds.has(key))) fail('invalid_order');
    let previousEnd = 0;
    for (const range of list(value.unmapped_ranges)) {
      if (!record(range) || Object.keys(range).length !== 2 || !Object.hasOwn(range, 'start')
        || !Object.hasOwn(range, 'end') || value.source_signature === null
        || !Number.isSafeInteger(range.start) || (range.start as number) < previousEnd
        || !Number.isSafeInteger(range.end) || (range.end as number) <= (range.start as number)
        || (range.end as number) > MAX_RESUME_TEXT_CHARACTERS) fail('invalid_range');
      previousEnd = range.end as number;
    }
    return { ok: true, value: value as unknown as ResumeMasterV1 };
  } catch (error) {
    if (error instanceof ResumeMasterError) return { ok: false, code: error.code };
    return { ok: false, code: 'invalid_master' };
  }
}
function requireMaster(value: unknown): ResumeMasterV1 | null {
  const result = validateResumeMaster(value);
  if (!result.ok) throw new ResumeMasterError(result.code);
  return result.value;
}

export function createEmptyResumeMaster(id: string = globalThis.crypto.randomUUID()): ResumeMasterV1 {
  return requireMaster({
    version: 1, id, revision: 1, source_signature: null, basics: { links: [] },
    education: [], activities: [], publications: [], skills: [], other_sections: [],
    section_order: [...RESUME_MASTER_SECTIONS], unmapped_ranges: [],
  })!;
}

function mapFacts(master: ResumeMasterV1, map: (fact: ResumeFact) => ResumeFact | null): ResumeMasterV1 {
  const objectFields = <T extends object>(item: T, fields: readonly string[]): T => {
    const next = { ...item } as Record<string, unknown>;
    for (const key of fields) {
      if (Object.hasOwn(next, key)) {
        const mapped = map(next[key] as ResumeFact);
        if (mapped) next[key] = mapped;
        else delete next[key];
      }
    }
    return next as T;
  };
  const mapped = (items: ResumeFact[]) => items.flatMap((fact) => { const next = map(fact); return next ? [next] : []; });
  return {
    ...master,
    basics: {
      ...objectFields(master.basics, BASIC_FIELDS),
      links: master.basics.links.flatMap((link) => { const url = map(link.url); return url ? [{ ...link, url }] : []; }),
    },
    education: master.education.map((item) => objectFields(item, EDUCATION_FIELDS)),
    activities: master.activities.map((item) => objectFields(item, ACTIVITY_FIELDS)),
    publications: master.publications.map((item) => objectFields(item, PUBLICATION_FIELDS)),
    skills: mapped(master.skills),
    other_sections: master.other_sections.map((section) => ({ ...section, items: mapped(section.items) })),
  };
}
function increment(revision: number): number {
  if (revision === Number.MAX_SAFE_INTEGER) fail('revision_limit');
  return revision + 1;
}
function changedMaster(original: ResumeMasterV1, next: ResumeMasterV1): ResumeMasterV1 {
  if (JSON.stringify(original) === JSON.stringify(next)) return original;
  return requireMaster({ ...next, revision: increment(original.revision) })!;
}

export function withdrawResumeMaster(value: unknown): ResumeMasterV1 | null {
  const master = requireMaster(value);
  if (!master) return null;
  const next = mapFacts(master, (fact) => fact.source.kind === 'resume' && fact.status !== 'withdrawn'
    ? { ...fact, status: 'withdrawn', revision: increment(fact.revision) } : fact);
  return changedMaster(master, { ...next, source_signature: null, unmapped_ranges: [] });
}

export function removeResumeMasterSources(value: unknown, retainedEntries?: ExperienceEntry[]): ResumeMasterV1 | null {
  const master = requireMaster(value);
  if (!master) return null;
  const next = mapFacts(master, (fact) => fact.source.kind === 'resume' ? null : fact);
  if (retainedEntries !== undefined) {
    const checked = validateExperienceEntries(retainedEntries);
    if (!checked.ok) fail('invalid_reference');
    const retained = new Map(checked.value.map((entry) => [entry.id, entry.revision]));
    const prune = <T extends { details: ResumeExperienceRef[] }>(item: T): T => ({
      ...item, details: item.details.filter((ref) => retained.get(ref.id) === ref.revision),
    });
    next.education = next.education.map(prune);
    next.activities = next.activities.map(prune);
    next.publications = next.publications.map(prune);
  }
  return changedMaster(master, { ...next, source_signature: null, unmapped_ranges: [] });
}

/** The caller must derive expectedDigest from the exact accepted rawText using
 *  sourceDigest. A supplied digest is not independent proof of source truth. */
export function isActiveResumeFact(fact: ResumeFact, context: ExperienceSourceContext): boolean {
  try { factValid(fact); } catch { return false; }
  if (fact.status !== 'confirmed') return false;
  if (fact.source.kind === 'manual') return true;
  return unicode(context.rawText) && DIGEST.test(context.expectedDigest)
    && fact.source.signature === context.expectedDigest
    && resumeTextCharacters(context.rawText) <= MAX_RESUME_TEXT_CHARACTERS
    && Array.from(context.rawText).slice(fact.source.start, fact.source.end).join('') === fact.source.quote;
}

export function resumeMasterFacts(value: unknown): ResumeFact[] {
  const master = requireMaster(value);
  if (!master) return [];
  const facts: ResumeFact[] = [];
  mapFacts(master, (fact) => { facts.push(fact); return fact; });
  return facts;
}

export interface ResumeMasterPreview {
  sections: Array<{
    id: string;
    kind: ResumeMasterSectionKind;
    heading?: string;
    blocks: Array<{ id: string; lines: string[] }>;
  }>;
  excludedFactCount: number;
  unresolvedExperienceRefs: ResumeExperienceRef[];
}

/** Deterministic preview only. This never writes source/profile skills, promotes
 *  confirmation, sends model context, or truncates a full field/experience. */
export function buildResumeMasterPreview(
  value: unknown, entries: ExperienceEntry[], context: ExperienceSourceContext,
): ResumeMasterPreview {
  const master = requireMaster(value);
  const result: ResumeMasterPreview = { sections: [], excludedFactCount: 0, unresolvedExperienceRefs: [] };
  if (!master) return result;
  const checked = validateExperienceEntries(entries);
  const byId = new Map((checked.ok ? checked.value : []).map((entry) => [entry.id, entry]));
  const fieldLines = (item: object, fields: readonly string[]): string[] => fields.flatMap((key) => {
    const fact = (item as Record<string, ResumeFact | undefined>)[key];
    if (!fact) return [];
    if (isActiveResumeFact(fact, context)) return [fact.value];
    result.excludedFactCount += 1;
    return [];
  });
  const details = (refs: ResumeExperienceRef[]) => refs.flatMap((ref) => {
    const entry = byId.get(ref.id);
    if (entry && entry.revision === ref.revision && isActiveExperience(entry, context)) return [entry.text];
    result.unresolvedExperienceRefs.push({ ...ref });
    return [];
  });
  const sections = new Map<string, ResumeMasterPreview['sections'][number]>();
  const put = (section: ResumeMasterPreview['sections'][number]) => {
    sections.set(section.id, { ...section, blocks: section.blocks.filter((block) => block.lines.length > 0) });
  };
  put({ id: 'basics', kind: 'basics', blocks: [
    { id: master.id, lines: fieldLines(master.basics, BASIC_FIELDS) },
    ...master.basics.links.map((link) => ({ id: link.id, lines: fieldLines(link, ['url']) })),
  ] });
  put({ id: 'education', kind: 'education', blocks: master.education.map((item) => ({ id: item.id,
    lines: [...fieldLines(item, EDUCATION_FIELDS), ...details(item.details)] })) });
  put({ id: 'activities', kind: 'activities', blocks: master.activities.map((item) => ({ id: item.id,
    lines: [...fieldLines(item, ACTIVITY_FIELDS), ...details(item.details)] })) });
  put({ id: 'publications', kind: 'publications', blocks: master.publications.map((item) => ({ id: item.id,
    lines: [...fieldLines(item, PUBLICATION_FIELDS), ...details(item.details)] })) });
  put({ id: 'skills', kind: 'skills', blocks: master.skills.map((fact) => ({ id: fact.id, lines: fieldLines({ fact }, ['fact']) })) });
  for (const section of master.other_sections) put({ id: section.id, kind: 'other', heading: section.heading,
    blocks: section.items.map((fact) => ({ id: fact.id, lines: fieldLines({ fact }, ['fact']) })) });
  result.sections = master.section_order.map((id) => sections.get(id)!).filter((section) => section.blocks.length > 0);
  return result;
}


export interface ResumeMasterEditBase {
  resumeText: string;
  entriesJson: string;
  masterJson: string;
}

/** An in-memory comparison key, never a log/telemetry value. JSONB and other
 *  clients may return different object-key order for the same document. Array
 *  order, exact strings, confirmation states and revisions remain significant. */
export function resumeMasterEditBase(profile: Pick<ProfileData, 'resume_text' | 'experience_entries' | 'resume_master'>): ResumeMasterEditBase {
  const canonical = (value: unknown): string => JSON.stringify(value, (_key, item: unknown) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return item;
    return Object.fromEntries(Object.entries(item as Record<string, unknown>).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0));
  });
  return {
    resumeText: profile.resume_text ?? '',
    entriesJson: canonical(profile.experience_entries ?? []),
    masterJson: canonical(profile.resume_master ?? null),
  };
}
