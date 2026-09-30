import { validateTargetResume, verifyTargetResumeSignatures } from './target-resume';
import {
  TARGET_RESUME_EXPORT_TEMPLATE, TARGET_RESUME_EXPORT_MAX_BODY_BYTES,
  type PreparedTargetResumeExport, type TargetResumeExportLocale,
  type TargetResumeExportPageSize, type TargetResumeExportProjection,
} from './target-resume-export-protocol';

export type TargetResumeExportErrorCode = 'invalid_document' | 'invalid_signature' | 'signature_unavailable'
  | 'invalid_options' | 'empty_document' | 'unsupported_character' | 'document_too_large';
export type TargetResumeExportResult<T> = { ok: true; value: T } | { ok: false; code: TargetResumeExportErrorCode };
export interface TargetResumeExportOptions {
  locale: TargetResumeExportLocale;
  page_size: TargetResumeExportPageSize;
}
class InvalidExport extends Error {
  constructor(readonly code: TargetResumeExportErrorCode) { super(code); }
}
function fail(code: TargetResumeExportErrorCode): never { throw new InvalidExport(code); }

/** Compact JSON matches the AI protocol/Python canonical bytes. No Unicode,
 * whitespace, object value or array ordering is normalized. */
function canonical(value: unknown): string {
  const seen = new Set<object>();
  const visit = (item: unknown, depth: number): string => {
    if (depth > 32) fail('invalid_document');
    if (item === null) return 'null';
    if (typeof item === 'string') {
      for (const c of item) {
        const code = c.codePointAt(0)!;
        if (code === 0 || code >= 0xd800 && code <= 0xdfff) fail('unsupported_character');
      }
      return JSON.stringify(item);
    }
    if (typeof item === 'boolean') return JSON.stringify(item);
    if (typeof item === 'number' && Number.isSafeInteger(item)) return JSON.stringify(item);
    if (!item || typeof item !== 'object' || seen.has(item)) fail('invalid_document');
    if (!Array.isArray(item) && Object.getPrototypeOf(item) !== Object.prototype && Object.getPrototypeOf(item) !== null) fail('invalid_document');
    seen.add(item);
    let output: string;
    if (Array.isArray(item)) {
      const values: string[] = [];
      for (let i = 0; i < item.length; i += 1) {
        if (!Object.hasOwn(item, i)) fail('invalid_document');
        values.push(visit(item[i], depth + 1));
      }
      output = `[${values.join(',')}]`;
    } else {
      const row = item as Record<string, unknown>;
      output = `{${Object.keys(row).sort().map(key => `${visit(key, depth + 1)}:${visit(row[key], depth + 1)}`).join(',')}}`;
    }
    seen.delete(item);
    return output;
  };
  return visit(value, 0);
}
/** XML 1.0 characters accepted by both renderers. Reject rather than stripping
 * unsupported control characters. TAB, LF and CR remain exact in the payload. */
function xmlText(value: string): void {
  for (const character of value) {
    const code = character.codePointAt(0)!;
    if (code !== 0x09 && code !== 0x0a && code !== 0x0d
      && !(code >= 0x20 && code <= 0xd7ff)
      && !(code >= 0xe000 && code <= 0xfffd)
      && !(code >= 0x10000 && code <= 0x10ffff)) fail('unsupported_character');
  }
}
function freeze<T>(value: T): T {
  if (value && typeof value === 'object') {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}
async function digest(value: string): Promise<string> {
  try {
    const bytes = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
    return `v1:sha256:${Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('')}`;
  } catch { return fail('signature_unavailable'); }
}

/** A displayed draft can be unsaved or historical. This serializes its current
 * selected wording; it does not rebind old sources, accept AI advice, save the
 * draft, translate its body, or claim the manual edits are verified facts.
 * Only projection is transportable: canonical_draft must stay in the browser. */
export async function prepareTargetResumeExport(draft: unknown,
  options: TargetResumeExportOptions): Promise<TargetResumeExportResult<PreparedTargetResumeExport>> {
  try {
    if (!options || !['en', 'zh'].includes(options.locale) || !['letter', 'a4'].includes(options.page_size)
      || Object.keys(options).length !== 2) fail('invalid_options');
    // validateTargetResume takes its own exact JSON clone synchronously. The
    // projection/options/canonical baseline are all captured before any await.
    const checked = validateTargetResume(draft);
    if (!checked.ok) fail(checked.code === 'document_too_large' ? 'document_too_large'
      : checked.code === 'invalid_unicode' ? 'unsupported_character' : 'invalid_document');
    const value = checked.value;
    const canonicalDraft = canonical(value);
    let nonblank = false;
    const sections: TargetResumeExportProjection['sections'] = [];
    for (const section of value.document.sections) {
      if (!section.included) continue;
      const blocks: TargetResumeExportProjection['sections'][number]['blocks'] = [];
      for (const block of section.blocks) {
        if (!block.included) continue;
        const lines = block.lines.filter(line => line.included).map(line => {
          xmlText(line.role); xmlText(line.label); xmlText(line.text);
          if (line.text.trim().length > 0) nonblank = true;
          return { role: line.role, label: line.label, text: line.text };
        });
        if (lines.length) blocks.push({ lines });
      }
      if (blocks.length) { xmlText(section.heading); sections.push({ kind: section.kind, heading: section.heading, blocks }); }
    }
    if (!nonblank) fail('empty_document');
    const projection: TargetResumeExportProjection = { version: 1, template: TARGET_RESUME_EXPORT_TEMPLATE,
      locale: options.locale, page_size: options.page_size, sections };
    const projectionJson = canonical(projection);
    // The transport checks the complete envelope again, including its request
    // ID/format/signatures. Never shorten a projection to make it fit.
    if (new TextEncoder().encode(projectionJson).byteLength > TARGET_RESUME_EXPORT_MAX_BODY_BYTES) fail('document_too_large');
    if (!globalThis.crypto?.subtle) fail('signature_unavailable');
    if (!await verifyTargetResumeSignatures(value)) fail('invalid_signature');
    const [documentSignature, exportSignature] = await Promise.all([digest(canonicalDraft), digest(projectionJson)]);
    return { ok: true, value: freeze({ projection, canonical_draft: canonicalDraft,
      document_signature: documentSignature, export_signature: exportSignature }) };
  } catch (error) {
    return { ok: false, code: error instanceof InvalidExport ? error.code : 'invalid_document' };
  }
}

/** Use immediately before download, alongside the caller's owner/scope/context
 * checks. No await means another edit cannot slip between hash and comparison. */
export function isPreparedTargetResumeExportCurrent(prepared: PreparedTargetResumeExport, currentDraft: unknown): boolean {
  try { return canonical(currentDraft) === prepared.canonical_draft; } catch { return false; }
}
