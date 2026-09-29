/** Private imports use their own owner/version contract; never Opportunity. */
import { privateImportEmailRequest, PrivateTargetError, type PrivateImportTarget } from './private-import-target-api';
import { toProfileRequest, coldEmailExperienceEvidence } from './api';
import { captureOwnerToken, isOwnerTokenValid, type OwnerToken } from './identity-owner';
import { contactSourceUrl } from './contact-instructions';
import { readEmailTargetConditions, isEmailConditionIssues, type EmailConditionIssue } from './email-target-conditions';
import { emailContactContextSignature, requireEmailContactContextReceipt } from './email-contact-context';
import type { EmailContactContext, EmailVariantsResponse, ProfileData } from './types';

export interface PrivateEmailContext {
  version: 1; target_scope: 'private_import'; verification: 'unverified'; purpose: 'first_contact';
  id: string; owner_id: string; revision: number; source_version: string; writing_version: string;
  projection_version: 1; policy_version: 1; title: string; organization: string | null; source_url: string | null;
  import_source: PrivateImportTarget['import_source']; provider_allowed: false;
  contact_policy: { state: 'unknown' | 'blocked'; reason: 'unverified_import' | 'no_email' | 'form_only' | 'multiple_restrictions' | 'policy_review_required';
    quotes: Array<{ start: number; end: number; quote: string; restriction: 'no_email' | 'form_only' }> };
}
export type PrivateEmailIssue = EmailConditionIssue | 'invalid_recipient' | 'contact_review_required' | 'contact_blocked';
export interface PrivateEmailValidation { outcome: 'ready' | 'review_required'; issues: PrivateEmailIssue[] }
const obj = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const exact = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const text = (v: unknown, max: number): v is string => typeof v === 'string' && Array.from(v).length <= max && !/[\u0000\ud800-\udfff]/u.test(v);
const invalid = (): never => { throw new PrivateTargetError('invalid_receipt'); };
export function readPrivateEmailContext(value: unknown, owner: OwnerToken, id: string): PrivateEmailContext {
  if (!obj(value) || !exact(value, ['version','target_scope','verification','purpose','id','owner_id','revision','source_version','writing_version','projection_version','policy_version','title','organization','source_url','import_source','provider_allowed','contact_policy'])
    || value.version !== 1 || value.target_scope !== 'private_import' || value.verification !== 'unverified' || value.purpose !== 'first_contact'
    || value.id !== id || value.owner_id !== owner.uid || !isOwnerTokenValid(owner, owner.uid)
    || !Number.isSafeInteger(value.revision) || (value.revision as number) < 1
    || !text(value.source_version, 69) || !/^pit1:[a-f0-9]{64}$/.test(value.source_version)
    || !text(value.writing_version, 69) || !/^pwt1:[a-f0-9]{64}$/.test(value.writing_version)
    || value.projection_version !== 1 || value.policy_version !== 1 || value.provider_allowed !== false
    || !text(value.title, 1000) || !value.title.trim() || !(value.organization === null || text(value.organization, 2000))
    || !(value.source_url === null || text(value.source_url, 8192) && contactSourceUrl(value.source_url) !== null && !/[\u0000-\u0020\u007f\\]/.test(value.source_url))) return invalid();
  if (value.import_source !== null) {
    const source = value.import_source;
    if (!obj(source) || !exact(source, ['version','description_source','ai_input_scope','llm_enriched']) || source.version !== 1
      || typeof source.description_source !== 'string' || !['page_text','page_excerpt','pasted_text','unknown'].includes(String(source.description_source))
      || typeof source.ai_input_scope !== 'string' || !['source_excerpt','unknown'].includes(String(source.ai_input_scope)) || typeof source.llm_enriched !== 'boolean' || (source.ai_input_scope === 'source_excerpt' && (source.llm_enriched !== true || source.description_source === 'unknown')) || (source.description_source === 'unknown' && source.llm_enriched !== false)) return invalid();
  }
  const policy = value.contact_policy;
  if (!obj(policy) || !exact(policy, ['state','reason','quotes']) || !Array.isArray(policy.quotes) || policy.quotes.length > 20
    || typeof policy.state !== 'string' || typeof policy.reason !== 'string' || !['unknown','blocked'].includes(String(policy.state)) || !['unverified_import','no_email','form_only','multiple_restrictions','policy_review_required'].includes(String(policy.reason))
    || (policy.state === 'unknown' && !['unverified_import','policy_review_required'].includes(String(policy.reason))) || (policy.state === 'blocked' && policy.reason === 'unverified_import') || (policy.state === 'unknown' && policy.quotes.length !== 0)
    || policy.quotes.some(q => !obj(q) || !exact(q, ['start','end','quote','restriction']) || !Number.isSafeInteger(q.start) || !Number.isSafeInteger(q.end)
      || (q.start as number) < 0 || (q.end as number) <= (q.start as number) || !text(q.quote, 2000) || !q.quote.trim()
      || (q.end as number) > 5 * 1024 * 1024 || typeof q.restriction !== 'string' || Array.from(q.quote).length !== (q.end as number) - (q.start as number) || !['no_email','form_only'].includes(String(q.restriction)))) return invalid();
  return structuredClone(value) as unknown as PrivateEmailContext;
}
export function privateEmailKey(value: PrivateEmailContext | null): string | null {
  if (!value) return null;
  try { return JSON.stringify(value, (_key, v) => obj(v) ? Object.fromEntries(Object.entries(v).sort(([a],[b]) => a < b ? -1 : a > b ? 1 : 0)) : v); }
  catch { return null; }
}
async function verifyVersions(context: PrivateEmailContext, wait: <T>(pending: Promise<T>) => Promise<T>) {
  const digest = async (value: string) => Array.from(new Uint8Array(await wait(crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))), n => n.toString(16).padStart(2, '0')).join('');
  const source = await digest(JSON.stringify({ id: context.id, owner_id: context.owner_id, revision: context.revision }));
  const projection = Object.fromEntries(Object.entries(context).filter(([key]) => key !== 'writing_version'));
  const writing = await digest(privateEmailKey(projection as unknown as PrivateEmailContext)!);
  if (context.source_version !== `pit1:${source}` || context.writing_version !== `pwt1:${writing}`) invalid();
}
export async function getPrivateEmailContext(id: string, options: { owner: OwnerToken; signal?: AbortSignal }): Promise<PrivateEmailContext> {
  let context: PrivateEmailContext | null = null;
  await privateImportEmailRequest(id, 'context', undefined, { ...options, verify: async (value, wait) => {
    context = readPrivateEmailContext(value, options.owner, id); await verifyVersions(context, wait);
  } });
  return context!;
}
function requirePrivateConditions(data: unknown) {
  if (!obj(data) || !obj(data.target_conditions) || !exact(data.target_conditions, ['version','record_kind','conditions','template_request'])) return invalid();
  const receipt = readEmailTargetConditions(data);
  if (!receipt || receipt.version !== 1 || receipt.record_kind !== 'unverified' || receipt.conditions.length !== 0 || receipt.template_request !== null) return invalid();
}
async function writingRequest(action: 'variants' | 'validate', id: string, profile: ProfileData, context: EmailContactContext,
  target: PrivateEmailContext, extra?: Record<string, unknown>, signal?: AbortSignal): Promise<Record<string, unknown>> {
  const owner = captureOwnerToken();
  if (owner.uid !== target.owner_id || !isOwnerTokenValid(owner, owner.uid)) return invalid();
  const data = await privateImportEmailRequest(id, action, { expected_target_version: target.writing_version,
    profile: toProfileRequest(profile), experience_evidence: coldEmailExperienceEvidence(profile), contact_context: context, ...extra }, { owner, signal, verify: async (data, wait) => {
  const received = readPrivateEmailContext(data.private_context, owner, id);
  await verifyVersions(received, wait);
  requirePrivateConditions(data);
  if (privateEmailKey(received) !== privateEmailKey(target) || data.version !== 1 || data.target_scope !== 'private_import'
    || data.verification !== 'unverified' || data.owner_id !== owner.uid || data.opportunity_id !== id || data.target_version !== target.writing_version
    || data.source_version !== target.source_version || data.pipeline_version !== 'private-cold-email-v1') return invalid();
  const contact = { purpose: context.purpose, context_sig: await wait(emailContactContextSignature(context)) };
  requireEmailContactContextReceipt(data, contact);
  if (action === 'variants' && Array.isArray(data.variants)) {
    if (data.variants.length !== 1) return invalid();
    data.variants.forEach(variant => requireEmailContactContextReceipt(variant, contact));
  }
  if (!isOwnerTokenValid(owner, owner.uid)) return invalid();
  } });
  return data;
}
export async function privateEmailVariants(profile: ProfileData, id: string, target: PrivateEmailContext, context: EmailContactContext): Promise<EmailVariantsResponse> {
  const data = await writingRequest('variants', id, profile, context, target);
  if (data.method !== 'template' || data.grounding !== 'no_target_data' || data.source_freshness !== 'unknown'
    || data.recipient_status !== 'unavailable' || data.recipient_email !== '' || data.lab_type !== null || data.recommended_style !== 'professional' || !Array.isArray(data.variants) || data.variants.length !== 1) return invalid();
  for (const variant of data.variants) {
    if (!obj(variant) || variant.id !== 'private-first-contact' || !text(variant.label, 100) || !text(variant.subject, 2000)
      || !text(variant.body, 5000) || variant.recipient_email !== '' || variant.mailto_link !== '') return invalid();
    requirePrivateConditions(variant);
    if (variant.lab_type != null || variant.method !== undefined && variant.method !== 'template') return invalid();
  }
  requirePrivateConditions(data);
  return data as unknown as EmailVariantsResponse;
}
export async function validatePrivateEmail(subject: string, body: string, recipient: string, reviewed: boolean,
  profile: ProfileData, id: string, target: PrivateEmailContext, context: EmailContactContext, signal?: AbortSignal): Promise<PrivateEmailValidation> {
  const data = await writingRequest('validate', id, profile, context, target, { subject, body, recipient, contact_requirements_reviewed: reviewed }, signal);
  if (!Array.isArray(data.issues) || new Set(data.issues).size !== data.issues.length || data.issues.some(issue =>
    typeof issue !== 'string' || !isEmailConditionIssues([issue]) && !['invalid_recipient','contact_review_required','contact_blocked'].includes(String(issue)))
    || typeof data.outcome !== 'string' || !['ready','review_required'].includes(String(data.outcome)) || (data.outcome === 'ready') !== (data.issues.length === 0)) return invalid();
  return { outcome: data.outcome as PrivateEmailValidation['outcome'], issues: data.issues as PrivateEmailIssue[] };
}
