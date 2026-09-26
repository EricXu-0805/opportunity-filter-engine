/** Source metadata, not a student's reading or competence declaration. */
export interface ResearchWork {
  work_id: string; title: string; year: number; publication_date: string | null;
  source_url: string; doi: string | null; abstract: string | null;
  abstract_status: 'present' | 'missing' | 'invalid' | 'too_long'; updated_date: string | null;
}
export interface ResearchSnapshot {
  version: 1; source: 'openalex'; record_source_url: string; identity_name: string;
  institution_id: string; author_id: string; gate_version: number; checked_at: string;
  works: ResearchWork[]; snapshot_version: string;
}
export interface ResearchContext {
  version: 1; status: 'available' | 'stale' | 'unavailable'; snapshot: ResearchSnapshot | null;
}
const snapshotKeys = ['version', 'source', 'record_source_url', 'identity_name', 'institution_id', 'author_id', 'gate_version', 'checked_at', 'works', 'snapshot_version'];
const workKeys = ['work_id', 'title', 'year', 'publication_date', 'source_url', 'doi', 'abstract', 'abstract_status', 'updated_date'];
function exact(value: unknown, keys: string[]): value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const proto = Object.getPrototypeOf(value);
  return (proto === Object.prototype || proto === null) && Reflect.ownKeys(value).length === keys.length
    && keys.every(key => Object.hasOwn(value, key));
}
function text(value: unknown, limit: number, singleLine = false): value is string {
  return typeof value === 'string' && !!value.trim() && [...value].length <= limit
    && ![...value].some(c => { const p = c.codePointAt(0)!; return p === 0 || (p >= 0xd800 && p <= 0xdfff); })
    && (!singleLine || !/[\r\n\u2028\u2029]/u.test(value));
}
function url(value: unknown): value is string {
  if (!text(value, 2000, true) || /[\s\\]/u.test(value)) return false;
  try { const parsed = new URL(value); return ['http:', 'https:'].includes(parsed.protocol) && !!parsed.hostname && !parsed.username && !parsed.password && !parsed.hash; } catch { return false; }
}
function id(value: unknown, kind: string): value is string {
  return typeof value === 'string' && new RegExp(`^https://openalex\\.org/${kind}[1-9][0-9]*$`).test(value);
}
function date(value: unknown): value is string {
  return typeof value === 'string' && /^[1-9][0-9]{3}-[0-9]{2}-[0-9]{2}$/.test(value)
    && Number.isFinite(Date.parse(value + 'T00:00:00Z')) && new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value;
}
function timestamp(value: unknown): value is string {
  if (typeof value !== 'string' || !/^[1-9][0-9]{3}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$/.test(value)) return false;
  return date(value.slice(0, 10)) && Number.isFinite(Date.parse(value)) && Number(value.slice(11, 13)) < 24 && Number(value.slice(14, 16)) < 60 && Number(value.slice(17, 19)) < 60;
}
function updated(value: unknown): value is string {
  if (date(value)) return true;
  if (typeof value !== 'string' || !/^[1-9][0-9]{3}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)?$/.test(value)) return false;
  return timestamp(value.replace(/(?:Z|\+00:00)$/, '') + 'Z');
}
function doi(value: unknown): value is string {
  return url(value) && /^https:\/\/doi\.org\/10\.[0-9]{4,9}\/[^\s?#]+$/.test(value);
}
/** Strict detached parse. Preserve historical status; the server owns freshness,
 * identity and SHA validation. The synchronous browser parser checks the token
 * format; target signatures bind the exact complete content independently. */
export function parseResearchContext(value: unknown): ResearchContext | null {
  try {
    if (!exact(value, ['version', 'status', 'snapshot']) || value.version !== 1
      || !['available', 'stale', 'unavailable'].includes(value.status as string)) return null;
    if (value.status === 'unavailable') return value.snapshot === null ? { version: 1, status: 'unavailable', snapshot: null } : null;
    const s = value.snapshot;
    if (!exact(s, snapshotKeys) || s.version !== 1 || s.source !== 'openalex' || !url(s.record_source_url)
      || !text(s.identity_name, 200) || !id(s.institution_id, 'I') || !id(s.author_id, 'A')
      || ['https://openalex.org/A9999999999', 'https://openalex.org/A5317838346'].includes(s.author_id)
      || !Number.isSafeInteger(s.gate_version) || (s.gate_version as number) < 3 || !timestamp(s.checked_at)
      || typeof s.snapshot_version !== 'string' || !/^rs1:[0-9a-f]{64}$/.test(s.snapshot_version)
      || !Array.isArray(s.works) || s.works.length > 3) return null;
    const seen = new Set<string>();
    for (const w of s.works) {
      if (!exact(w, workKeys) || !id(w.work_id, 'W') || seen.has(w.work_id) || !text(w.title, 1000)
        || !Number.isInteger(w.year) || (w.year as number) < 1000 || (w.year as number) > 2100
        || (w.publication_date !== null && (!date(w.publication_date) || Number(w.publication_date.slice(0, 4)) !== w.year)) || (w.updated_date !== null && !updated(w.updated_date))
        || (w.doi !== null && !doi(w.doi)) || w.source_url !== (w.doi ?? w.work_id)
        || !['present', 'missing', 'invalid', 'too_long'].includes(w.abstract_status as string)
        || (w.abstract_status === 'present' ? !text(w.abstract, 12000) : w.abstract !== null)) return null;
      seen.add(w.work_id);
    }
    return structuredClone(value) as unknown as ResearchContext;
  } catch { return null; }
}
export function isResearchContext(value: unknown): value is ResearchContext { return parseResearchContext(value) !== null; }
