/** Complete official-page excerpts. They are target material, never student facts. */
export interface LabSection { section_id: string; heading: string; text: string }
export interface LabPage {
  kind: 'faculty_profile' | 'lab_website'; requested_url: string; source_url: string;
  page_title: string; identity_text: string;
  linked_from: { profile_url: string; anchor_text: string; href: string } | null;
  sections: LabSection[];
}
export interface LabSnapshot {
  version: 1; source: 'official_website'; record_id: string; record_source_url: string;
  school: string; department: string; identity_name: string; policy_version: 1;
  checked_at: string; pages: LabPage[]; snapshot_version: string;
}
export interface LabContext {
  version: 1; status: 'available' | 'stale' | 'unavailable'; snapshot: LabSnapshot | null;
}
const snapshotKeys = ['version', 'source', 'record_id', 'record_source_url', 'school', 'department', 'identity_name', 'policy_version', 'checked_at', 'pages', 'snapshot_version'];
const pageKeys = ['kind', 'requested_url', 'source_url', 'page_title', 'identity_text', 'linked_from', 'sections'];
function exact(value: unknown, keys: string[]): value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const proto = Object.getPrototypeOf(value);
  return (proto === Object.prototype || proto === null) && Reflect.ownKeys(value).length === keys.length
    && keys.every(key => Object.hasOwn(value, key));
}
function text(value: unknown, limit: number, blank = false): value is string {
  return typeof value === 'string' && (blank || !!value.trim()) && [...value].length <= limit
    && ![...value].some(c => { const p = c.codePointAt(0)!; return p === 0 || (p >= 0xd800 && p <= 0xdfff); });
}
function url(value: unknown): value is string {
  if (!text(value, 2000) || !/^[\x21-\x7e]+$/.test(value) || /[\\?#]/.test(value)) return false;
  try {
    const p = new URL(value);
    return p.protocol === 'https:' && !p.username && !p.password && !p.port && p.href === value && p.hostname.length <= 253
      && /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(p.hostname);
  } catch { return false; }
}
function timestamp(value: unknown): value is string {
  if (typeof value !== 'string' || !/^[1-9][0-9]{3}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$/.test(value)) return false;
  const ms = Date.parse(value);
  return Number.isFinite(ms) && new Date(ms).toISOString().slice(0, 19) === value.slice(0, 19);
}
/** Historical parse: the server owns receipt authenticity, current identity,
 * freshness and SHA verification. Browser parsing preserves the saved status;
 * document signatures separately bind all source content. */
export function parseLabContext(value: unknown): LabContext | null {
  try {
    if (!exact(value, ['version', 'status', 'snapshot']) || value.version !== 1
      || !['available', 'stale', 'unavailable'].includes(value.status as string)) return null;
    if (value.status === 'unavailable') return value.snapshot === null ? { version: 1, status: 'unavailable', snapshot: null } : null;
    const s = value.snapshot;
    if (!exact(s, snapshotKeys) || s.version !== 1 || s.source !== 'official_website' || s.policy_version !== 1
      || !text(s.record_id, 200) || !text(s.school, 200) || !text(s.department, 200) || !text(s.identity_name, 200)
      || !url(s.record_source_url) || !timestamp(s.checked_at) || typeof s.snapshot_version !== 'string'
      || !/^ls1:[0-9a-f]{64}$/.test(s.snapshot_version) || !Array.isArray(s.pages) || s.pages.length < 1 || s.pages.length > 2) return null;
    let total = 0;
    for (const [index, p] of s.pages.entries()) {
      if (!exact(p, pageKeys) || p.kind !== (index === 0 ? 'faculty_profile' : 'lab_website')
        || !url(p.requested_url) || p.source_url !== p.requested_url || !text(p.page_title, 1000)
        || !text(p.identity_text, 200) || !Array.isArray(p.sections) || !p.sections.length || p.sections.length > 32) return null;
      if (index === 0) {
        if (p.source_url !== s.record_source_url || p.linked_from !== null) return null;
      } else {
        const link = p.linked_from;
        if (!exact(link, ['profile_url', 'anchor_text', 'href']) || link.profile_url !== s.record_source_url
          || link.href !== p.source_url || p.source_url === s.record_source_url || !text(link.anchor_text, 500)) return null;
      }
      for (const [i, section] of p.sections.entries()) {
        if (!exact(section, ['section_id', 'heading', 'text']) || section.section_id !== `s${i + 1}`
          || !text(section.heading, 1000, true) || !text(section.text, 4000)) return null;
        total += [...section.heading].length + [...section.text].length;
        if (total > 24000) return null;
      }
    }
    return structuredClone(value) as unknown as LabContext;
  } catch { return null; }
}
export function isLabContext(value: unknown): value is LabContext { return parseLabContext(value) !== null; }
