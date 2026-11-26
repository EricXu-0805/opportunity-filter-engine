import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { activeExperienceEntries, createManualCandidate, sourceDigest } from './experience-evidence';
import {
  commitWorkReview, emptyWorkRecord, parseWorkCsv, parseWorkPaste, prepareWorkReview, validWorkRecord, workText,
} from './linkedin-experience-import';

beforeEach(() => vi.stubGlobal('crypto', webcrypto));
afterEach(() => vi.unstubAllGlobals());
const acme = { ...emptyWorkRecord(), company: 'Fictional Rain Lab', role: 'Assistant', start: 'Sep 2024', duties: 'Cleaned datasets' };

describe('owner-provided experience', () => {
  it('preserves quoted multiline descriptions, escaped quotes, dates, optional fields and row order', () => {
    const data = '\uFEFFCompany Name,Title,Description,Location,Started On,Finished On\r\n'
      + '"Rain, Inc.",Analyst,"Reviewed ""A""\nReported B",Remote,Sep 2024,Jun 2025\r\n'
      + 'Fictional Org,Coordinator,,,2026,\r\n';
    const result = parseWorkCsv(data);
    expect(result[0]).toEqual({ company: 'Rain, Inc.', role: 'Analyst', duties: 'Reviewed "A"\nReported B', results: '', start: 'Sep 2024', end: 'Jun 2025' });
    expect(result[1].end).toBe('');
    expect(parseWorkPaste(data)).toEqual(result);
    for (const invalid of ['Name,Location\nA,B', 'Company,Title\n"open,role', 'Company,Title\nA,B,C', 'Company,Employer,Title\nA,B,C']) {
      expect(() => parseWorkCsv(invalid)).toThrow('csv');
    }
  });
  it('keeps unknowns and unlabelled descriptions, accepts multiple labelled roles, and refuses a bare URL', () => {
    expect(parseWorkPaste('Used a spreadsheet\nReduced processing time')[0]).toEqual({ ...emptyWorkRecord(), duties: 'Used a spreadsheet\nReduced processing time' });
    expect(parseWorkPaste('公司：甲公司\n职位：助理\n职责：核对记录\n成果：发现三处差异\nCompany: Fictional B\nTitle: Analyst')).toHaveLength(2);
    expect(() => parseWorkPaste('https://www.linkedin.com/in/example')).toThrow('text');
    expect(validWorkRecord({ ...emptyWorkRecord(), company: 'https://www.linkedin.com/in/example', role: 'Assistant' })).toBe(false);
  });
  it('requires an explicit choice, preserves old source evidence on merge and prevents double imports', async () => {
    const raw = 'Assistant at Fictional Rain Lab\nChecked reference values.';
    const existing = { ...createManualCandidate('Unrelated old experience', 'older'), status: 'confirmed' as const };
    const { rows, targets } = await prepareWorkReview([acme], [existing], raw);
    const [row] = rows;
    const target = targets.find(t => t.id === row.target)!;
    expect(target.source.kind).toBe('resume');
    expect(() => commitWorkReview(rows, [existing], targets)).toThrow('decision');
    const combined = 'Assistant at Fictional Rain Lab. Checked reference values and cleaned datasets.';
    const saved = commitWorkReview([{ ...row, action: 'combine', combined }], [existing], targets);
    expect(saved[0]).toEqual(existing);
    expect(saved.find(e => e.id === target.id)).toMatchObject({ status: 'withdrawn', source: target.source, text: target.text });
    expect(saved.at(-1)).toMatchObject({ status: 'confirmed', text: combined, source: { kind: 'manual' } });
    const reopened = JSON.parse(JSON.stringify(saved));
    expect(activeExperienceEntries(reopened, { rawText: '', expectedDigest: await sourceDigest('') }).map(e => e.text)).toContain(combined);
    const repeat = await prepareWorkReview([acme], reopened, raw);
    expect(repeat.rows[0].target).toBe(row.id);
    expect(() => commitWorkReview([{ ...repeat.rows[0], action: 'new' }], reopened, repeat.targets)).toThrow('duplicate');
    expect(commitWorkReview([{ ...repeat.rows[0], action: 'keep' }], reopened, repeat.targets)).toEqual(reopened);
  });
  it('leaves quotes from a replaced résumé intact and excludes them from confirmation choices', async () => {
    const older = await prepareWorkReview([acme], [], 'Assistant at Fictional Rain Lab. Checked references.');
    const oldQuote = older.targets[0];
    const current = await prepareWorkReview([acme], [oldQuote], 'New experience at Fictional Ice Studio.');
    expect(current.targets.some(t => t.id === oldQuote.id)).toBe(false);
    expect(current.rows[0].target).toBe('');
    const next = commitWorkReview([{ ...current.rows[0], action: 'new' }], [oldQuote], current.targets);
    expect(next[0]).toEqual(oldQuote);
  });
  it('writes confirmed existing résumé wording when the owner keeps an unimported matched passage', async () => {
    const { rows, targets } = await prepareWorkReview([acme], [], 'Fictional Rain Lab assistant. Verified test readings.');
    const saved = commitWorkReview([{ ...rows[0], action: 'keep' }], [], targets);
    expect(saved).toHaveLength(1);
    expect(saved[0]).toMatchObject({ status: 'confirmed', source: { kind: 'resume' }, text: targets[0].text });
  });
  it('preserves the final owner edits and prohibits two input rows overwriting the same source', async () => {
    const { rows, targets } = await prepareWorkReview([acme, acme], [], '');
    expect(() => commitWorkReview(rows.map(r => ({ ...r, action: 'new' })), [], targets)).toThrow('duplicate');
    const fixed = { ...acme, results: 'Reduced review time by 12%.' };
    expect(commitWorkReview([{ ...rows[0], fields: fixed, action: 'new' }], [], targets)[0].text).toBe(workText(fixed));
  });
});
