/** Complete official-page excerpts. They are target material, never student facts. */
export interface LabSection { section_id: string; heading: string; text: string }
export interface LabPage {
  kind: 'faculty_profile' | 'lab_website'; requested_url: string; source_url: string;
  page_title: string; identity_text: string;
  linked_from: { profile_url: string; anchor_text: string; href: string } | null;
  sections: LabSection[];
}
export interface LabSnapshotV1 {
  version: 1; source: 'official_website'; record_id: string; record_source_url: string;
  school: string; department: string; identity_name: string; policy_version: 1;
  checked_at: string; pages: LabPage[]; snapshot_version: string;
}
export interface LabResearchPage {
  kind: 'lab_research'; requested_url: string; source_url: string; page_title: string;
  sections: LabSection[];
}
export interface LabSourceDocument {
  role: 'profile' | 'home' | 'team' | 'research'; requested_url: string; source_url: string;
  page_title: string; checked_at: string; body_sha256: string;
}
export interface LabSourceLink { from_url: string; raw_href: string; anchor_text: string; to_url: string }
export interface LabSourceChain {
  documents: [LabSourceDocument, LabSourceDocument, LabSourceDocument, LabSourceDocument];
  links: [LabSourceLink, LabSourceLink, LabSourceLink];
  identity: { source_url: string; full_name: string; role_text: string };
}
export interface LabSnapshotV2 extends Omit<LabSnapshotV1, 'version' | 'policy_version' | 'pages'> {
  version: 2; policy_version: 2; pages: [LabPage, LabResearchPage]; source_chain: LabSourceChain;
}
export type LabSnapshot = LabSnapshotV1 | LabSnapshotV2;
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
  if (!text(value, 2000) || !/^[\x21-\x7e]+$/.test(value) || /[\\?#"<>`{}^]/.test(value)) return false;
  try {
    const p = new URL(value);
    // No punycode label: whether an invalid one even parses differs between
    // runtimes (Node 25 throws, Node 24 accepts), and the browser has no IDNA
    // round trip to match the backend's. Refusing only hides the source.
    return p.protocol === 'https:' && !p.username && !p.password && !p.port && p.href === value && p.hostname.length <= 253
      && /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(p.hostname)
      && !p.hostname.split('.').some(label => label.startsWith('xn--'));
  } catch { return false; }
}
function timestamp(value: unknown): value is string {
  if (typeof value !== 'string' || !/^[1-9][0-9]{3}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$/.test(value)) return false;
  const ms = Date.parse(value);
  return Number.isFinite(ms) && new Date(ms).toISOString().slice(0, 19) === value.slice(0, 19);
}
/** Resolve only an observed canonical HTTPS or ordinary relative link. This
 * preserves the raw link separately and never authorizes redirects or fetching. */
function observedLink(raw: unknown, from: string, to: string): boolean {
  if (!text(raw, 2000)) return false;
  try {
    if (raw.startsWith('/') && !raw.startsWith('//')) {
      const resolved = new URL(from).origin + raw;
      return url(resolved) && resolved === to;
    }
    if (!raw.startsWith('https://')) return false;
    if (url(raw)) return raw === to;
    // Only a missing slash on the absolute origin is canonicalized.
    const parsed = new URL(raw);
    return parsed.origin === raw && url(raw + '/') && raw + '/' === to;
  } catch { return false; }
}
function validChain(s: Record<string, unknown>, pages: Record<string, unknown>[]): boolean {
  const chain = s.source_chain;
  if (!exact(chain, ['documents', 'links', 'identity']) || !Array.isArray(chain.documents) || chain.documents.length !== 4
    || !Array.isArray(chain.links) || chain.links.length !== 3) return false;
  const roles = ['profile', 'home', 'team', 'research'];
  const documents: Record<string, unknown>[] = [];
  for (const [i, d] of chain.documents.entries()) {
    if (!exact(d, ['role', 'requested_url', 'source_url', 'page_title', 'checked_at', 'body_sha256'])
      || d.role !== roles[i] || !url(d.requested_url) || d.source_url !== d.requested_url
      || !text(d.page_title, 1000) || d.checked_at !== s.checked_at
      || typeof d.body_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(d.body_sha256)) return false;
    documents.push(d);
  }
  if (new Set(documents.map(d => d.source_url)).size !== 4) return false;
  const labOrigin = new URL(documents[1].source_url as string).origin;
  if (documents.slice(2).some(d => new URL(d.source_url as string).origin !== labOrigin)) return false;
  for (const [i, documentIndex] of [0, 3].entries()) {
    const page = pages[i], document = documents[documentIndex];
    if (page.source_url !== document.source_url || page.page_title !== document.page_title) return false;
  }
  const edges = [[0, 1], [1, 2], [1, 3]];
  for (const [i, [from, to]] of edges.entries()) {
    const link = chain.links[i];
    if (!exact(link, ['from_url', 'raw_href', 'anchor_text', 'to_url']) || !text(link.anchor_text, 500)
      || link.from_url !== documents[from].source_url || link.to_url !== documents[to].source_url
      || !observedLink(link.raw_href, link.from_url as string, link.to_url as string)) return false;
  }
  return exact(chain.identity, ['source_url', 'full_name', 'role_text'])
    && chain.identity.source_url === documents[2].source_url && text(chain.identity.full_name, 200)
    && chain.identity.full_name === s.identity_name && pages[0].identity_text === s.identity_name
    && text(chain.identity.role_text, 2000);
}
/** Historical parse: the server owns receipt authenticity, current identity,
 * freshness and SHA verification. Browser parsing preserves the saved status;
 * document signatures separately bind all source content. */
export function parseLabContext(value: unknown): LabContext | null {
  try {
    if (!exact(value, ['version', 'status', 'snapshot']) || value.version !== 1
      || !['available', 'stale', 'unavailable'].includes(value.status as string)) return null;
    if (value.status === 'unavailable') return value.snapshot === null ? { version: 1, status: 'unavailable', snapshot: null } : null;
    const candidate = value.snapshot;
    if (!candidate || typeof candidate !== 'object') return null;
    const v2 = (candidate as Record<string, unknown>).version === 2;
    if (!exact(candidate, v2 ? [...snapshotKeys, 'source_chain'] : snapshotKeys)) return null;
    const s = candidate;
    if (s.version !== (v2 ? 2 : 1) || s.source !== 'official_website' || s.policy_version !== (v2 ? 2 : 1)
      || !text(s.record_id, 200) || !text(s.school, 200) || !text(s.department, 200) || !text(s.identity_name, 200)
      || !url(s.record_source_url) || !timestamp(s.checked_at) || typeof s.snapshot_version !== 'string'
      || !(v2 ? /^ls2:[0-9a-f]{64}$/ : /^ls1:[0-9a-f]{64}$/).test(s.snapshot_version)
      || !Array.isArray(s.pages) || s.pages.length < 1 || s.pages.length > 2 || (v2 && s.pages.length !== 2)) return null;
    let total = 0;
    const pages: Record<string, unknown>[] = [];
    for (const [index, p] of s.pages.entries()) {
      const research = v2 && index === 1;
      if (!exact(p, research ? ['kind', 'requested_url', 'source_url', 'page_title', 'sections'] : pageKeys)
        || p.kind !== (index === 0 ? 'faculty_profile' : research ? 'lab_research' : 'lab_website')
        || !url(p.requested_url) || p.source_url !== p.requested_url || !text(p.page_title, 1000)
        || (!research && !text(p.identity_text, 200)) || !Array.isArray(p.sections) || !p.sections.length || p.sections.length > 32) return null;
      if (index === 0) {
        if (p.source_url !== s.record_source_url || p.linked_from !== null) return null;
      } else if (!research) {
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
      pages.push(p);
    }
    if (v2 && !validChain(s, pages)) return null;
    return structuredClone(value) as unknown as LabContext;
  } catch { return null; }
}
export function isLabContext(value: unknown): value is LabContext { return parseLabContext(value) !== null; }
