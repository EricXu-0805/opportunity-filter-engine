import {
  createManualCandidate, createResumeCandidates, isActiveExperience, MAX_EXPERIENCE_ENTRIES,
  MAX_EXPERIENCE_ENTRY_CHARACTERS, sourceDigest, validateExperienceEntries,
} from './experience-evidence';
import type { ExperienceEntry } from './types';

const fieldNames = ['company', 'role', 'start', 'end', 'duties', 'results'] as const;
export type WorkField = typeof fieldNames[number];
export type WorkRecord = Record<WorkField, string>;
export const emptyWorkRecord = (): WorkRecord => ({ company: '', role: '', start: '', end: '', duties: '', results: '' });
export const MAX_WORK_FILE_BYTES = 512_000;
export type ImportAction = 'new' | 'keep' | 'combine' | 'skip';
export type WorkReview = {
  fields: WorkRecord; id: string; target: string; action: ImportAction | ''; combined: string;
};

const aliases: Record<WorkField, string[]> = {
  company: ['Company Name', 'Company', 'Employer', '公司', '公司名称', '组织'],
  role: ['Title', 'Role', 'Position', 'Job Title', '职位', '职务', '岗位'],
  start: ['Started On', 'Start Date', 'Start', '开始时间', '开始日期'],
  end: ['Finished On', 'End Date', 'End', '结束时间', '结束日期'],
  duties: ['Description', 'Responsibilities', 'Duties', '职责', '描述', '工作内容'],
  results: ['Accomplishments', 'Achievements', 'Results', 'Outcomes', '成果', '成就'],
};
const column = (s: string) => fieldNames.find(key => aliases[key].some(a => a.toLowerCase() === s.trim().toLowerCase()));
const normalize = (text: string) => text.normalize('NFKC').trim().replace(/\s+/gu, ' ').toLowerCase();
const urlOnly = (text: string) => /^(?:https?:\/\/|www\.|linkedin\.com\/)[^\s]+$/iu.test(text.trim());

export function workText(value: WorkRecord): string {
  return [
    [value.role.trim(), value.company.trim()].filter(Boolean).join(' — '),
    [value.start.trim() && 'From ' + value.start.trim(), value.end.trim() && 'To ' + value.end.trim()].filter(Boolean).join(' · '),
    value.duties.trim(), value.results.trim(),
  ].filter(Boolean).join('\n');
}

export function validWorkRecord(value: WorkRecord): boolean {
  const text = workText(value);
  return !!value.company.trim() && !urlOnly(value.company) && !![value.role, value.duties, value.results].some(v => v.trim() && !urlOnly(v))
    && Array.from(text).length <= MAX_EXPERIENCE_ENTRY_CHARACTERS;
}

/** Read the CSV locally. Doubled quotes and line breaks inside a quoted description are data. */
function csvRows(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], cell = '', quoted = false, closed = false;
  const finish = () => {
    row.push(cell.trim());
    if (row.some(Boolean)) rows.push(row);
    if (rows.length > MAX_EXPERIENCE_ENTRIES + 1) throw Error('limit');
    row = []; cell = ''; closed = false;
  };
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (char !== '"') { cell += char; continue; }
      if (text[i + 1] === '"') { cell += '"'; i++; continue; }
      quoted = false; closed = true;
    } else if (char === ',') {
      row.push(cell.trim()); cell = ''; closed = false;
    } else if (char === '\n' || char === '\r') {
      if (char === '\r' && text[i + 1] === '\n') i++;
      finish();
    } else if (char === '"' && !cell && !closed) {
      quoted = true;
    } else if (char === '"' || (closed && !/\s/u.test(char))) {
      throw Error('csv');
    } else {
      cell += char;
    }
  }
  if (quoted) throw Error('csv');
  finish();
  return rows;
}

export function parseWorkCsv(content: string): WorkRecord[] {
  if (content.length > MAX_WORK_FILE_BYTES) throw Error('limit');
  const [header, ...rows] = csvRows(content.replace(/^\uFEFF/u, ''));
  const keys = (header ?? []).map(column);
  const known = keys.filter(k => k !== undefined);
  if (!keys.includes('company') || !keys.includes('role') || new Set(known).size !== known.length || !rows.length) throw Error('csv');
  return rows.map(row => {
    if (row.length !== keys.length) throw Error('csv');
    const value = emptyWorkRecord();
    keys.forEach((key, index) => { if (key) value[key] = row[index]; });
    return value;
  });
}

/** Pasted profile text stays verbatim in the description unless it contains explicit labels. */
export function parseWorkPaste(content: string): WorkRecord[] {
  const text = content.trim();
  if (text.length > MAX_WORK_FILE_BYTES) throw Error('limit');
  if (!text || urlOnly(text)) throw Error('text');
  const first = text.split(/\r?\n/u, 1)[0];
  if (first.includes(',') && first.split(',').some(c => column(c.replace(/^"|"$/gu, '')) === 'company')) return parseWorkCsv(text);
  const rows: WorkRecord[] = [];
  let row = emptyWorkRecord();
  let current: WorkField | undefined;
  for (const line of text.split(/\r?\n/u)) {
    const label = /^([^:：]{1,30})[:：]\s*(.*)$/u.exec(line);
    const key = label && column(label[1]);
    if (key) {
      if (key === 'company' && row.company.trim()) { rows.push(row); row = emptyWorkRecord(); }
      current = key; row[key] = [row[key], label[2]].filter(Boolean).join('\n');
    }
    else { const field = current ?? 'duties'; row[field] += (row[field] ? '\n' : '') + line; }
  }
  rows.push(row);
  if (rows.length > MAX_EXPERIENCE_ENTRIES) throw Error('limit');
  return rows;
}

const unconfirmedPull = (entry: ExperienceEntry) => entry.source.kind === 'github' && entry.status === 'candidate';

export async function prepareWorkReview(values: WorkRecord[], entries: ExperienceEntry[], resume: string) {
  if (!values.length || values.length > MAX_EXPERIENCE_ENTRIES) throw Error('limit');
  const choices = new Map(entries.map(entry => [entry.id, entry]));
  if (resume.trim()) for (const entry of await createResumeCandidates(resume)) {
    if (!choices.has(entry.id)) choices.set(entry.id, entry);
  }
  const source = { rawText: resume, expectedDigest: await sourceDigest(resume) };
  // An imported pull request is confirmed only by its own button in the library.
  const targets = [...choices.values()].filter(entry =>
    (entry.status === 'candidate' || entry.status === 'confirmed') && !unconfirmedPull(entry)
    && (entry.source.kind !== 'resume' || isActiveExperience({ ...entry, status: 'confirmed' }, source)));

  const rows: WorkReview[] = [];
  for (const fields of values) {
    const id = 'li:' + await sourceDigest(JSON.stringify(fieldNames.map(key => normalize(fields[key]))));
    const prior = choices.get(id);
    if (prior && !targets.includes(prior)) targets.push(prior);
    const company = normalize(fields.company);
    const similar = targets.filter(entry => company.length >= 2 && normalize(entry.text).includes(company));
    const target = choices.get(id)?.id ?? (similar.length === 1 ? similar[0].id : '');
    rows.push({ fields, id, target, action: '', combined: target ? choices.get(target)?.text ?? '' : '' });
  }
  return { rows, targets };
}

export function commitWorkReview(rows: WorkReview[], entries: ExperienceEntry[], targets: ExperienceEntry[]): ExperienceEntry[] {
  const next = new Map(entries.map(e => [e.id, e]));
  const available = new Map(targets.map(e => [e.id, e]));
  const modified = new Set<string>();
  for (const row of rows) {
    if (!row.action) throw Error('decision');
    if (row.action === 'skip') continue;
    const target = available.get(row.target);
    if (row.action === 'keep') {
      if (!target || unconfirmedPull(target)) throw Error('target');
      if (target.status === 'candidate') {
        if (modified.has(target.id)) throw Error('duplicate');
        next.set(target.id, { ...target, revision: target.revision + 1, status: 'confirmed' });
        modified.add(target.id);
      }
      continue;
    }
    if (!validWorkRecord(row.fields)) throw Error('fields');
    if (modified.has(row.id)) throw Error('duplicate');
    const existing = next.get(row.id);
    if (existing && (row.action !== 'combine' || target?.id !== existing.id)) throw Error('duplicate');
    if (row.action === 'combine' && (!target || !row.combined.trim() || urlOnly(row.combined))) throw Error('target');
    if (row.action === 'combine' && target && target.id !== row.id) {
      if (modified.has(target.id)) throw Error('duplicate');
      // Preserve the exact résumé quote, original identity and prior text.
      // Only the separate, owner-confirmed wording becomes active.
      next.set(target.id, { ...target, revision: target.revision + 1, status: 'withdrawn' });
      modified.add(target.id);
    }
    const text = row.action === 'combine' ? row.combined.trim() : workText(row.fields);
    const candidate = createManualCandidate(text, row.id);
    next.set(row.id, { ...candidate, revision: existing ? existing.revision + 1 : 1, status: 'confirmed' });
    modified.add(row.id);
  }
  const result = [...next.values()];
  if (!validateExperienceEntries(result).ok) throw Error('limit');
  return result;
}
