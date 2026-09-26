import { isTargetResumeEvidence } from './target-resume-evidence';
import { validateTargetResume, type TargetResumeLine, type TargetResumeV1 } from './target-resume';
import type { TargetResumeAiEvidence } from './target-resume-ai-protocol';
import type { TargetResumePlanSourceEvidence } from './target-resume-plan-protocol';

export const TARGET_RESUME_PROVENANCE_MAX_BYTES = 256 * 1024;
export const TARGET_RESUME_PROVENANCE_MAX_EVENTS = 512;
export const TARGET_RESUME_PROVENANCE_MAX_CHANGES = 1024;
export type TargetResumeProvenanceKind = 'manual' | 'ai_rewrite' | 'plan' | 'target_order';
export interface TargetResumeProvenanceCheck {
  version: string; pipeline_version: string; request_id: string; document_signature: string;
  original: string; evidence: TargetResumeLine['evidence'];
}
export interface TargetResumeProvenancePath {
  section_id: string | null; block_id: string | null; line_id: string | null;
  field: 'text' | 'included' | 'order';
}
export interface TargetResumeProvenanceAnnotation extends TargetResumeProvenancePath {
  reason: string | null; target_evidence: TargetResumeAiEvidence[];
  source_evidence: TargetResumePlanSourceEvidence[]; check: TargetResumeProvenanceCheck | null;
}
export interface TargetResumeProvenanceChange extends TargetResumeProvenanceAnnotation {
  before: string | boolean | string[]; after: string | boolean | string[];
}
export interface TargetResumeProvenanceEvent {
  id: string; kind: TargetResumeProvenanceKind; changes: TargetResumeProvenanceChange[];
}
/** Locally supplied operation records. They are not authenticated server receipts. */
export interface TargetResumeProvenance {
  version: 1 | 2; document_id: string; opportunity_id: string;
  base: TargetResumeV1['base']; events: TargetResumeProvenanceEvent[];
}
export interface TargetResumeProvenanceAction {
  kind: TargetResumeProvenanceKind; id?: string; annotations?: TargetResumeProvenanceAnnotation[];
}
export type TargetResumeProvenanceCode = 'invalid' | 'too_large';
export class TargetResumeProvenanceError extends Error {
  constructor(readonly code: TargetResumeProvenanceCode) { super(`target_resume_provenance_${code}`); this.name = 'TargetResumeProvenanceError'; }
}
function fail(code: TargetResumeProvenanceCode = 'invalid'): never { throw new TargetResumeProvenanceError(code); }
function object(value: unknown): value is Record<string, unknown> { return !!value && typeof value === 'object' && !Array.isArray(value); }
function shape(value: unknown, keys: string[]): asserts value is Record<string, unknown> {
  if (!object(value) || Object.keys(value).length !== keys.length || keys.some(k => !Object.hasOwn(value, k))) fail();
}
function text(value: unknown): asserts value is string {
  if (typeof value !== 'string') fail();
  for (const c of value) { const n = c.codePointAt(0)!; if (n === 0 || (n >= 0xd800 && n <= 0xdfff)) fail(); }
}
function nonblank(value: unknown): asserts value is string { text(value); if (!value.trim()) fail(); }
function id(value: unknown): asserts value is string { nonblank(value); if (Array.from(value).length > 200) fail(); }
function canonical(value: unknown): string {
  const seen = new Set<object>();
  const walk = (v: unknown, depth: number): string => {
    if (depth > 32) fail();
    if (v === null) return 'null';
    if (typeof v === 'string') { text(v); return JSON.stringify(v); }
    if (typeof v === 'boolean') return String(v);
    if (typeof v === 'number') { if (!Number.isSafeInteger(v)) fail(); return String(v); }
    if (!v || typeof v !== 'object' || seen.has(v)) fail();
    if (!Array.isArray(v) && Object.getPrototypeOf(v) !== Object.prototype && Object.getPrototypeOf(v) !== null) fail();
    seen.add(v);
    let result: string;
    if (Array.isArray(v)) {
      const values: string[] = [];
      for (let i = 0; i < v.length; i++) { if (!Object.hasOwn(v, i)) fail(); values.push(walk(v[i], depth + 1)); }
      result = `[${values.join(',')}]`;
    } else {
      const row = v as Record<string, unknown>;
      result = `{${Object.keys(row).sort().map(k => { text(k); return `${JSON.stringify(k)}:${walk(row[k], depth + 1)}`; }).join(',')}}`;
    }
    seen.delete(v); return result;
  };
  return walk(value, 0);
}
function same(a: unknown, b: unknown): boolean { return canonical(a) === canonical(b); }
function clone<T>(v: T): T { return JSON.parse(canonical(v)) as T; }
function document(value: unknown): TargetResumeV1 { const checked = validateTargetResume(value); if (!checked.ok) fail(); return checked.value; }
const PATH_KEYS = ['section_id', 'block_id', 'line_id', 'field'];
const META_KEYS = ['reason', 'target_evidence', 'source_evidence', 'check'];
const KINDS: TargetResumeProvenanceKind[] = ['manual', 'ai_rewrite', 'plan', 'target_order'];
function pathKey(path: TargetResumeProvenancePath): string { return JSON.stringify([path.section_id, path.block_id, path.line_id, path.field]); }
function path(value: Record<string, unknown>): TargetResumeProvenancePath {
  for (const key of ['section_id', 'block_id', 'line_id']) if (value[key] !== null) id(value[key]);
  if (!['text', 'included', 'order'].includes(value.field as string)) fail();
  return value as unknown as TargetResumeProvenancePath;
}
function location(doc: TargetResumeV1, p: TargetResumeProvenancePath) {
  const section = p.section_id === null ? undefined : doc.document.sections.find(s => s.id === p.section_id);
  if (p.section_id !== null && !section) fail();
  const block = p.block_id === null ? undefined : section?.blocks.find(b => b.id === p.block_id);
  if (p.block_id !== null && !block) fail();
  const line = p.line_id === null ? undefined : block?.lines.find(l => l.id === p.line_id);
  if (p.line_id !== null && !line) fail();
  if (p.field === 'text' && !line) fail();
  if (p.field === 'included' && !section) fail();
  if (p.field === 'order' && line) fail();
  return { section, block, line };
}
function read(doc: TargetResumeV1, p: TargetResumeProvenancePath): TargetResumeProvenanceChange['before'] {
  const { section, block, line } = location(doc, p);
  if (p.field === 'text') return line!.text;
  if (p.field === 'included') return (line ?? block ?? section)!.included;
  return (block?.lines ?? section?.blocks ?? doc.document.sections).map(v => v.id);
}
function write(doc: TargetResumeV1, p: TargetResumeProvenancePath, value: TargetResumeProvenanceChange['before']): void {
  const { section, block, line } = location(doc, p);
  if (p.field === 'text') { line!.text = value as string; return; }
  if (p.field === 'included') { (line ?? block ?? section)!.included = value as boolean; return; }
  const ids = value as string[];
  const reorder = <T extends { id: string }>(items: T[]) => ids.map(id => items.find(item => item.id === id)!);
  if (block) block.lines = reorder(block.lines);
  else if (section) section.blocks = reorder(section.blocks);
  else doc.document.sections = reorder(doc.document.sections);
}
function range(source: string, evidence: Record<string, unknown>): void {
  nonblank(evidence.quote);
  if (!Number.isSafeInteger(evidence.start) || !Number.isSafeInteger(evidence.end)
    || (evidence.start as number) < 0 || (evidence.end as number) <= (evidence.start as number)
    || Array.from(source).slice(evidence.start as number, evidence.end as number).join('') !== evidence.quote
    || (evidence.end as number) > Array.from(source).length) fail();
}
function metadata(value: Record<string, unknown>, doc: TargetResumeV1, p: TargetResumeProvenancePath, kind: TargetResumeProvenanceKind, version: 1 | 2): void {
  const { section, block, line } = location(doc, p);
  if (value.reason !== null) text(value.reason);
  if (!Array.isArray(value.target_evidence) || !Array.isArray(value.source_evidence)) fail();
  if ((kind === 'manual' || kind === 'target_order')
    && (value.reason !== null || value.target_evidence.length || value.source_evidence.length || value.check !== null)) fail();
  for (const e of value.target_evidence) {
    if (!isTargetResumeEvidence(doc.target_snapshot, e, version === 2)) fail();
  }
  for (const e of value.source_evidence) {
    shape(e, ['unit_id', 'start', 'end', 'quote']); id(e.unit_id);
    // A plan item may cite another original line in this block, never another project.
    const source = block?.lines.find(l => l.id === e.unit_id);
    if (!source) fail(); range(source.original, e);
  }
  if (value.check !== null) {
    if (!['ai_rewrite', 'plan'].includes(kind) || p.field !== 'text' || line?.evidence.kind !== 'experience' || section?.kind === 'basics') fail();
    const c = value.check;
    shape(c, ['version', 'pipeline_version', 'request_id', 'document_signature', 'original', 'evidence']);
    for (const key of ['version', 'pipeline_version', 'request_id']) nonblank(c[key]);
    if (typeof c.document_signature !== 'string' || !/^v1:sha256:[a-f0-9]{64}$/.test(c.document_signature)) fail();
    text(c.original);
    shape(c.evidence, ['kind', 'id', 'revision']);
    if (c.original !== line.original || !same(c.evidence, line.evidence)) fail();
  }
  if (kind === 'target_order' && p.field !== 'order') fail();
  if (kind === 'ai_rewrite' && !['text', 'order'].includes(p.field)) fail();
  if (kind === 'plan' && p.field === 'order') fail();
  if ((kind === 'ai_rewrite' || kind === 'plan') && p.field === 'text'
    && (line?.evidence.kind !== 'experience' || section?.kind === 'basics')) fail();
}
function values(change: TargetResumeProvenanceChange, doc: TargetResumeV1): void {
  if (change.field === 'text') { text(change.before); text(change.after); }
  else if (change.field === 'included') { if (typeof change.before !== 'boolean' || typeof change.after !== 'boolean') fail(); }
  else {
    const current = read(doc, change) as string[];
    for (const value of [change.before, change.after]) {
      if (!Array.isArray(value) || value.length !== current.length || new Set(value).size !== value.length
        || value.some(v => typeof v !== 'string' || !current.includes(v))) fail();
    }
  }
}
function parse(value: unknown, doc: TargetResumeV1): TargetResumeProvenance | null {
  if (value === null) return null;
  const serialized = canonical(value);
  if (new TextEncoder().encode(serialized).byteLength > TARGET_RESUME_PROVENANCE_MAX_BYTES) fail('too_large');
  const copy: unknown = JSON.parse(serialized);
  shape(copy, ['version', 'document_id', 'opportunity_id', 'base', 'events']);
  if (![1, 2].includes(copy.version as number) || (copy.version === 2 && (!('context_version' in doc.target_snapshot) || doc.target_snapshot.context_version !== 3)) || copy.document_id !== doc.id || copy.opportunity_id !== doc.opportunity_id || !same(copy.base, doc.base)) fail();
  if (!Array.isArray(copy.events) || !copy.events.length) fail();
  if (copy.events.length > TARGET_RESUME_PROVENANCE_MAX_EVENTS) fail('too_large');
  const ids = new Set<string>();
  const replay = clone(doc);
  for (const event of [...copy.events].reverse()) {
    shape(event, ['id', 'kind', 'changes']); id(event.id);
    if (ids.has(event.id) || !KINDS.includes(event.kind as TargetResumeProvenanceKind)) fail(); ids.add(event.id);
    if (!Array.isArray(event.changes) || !event.changes.length) fail();
    if (event.changes.length > TARGET_RESUME_PROVENANCE_MAX_CHANGES) fail('too_large');
    const paths = new Set<string>();
    for (const raw of [...event.changes].reverse()) {
      shape(raw, [...PATH_KEYS, 'before', 'after', ...META_KEYS]);
      const p = path(raw); const key = pathKey(p); if (paths.has(key)) fail(); paths.add(key);
      const change = raw as unknown as TargetResumeProvenanceChange;
      metadata(raw, replay, p, event.kind as TargetResumeProvenanceKind, copy.version as 1 | 2); values(change, replay);
      if (!same(read(replay, p), change.after)) fail();
      if (event.kind !== 'manual' && same(change.before, change.after)) fail();
      write(replay, p, change.before);
    }
  }
  return copy as unknown as TargetResumeProvenance;
}
export function validateTargetResumeProvenance(value: unknown, doc: TargetResumeV1):
  { ok: true; value: TargetResumeProvenance | null } | { ok: false; code: TargetResumeProvenanceCode } {
  try { return { ok: true, value: parse(value, document(doc)) }; }
  catch (error) { return { ok: false, code: error instanceof TargetResumeProvenanceError ? error.code : 'invalid' }; }
}
/** Order paths identify their container: all-null=sections, section=blocks,
 * section+block=lines. Inclusion may address a section, block, or line. */
export function appendTargetResumeProvenance(previous: TargetResumeProvenance | null,
  before: TargetResumeV1, after: TargetResumeV1, action: TargetResumeProvenanceAction): TargetResumeProvenance | null {
  const old = document(before); const next = document(after); const prior = parse(previous, old);
  if (!KINDS.includes(action.kind)) fail();
  if (!same({ ...old, document: null }, { ...next, document: null })) fail();
  const version = 'context_version' in next.target_snapshot && next.target_snapshot.context_version === 3 ? 2 : 1;
  const annotations = new Map<string, TargetResumeProvenanceAnnotation>();
  for (const annotation of action.annotations ?? []) {
    shape(annotation, [...PATH_KEYS, ...META_KEYS]); const p = path(annotation);
    metadata(annotation, old, p, action.kind, version);
    const key = pathKey(p); if (annotations.has(key)) fail(); annotations.set(key, clone(annotation));
  }
  const changes: TargetResumeProvenanceChange[] = [];
  function diff(p: TargetResumeProvenancePath) {
    const a = read(old, p); const b = read(next, p); if (same(a, b)) return;
    const annotation = annotations.get(pathKey(p));
    changes.push({ ...p, before: clone(a), after: clone(b), reason: null, target_evidence: [], source_evidence: [], check: null, ...annotation });
  }
  diff({ section_id: null, block_id: null, line_id: null, field: 'order' });
  for (const s of old.document.sections) {
    const section = { section_id: s.id, block_id: null, line_id: null };
    diff({ ...section, field: 'included' }); diff({ ...section, field: 'order' });
    for (const b of s.blocks) {
      const block = { ...section, block_id: b.id };
      diff({ ...block, field: 'included' }); diff({ ...block, field: 'order' });
      for (const l of b.lines) {
        const line = { ...block, line_id: l.id };
        diff({ ...line, field: 'included' }); diff({ ...line, field: 'text' });
      }
    }
  }
  if (!changes.length) return prior;
  const events = prior?.events ?? [];
  const last = events.at(-1);
  if (action.kind === 'manual' && last?.kind === 'manual' && changes.length === 1 && last.changes.length === 1
    && pathKey(changes[0]) === pathKey(last.changes[0])) {
    // Keep the manual marker even when the text returns to its earlier value.
    last.changes[0].after = changes[0].after;
  } else {
    const eventId = action.id ?? globalThis.crypto.randomUUID(); id(eventId);
    events.push({ id: eventId, kind: action.kind, changes });
  }
  return parse({ version, document_id: next.id, opportunity_id: next.opportunity_id, base: clone(next.base), events }, next);
}
/** Latest text operation only. Never resurrect an older check after manual edits.
 * These records do not attest to truth or to authenticated server execution. */
export function currentLineRecord(provenance: TargetResumeProvenance | null, doc: TargetResumeV1, lineId: string):
  { kind: TargetResumeProvenanceKind; change: TargetResumeProvenanceChange } | null {
  const checked = parse(provenance, document(doc));
  if (!checked) return null;
  for (const event of [...checked.events].reverse()) {
    const change = event.changes.find(c => c.field === 'text' && c.line_id === lineId);
    if (change) return { kind: event.kind, change };
  }
  return null;
}
