import { createHash, webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import golden from '../../../tests/fixtures/private-resume-context-v5-golden.json';
import publicGolden from '../../../tests/fixtures/target-resume-context-v4-golden.json';
import { DEFAULT_PROFILE } from '@/app/home/types';
import { isPrivateResumeContext, verifyPrivateResumeSource, type PrivateResumeContext } from './private-resume-context';
import { createTargetResume, hasTargetResumeCriteria, isCurrentTargetResumeContext, targetResumeContextSignature,
  validateTargetResume, verifyTargetResumeSignatures, type TargetResumeContext, type TargetResumeV1 } from './target-resume';
import { appendTargetResumeProvenance, validateTargetResumeProvenance } from './target-resume-provenance';
import { prepareTargetResumeAI } from './target-resume-ai';
import { prepareTargetResumePlan } from './target-resume-plan';
import { prepareTargetResumeExport } from './target-resume-export';

const clone = <T,>(value: T): T => structuredClone(value);
const context = () => clone(golden.receipt.context) as PrivateResumeContext;
const doc = () => clone(golden.draft) as TargetResumeV1;
const fetchMock = vi.fn<typeof fetch>();
const pit1 = (id: string, owner_id: string, revision: number) =>
  'pit1:' + createHash('sha256').update(JSON.stringify({ id, owner_id, revision })).digest('hex');
beforeEach(() => { vi.stubGlobal('crypto', webcrypto); fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('private résumé source as a draft target', () => {
  it('signs the route receipt context exactly as the server does', async () => {
    expect(isPrivateResumeContext(context())).toBe(true);
    expect(await verifyPrivateResumeSource(context())).toBe(true);
    expect(await targetResumeContextSignature(context())).toBe(golden.receipt.target_signature);
    expect(hasTargetResumeCriteria(context())).toBe(false);
    expect(isCurrentTargetResumeContext(context())).toBe(false);
  });

  it('creates a full draft from every confirmed section and saves manual edits as provenance V1', async () => {
    const source = doc().base_snapshot;
    const input = { ...DEFAULT_PROFILE, resume_text: source.resume_text, resume_master: source.resume_master,
      experience_entries: source.experience_entries, research_interests: 'Parsers and systems.' };
    const created = await createTargetResume(input, context(), 'private-full-draft');
    const expected = doc().document;
    for (const section of expected.sections) for (const block of section.blocks) for (const line of block.lines) line.text = line.original;
    expect(created.document).toEqual(expected);
    expect(created.base_snapshot).toEqual({ ...source, research_interests: 'Parsers and systems.' });
    expect(created.target_snapshot).toEqual(context());
    expect(created.base.target_signature).toBe(golden.receipt.target_signature);
    expect(validateTargetResume(created).ok).toBe(true);
    expect(await verifyTargetResumeSignatures(created)).toBe(true);
    const edited = clone(created); edited.document.sections[0].blocks[0].lines[0].text += ' (edited)';
    const provenance = appendTargetResumeProvenance(null, created, edited, { kind: 'manual', id: 'private-edit' });
    expect(provenance).toMatchObject({ version: 1, opportunity_id: context().opportunity_id });
    expect(provenance?.events).toHaveLength(1);
    expect(validateTargetResumeProvenance(provenance, edited).ok).toBe(true);
    expect(validateTargetResume(doc())).toEqual({ ok: true, value: golden.draft });
    expect(await verifyTargetResumeSignatures(doc())).toBe(true);
  });

  it('refuses a source whose version does not bind its id, owner and revision, even with a recomputed outer hash', async () => {
    const value = doc(), target = value.target_snapshot as PrivateResumeContext;
    target.private_source.revision++;
    const canonical = JSON.stringify(target, (_k, v) => v && typeof v === 'object' && !Array.isArray(v)
      ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) : v);
    value.base.target_signature = 'v1:sha256:' + createHash('sha256').update(canonical).digest('hex');
    expect(await verifyTargetResumeSignatures(value)).toBe(false);
    await expect(targetResumeContextSignature(target)).rejects.toMatchObject({ code: 'invalid_signature' });
    const source = doc().base_snapshot;
    await expect(createTargetResume({ ...DEFAULT_PROFILE, resume_text: source.resume_text, resume_master: source.resume_master,
      experience_entries: source.experience_entries }, target)).rejects.toThrow();
  });

  it('hashes the context as it was passed, not a later mutation', async () => {
    const value = context(), result = targetResumeContextSignature(value);
    value.description = 'Later source'; value.private_source.revision++;
    expect(await result).toBe(golden.receipt.target_signature);
  });

  it('refuses a complete draft over the size limit without truncating the private source', async () => {
    const value = doc(), target = value.target_snapshot as PrivateResumeContext;
    target.description = 'x'.repeat(2 * 1024 * 1024);
    expect(isPrivateResumeContext(target)).toBe(true);
    expect(validateTargetResume(value)).toEqual({ ok: false, code: 'document_too_large' });
    await expect(targetResumeContextSignature(target)).rejects.toMatchObject({ code: 'document_too_large' });
    expect(target.description).toHaveLength(2 * 1024 * 1024);
  });

  it('keeps the public AI tools closed to a private draft', async () => {
    expect(await prepareTargetResumeAI(doc())).toMatchObject({ ok: false, code: 'legacy_target_context' });
    expect(await prepareTargetResumePlan(doc(), { target_pages: 1 })).toMatchObject({ ok: false, code: 'legacy_target_context' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('exports only the selected résumé wording, never the private source or evidence', async () => {
    const prepared = await prepareTargetResumeExport(doc(), { locale: 'en', page_size: 'letter' });
    expect(prepared.ok).toBe(true); if (!prepared.ok) return;
    const serialized = JSON.stringify(prepared.value.projection);
    expect(serialized).not.toContain(context().description); expect(serialized).not.toContain(context().private_source.owner_id);
    expect(serialized).not.toContain('private_source'); expect(serialized).not.toContain('experience_entries');
    expect(prepared.value.document_signature).toBe(golden.document_signature);
  });

  it.each([1000, 1001])('counts title length in Unicode characters (%s emoji)', length => {
    const value = context(); value.title = '😀'.repeat(length);
    expect(isPrivateResumeContext(value)).toBe(length === 1000);
  });

  it.each(['extra', 'criteria', 'authority', 'requirements', 'public_id', 'other_prefix', 'owner', 'revision_bool', 'revision_zero',
    'purpose', 'source_extra', 'label', 'label_excerpt', 'url', 'empty', 'surrogate', 'nul', 'version'])('refuses a promoted or malformed snapshot (%s)', fault => {
    const value = context() as unknown as Record<string, unknown>, source = value.private_source as Record<string, unknown>;
    if (fault === 'extra') value.extra = true;
    if (fault === 'criteria') value.criteria = {};
    if (fault === 'authority') source.verification = 'verified';
    if (fault === 'requirements') value.requirements = ['Guessed skill'];
    if (fault === 'public_id') value.opportunity_id = 'public-lab';
    if (fault === 'other_prefix') value.opportunity_id = 'publics-import:' + context().opportunity_id.slice(15);
    if (fault === 'owner') source.owner_id = 'A1000000-0000-4000-8000-000000000001';
    if (fault === 'revision_bool') source.revision = true;
    if (fault === 'revision_zero') source.revision = 0;
    if (fault === 'purpose') source.purpose = 'email';
    if (fault === 'source_extra') source.provider_allowed = true;
    if (fault === 'label') source.import_source = { version: 1, description_source: 'unknown', ai_input_scope: 'full_source', llm_enriched: true };
    if (fault === 'label_excerpt') source.import_source = { version: 1, description_source: 'unknown', ai_input_scope: 'source_excerpt', llm_enriched: true };
    if (fault === 'url') value.source_url = 'javascript:alert(1)';
    if (fault === 'empty') value.description = '  ';
    if (fault === 'surrogate') value.description = '\ud800';
    if (fault === 'nul') value.description += '\u0000';
    if (fault === 'version') source.version = 2;
    expect(isPrivateResumeContext(value)).toBe(false);
    const draft = doc(); draft.target_snapshot = value as unknown as TargetResumeContext;
    expect(validateTargetResume(draft)).toEqual({ ok: false, code: ['surrogate', 'nul'].includes(fault) ? 'invalid_unicode' : 'invalid_target' });
  });

  it('accepts the largest revision the import storage allows', async () => {
    const value = context(); value.private_source.revision = Number.MAX_SAFE_INTEGER;
    value.private_source.source_version = pit1(value.opportunity_id, value.private_source.owner_id, value.private_source.revision);
    expect(isPrivateResumeContext(value)).toBe(true);
    expect(await verifyPrivateResumeSource(value)).toBe(true);
  });

  it.each([1, 2, 3, 4])('does not let a private-import id pass as a public v%s snapshot', version => {
    const draft = clone(publicGolden.draft) as TargetResumeV1, target = draft.target_snapshot as unknown as Record<string, unknown>;
    target.opportunity_id = context().opportunity_id; draft.opportunity_id = context().opportunity_id;
    if (version < 4) delete target.lab;
    if (version < 3) delete target.research;
    if (version < 2) { delete target.criteria; delete target.context_version; } else target.context_version = version;
    expect(validateTargetResume(draft)).toEqual({ ok: false, code: 'invalid_target' });
    expect(hasTargetResumeCriteria(target)).toBe(false);
  });
});
