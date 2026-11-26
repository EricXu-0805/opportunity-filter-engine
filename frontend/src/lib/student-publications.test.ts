import { describe, expect, it } from 'vitest';
import { alreadyImported, authorIdentifier, confirmedStudentWork, scholarUser, studentWorks, validStudentAuthorship } from './student-publications';
import { createEmptyResumeMaster, validateResumeMaster } from './resume-master';

const orcid = '0000-0002-1825-0097';
const scholar = 'StudentDemo1';
const author = (id: string, campus: string, name = 'Alex Example', orcidValue?: string) => ({
  author: { id: 'https://openalex.org/' + id, display_name: name, orcid: orcidValue },
  institutions: [{ display_name: campus }],
});
const work = (id: number, ...authors: ReturnType<typeof author>[]) => ({
  id: 'https://openalex.org/W' + id, display_name: 'Example publication ' + id, authorships: authors,
});
const before = author('A123', 'Previous campus', 'Alex Example', 'https://orcid.org/' + orcid);
const after = author('A123', 'New campus', 'A. Example', orcid);
const homonym = author('A456', 'Previous campus');
const exportRows = { results: [work(11, before), work(12, homonym, after), work(13, homonym)] };

describe('student-supplied OpenAlex Works', () => {
  it('keeps the listed stable identity through a move or name change, excluding a same-name coauthor', () => {
    for (const identity of ['A123', orcid]) {
      const result = studentWorks(JSON.stringify(exportRows), scholar, identity);
      expect(result.skipped).toBe(1);
      expect(result.works.map((item) => item.source.work_id)).toEqual(['W11', 'W12']);
      expect(result.works.map((item) => item.authorName)).toEqual(['Alex Example', 'A. Example']);
      const saved = confirmedStudentWork(result.works[1]);
      expect(saved.student_authorship).toEqual({ scholar_id: scholar, author_id: 'A123', work_id: 'W12', ...(identity === orcid ? { orcid } : {}) });
      expect(saved.authors).toBeUndefined();
      expect(alreadyImported([saved], result.works[1])).toBe(true);
      expect(validateResumeMaster({ ...createEmptyResumeMaster(), publications: [saved] }).ok).toBe(true);
    }
  });
  it('skips ambiguous or missing identifiers, duplicate work records, and absent authorships on the confirmed profile', () => {
    const contradictory = { ...before, raw_orcid: '9999-9999-9999-9994' };
    expect(studentWorks(JSON.stringify(work(7, contradictory)), scholar, orcid).works).toHaveLength(0);
    const byline = { ...before, raw_author_name: 'A. Example at publication' };
    expect(studentWorks(JSON.stringify(work(8, byline)), scholar, orcid).works[0].authorName).toBe(byline.raw_author_name);
    const rows = [work(1, before, before), work(2, before), work(2, homonym), work(3, homonym), work(4)];
    expect(studentWorks(JSON.stringify(rows), scholar, 'A123')).toEqual({ works: [], skipped: 5 });
    expect(studentWorks(JSON.stringify(work(5, homonym)), scholar, orcid).works).toHaveLength(0);
    const [matched] = studentWorks(JSON.stringify({ ...work(5, before), doi: 'https://doi.org/10.1234/Fiction' }), scholar, orcid).works;
    const existing = confirmedStudentWork(matched);
    delete existing.student_authorship;
    delete existing.url;
    expect(existing.doi?.value).toBe('10.1234/fiction');
    expect(alreadyImported([existing], matched)).toBe(true);
  });
  it('accepts canonical public routes, validates ORCID checksums, and rejects incorrect exports and stored metadata', () => {
    expect(scholarUser('https://scholar.google.com/citations?hl=en&user=' + scholar)).toBe(scholar);
    expect(scholarUser('https://scholar.google.com.other.test/citations?user=' + scholar)).toBeNull();
    expect(scholarUser('https://scholar.google.com/citations?user=X&user=Y')).toBeNull();
    expect(authorIdentifier('https://openalex.org/A123')).toBe('A123');
    expect(authorIdentifier('https://orcid.org/' + orcid)).toBe(orcid);
    expect(authorIdentifier('0000-0002-1825-0098')).toBeNull();
    expect(authorIdentifier('Alex Example')).toBeNull();
    expect(() => studentWorks('{"results":[{}]}', scholar, 'A123')).toThrow();
    expect(() => studentWorks(JSON.stringify(Array(201).fill(work(1))), scholar, 'A123')).toThrow();
    expect(validStudentAuthorship({ scholar_id: scholar, work_id: 'W1', author_id: 'https://example.org' })).toBe(false);
  });
});
