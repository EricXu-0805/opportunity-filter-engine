import type {
  ExperienceEntry, Opportunity, ProfileData, ResumeExperienceRef, ResumeFact,
  ResumeMasterSectionKind, ResumeMasterV1,
} from './types';
import { isActiveExperience, sourceDigest, validateExperienceEntries } from './experience-evidence';
import { isActiveResumeFact, validateResumeMaster } from './resume-master';
import { MAX_RESUME_TEXT_CHARACTERS, resumeTextCharacters } from './resume-input';

export const MAX_TARGET_RESUME_BYTES = 2 * 1024 * 1024;
const DIGEST = /^[a-f0-9]{64}$/;
const FINGERPRINT = /^v1:sha256:[a-f0-9]{64}$/;
const BASIC_FIELDS = ['name', 'email', 'phone', 'location'] as const;
const EDUCATION_FIELDS = ['school', 'degree', 'field', 'start', 'end'] as const;
const ACTIVITY_FIELDS = ['title', 'organization', 'location', 'start', 'end', 'url'] as const;
const PUBLICATION_FIELDS = ['title', 'authors', 'venue', 'date', 'publication_status', 'url', 'doi'] as const;

export interface TargetResumeContext {
  opportunity_id: string; title: string; organization: string; source_url: string;
  description: string; requirements: string[];
}
export interface TargetResumeLine {
  id: string;
  role: string;
  label: string;
  original: string;
  text: string;
  included: boolean;
  evidence: { kind: 'fact' | 'experience'; id: string; revision: number };
}
export interface TargetResumeBlock { id: string; included: boolean; lines: TargetResumeLine[] }
export interface TargetResumeSection {
  id: string; kind: ResumeMasterSectionKind; heading: string; included: boolean; blocks: TargetResumeBlock[];
}
export interface TargetResumeV1 {
  kind: 'full_resume'; version: 1; id: string; opportunity_id: string;
  base: {
    master_id: string; master_revision: number; profile_signature: string;
    source_signature: string; target_signature: string;
  };
  base_snapshot: { resume_text: string; experience_entries: ExperienceEntry[]; resume_master: ResumeMasterV1 };
  target_snapshot: TargetResumeContext;
  document: { sections: TargetResumeSection[] };
}
export interface LoadedTargetResume { revision: number; doc: TargetResumeV1; updated_at: string }
export type TargetResumeSaveResult =
  | { status: 'saved' | 'unchanged'; value: LoadedTargetResume }
  | { status: 'conflict'; current: LoadedTargetResume }
  | { status: 'missing' | 'abandoned' | 'unavailable' | 'failed' };
export type TargetResumeErrorCode =
  | 'invalid_document' | 'document_too_large' | 'invalid_unicode' | 'invalid_json'
  | 'invalid_master' | 'master_required' | 'confirmed_content_required'
  | 'invalid_experiences' | 'invalid_source' | 'invalid_target' | 'invalid_signature'
  | 'invalid_evidence' | 'signature_unavailable';
export class TargetResumeError extends Error {
  constructor(public readonly code: TargetResumeErrorCode) {
    super(code); // Safe codes only: no private field, quote, draft text or provider error.
    this.name = 'TargetResumeError';
  }
}
function fail(code: TargetResumeErrorCode): never { throw new TargetResumeError(code); }
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function shape(value: unknown, keys: readonly string[], code: TargetResumeErrorCode = 'invalid_document'): asserts value is Record<string, unknown> {
  if (!record(value) || Object.keys(value).length !== keys.length
    || keys.some((key) => !Object.hasOwn(value, key))) fail(code);
}
function wellFormed(value: string): boolean {
  for (const character of value) {
    const point = character.codePointAt(0)!;
    // PostgreSQL jsonb cannot represent U+0000, even when JSON-escaped.
    // Reject it without rewriting the student's original input.
    if (point === 0 || (point >= 0xd800 && point <= 0xdfff)) return false;
  }
  return true;
}
function string(value: unknown, code: TargetResumeErrorCode = 'invalid_document'): asserts value is string {
  if (typeof value !== 'string') fail(code);
  if (!wellFormed(value)) fail('invalid_unicode');
}
function identifier(value: unknown, max = 200): asserts value is string {
  string(value);
  if (!value.trim() || resumeTextCharacters(value) > max) fail('invalid_document');
}

/** JSON-only canonical representation: object insertion order is irrelevant;
 *  array order, Unicode, whitespace and every defined value remain exact.
 *  Only profile optional object properties may omit undefined, as JSON does. */
function canonical(value: unknown, omitUndefined = false): string {
  const ancestors = new Set<object>();
  const walk = (item: unknown, depth: number): string => {
    if (depth > 32) fail('invalid_json');
    if (item === null) return 'null';
    if (typeof item === 'string') { string(item); return JSON.stringify(item); }
    if (typeof item === 'boolean') return JSON.stringify(item);
    if (typeof item === 'number') {
      if (!Number.isFinite(item)) fail('invalid_json');
      return JSON.stringify(item);
    }
    if (typeof item !== 'object' || ancestors.has(item)) fail('invalid_json');
    const proto = Object.getPrototypeOf(item);
    if (!Array.isArray(item) && proto !== Object.prototype && proto !== null) fail('invalid_json');
    ancestors.add(item);
    let output: string;
    if (Array.isArray(item)) {
      // Sparse arrays/undefined are rejected rather than quietly becoming null.
      const values: string[] = [];
      for (let index = 0; index < item.length; index += 1) {
        if (!Object.hasOwn(item, index)) fail('invalid_json');
        values.push(walk(item[index], depth + 1));
      }
      output = `[${values.join(',')}]`;
    } else {
      const object = item as Record<string, unknown>;
      output = `{${Object.keys(object).filter((key) => !omitUndefined || object[key] !== undefined).sort().map((key) => {
        string(key);
        return `${JSON.stringify(key)}:${walk(object[key], depth + 1)}`;
      }).join(',')}}`;
    }
    ancestors.delete(item);
    return output;
  };
  return walk(value, 0);
}
function encodedBytes(value: string): number { return new TextEncoder().encode(value).byteLength; }
function documentJson(value: unknown): string {
  // Compact JSON wire size, not JS UTF-16 length. Reject before interpreting it.
  const result = canonical(value);
  if (encodedBytes(result) > MAX_TARGET_RESUME_BYTES) fail('document_too_large');
  return result;
}
async function fingerprint(value: string): Promise<string> {
  try {
    const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
    return `v1:sha256:${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')}`;
  } catch { return fail('signature_unavailable'); }
}
function targetValid(value: unknown): asserts value is TargetResumeContext {
  shape(value, ['opportunity_id', 'title', 'organization', 'source_url', 'description', 'requirements'], 'invalid_target');
  try { identifier(value.opportunity_id); } catch { fail('invalid_target'); }
  for (const key of ['title', 'organization', 'source_url', 'description']) string(value[key], 'invalid_target');
  if (!Array.isArray(value.requirements)) fail('invalid_target');
  for (const requirement of value.requirements) string(requirement, 'invalid_target');
}

export async function targetResumeProfileSignature(profile: ProfileData): Promise<string> {
  // Compute before the first await so later edits cannot change this fingerprint.
  return fingerprint(canonical(profile, true));
}
export async function targetResumeContextSignature(target: TargetResumeContext): Promise<string> {
  targetValid(target);
  return fingerprint(documentJson(target));
}

/** Deliberate public-field allowlist. No contact reveal, raw scrape, inference
 *  metadata, tracking state or arbitrary opportunity properties enter a draft.
 *  Requirements here are the stated skills list; the complete clean description
 *  remains available for other criteria. Inferred skills are not stated facts. */
export function targetResumeContextFromOpportunity(opportunity: Opportunity): TargetResumeContext {
  const target: TargetResumeContext = {
    opportunity_id: opportunity.id,
    title: opportunity.title,
    organization: opportunity.organization,
    source_url: opportunity.source_url ?? opportunity.url ?? '',
    description: opportunity.description_clean,
    requirements: opportunity.skills_attribution === 'inferred' || opportunity.metadata?.skills_attribution === 'inferred'
      ? [] : [...(opportunity.eligibility?.skills_required ?? [])],
  };
  targetValid(target);
  return JSON.parse(documentJson(target)) as TargetResumeContext;
}

function confirmedDocument(snapshot: TargetResumeV1['base_snapshot'], sourceSignature: string): TargetResumeV1['document'] {
  const master = snapshot.resume_master;
  const context = { rawText: snapshot.resume_text, expectedDigest: sourceSignature };
  const entries = new Map(snapshot.experience_entries.map((entry) => [entry.id, entry]));
  const sections = new Map<string, TargetResumeSection>();
  let sequence = 0;
  const line = (role: string, label: string, original: string, evidence: TargetResumeLine['evidence']): TargetResumeLine => ({
    id: `line-${++sequence}`, role, label, original, text: original, included: true, evidence,
  });
  const field = (fact: ResumeFact | undefined, role: string, label = ''): TargetResumeLine[] => fact && isActiveResumeFact(fact, context)
    ? [line(role, label, fact.value, { kind: 'fact', id: fact.id, revision: fact.revision })] : [];
  const fields = (item: object, keys: readonly string[]) => keys.flatMap((key) => field((item as Record<string, ResumeFact | undefined>)[key], key));
  const details = (refs: ResumeExperienceRef[]) => refs.flatMap((ref) => {
    const entry = entries.get(ref.id);
    return entry && entry.revision === ref.revision && isActiveExperience(entry, context)
      ? [line('experience', '', entry.text, { kind: 'experience', id: entry.id, revision: entry.revision })] : [];
  });
  const block = (id: string, lines: TargetResumeLine[]): TargetResumeBlock => ({ id, included: true, lines });
  const section = (id: string, kind: ResumeMasterSectionKind, blocks: TargetResumeBlock[], heading = '') => {
    sections.set(id, { id, kind, heading, included: true, blocks: blocks.filter((item) => item.lines.length > 0) });
  };
  section('basics', 'basics', [block(master.id, fields(master.basics, BASIC_FIELDS)),
    ...master.basics.links.map((link) => block(link.id, field(link.url, 'url', link.label)))]);
  section('education', 'education', master.education.map((item) => block(item.id, [...fields(item, EDUCATION_FIELDS), ...details(item.details)])));
  section('activities', 'activities', master.activities.map((item) => block(item.id, [...fields(item, ACTIVITY_FIELDS), ...details(item.details)])));
  section('publications', 'publications', master.publications.map((item) => block(item.id, [...fields(item, PUBLICATION_FIELDS), ...details(item.details)])));
  section('skills', 'skills', master.skills.map((fact) => block(fact.id, field(fact, 'skill'))));
  for (const item of master.other_sections) section(item.id, 'other', item.items.map((fact) => block(fact.id, field(fact, 'other', item.heading))), item.heading);
  const ordered = master.section_order.map((id) => sections.get(id)!).filter((item) => item.blocks.length > 0);
  if (ordered.length === 0) fail('confirmed_content_required');
  return { sections: ordered };
}
function freezeDeep<T>(value: T): T {
  if (value && typeof value === 'object') {
    for (const item of Object.values(value)) freezeDeep(item);
    Object.freeze(value);
  }
  return value;
}
function freezeSnapshots(doc: TargetResumeV1): TargetResumeV1 {
  freezeDeep(doc.base);
  freezeDeep(doc.base_snapshot);
  freezeDeep(doc.target_snapshot);
  return doc;
}
function exactSet<T extends { id: string }>(items: unknown, expected: T[]): Map<string, T> {
  if (!Array.isArray(items) || items.length !== expected.length) fail('invalid_evidence');
  const byId = new Map(expected.map((item) => [item.id, item]));
  const seen = new Set<string>();
  for (const item of items) {
    if (!record(item) || typeof item.id !== 'string' || seen.has(item.id) || !byId.has(item.id)) fail('invalid_evidence');
    seen.add(item.id);
  }
  return byId;
}

/** Synchronous shape/source-quote validation. Storage MUST additionally await
 *  verifyTargetResumeSignatures; format checking alone cannot verify SHA-256.
 *  Originals/roles/labels/locations are rebuilt from confirmed snapshot facts,
 *  while text, ordering and inclusion remain independent user draft choices. */
export function validateTargetResume(value: unknown): { ok: true; value: TargetResumeV1 } | { ok: false; code: TargetResumeErrorCode } {
  try {
    const serialized = documentJson(value);
    const parsed: unknown = JSON.parse(serialized);
    shape(parsed, ['kind', 'version', 'id', 'opportunity_id', 'base', 'base_snapshot', 'target_snapshot', 'document']);
    if (parsed.kind !== 'full_resume' || parsed.version !== 1) fail('invalid_document');
    identifier(parsed.id, 80); identifier(parsed.opportunity_id);
    shape(parsed.base, ['master_id', 'master_revision', 'profile_signature', 'source_signature', 'target_signature']);
    if (typeof parsed.base.source_signature !== 'string' || !DIGEST.test(parsed.base.source_signature)
      || typeof parsed.base.profile_signature !== 'string' || !FINGERPRINT.test(parsed.base.profile_signature)
      || typeof parsed.base.target_signature !== 'string' || !FINGERPRINT.test(parsed.base.target_signature)) fail('invalid_signature');
    shape(parsed.base_snapshot, ['resume_text', 'experience_entries', 'resume_master']);
    string(parsed.base_snapshot.resume_text, 'invalid_source');
    if (resumeTextCharacters(parsed.base_snapshot.resume_text) > MAX_RESUME_TEXT_CHARACTERS) fail('invalid_source');
    const master = validateResumeMaster(parsed.base_snapshot.resume_master);
    if (!master.ok || !master.value) fail('invalid_master');
    const entries = validateExperienceEntries(parsed.base_snapshot.experience_entries);
    if (!entries.ok) fail('invalid_experiences');
    if (parsed.base.master_id !== master.value.id || parsed.base.master_revision !== master.value.revision) fail('invalid_evidence');
    targetValid(parsed.target_snapshot);
    if (parsed.opportunity_id !== parsed.target_snapshot.opportunity_id) fail('invalid_target');
    shape(parsed.document, ['sections']);
    const doc = parsed as unknown as TargetResumeV1;
    const expected = confirmedDocument(doc.base_snapshot, doc.base.source_signature);
    const sections = exactSet(doc.document.sections, expected.sections);
    for (const item of doc.document.sections) {
      shape(item, ['id', 'kind', 'heading', 'included', 'blocks']);
      const source = sections.get(item.id)!;
      if (item.kind !== source.kind || item.heading !== source.heading || typeof item.included !== 'boolean') fail('invalid_evidence');
      const blocks = exactSet(item.blocks, source.blocks);
      for (const group of item.blocks) {
        shape(group, ['id', 'included', 'lines']);
        if (typeof group.included !== 'boolean') fail('invalid_document');
        const originals = exactSet(group.lines, blocks.get(group.id)!.lines);
        for (const row of group.lines) {
          shape(row, ['id', 'role', 'label', 'original', 'text', 'included', 'evidence']);
          const original = originals.get(row.id)!;
          shape(row.evidence, ['kind', 'id', 'revision']);
          if (row.role !== original.role || row.label !== original.label || row.original !== original.original
            || row.evidence.kind !== original.evidence.kind || row.evidence.id !== original.evidence.id
            || row.evidence.revision !== original.evidence.revision || typeof row.included !== 'boolean') fail('invalid_evidence');
          string(row.text); // Empty/manual text is valid. It never replaces original evidence.
        }
      }
    }
    return { ok: true, value: freezeSnapshots(doc) };
  } catch (error) {
    return { ok: false, code: error instanceof TargetResumeError ? error.code : 'invalid_document' };
  }
}
function requireDoc(value: unknown): TargetResumeV1 {
  const checked = validateTargetResume(value);
  if (!checked.ok) throw new TargetResumeError(checked.code);
  return checked.value;
}

/** Verifies source/target content binding, not independent truth or the user's
 *  identity. Full-profile freshness requires the current profile at the caller. */
export async function verifyTargetResumeSignatures(value: unknown): Promise<boolean> {
  const checked = validateTargetResume(value);
  if (!checked.ok) return false;
  const doc = checked.value; // An owned clone before await; caller edits cannot race verification.
  try {
    const [source, target] = await Promise.all([
      sourceDigest(doc.base_snapshot.resume_text), targetResumeContextSignature(doc.target_snapshot),
    ]);
    return source === doc.base.source_signature && target === doc.base.target_signature;
  } catch { return false; }
}

export async function createTargetResume(profile: ProfileData, target: TargetResumeContext, id: string = globalThis.crypto.randomUUID()): Promise<TargetResumeV1> {
  identifier(id, 80);
  const profileJson = canonical(profile, true);
  const profileSnapshot = JSON.parse(profileJson) as ProfileData;
  const master = validateResumeMaster(profileSnapshot.resume_master);
  if (!master.ok) fail('invalid_master');
  if (!master.value) fail('master_required');
  const entries = validateExperienceEntries(profileSnapshot.experience_entries);
  if (!entries.ok) fail('invalid_experiences');
  const raw = profileSnapshot.resume_text ?? '';
  string(raw, 'invalid_source');
  if (resumeTextCharacters(raw) > MAX_RESUME_TEXT_CHARACTERS) fail('invalid_source');
  targetValid(target);
  const targetSnapshot = JSON.parse(documentJson(target)) as TargetResumeContext;
  const [sourceSignature, profileSignature, targetSignature] = await Promise.all([
    sourceDigest(raw), fingerprint(profileJson), targetResumeContextSignature(targetSnapshot),
  ]).catch(() => fail('signature_unavailable'));
  const baseSnapshot = { resume_text: raw, experience_entries: entries.value, resume_master: master.value };
  const doc: TargetResumeV1 = {
    kind: 'full_resume', version: 1, id, opportunity_id: targetSnapshot.opportunity_id,
    base: { master_id: master.value.id, master_revision: master.value.revision, profile_signature: profileSignature,
      source_signature: sourceSignature, target_signature: targetSignature },
    base_snapshot: baseSnapshot, target_snapshot: targetSnapshot,
    document: confirmedDocument(baseSnapshot, sourceSignature),
  };
  return requireDoc(doc);
}

/** A deterministic, bounded literal-overlap suggestion, not AI or a match score.
 *  Only whole blocks move within their existing sections. Ties retain the user's
 *  current order; nothing is selected, dropped, summarized or rewritten. */
export function suggestTargetResumeOrder(value: TargetResumeV1): TargetResumeV1 {
  const doc = requireDoc(value);
  const tokens = (text: string, limit: number): Set<string> => {
    const found = new Set<string>();
    for (const match of text.toLowerCase().matchAll(/[\p{L}\p{N}][\p{L}\p{N}+#.-]*/gu)) {
      const word = match[0].replace(/[.-]+$/u, '');
      if (word.length >= 1 && word.length <= 80) found.add(word);
      if (found.size >= limit) break;
    }
    return found;
  };
  const target = tokens([...doc.target_snapshot.requirements, doc.target_snapshot.title,
    doc.target_snapshot.organization, doc.target_snapshot.description].join('\n'), 256);
  for (const section of doc.document.sections) {
    section.blocks = section.blocks.map((block, index) => {
      // The overall document is bounded. Scan the whole block, including its
      // tail; the target term set (and score) remains capped at 256 terms.
      const words = tokens(block.included ? block.lines.filter((row) => row.included).map((row) => row.text).join('\n') : '', Number.POSITIVE_INFINITY);
      let score = 0;
      for (const term of target) if (words.has(term)) score += 1;
      return { block, index, score };
    }).sort((a, b) => b.score - a.score || a.index - b.index).map(({ block }) => block);
  }
  return doc;
}
