import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createHash, webcrypto } from 'node:crypto';
import baseGolden from '../../../tests/fixtures/target-resume-ai-golden.json';
import exportGolden from '../../../tests/fixtures/target-resume-export-golden.json';
import type { TargetResumeV1 } from './target-resume';
import { validateTargetResume } from './target-resume';
import type { TargetResumeExportProjection } from './target-resume-export-protocol';
import { isPreparedTargetResumeExportCurrent, prepareTargetResumeExport, type TargetResumeExportOptions, type TargetResumeExportResult } from './target-resume-export';

beforeEach(() => vi.stubGlobal('crypto', webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const doc = () => clone(baseGolden.draft) as TargetResumeV1;
const lines = (draft: TargetResumeV1) => draft.document.sections.flatMap(s => s.blocks.flatMap(b => b.lines));
const texts = (projection: TargetResumeExportProjection) => projection.sections.flatMap(s => s.blocks.flatMap(b => b.lines.map(l => l.text)));
const unwrap = <T,>(value: TargetResumeExportResult<T>): T => { if (!value.ok) throw Error(value.code); return value.value; };
const options: TargetResumeExportOptions = { locale: 'en', page_size: 'letter' };
const prepare = async (draft = doc(), opts = options) => unwrap(await prepareTargetResumeExport(draft, opts));
function goldenDraft() {
  const value = doc();
  const edits = exportGolden.draft_edits;
  for (const s of value.document.sections) {
    if (edits.excluded_sections.includes(s.id)) s.included = false;
    for (const b of s.blocks) {
      if (edits.excluded_blocks.includes(b.id)) b.included = false;
      for (const l of b.lines) {
        if (edits.excluded_lines.includes(l.id)) l.included = false;
        const replacement = (edits.line_text as Record<string, string>)[l.id];
        if (replacement !== undefined) l.text = replacement;
      }
    }
  }
  value.document.sections.sort((a, b) => edits.section_order.indexOf(a.id) - edits.section_order.indexOf(b.id));
  return value;
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
    .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(',')}}`;
  return JSON.stringify(value);
}
const signature = (value: string) => `v1:sha256:${createHash('sha256').update(value).digest('hex')}`;

describe('exact selected current-document projection', () => {
  it('matches shared export golden without repeating the source fixture', async () => {
    const value = await prepare(goldenDraft(), exportGolden.options as TargetResumeExportOptions);
    expect(value.projection).toEqual(exportGolden.projection);
    expect(value.document_signature).toBe(exportGolden.document_signature);
    expect(value.export_signature).toBe(exportGolden.export_signature);
    expect(signature(value.canonical_draft)).toBe(value.document_signature);
    expect(signature(canonical(value.projection))).toBe(value.export_signature);
  });
  it('applies all three inclusion levels and omits blocks/sections with no selected lines', async () => {
    const d = goldenDraft();
    const p = (await prepare(d)).projection;
    expect(p.sections.map(s => s.kind)).toEqual(['other', 'activities', 'education', 'basics']);
    expect(texts(p)).not.toContain('student@example.test');
    expect(texts(p)).not.toContain('Python — beginner');
    expect(texts(p)).not.toContain('研究记录');
    const ed = d.document.sections.find(s => s.kind === 'education')!;
    ed.blocks[0].lines.forEach(line => { line.included = false; });
    expect((await prepare(d)).projection.sections.some(s => s.kind === 'education')).toBe(false);
  });
  it('keeps current section, block and line order without inferring a new order', async () => {
    const d = doc(); d.document.sections.reverse();
    for (const s of d.document.sections) { s.blocks.reverse(); for (const b of s.blocks) b.lines.reverse(); }
    const projection = (await prepare(d)).projection;
    expect(projection.sections.map(s => s.kind)).toEqual(d.document.sections.map(s => s.kind));
    expect(texts(projection)).toEqual(lines(d).map(l => l.text));
  });
  it('uses complete edited text, preserving leading/trailing spaces, CRLF, TAB, blank lines and empty selected fields', async () => {
    const d = doc(); const all = lines(d);
    const edited = '  中文\r\n\r\nEnglish\t😀 <xml>& literal  \n';
    all[0].text = edited; all[1].text = ''; all[2].text = '\t \r\n';
    const projection = (await prepare(d)).projection;
    expect(texts(projection).slice(0, 3)).toEqual([edited, '', '\t \r\n']);
    expect(texts(projection)).toContain('My manual draft edit is not evidence.');
    expect(texts(projection)).not.toContain(baseGolden.draft.base_snapshot.experience_entries[0].text);
  });
  it.each(['汉', '😀'])('preserves 60000 %s characters without a bullet-sized cap', async character => {
    const d = doc(); const original = character.repeat(60000); lines(d)[0].text = original;
    const result = await prepare(d);
    expect(texts(result.projection)[0]).toBe(original);
    expect(Array.from(texts(result.projection)[0])).toHaveLength(60000);
  });
  it('permits a valid manually edited field longer than the master fact limit', async () => {
    const d = doc(); lines(d)[0].text = '全文'.repeat(50001);
    expect(validateTargetResume(d).ok).toBe(true);
    expect(texts((await prepare(d)).projection)[0]).toBe(lines(d)[0].text);
  });
  it('retains role, original labels and empty standard headings; locale never translates body', async () => {
    const en = await prepare(); const zh = await prepare(doc(), { locale: 'zh', page_size: 'letter' });
    expect(texts(en.projection)).toEqual(texts(zh.projection));
    expect(en.projection.sections[0].heading).toBe('');
    expect(en.projection.sections.find(s => s.kind === 'education')!.blocks[0].lines.map(l => l.role)).toEqual(['school', 'degree']);
    const other = zh.projection.sections.find(s => s.kind === 'other')!;
    expect(other.heading).toBe('Awards 奖项'); expect(other.blocks[0].lines[0].label).toBe('Awards 奖项');
  });
  it('uses strict structural allowlists so IDs, source snapshots, evidence, originals and excluded text cannot leak into projection', async () => {
    const d = goldenDraft(); const p = (await prepare(d)).projection;
    expect(Object.keys(p).sort()).toEqual(['locale', 'page_size', 'sections', 'template', 'version']);
    for (const section of p.sections) {
      expect(Object.keys(section).sort()).toEqual(['blocks', 'heading', 'kind']);
      for (const block of section.blocks) {
        expect(Object.keys(block)).toEqual(['lines']);
        for (const line of block.lines) expect(Object.keys(line).sort()).toEqual(['label', 'role', 'text']);
      }
    }
    const serialized = JSON.stringify(p);
    for (const hidden of [d.id, d.opportunity_id, d.base.profile_signature, 'base_snapshot', 'resume_text', 'evidence-one', 'student@example.test', 'Submitted, not accepted']) expect(serialized).not.toContain(hidden);
  });
});

describe('document state, immutable capture and signatures', () => {
  it('captures the draft and export options before awaiting source hashes', async () => {
    const d = doc(); const opts = { ...options }; const before = clone(d);
    const pending = prepareTargetResumeExport(d, opts);
    lines(d)[0].text = 'Changed after clicking'; opts.locale = 'zh'; opts.page_size = 'a4';
    const result = unwrap(await pending);
    expect(texts(result.projection)[0]).toBe(lines(before)[0].text);
    expect(result.projection).toMatchObject(options);
    expect(result.document_signature).toBe(baseGolden.document_signature);
    expect(isPreparedTargetResumeExportCurrent(result, d)).toBe(false);
  });
  it('deep freezes prepared output without freezing or modifying the source draft', async () => {
    const d = doc(); const before = clone(d); const result = await prepare(d);
    expect(d).toEqual(before); expect(Object.isFrozen(d.document.sections)).toBe(false);
    expect(Object.isFrozen(result)).toBe(true); expect(Object.isFrozen(result.projection.sections[0].blocks[0].lines[0])).toBe(true);
    expect(() => { result.projection.sections[0].blocks[0].lines[0].text = 'bad'; }).toThrow();
  });
  it('accepts an owned historical/unsaved draft without rebinding it to new profile or target material', async () => {
    const d = doc(); const initial = clone(d.base); lines(d)[0].text = 'Unsaved wording';
    const result = await prepare(d);
    expect(texts(result.projection)[0]).toBe('Unsaved wording'); expect(d.base).toEqual(initial);
    expect(JSON.parse(result.canonical_draft).base).toEqual(initial);
  });
  it.each([['en', 'letter'], ['en', 'a4'], ['zh', 'letter'], ['zh', 'a4']] as const)('binds %s/%s in projection hash while the whole draft hash stays unchanged', async (locale, page_size) => {
    const p = await prepare(doc(), { locale, page_size });
    expect(p.document_signature).toBe(baseGolden.document_signature);
    expect(p.export_signature).toBe(signature(canonical(p.projection)));
    const opposite = await prepare(doc(), { locale: locale === 'en' ? 'zh' : 'en', page_size });
    expect(opposite.export_signature).not.toBe(p.export_signature);
  });
  it('canonical equality ignores object key insertion order but detects even edits to excluded text', async () => {
    const d = doc(); lines(d)[1].included = false; const result = await prepare(d);
    expect(isPreparedTargetResumeExportCurrent(result, Object.fromEntries(Object.entries(d).reverse()))).toBe(true);
    lines(d)[1].text = 'A new excluded edit';
    expect(isPreparedTargetResumeExportCurrent(result, d)).toBe(false);
    expect((await prepare(d)).export_signature).toBe(result.export_signature);
    expect((await prepare(d)).document_signature).not.toBe(result.document_signature);
  });
  it.each([
    ['selection', (d: TargetResumeV1) => { lines(d)[0].included = false; }],
    ['ordering', (d: TargetResumeV1) => { d.document.sections.reverse(); }],
    ['rebuilt identity', (d: TargetResumeV1) => { d.id = 'new-draft'; }],
    ['source withdrawal', (d: TargetResumeV1) => { d.base_snapshot.experience_entries[0].status = 'withdrawn'; }],
    ['new target context', (d: TargetResumeV1) => { d.target_snapshot.description += ' changed'; }],
  ] as const)('retires the prepared download after %s', async (_label, mutate) => {
    const d = doc(); const p = await prepare(d); mutate(d);
    expect(isPreparedTargetResumeExportCurrent(p, d)).toBe(false);
  });
  it('fails closed for malformed, sparse or cyclic values in the synchronous final comparison', async () => {
    const p = await prepare(); const circular: Record<string, unknown> = {}; circular.self = circular;
    for (const value of [null, undefined, circular, { ...doc(), extra: undefined }, { ...doc(), document: { sections: new Array(2) } }])
      expect(isPreparedTargetResumeExportCurrent(p, value)).toBe(false);
  });
});

describe('safe refusals without modifying user content', () => {
  it.each(['none-selected', 'all-blank'] as const)('rejects %s instead of returning a successful empty file', async kind => {
    const d = doc();
    for (const line of lines(d)) { if (kind === 'none-selected') line.included = false; else line.text = ' \r\n\t'; }
    const before = clone(d);
    expect(await prepareTargetResumeExport(d, options)).toEqual({ ok: false, code: 'empty_document' }); expect(d).toEqual(before);
  });
  it.each(['\0', '\u0001', '\u000b', '\u000c', '\u001f', '\ud800', '\udfff', '\ufffe', '\uffff'])('rejects XML-invalid character %j in selected text without trimming it', async character => {
    const d = doc(); lines(d)[0].text = `Before${character}After`; const before = clone(d);
    expect(await prepareTargetResumeExport(d, options)).toEqual({ ok: false, code: 'unsupported_character' }); expect(d).toEqual(before);
  });
  it('rejects unsupported characters in an otherwise structurally valid custom heading and label', async () => {
    const d = doc(); const section = d.document.sections.find(s => s.kind === 'other')!;
    const heading = 'Awards\u0001';
    d.base_snapshot.resume_master.other_sections[0].heading = heading;
    section.heading = heading; section.blocks[0].lines[0].label = heading;
    expect(validateTargetResume(d).ok).toBe(true);
    expect(await prepareTargetResumeExport(d, options)).toEqual({ ok: false, code: 'unsupported_character' });
  });
  it('does not send or reject XML-only-invalid content that is excluded from the projection', async () => {
    const d = doc(); lines(d)[0].text = 'Private\u0001excluded'; lines(d)[0].included = false;
    expect(validateTargetResume(d).ok).toBe(true);
    const p = await prepare(d); expect(JSON.stringify(p.projection)).not.toContain('Private');
  });
  it.each(['source_signature', 'target_signature'] as const)('rejects forged %s without leaking source text', async key => {
    const d = doc(); d.base[key] = (key === 'source_signature' ? '' : 'v1:sha256:') + 'f'.repeat(64);
    expect(await prepareTargetResumeExport(d, options)).toEqual({ ok: false, code: key === 'source_signature' ? 'invalid_document' : 'invalid_signature' });
  });
  it('rejects a changed original or withdrawn snapshot entry rather than filling data back from raw source', async () => {
    const d = doc(); lines(d)[0].original = 'Unconfirmed';
    expect(await prepareTargetResumeExport(d, options)).toEqual({ ok: false, code: 'invalid_document' });
    const withdrawn = doc(); withdrawn.base_snapshot.experience_entries[0].status = 'withdrawn';
    expect(await prepareTargetResumeExport(withdrawn, options)).toEqual({ ok: false, code: 'invalid_document' });
  });
  it.each([null, {}, { locale: 'fr', page_size: 'letter' }, { locale: 'en', page_size: 'legal' }, { ...options, format: 'pdf' }])('rejects invalid options %j', async opts => {
    expect(await prepareTargetResumeExport(doc(), opts as TargetResumeExportOptions)).toEqual({ ok: false, code: 'invalid_options' });
  });
  it('rejects oversized whole drafts without any text clipping', async () => {
    const d = doc(); lines(d)[0].text = '汉'.repeat(800000);
    expect(await prepareTargetResumeExport(d, options)).toEqual({ ok: false, code: 'document_too_large' });
    expect(lines(d)[0].text.length).toBe(800000);
  });
  it('returns a safe error when digest capability is unavailable', async () => {
    vi.stubGlobal('crypto', undefined);
    expect(await prepareTargetResumeExport(doc(), options)).toEqual({ ok: false, code: 'signature_unavailable' });
  });
  it('returns a safe digest error if the final hash fails after valid source checks', async () => {
    let calls = 0;
    vi.stubGlobal('crypto', { subtle: { digest: (...args: Parameters<SubtleCrypto['digest']>) => {
      calls += 1;
      if (calls > 2) return Promise.reject(new Error('PRIVATE SOURCE ERROR'));
      return webcrypto.subtle.digest(args[0], args[1] as ArrayBuffer);
    } } });
    expect(await prepareTargetResumeExport(doc(), options)).toEqual({ ok: false, code: 'signature_unavailable' });
  });
});
