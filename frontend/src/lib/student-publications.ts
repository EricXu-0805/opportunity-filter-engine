import type { ResumeFact, ResumePublicationItem, StudentAuthorship } from './types';

const scholarHosts = new Set(['scholar.google.com', 'scholar.google.com.hk', 'scholar.google.com.tw',
  'scholar.google.co.uk', 'scholar.google.ca', 'scholar.google.de', 'scholar.google.fr', 'scholar.google.co.jp',
  'scholar.google.co.in', 'scholar.google.com.au', 'scholar.google.co.kr', 'scholar.google.com.br']);
const scholarId = /^[A-Za-z0-9_-]{1,40}$/;
const authorId = /^A[1-9][0-9]{0,18}$/;
const workId = /^W[1-9][0-9]{0,18}$/;
const orcidId = /^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/;
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);

export function scholarUser(link?: string): string | null {
  try {
    const url = new URL(link ?? '');
    if (url.protocol !== 'https:' || !scholarHosts.has(url.hostname) || url.port
      || url.username || url.password || url.pathname !== '/citations') return null;
    const users = url.searchParams.getAll('user');
    return users.length === 1 && scholarId.test(users[0]) ? users[0] : null;
  } catch { return null; }
}

function canonicalOrcid(value: string): string | null {
  if (!orcidId.test(value)) return null;
  const digits = value.replaceAll('-', '');
  let total = 0;
  for (const digit of digits.slice(0, 15)) total = (total + Number(digit)) * 2;
  const check = (12 - total % 11) % 11;
  return digits[15] === (check === 10 ? 'X' : String(check)) ? value : null;
}

export function authorIdentifier(input: unknown): string | null {
  if (typeof input !== 'string') return null;
  const value = input.trim();
  const openalex = value.replace(/^https:\/\/openalex\.org\//i, '').toUpperCase();
  if (authorId.test(openalex)) return openalex;
  return canonicalOrcid(value.replace(/^https:\/\/orcid\.org\//i, '').toUpperCase());
}

function openalexWork(input: unknown): string | null {
  if (typeof input !== 'string') return null;
  const id = input.replace(/^https:\/\/openalex\.org\//i, '').toUpperCase();
  return workId.test(id) ? id : null;
}

export function validStudentAuthorship(value: unknown): value is StudentAuthorship {
  return record(value) && Object.keys(value).every((key) => ['scholar_id', 'author_id', 'work_id', 'orcid', 'linked_by'].includes(key))
    && typeof value.scholar_id === 'string' && scholarId.test(value.scholar_id)
    && typeof value.author_id === 'string' && authorId.test(value.author_id)
    && typeof value.work_id === 'string' && workId.test(value.work_id)
    && (!Object.hasOwn(value, 'linked_by') || (typeof value.linked_by === 'string' && (
      value.linked_by === 'https://openalex.org/' + value.work_id || publicDoi(value.linked_by)?.toLowerCase() === value.linked_by)))
    && (!Object.hasOwn(value, 'orcid') || (typeof value.orcid === 'string' && canonicalOrcid(value.orcid) !== null));
}

export interface StudentWork {
  title: string;
  authorName: string;
  doi?: string;
  source: StudentAuthorship;
}

/** Uses the identifier on one authorship, never the name, affiliation or coauthors. */
export function studentWorks(json: string, scholar: string, identity: string): { works: StudentWork[]; skipped: number } {
  if (!scholarId.test(scholar) || authorIdentifier(identity) !== identity || json.length > 2_000_000) throw new Error('invalid_export');
  const parsed: unknown = JSON.parse(json);
  const rows = record(parsed) && Array.isArray(parsed.results) ? parsed.results : Array.isArray(parsed) ? parsed : [parsed];
  if (!rows.length || rows.length > 200 || !rows.every((row) => record(row) && Array.isArray(row.authorships))) throw new Error('invalid_export');
  const works: StudentWork[] = [];
  const counts = new Map<string, number>();
  for (const row of rows as Record<string, unknown>[]) {
    const id = openalexWork(row.id);
    if (id) counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  for (const row of rows as Record<string, unknown>[]) {
    const work = openalexWork(row.id);
    const title = row.display_name ?? row.title;
    if (!work || counts.get(work) !== 1 || typeof title !== 'string' || !title.trim() || title.length > 2000) continue;
    const matches = (row.authorships as unknown[]).flatMap((slot) => {
      if (!record(slot) || !record(slot.author)) return [];
      const id = authorIdentifier(slot.author.id);
      if (!id || !authorId.test(id)) return [];
      const orcid = authorIdentifier(slot.author.orcid);
      if (identity !== id && (identity !== orcid || !orcidId.test(identity))) return [];
      // The publisher's deposited ORCID and OpenAlex's resolved author can disagree.
      // An internally contradictory signature must not establish student ownership.
      const deposited = authorIdentifier(slot.raw_orcid);
      if (slot.raw_orcid && (!deposited || !orcidId.test(deposited) || (orcid && deposited !== orcid))) return [{ id, name: null }];
      const name = typeof slot.raw_author_name === 'string' && slot.raw_author_name.trim()
        ? slot.raw_author_name : slot.author.display_name;
      return [{ id, name }];
    });
    const [author] = matches;
    if (matches.length !== 1 || typeof author.name !== 'string' || !author.name.trim() || author.name.length > 300) continue;
    const source: StudentAuthorship = { scholar_id: scholar, work_id: work, author_id: author.id };
    if (orcidId.test(identity)) source.orcid = identity;
    const doi = publicDoi(row.doi);
    works.push({ title, authorName: author.name, ...(doi ? { doi } : {}), source });
  }
  return { works, skipped: rows.length - works.length };
}

function publicDoi(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 300) return null;
  const doi = value.trim().replace(/^https:\/\/(?:dx\.)?doi\.org\//i, '');
  return /^10\.\d{4,9}\/\S+$/u.test(doi) && !Array.from(doi).some((char) => char.charCodeAt(0) < 32) ? doi : null;
}

export function studentAuthorshipBound(source: unknown, url: unknown, doi: unknown): boolean {
  if (!validStudentAuthorship(source)) return false;
  const link = record(url) ? url.value : null;
  const workUrl = 'https://openalex.org/' + source.work_id;
  if (!source.linked_by) return link === workUrl;
  if (source.linked_by === workUrl) return openalexWork(link) === source.work_id;
  return [record(doi) ? doi.value : null, link].some((value) => publicDoi(value)?.toLowerCase() === source.linked_by);
}

type PublicationMatch = { kind: 'new' | 'present' | 'conflict' } |
  { kind: 'link'; item: ResumePublicationItem; locator: string };

export function existingStudentWork(items: ResumePublicationItem[], work: StudentWork): PublicationMatch {
  const workUrl = 'https://openalex.org/' + work.source.work_id;
  const doi = work.doi?.toLowerCase();
  const sameDoi = (value?: string) => !!doi && publicDoi(value)?.toLowerCase() === doi;
  const rows = items.filter((item) => item.student_authorship?.work_id === work.source.work_id
    || openalexWork(item.url?.value) === work.source.work_id || sameDoi(item.doi?.value) || sameDoi(item.url?.value));
  if (!rows.length) return { kind: 'new' };
  if (rows.length !== 1) return { kind: 'conflict' };
  const item = rows[0];
  if (item.student_authorship) {
    const source = item.student_authorship;
    return { kind: source.work_id === work.source.work_id && source.author_id === work.source.author_id
      && source.scholar_id === work.source.scholar_id ? 'present' : 'conflict' };
  }
  const otherWork = openalexWork(item.url?.value);
  const conflictingDoi = doi && [item.url?.value, item.doi?.value].some((value) => publicDoi(value) && !sameDoi(value));
  if (item.title?.status !== 'confirmed' || (otherWork && otherWork !== work.source.work_id) || conflictingDoi) return { kind: 'conflict' };
  if (item.url?.status === 'confirmed' && otherWork === work.source.work_id) return { kind: 'link', item, locator: workUrl };
  if (doi && [item.doi, item.url].some((fact) => fact?.status === 'confirmed' && sameDoi(fact.value))) {
    return { kind: 'link', item, locator: doi };
  }
  return { kind: 'conflict' };
}

export function addStudentWork(items: ResumePublicationItem[], work: StudentWork): void {
  const match = existingStudentWork(items, work);
  if (match.kind === 'new') items.push(confirmedStudentWork(work));
  if (match.kind === 'link') match.item.student_authorship = { ...work.source, linked_by: match.locator };
}

export function confirmedStudentWork(work: StudentWork): ResumePublicationItem {
  const fact = (value: string): ResumeFact => ({
    id: crypto.randomUUID(), revision: 1, status: 'confirmed', value, source: { kind: 'manual' },
  });
  return { id: crypto.randomUUID(), details: [], title: fact(work.title),
    url: fact('https://openalex.org/' + work.source.work_id), ...(work.doi ? { doi: fact(work.doi) } : {}), student_authorship: work.source };
}
