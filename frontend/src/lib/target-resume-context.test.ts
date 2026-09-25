import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createHash, webcrypto } from 'node:crypto';
import legacyGolden from '../../../tests/fixtures/target-resume-ai-golden.json';
import { DEFAULT_PROFILE } from '@/app/home/types';
import type { Opportunity } from './types';
import { createTargetResume, isCurrentTargetResumeContext, targetResumeContextFromOpportunity,
  targetResumeContextSignature, validateTargetResume, verifyTargetResumeSignatures, type TargetResumeV1 } from './target-resume';
import { prepareTargetResumeAI } from './target-resume-ai';
import { prepareTargetResumeExport } from './target-resume-export';

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const emptyCriteria = () => ({ eligibility: {}, timing: {}, application: {}, setting: {}, availability: {}, attribution: {} });
const canonical = (value: unknown): string => JSON.stringify(value, (_key, item: unknown) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) : item);
const fingerprint = (value: unknown) => `v1:sha256:${createHash('sha256').update(canonical(value)).digest('hex')}`;
function opportunity(): Opportunity {
  return { id: 'criteria-target', title: 'Research', organization: 'Example lab', source_url: 'https://example.test/lab',
    description_clean: 'Build instruments with Python.', keywords: ['instruments'], opportunity_type: 'research', paid: 'stipend',
    location: 'Urbana 王', on_campus: true, eligibility: { preferred_year: ['Junior'], majors: ['ECE'], skills_required: ['Python'],
      international_friendly: 'unknown', citizenship_required: false },
    application: { contact_method: 'email', application_effort: 'low', requires_resume: 'yes' },
    metadata: { is_active: true, confidence_score: 0.75 } };
}
function oldDoc() { return clone(legacyGolden.draft) as TargetResumeV1; }
function currentDoc() {
  const doc = oldDoc();
  doc.target_snapshot = { ...doc.target_snapshot, context_version: 2, criteria: emptyCriteria() };
  doc.base.target_signature = fingerprint(doc.target_snapshot);
  return doc;
}
beforeEach(() => vi.stubGlobal('crypto', webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('versioned persisted target context', () => {
  it('captures exact public criteria, retaining null and wire strings without private or volatile fields', () => {
    const input = { ...opportunity(), deadline: '2026-10-15', deadline_is_estimate: false, is_rolling: true,
      start_date: 'Spring 2027', posted_date: null, duration: '12 weeks', remote_option: 'hybrid', department: 'ECE',
      lab_or_program: 'Lab A', pi_name: null, source_type: 'campus_program', record_kind: 'listing',
      faculty_availability_status: 'unknown', paid_attribution: null,
      target_truth: { listing_state: 'open', reference_only: false, actionable: true, accepting_state: 'accepting',
        reason_code: null, verified_at: '2026-09-24', expires_at: '2026-10-24', private_extra: 'exclude' },
      eligibility: { ...opportunity().eligibility, min_gpa: 3.5, skills_preferred: ['C++'], work_auth_notes: 'Check source', first_time_researchers: true },
      application: { ...opportunity().application, requires_transcript: 'unknown', requires_cover_letter: null, requires_recommendation: 'no', application_url: null },
      metadata: { ...opportunity().metadata, deadline_note: 'Applications close October 15.', paid_attribution: 'inferred',
        skills_attribution: 'inferred', majors_attribution: null, private_extra: 'exclude' }, contact_email: 'private@example.test', description_raw: 'raw scrape' };
    const result = targetResumeContextFromOpportunity(input as unknown as Opportunity);
    expect(result).toMatchObject({ context_version: 2, requirements: [], criteria: {
      eligibility: { preferred_year: ['Junior'], majors: ['ECE'], skills_required: ['Python'], international_friendly: 'unknown', citizenship_required: false, skills_preferred: ['C++'], work_auth_notes: 'Check source', first_time_researchers: true, min_gpa_decimal: '3.5' },
      timing: { deadline: input.deadline, deadline_is_estimate: false, is_rolling: true, deadline_note: input.metadata.deadline_note,
        start_date: input.start_date, posted_date: null, duration: input.duration },
      application: input.application,
      setting: { location: 'Urbana 王', on_campus: true, opportunity_type: 'research', paid: 'stipend', remote_option: 'hybrid', department: 'ECE', lab_or_program: 'Lab A', pi_name: null },
      availability: { source_type: 'campus_program', record_kind: 'listing', faculty_availability_status: 'unknown',
        target_truth: { listing_state: 'open', reference_only: false, actionable: true, accepting_state: 'accepting', reason_code: null } },
      attribution: { paid_attribution: null, skills_attribution: 'inferred', majors_attribution: null },
    } });
    expect(isCurrentTargetResumeContext(result)).toBe(true);
    expect(JSON.stringify(result)).not.toMatch(/private@example|raw scrape|private_extra|verified_at|expires_at|confidence_score|is_active/);
    expect(result.criteria.eligibility).not.toHaveProperty('min_gpa');
  });
  it('distinguishes omitted, null, false and empty values without supplying defaults', () => {
    const minimal = { id: 'minimal', title: '', organization: '', description_clean: '' } as Opportunity;
    expect(targetResumeContextFromOpportunity(minimal)).toEqual({ opportunity_id: 'minimal', title: '', organization: '', source_url: '', description: '', requirements: [], context_version: 2, criteria: emptyCriteria() });
    const input = { ...minimal, paid: null, on_campus: false, eligibility: { majors: [], citizenship_required: null }, application: { requires_resume: '' } };
    const value = targetResumeContextFromOpportunity(input as unknown as Opportunity);
    expect(value.criteria.eligibility).toEqual({ majors: [], citizenship_required: null });
    expect(value.criteria.setting).toEqual({ paid: null, on_campus: false });
    expect(value.criteria.application).toEqual({ requires_resume: '' });
  });
  it.each([3.5, 1e-7, 1e21, -0, ' 3.50 ', null])('preserves minimum GPA as deterministic decimal text: %s', (min_gpa) => {
    const input = opportunity(); Object.assign(input.eligibility, { min_gpa });
    expect(targetResumeContextFromOpportunity(input).criteria.eligibility.min_gpa_decimal).toBe(typeof min_gpa === 'number' ? JSON.stringify(min_gpa) : min_gpa);
  });
  it.each([
    ['wire bool materials', (o: Opportunity) => Object.assign(o.application, { requires_resume: true })],
    ['wire bool paid', (o: Opportunity) => Object.assign(o, { paid: false })],
    ['string citizenship', (o: Opportunity) => Object.assign(o.eligibility, { citizenship_required: 'yes' })],
    ['nonfinite GPA', (o: Opportunity) => Object.assign(o.eligibility, { min_gpa: Infinity })],
    ['string years', (o: Opportunity) => Object.assign(o.eligibility, { preferred_year: 'Junior' })],
    ['bad attribution', (o: Opportunity) => Object.assign(o, { skills_attribution: 'verified' })],
  ] as const)('rejects malformed provided fields: %s', (_label, mutate) => {
    const input = opportunity(); mutate(input);
    expect(() => targetResumeContextFromOpportunity(input)).toThrowError('invalid_target');
  });
  it('uses explicit top-level attribution even when metadata disagrees', () => {
    const input = opportunity(); input.skills_attribution = null; input.metadata.skills_attribution = 'inferred';
    const value = targetResumeContextFromOpportunity(input);
    expect(value.criteria.attribution.skills_attribution).toBeNull();
    expect(value.requirements).toEqual(['Python']);
  });
  it('accepts legacy documents without upgrading their source, but forbids AI and new legacy creation', async () => {
    const doc = oldDoc(), before = canonical(doc);
    expect(isCurrentTargetResumeContext(doc.target_snapshot)).toBe(false);
    expect(validateTargetResume(doc)).toEqual({ ok: true, value: doc });
    expect(await verifyTargetResumeSignatures(doc)).toBe(true);
    doc.document.sections[0].blocks[0].lines[0].text = 'Manual old draft 王';
    expect((await prepareTargetResumeExport(doc, { locale: 'en', page_size: 'letter' })).ok).toBe(true);
    expect(await prepareTargetResumeAI(doc)).toEqual({ ok: false, code: 'legacy_target_context' });
    expect(canonical(doc.target_snapshot)).toBe(canonical(legacyGolden.draft.target_snapshot));
    expect(doc.base.target_signature).toBe(legacyGolden.draft.base.target_signature);
    await expect(createTargetResume({ ...DEFAULT_PROFILE, ...doc.base_snapshot }, doc.target_snapshot)).rejects.toMatchObject({ code: 'invalid_target' });
    expect(canonical(oldDoc())).toBe(before);
  });
  it('validates and hashes v2 contexts including exact missing/null/array/provenance distinctions', async () => {
    const doc = currentDoc(); expect(validateTargetResume(doc).ok).toBe(true);
    expect(await verifyTargetResumeSignatures(doc)).toBe(true);
    expect(await targetResumeContextSignature(doc.target_snapshot)).toBe(doc.base.target_signature);
    const changed = clone(doc); if (!isCurrentTargetResumeContext(changed.target_snapshot)) throw new Error('expected v2');
    changed.target_snapshot.criteria.eligibility.citizenship_required = null;
    expect(validateTargetResume(changed).ok).toBe(true); expect(await verifyTargetResumeSignatures(changed)).toBe(false);
  });
  it.each(['criteria-extra', 'group-extra', 'group-missing', 'truth-extra', 'null-group', 'unknown-version'] as const)('rejects malformed v2 without falling back to legacy: %s', (bad) => {
    const doc = currentDoc(); const context = doc.target_snapshot as unknown as Record<string, unknown>;
    const criteria = context.criteria as Record<string, unknown>;
    if (bad === 'criteria-extra') criteria.unrecognized = {};
    if (bad === 'group-extra') criteria.application = { contact_email: 'must not persist' };
    if (bad === 'group-missing') delete criteria.timing;
    if (bad === 'truth-extra') criteria.availability = { target_truth: { actionable: true, verified_at: 'unrecognized' } };
    if (bad === 'null-group') criteria.setting = null;
    if (bad === 'unknown-version') context.context_version = 3;
    expect(isCurrentTargetResumeContext(context)).toBe(false); expect(validateTargetResume(doc).ok).toBe(false);
  });
  it('counts all new criteria against the unchanged AI target budget without truncating the saved source', async () => {
    const doc = currentDoc(); if (!isCurrentTargetResumeContext(doc.target_snapshot)) throw new Error('expected v2');
    doc.target_snapshot.criteria.eligibility.work_auth_notes = '完整来源😀'.repeat(6000);
    doc.base.target_signature = fingerprint(doc.target_snapshot);
    const result = await prepareTargetResumeAI(doc);
    expect(result.ok).toBe(true); if (!result.ok) throw new Error(result.code);
    expect(result.value.batches).toEqual([]);
    expect(result.value.skipped.length).toBeGreaterThan(0);
    expect(result.value.skipped.every(item => item.reason_code === 'target_too_large')).toBe(true);
    expect(result.value.draft.target_snapshot).toEqual(doc.target_snapshot);
  });
});
