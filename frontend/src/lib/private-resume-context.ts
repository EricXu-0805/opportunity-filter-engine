/** Complete saved import text, scoped to its owner; no public authority fields. */
export interface PrivateResumeContext {
  context_version: 5; opportunity_id: string; title: string; organization: string;
  source_url: string; description: string; requirements: [];
  private_source: {
    version: 1; purpose: 'resume'; target_scope: 'private_import'; verification: 'unverified';
    owner_id: string; revision: number; source_version: string;
    import_source: { version: 1; description_source: 'page_text' | 'page_excerpt' | 'pasted_text' | 'unknown';
      ai_input_scope: 'full_source' | 'source_excerpt' | 'unknown'; llm_enriched: boolean } | null;
  };
}
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const exact = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const uuid = (value: unknown): value is string => typeof value === 'string' && value.length === 36 && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
// Limits are Unicode codepoints, as the import storage counts them.
const text = (value: unknown, max: number): value is string => {
  if (typeof value !== 'string' || /[\u0000\ud800-\udfff]/u.test(value)) return false;
  if (value.length <= max) return true;
  let count = 0;
  for (const _character of value) { if (++count > max) return false; }
  return true;
};
function safeLink(value: string): boolean {
  if (!value) return true;
  if (/[\u0000- \u007f\\]/.test(value)) return false;
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password && !!url.hostname; }
  catch { return false; }
}
export function isPrivateResumeContext(value: unknown): value is PrivateResumeContext {
  if (!object(value) || !exact(value, ['context_version','opportunity_id','title','organization','source_url','description','requirements','private_source'])
    || value.context_version !== 5 || typeof value.opportunity_id !== 'string' || !value.opportunity_id.startsWith('private-import:') || !uuid(value.opportunity_id.slice(15))
    || !text(value.title, 1000) || !value.title.trim() || !text(value.organization, 2000) || !text(value.source_url, 8192) || !safeLink(value.source_url)
    || !text(value.description, 5 * 1024 * 1024) || !value.description.trim() || !Array.isArray(value.requirements) || value.requirements.length !== 0) return false;
  const source = value.private_source;
  if (!object(source) || !exact(source, ['version','purpose','target_scope','verification','owner_id','revision','source_version','import_source'])
    || source.version !== 1 || source.purpose !== 'resume' || source.target_scope !== 'private_import' || source.verification !== 'unverified'
    || !uuid(source.owner_id) || !Number.isSafeInteger(source.revision) || Number(source.revision) < 1
    || typeof source.source_version !== 'string' || !/^pit1:[a-f0-9]{64}$/.test(source.source_version)) return false;
  const labels = source.import_source;
  return labels === null || object(labels) && exact(labels, ['version','description_source','ai_input_scope','llm_enriched'])
    && labels.version === 1 && typeof labels.description_source === 'string' && typeof labels.ai_input_scope === 'string' && ['page_text','page_excerpt','pasted_text','unknown'].includes(labels.description_source)
    && ['full_source','source_excerpt','unknown'].includes(labels.ai_input_scope) && typeof labels.llm_enriched === 'boolean'
    && (labels.ai_input_scope !== 'source_excerpt' || labels.llm_enriched && labels.description_source !== 'unknown')
    && (labels.ai_input_scope !== 'full_source' || labels.llm_enriched && ['page_text','pasted_text'].includes(labels.description_source));
}
/** Identity/revision binding only; independent truth and live ownership need a fresh server read. */
export async function verifyPrivateResumeSource(value: PrivateResumeContext): Promise<boolean> {
  if (!isPrivateResumeContext(value)) return false;
  const { owner_id, revision, source_version } = value.private_source;
  const bytes = new TextEncoder().encode(JSON.stringify({ id: value.opportunity_id, owner_id, revision }));
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  return source_version === 'pit1:' + Array.from(digest, n => n.toString(16).padStart(2, '0')).join('');
}
/** In-memory equality for a checked source, not a server-authenticated receipt. */
export function privateResumeKey(value: PrivateResumeContext | null): string | null {
  if (!isPrivateResumeContext(value)) return null;
  return JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) : item);
}
