/** Cross-language golden contract. Storage uses a mocked SDK boundary: this
 * exercises real validators/owner/CAS envelopes, not PostgreSQL or hosted ACLs. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import golden from '../../../tests/fixtures/target-resume-context-v2-golden.json';
import legacy from '../../../tests/fixtures/target-resume-ai-golden.json';
import {
  targetResumeContextFromOpportunity, targetResumeContextSignature, validateTargetResume,
  verifyTargetResumeSignatures, type TargetResumeV1,
} from './target-resume';
import type { Opportunity } from './types';
import { prepareTargetResumeAI } from './target-resume-ai';
import { prepareTargetResumeExport } from './target-resume-export';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
const { rpc, from, device } = vi.hoisted(() => ({ rpc: vi.fn(), from: vi.fn(), device: vi.fn() }));
vi.mock('./supabase', () => ({ supabase: { rpc, from }, getDeviceId: device }));
import { loadTargetResume, loadTargetResumeHistory, loadTargetResumeVersion, saveTargetResume } from './target-resume-storage';

const clone = <T,>(value: T): T => structuredClone(value);
const current = () => clone(golden.draft) as TargetResumeV1;
const old = () => clone(legacy.draft) as TargetResumeV1;
const input = () => clone(golden.public_opportunity) as unknown as Opportunity;
const UID = '77000000-0000-4000-8000-000000000023';
const stamp = '2026-09-24T18:00:00.000Z';
const row = (doc: TargetResumeV1, revision: number) => ({ revision, doc, updated_at: stamp });

beforeEach(() => { vi.stubGlobal('crypto', webcrypto); rpc.mockReset(); from.mockReset(); device.mockReset(); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('independent v2 cross-language golden', () => {
  it('matches exact public context, Unicode budget-independent hashes, full manifest and current manual wording', async () => {
    const source = input(), before = clone(source);
    expect(targetResumeContextFromOpportunity(source)).toEqual(golden.draft.target_snapshot);
    expect(source).toEqual(before);
    const checked = validateTargetResume(current());
    expect(checked).toEqual({ ok: true, value: golden.draft });
    expect(await verifyTargetResumeSignatures(current())).toBe(true);
    expect(await targetResumeContextSignature(current().target_snapshot)).toBe(golden.draft.base.target_signature);
    const prepared = await prepareTargetResumeAI(current());
    expect(prepared.ok).toBe(true);
    if (!prepared.ok) throw new Error(prepared.code);
    expect(prepared.value.document_signature).toBe(golden.document_signature);
    expect(prepared.value.units).toEqual(golden.units);
    expect(prepared.value.units.map(unit => unit.unit_id)).toEqual(golden.manifest.unit_ids);
    expect(prepared.value.protected_unit_count).toBe(golden.manifest.protected_unit_count);
    expect(prepared.value.units.find(unit => unit.unit_id === 'line-6')).toMatchObject({
      original: 'I did not lead the team. I built a Python parser 😀 with my teammates.',
      before_text: 'My manual draft edit is not evidence.',
    });
    expect(JSON.stringify(current().target_snapshot)).not.toMatch(/excluded@|excluded raw|verified_at|expires_at|confidence_score|private_extra/);
  });

  it.each(golden.context_cases)('uses shared ECMAScript numeric/string oracle: $name', async item => {
    const opportunity = input();
    Object.assign(opportunity.eligibility, { min_gpa: JSON.parse(item.input_json) as unknown });
    const target = targetResumeContextFromOpportunity(opportunity);
    expect(target.criteria.eligibility.min_gpa_decimal).toBe(item.expected_min_gpa_decimal);
    expect(await targetResumeContextSignature(target)).toBe(item.target_signature);
  });

  it.each(golden.target_cases)('preserves the exact $name context without migration/defaults', async item => {
    const doc = current(); doc.target_snapshot = clone(item.target) as TargetResumeV1['target_snapshot'];
    doc.base.target_signature = item.target_signature;
    expect(validateTargetResume(doc)).toEqual({ ok: true, value: doc });
    expect(await verifyTargetResumeSignatures(doc)).toBe(true);
    expect(await targetResumeContextSignature(doc.target_snapshot)).toBe(item.target_signature);
  });

  it.each(['eligibility', 'timing', 'application', 'setting', 'availability', 'attribution'] as const)(
    'rejects extra fields in %s instead of dropping them before signing', group => {
      const doc = current();
      Object.assign((doc.target_snapshot as typeof golden.draft.target_snapshot).criteria[group], { private_extra: 'not accepted' });
      expect(validateTargetResume(doc).ok).toBe(false);
    },
  );

  it.each([
    ['eligibility', 'preferred_year', ['Senior']], ['timing', 'deadline', '2027-01-01'],
    ['application', 'requires_resume', 'no'], ['setting', 'remote_option', 'remote'],
    ['availability', 'faculty_availability_status', 'not_accepting'], ['attribution', 'skills_attribution', 'inferred'],
  ] as const)('detects a valid %s edit when a stored signature has not changed', async (group, key, value) => {
    const doc = current();
    Object.assign((doc.target_snapshot as typeof golden.draft.target_snapshot).criteria[group], { [key]: clone(value) });
    expect(validateTargetResume(doc).ok).toBe(true);
    expect(await verifyTargetResumeSignatures(doc)).toBe(false);
  });

  it('does not change the old golden, silently upgrade its provenance, or disable manual export', async () => {
    const doc = old();
    expect(validateTargetResume(doc)).toEqual({ ok: true, value: legacy.draft });
    expect(await verifyTargetResumeSignatures(doc)).toBe(true);
    expect(await prepareTargetResumeAI(doc)).toEqual({ ok: false, code: 'legacy_target_context' });
    const exported = await prepareTargetResumeExport(doc, { locale: 'zh', page_size: 'a4' });
    expect(exported.ok).toBe(true);
    if (!exported.ok) throw new Error(exported.code);
    expect(exported.value.document_signature).toBe(golden.legacy_document_signature);
    expect(exported.value.projection).toEqual(golden.export.projection);
    expect(exported.value.export_signature).toBe(golden.export.export_signature);
    expect(doc).toEqual(legacy.draft);
  });

  it('exports only current selected text, while binding the whole v2 draft signature', async () => {
    const doc = current(), before = clone(doc);
    const exported = await prepareTargetResumeExport(doc, { locale: 'zh', page_size: 'a4' });
    expect(exported.ok).toBe(true);
    if (!exported.ok) throw new Error(exported.code);
    expect(exported.value.document_signature).toBe(golden.document_signature);
    expect(exported.value.projection).toEqual(golden.export.projection);
    expect(exported.value.export_signature).toBe(golden.export.export_signature);
    expect(JSON.stringify(exported.value.projection)).not.toMatch(/criteria|target_snapshot|resume_text|evidence-one|original/);
    expect(JSON.stringify(exported.value.projection)).toContain('My manual draft edit is not evidence.');
    expect(doc).toEqual(before);
  });
});

describe('v1/v2 current and history compatibility at mocked SDK boundary', () => {
  let single: ReturnType<typeof vi.fn>, limit: ReturnType<typeof vi.fn>, select: ReturnType<typeof vi.fn>;
  let filters: Array<[string, unknown]>;
  beforeEach(async () => {
    localStorage.clear(); advanceOwnerEpoch(null); advanceOwnerEpoch(UID); await syncLocalIdentityOwner(UID);
    device.mockResolvedValue(UID); filters = [];
    single = vi.fn(); limit = vi.fn(); select = vi.fn();
    const chain = { select, eq: vi.fn((key, value) => { filters.push([key, value]); return chain; }),
      lt: vi.fn(() => chain), order: vi.fn(() => chain), maybeSingle: single, limit };
    select.mockReturnValue(chain); from.mockReturnValue(chain);
  });

  it.each(['legacy', 'current'] as const)('saves and reopens exact %s snapshots without automatic source upgrade', async kind => {
    const doc = kind === 'current' ? current() : old(), before = clone(doc), token = captureOwnerToken();
    rpc.mockImplementation(async (_name, args) => ({ data: { status: 'saved', ...row(clone(args.p_doc), 8) }, error: null }));
    expect(await saveTargetResume(doc, 7, token)).toEqual({ status: 'saved', value: row(before, 8) });
    expect(rpc).toHaveBeenCalledWith('commit_target_resume_cas', { p_expected_owner: UID,
      p_opportunity_id: doc.opportunity_id, p_expected_revision: 7, p_doc: before });
    single.mockResolvedValue({ data: row(before, 8), error: null });
    expect(await loadTargetResume(doc.opportunity_id, token)).toEqual(row(before, 8));
    expect(filters).toContainEqual(['owner_id', UID]);
    expect(doc).toEqual(before);
  });

  it('reads mixed history metadata, verifies each selected body, and restores old context as a new version', async () => {
    const token = captureOwnerToken(), opportunityId = current().opportunity_id;
    limit.mockResolvedValue({ data: [{ revision: 8, updated_at: stamp }, { revision: 7, updated_at: stamp }], error: null });
    expect(await loadTargetResumeHistory(opportunityId, token)).toHaveLength(2);
    expect(select).toHaveBeenLastCalledWith('revision,updated_at');
    single.mockResolvedValueOnce({ data: row(current(), 8), error: null }).mockResolvedValueOnce({ data: row(old(), 7), error: null });
    expect((await loadTargetResumeVersion(opportunityId, 8, token))?.doc).toEqual(golden.draft);
    const historical = await loadTargetResumeVersion(opportunityId, 7, token);
    expect(historical?.doc).toEqual(legacy.draft);
    if (!historical) throw new Error('history unexpectedly absent');
    rpc.mockResolvedValue({ data: { status: 'saved', ...row(old(), 9) }, error: null });
    expect(await saveTargetResume(historical.doc, 8, token)).toEqual({ status: 'saved', value: row(old(), 9) });
    expect(rpc).toHaveBeenCalledTimes(1);
    expect(historical.doc.target_snapshot).not.toHaveProperty('context_version');
  });

  it('rejects tampered v2 criteria on save/current/history instead of acknowledging corrupt provenance', async () => {
    const doc = current();
    (doc.target_snapshot as typeof golden.draft.target_snapshot).criteria.setting.location = 'Changed lab';
    const token = captureOwnerToken();
    expect(await saveTargetResume(doc, 1, token)).toEqual({ status: 'failed' });
    expect(rpc).not.toHaveBeenCalled();
    single.mockResolvedValue({ data: row(doc, 2), error: null });
    await expect(loadTargetResume(doc.opportunity_id, token)).rejects.toMatchObject({ code: 'invalid' });
    await expect(loadTargetResumeVersion(doc.opportunity_id, 2, token)).rejects.toMatchObject({ code: 'invalid' });
  });
});
