import type {
  ExperienceEntry, ExperienceSource, ProfileData, ResumeActivityItem, ResumeFact, ResumeMasterV1,
  ResumeExperienceRef, ResumeMasterSectionKind,
} from './types';
import { isActiveExperience, validateExperienceEntries, type ExperienceSourceContext } from './experience-evidence';
import {
  BULLET_LINE, MAX_RESUME_TEXT_CHARACTERS, RESUME_EMAIL, RESUME_PHONE, RESUME_URL, resumeContactLine,
  resumeSectionHeading, resumeTextCharacters, type ResumeSectionKind,
} from './resume-input';

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

const MONTH = String.raw`(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?`;
const YEAR = String.raw`(?:19|20)\d{2}`;
const DATE = String.raw`(?:(?:${MONTH}|Spring|Summer|Fall|Autumn|Winter)\s+${YEAR}|\d{1,2}/${YEAR}|${YEAR}(?:[./]\d{1,2}|年(?:\d{1,2}月)?)?)`;
const DATE_RANGE = new RegExp(String.raw`(${DATE})\s*(?:[-–—~]|to)\s*(${DATE}|Present|Current|Now|至今)`, 'iu');
const EXPECTED_DATE = new RegExp(String.raw`(?:expected|anticipated|graduating|graduation|class of)\s*:?\s*${DATE}|${DATE}\s*\(expected\)`, 'iu');
// One date that ends a line after a column gap or separator: "Project<tab>Spring 2025".
const LAST_DATE = new RegExp(String.raw`(?:^|\t|\s[|–—-]\s)(${DATE})\s*$`, 'u');
const PLACE = String.raw`[\p{Lu}][\p{L}.' -]*,\s*(?:[A-Z]{2}|USA|China|Canada|United States|United Kingdom|UK|India|Japan|Korea|South Korea|Singapore|Germany|France|Hong Kong|Taiwan|Australia)`;
const LABELLED_PLACE = new RegExp(String.raw`^(?:[\p{L} ]{2,20}:\s*)?(${PLACE})$`, 'u');
const TRAILING_PLACE = new RegExp(String.raw`(?:\(\s*(${PLACE})\s*\)|(?:,\s*|\t|\s[|–—-]\s)(${PLACE}))\s*$`, 'u');
const PERSON = /^(?:[\p{Lu}][\p{L}.'’-]*)(?:\s+[\p{Lu}][\p{L}.'’-]*){1,4}$|^\p{Script=Han}{2,4}$/u;
const SCHOOL = /\b(?:University|College|Institute|School|Academy|Polytechnic|UNIVERSITY|COLLEGE|INSTITUTE|SCHOOL|ACADEMY|POLYTECHNIC)\b|大学|学院/u;
const DEGREE = /(?<![\p{L}.])(?:(?:B|M)\.?\s?(?:S|A|Sc|Eng|E|Ed)\.?|Ph\.?\s?D\.?|MBA|(?:Bachelor|Master)(?:'s|’s)?(?: of (?:Science|Arts|Engineering|Fine Arts|Business Administration|Applied Science))?|Associate(?:'s|’s)? of (?:Science|Arts)|Doctor of Philosophy|本科|学士|硕士|博士)(?![\p{L}])/u;
const FIELD = /^(?:,\s*|\s+in\s+|\s+of\s+|\s+)((?:[\p{Lu}][\p{L}&'-]*)(?:\s+(?:(?:and|&|of|in)\s+)?[\p{Lu}][\p{L}&'-]*)*)/u;
const NOT_A_FIELD = new RegExp(String.raw`^(?:${MONTH}|Spring|Summer|Fall|Autumn|Winter|Expected|Class|GPA|Minor|Honors|Present)\b`, 'u');
const ROLE = /\b(?:intern|assistant|engineer|researcher|developer|analyst|manager|lead|leader|fellow|tutor|consultant|scientist|coordinator|director|president|officer|volunteer|member|designer|associate|specialist|technician|founder|chair|captain|mentor|instructor|grader|programmer|trainee|editor|writer)s?\b/iu;
const FIELD_SEPARATOR = /\t|\s[|–—]\s|\s-\s|,\s|\s(?:at|@)\s/u;
const JOINERS = new Set(['of', 'and', '&', 'for', 'the', 'in', 'at', 'on', 'de', 'la']);

/** A row of names: every field is a few words that start with a capital or
 *  a digit, joined by small words ("Teaching Assistant, CS 225 Data
 *  Structures", "Department of Computer Science"). */
function namesRow(text: string): boolean {
  return text.split(FIELD_SEPARATOR).every((field) => {
    const words = field.trim().split(/\s+/u);
    return words.length <= 6 && words.every((word) => JOINERS.has(word) || /^[^\p{L}\p{N}]*[\p{Lu}\p{N}]/u.test(word));
  });
}
const SKILL_LABEL = /^[\p{L} &/]{2,30}:\s*/u;
// "School: …" / "学校: …" rows, as this product's own résumé export prints them.
const LABELLED = /^\s*([\p{L}][\p{L} /-]{0,28}?)\s*[:：]\s*(\S.*?)\s*$/u;
const LABELS = new Map<string, string>(Object.entries({
  email: 'email', 'e-mail': 'email', 邮箱: 'email', phone: 'phone', mobile: 'phone', 电话: 'phone', 手机: 'phone',
  location: 'location', address: 'location', 地点: 'location', 所在地: 'location',
  school: 'school', university: 'school', 学校: 'school', degree: 'degree', 学位: 'degree',
  field: 'field', major: 'field', 'field of study': 'field', 专业: 'field',
  start: 'start', 'start date': 'start', 开始: 'start', end: 'end', 'end date': 'end', graduation: 'end', 结束: 'end',
  organization: 'organization', company: 'organization', employer: 'organization', 机构: 'organization',
  title: 'title', role: 'title', position: 'title', 职位: 'title',
}));

interface SourceLine { text: string; start: number }
interface ProposedItem { fields: Partial<Record<string, ResumeFact>>; kind?: ResumeActivityItem['kind'] }

/** Candidate facts found verbatim in the résumé: contact details, schools and
 *  degrees, roles and projects with their dates, and the skills list. Every
 *  fact quotes its exact source span and starts unconfirmed; nothing is
 *  inferred beyond where a span begins and ends. Fields the master already
 *  holds stay as they are, and a span that was proposed before is never
 *  proposed again, including one the student excluded. */
export function proposeResumeMaster(value: unknown, rawText: string, signature: string): ResumeMasterV1 {
  const master = requireMaster(value) ?? createEmptyResumeMaster();
  const points = Array.from(rawText);
  const lines: SourceLine[] = [];
  for (let start = 0, index = 0; index <= points.length; index++) {
    if (index === points.length || points[index] === '\n') {
      lines.push({ text: points.slice(start, index).join('').replace(/\r$/u, ''), start });
      start = index + 1;
    }
  }
  /** The trimmed text between two UTF-16 offsets of a line, as a candidate. */
  const fact = (line: SourceLine, from: number, to: number): ResumeFact | undefined => {
    const raw = line.text.slice(from, to);
    const quote = raw.trim();
    if (!quote) return undefined;
    const start = line.start + Array.from(line.text.slice(0, from + raw.indexOf(quote))).length;
    return { id: globalThis.crypto.randomUUID(), revision: 1, status: 'candidate', value: quote,
      source: { kind: 'resume', signature, quote, start, end: start + Array.from(quote).length } };
  };
  const match = (line: SourceLine, found: RegExpExecArray | null, group = 0, base = 0): ResumeFact | undefined => {
    if (!found || found[group] === undefined) return undefined;
    const offset = base + found.index + found[0].indexOf(found[group]);
    return fact(line, offset, offset + found[group].length);
  };
  const place = (found: RegExpExecArray) => (found[1] ? 1 : 2);
  /** Date range, an "expected" graduation date, or one trailing date. Returns
   *  where the dates begin, so the rest of the line can be read as names. */
  const dates = (line: SourceLine, item: ProposedItem, expected: boolean): number | undefined => {
    const range = DATE_RANGE.exec(line.text);
    if (range) {
      item.fields.start ??= match(line, range, 1);
      item.fields.end ??= match(line, range, 2);
      return range.index;
    }
    const graduation = expected ? EXPECTED_DATE.exec(line.text) : null;
    if (graduation) {
      item.fields.end ??= match(line, graduation);
      return graduation.index;
    }
    const last = LAST_DATE.exec(line.text);
    if (last) item.fields.start ??= match(line, last, 1);
    return last?.index;
  };

  const basics: Partial<Record<(typeof BASIC_FIELDS)[number], ResumeFact>> = {};
  const links: ResumeFact[] = [];
  const education: ProposedItem[] = [];
  const activities: ProposedItem[] = [];
  const skills: ResumeFact[] = [];
  /** Name (first line only), email, phone, place and profile links. */
  const contact = (line: SourceLine, first: boolean) => {
    const email = RESUME_EMAIL.exec(line.text);
    basics.email ??= match(line, email);
    basics.phone ??= match(line, RESUME_PHONE.exec(line.text));
    for (const url of line.text.matchAll(new RegExp(RESUME_URL.source, 'giu'))) {
      if (email && url.index >= email.index && url.index < email.index + email[0].length) continue;
      const link = match(line, url);
      if (link) links.push(link);
    }
    const labelled = LABELLED.exec(line.text);
    if (labelled && LABELS.get(labelled[1].toLowerCase()) === 'location') basics.location ??= match(line, labelled, 2);
    let offset = 0;
    for (const segment of line.text.split(/(\s[|•·]\s|\t)/u)) {
      if (first && offset === 0 && PERSON.test(segment.trim())) basics.name ??= fact(line, 0, segment.length);
      basics.location ??= match(line, LABELLED_PLACE.exec(segment.trim()), 1, offset + segment.indexOf(segment.trim()));
      offset += segment.length;
    }
  };
  const activity = (kind: ResumeActivityItem['kind']): ProposedItem => {
    const item: ProposedItem = { fields: {}, kind };
    activities.push(item);
    return item;
  };

  // Sections that mark their points with glyph bullets. In the others a
  // point has no glyph, so a short line with a comma or a role word in it is
  // as likely a point as a role row.
  const sectionOf: number[] = [];
  const glyphSections = new Set<number>();
  lines.forEach((line, index) => {
    sectionOf[index] = (sectionOf[index - 1] ?? 0) + (resumeSectionHeading(line.text.trim()) ? 1 : 0);
    if (BULLET_LINE.test(line.text)) glyphSections.add(sectionOf[index]);
  });

  let section: { kind: ResumeSectionKind; heading: string } | null = null;
  let current: ProposedItem | null = null;
  let headerOpen = false;
  let opening = true;
  for (const [index, line] of lines.entries()) {
    const text = line.text.trim();
    if (!text) continue;
    // The first line names the student, even when it is set in capitals,
    // unless it is a heading (a layout that prints the main column first).
    if (opening) {
      opening = false;
      if (PERSON.test(text.split(/\s[|•·]\s|\t/u)[0].trim()) && !resumeSectionHeading(text)) {
        contact(line, true);
        continue;
      }
    }
    const role = section && (section.kind === 'experience' || section.kind === 'projects');
    const heading = resumeSectionHeading(text);
    if (heading && !(role && heading === 'other' && ROLE.test(text))) {
      section = { kind: heading, heading: text.toLowerCase() };
      current = null;
      headerOpen = false;
      continue;
    }
    // Above the first heading, and any contact line elsewhere (a sidebar
    // printed after the main column).
    if (!section || resumeContactLine(text)) {
      contact(line, false);
      if (!section) continue;
    }
    if (BULLET_LINE.test(line.text)) {
      headerOpen = false;
      continue;
    }
    const labelled = LABELLED.exec(line.text);
    const label = labelled ? LABELS.get(labelled[1].toLowerCase()) : undefined;
    if (label && section.kind === 'education' && ['school', 'degree', 'field', 'start', 'end'].includes(label)) {
      if (!current || (label === 'school' && current.fields.school)) {
        current = { fields: {} };
        education.push(current);
      }
      current.fields[label] ??= match(line, labelled, 2);
      continue;
    }
    if (label && role && ['title', 'organization', 'location', 'start', 'end'].includes(label)) {
      if (!current || label === 'title') current = activity(section.kind === 'projects' ? 'project' : 'other');
      current.fields[label] ??= match(line, labelled, 2);
      headerOpen = true;
      continue;
    }
    const words = text.split(/\s+/u).length;
    const sentence = /[.!?]$/u.test(text);
    if (section.kind === 'skills') {
      const skillLabel = SKILL_LABEL.exec(line.text);
      let offset = skillLabel ? skillLabel[0].length : 0;
      for (const item of line.text.slice(offset).split(/([,;|•·、，；\t])/u)) {
        if (/[\p{L}\p{N}]/u.test(item) && item.trim().split(/\s+/u).length <= 4 && Array.from(item.trim()).length <= 60) {
          const skill = fact(line, offset, offset + item.length);
          if (skill) skills.push(skill);
        }
        offset += item.length;
      }
    } else if (section.kind === 'education') {
      const trailing = TRAILING_PLACE.exec(line.text);
      const content = trailing ? line.text.slice(0, trailing.index) : line.text;
      const degree = DEGREE.exec(content);
      const school = SCHOOL.test(content);
      if (!school && !degree && !DATE_RANGE.test(content) && !EXPECTED_DATE.test(content)) continue;
      if (!current || (school && current.fields.school)) {
        current = { fields: {} };
        education.push(current);
      }
      if (school) {
        const cut = content.search(/\s[-–—|]\s|\t|\(/u);
        // A Chinese school name is one token: "北京大学 物理学院 本科".
        const han = /\S*(?:大学|学院)\S*/u.exec(content);
        current.fields.school ??= han ? match(line, han) : fact(line, 0, cut < 0 ? content.length : cut);
      }
      if (degree) {
        current.fields.degree ??= match(line, degree);
        const rest = degree.index + degree[0].length;
        const field = FIELD.exec(content.slice(rest));
        if (field && !NOT_A_FIELD.test(field[1])) current.fields.field ??= match(line, field, 1, rest);
      }
      dates(line, current, true);
    } else if (role) {
      const project = section.kind === 'projects';
      const range = DATE_RANGE.test(line.text);
      const glyphs = glyphSections.has(sectionOf[index]);
      if (current && headerOpen && !project && words <= 12 && !sentence && !(range && current.fields.start)
        && (glyphs || range || namesRow(text))) {
        // A second header row: the organization, place or dates of the same role.
        dates(line, current, false);
        const trailing = TRAILING_PLACE.exec(line.text);
        if (trailing) current.fields.location ??= match(line, trailing, place(trailing));
        const head = (trailing ? line.text.slice(0, trailing.index) : line.text).split(/\t/u)[0];
        if (!current.fields.organization && !DATE_RANGE.test(head)) current.fields.organization = fact(line, 0, head.length);
        continue;
      }
      // A list printed with graphic markers has no bullet glyphs: a role or
      // project header names one, usually with dates or a separator; anything
      // else (an accomplishment sentence) stays with the experience library.
      const header = range || (words <= 12 && !sentence && (project
        ? /\t|\s[-–—|:]\s/u.test(line.text) || words <= 8
        : glyphs ? ROLE.test(text) || FIELD_SEPARATOR.test(text)
          : namesRow(text) && text.split(FIELD_SEPARATOR).slice(0, 2).some((field) => ROLE.test(field))))
        || (project && words > 12 && /^[^\t]{1,80}?\s[-–—|:]\s/u.test(line.text) && !/^\p{Ll}/u.test(text));
      if (!header) {
        headerOpen = false;
        continue;
      }
      current = activity(project ? 'project'
        : /volunteer/u.test(section.heading) ? 'volunteer'
          : /leadership|activities/u.test(section.heading) ? 'other'
            : /research/u.test(section.heading) || /\bresearch\b|\blab(?:oratory)?\b/iu.test(text) ? 'research' : 'employment');
      headerOpen = true;
      let head = line.text.slice(0, dates(line, current, false)).replace(/[\s|–—-]+$/u, '');
      const trailing = TRAILING_PLACE.exec(head);
      if (trailing) {
        current.fields.location = match(line, trailing, place(trailing));
        head = head.slice(0, trailing.index);
      }
      if (project) {
        const title = head.split(/\s[-–—|:]\s|\t/u)[0].replace(/\s*\([^)]*\)\s*$/u, '');
        current.fields.title = fact(line, 0, title.length);
        continue;
      }
      const split = FIELD_SEPARATOR.exec(head);
      const before = fact(line, 0, split ? split.index : head.length);
      const after = split ? fact(line, split.index + split[0].length, head.length) : undefined;
      // "Organization — Title" layouts put the role second.
      const swap = !!after && ROLE.test(after.value) && !ROLE.test(before?.value ?? '');
      current.fields.title = swap ? after : before;
      current.fields.organization = swap ? before : after;
    }
  }

  const taken = new Set<string>();
  for (const item of resumeMasterFacts(master)) {
    if (item.source.kind === 'resume' && item.source.signature === signature) taken.add(`${item.source.start}:${item.source.end}`);
  }
  const fresh = (item: ResumeFact | undefined): item is ResumeFact => !!item && item.source.kind === 'resume'
    && !taken.has(`${item.source.start}:${item.source.end}`);
  const next: ResumeMasterV1 = JSON.parse(JSON.stringify(master));
  // A withdrawn fact quotes a résumé that was replaced; it stays visible in
  // a list, but it holds no field against the current résumé's candidate.
  const holds = (item: ResumeFact | undefined) => !!item && item.status !== 'withdrawn';
  for (const key of BASIC_FIELDS) if (!holds(next.basics[key]) && fresh(basics[key])) next.basics[key] = basics[key];
  const linked = new Set(next.basics.links.filter((link) => holds(link.url)).map((link) => link.url.value));
  for (const url of links) {
    const label = url.value.replace(/^(?:https?:\/\/)?(?:www\.)?/iu, '').split('/')[0];
    // "https:///x" names no host, so it is no profile link to offer.
    if (!fresh(url) || linked.has(url.value) || !label.trim() || resumeTextCharacters(label) > 120) continue;
    next.basics.links.push({ id: globalThis.crypto.randomUUID(), label, url });
    linked.add(url.value);
  }
  // An item proposed before (any of its spans taken) is not proposed again.
  const unseen = (item: ProposedItem) => {
    const fields = Object.entries(item.fields).filter((entry): entry is [string, ResumeFact] => !!entry[1]);
    return fields.length && fields.every(([, field]) => fresh(field)) ? Object.fromEntries(fields) : null;
  };
  for (const item of education) {
    const fields = unseen(item);
    if (fields) next.education.push({ id: globalThis.crypto.randomUUID(), ...fields, details: [] });
  }
  for (const item of activities) {
    const fields = unseen(item);
    if (fields) next.activities.push({ id: globalThis.crypto.randomUUID(), kind: item.kind!, ...fields, details: [] });
  }
  const named = new Set(next.skills.filter(holds).map((skill) => skill.value.trim().toLowerCase()));
  for (const skill of skills) {
    if (!fresh(skill) || named.has(skill.value.toLowerCase())) continue;
    next.skills.push(skill);
    named.add(skill.value.toLowerCase());
  }
  if (JSON.stringify(next) === JSON.stringify(master)) return master;
  return requireMaster({ ...next, source_signature: signature })!;
}
