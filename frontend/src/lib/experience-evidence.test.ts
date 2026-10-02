import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { ExperienceEntry } from './types';
import { storedWraps } from './resume-input';
import {
  activeExperienceEntries, createManualCandidate, createResumeCandidates,
  isActiveExperience, removeResumeEntries, sourceDigest,
  validateExperienceEntries, withdrawResumeEntries,
} from './experience-evidence';

beforeEach(() => vi.stubGlobal('crypto', webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const manual = (overrides: Partial<ExperienceEntry> = {}): ExperienceEntry => ({
  id: 'exp-1', revision: 1, text: 'Built a robot.', status: 'candidate', source: { kind: 'manual' }, ...overrides,
});

describe('experience evidence input contract', () => {
  it('hashes full exact UTF-8 with SHA-256, including tails and whitespace', async () => {
    expect(await sourceDigest('abc')).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
    expect(await sourceDigest('abc ')).not.toBe(await sourceDigest('abc'));
    expect(await sourceDigest('x'.repeat(59_999) + 'A')).not.toBe(await sourceDigest('x'.repeat(59_999) + 'B'));
  });
  it('does not substitute a weak hash when WebCrypto is unavailable', async () => {
    vi.stubGlobal('crypto', {});
    await expect(sourceDigest('resume')).rejects.toMatchObject({ code: 'source_digest_unavailable' });
  });
  it.each(['\ud800', '\udfff', 'before\ud800after', '\ud800\ud800', '\udfff\udfff'])('refuses malformed Unicode before hashing or proposing entries: %j', async (raw) => {
    const digest = vi.spyOn(webcrypto.subtle, 'digest');
    await expect(sourceDigest(raw)).rejects.toMatchObject({ code: 'invalid_unicode' });
    await expect(createResumeCandidates(raw)).rejects.toMatchObject({ code: 'invalid_unicode' });
    expect(digest).not.toHaveBeenCalled();
  });
  it('keeps literal replacement characters, valid surrogate pairs and decomposed Unicode exact', async () => {
    await expect(sourceDigest('\ufffd')).resolves.toMatch(/^[a-f0-9]{64}$/);
    expect(await sourceDigest('é')).not.toBe(await sourceDigest('e\u0301'));
    const [entry] = await createResumeCandidates('研究\ud83d\ude00成果');
    expect(entry.source).toMatchObject({ quote: '研究😀成果', start: 0, end: 5 });
  });
  it('rejects unknown entry and source keys rather than dropping them', () => {
    const resume = { kind: 'resume', signature: 'a'.repeat(64), quote: 'actual', start: 0, end: 6 };
    for (const entry of [
      { ...manual(), surprise: 'hidden data' },
      { ...manual(), source: { kind: 'manual', quote: 'old quote' } },
      { ...manual(), source: { ...resume, surprise: 'hidden data' } },
    ]) {
      expect(validateExperienceEntries([entry])).toEqual({ ok: false, code: 'invalid_entry' });
      expect(activeExperienceEntries([entry], { rawText: 'actual', expectedDigest: 'a'.repeat(64) })).toEqual([]);
    }
  });
  it('rejects malformed Unicode in persisted IDs, entry text and source quotes without changing the input', () => {
    for (const invalid of [
      { ...manual(), id: '\ud800' },
      { ...manual(), text: 'before\udfffafter' },
      { ...manual(), source: { kind: 'resume', signature: 'a'.repeat(64), quote: '\ud800', start: 0, end: 1 } },
    ]) {
      const serialized = JSON.stringify(invalid);
      expect(validateExperienceEntries([invalid])).toEqual({ ok: false, code: 'invalid_unicode' });
      expect(JSON.stringify(invalid)).toBe(serialized);
    }
  });
  it('uses Unicode codepoint limits for the complete resume', async () => {
    await expect(sourceDigest('😀'.repeat(60_000))).resolves.toMatch(/^[a-f0-9]{64}$/);
    await expect(sourceDigest('😀'.repeat(60_001))).rejects.toMatchObject({ code: 'resume_too_long' });
  });
  it('treats legacy omission as unconfirmed empty, but rejects null/object', () => {
    expect(validateExperienceEntries(undefined)).toEqual({ ok: true, value: [] });
    expect(validateExperienceEntries(null).ok).toBe(false);
    expect(validateExperienceEntries({}).ok).toBe(false);
  });
  it.each([
    { id: '' }, { id: 'x'.repeat(81) }, { revision: 0 }, { revision: 1.1 },
    { revision: Number.MAX_SAFE_INTEGER + 1 }, { status: 'invented' },
    { text: '  ' }, { text: 'x'.repeat(6_001) }, { source: { kind: 'unknown' } },
  ])('rejects malformed entry %j', (invalid) => {
    expect(validateExperienceEntries([{ ...manual(), ...invalid }]).ok).toBe(false);
  });
  it('rejects duplicate IDs and entry/count/text budgets without truncation', () => {
    expect(validateExperienceEntries([manual(), manual()])).toEqual({ ok: false, code: 'duplicate_id' });
    expect(validateExperienceEntries(Array.from({ length: 101 }, (_, i) => manual({ id: `${i}` })))).toEqual({ ok: false, code: 'too_many_entries' });
    const max = Array.from({ length: 10 }, (_, i) => manual({ id: `${i}`, text: '😀'.repeat(6_000) }));
    expect(validateExperienceEntries(max).ok).toBe(true);
    expect(validateExperienceEntries([...max, manual()])).toEqual({ ok: false, code: 'text_limit' });
  });
  it('separately bounds quote budgets and requires safe codepoint ranges', () => {
    const source = { kind: 'resume' as const, signature: 'a'.repeat(64), quote: 'x'.repeat(6_000), start: 0, end: 6_000 };
    const entries = Array.from({ length: 11 }, (_, i) => manual({ id: `${i}`, text: 'edited', source }));
    expect(validateExperienceEntries(entries)).toEqual({ ok: false, code: 'quote_limit' });
    for (const invalid of [{ start: -1 }, { start: 0.5 }, { end: 60_001 }, { end: 5_999 }, { signature: 'A'.repeat(64) }]) {
      expect(validateExperienceEntries([manual({ source: { ...source, ...invalid } })]).ok).toBe(false);
    }
  });
});

describe('local proposals and confirmed eligibility', () => {
  it('retains exact Unicode offsets, CRLF and quotes while producing only candidates', async () => {
    const raw = '  姓名😀\r\n\r\n  Built a robot.\r\nPublished a paper.  \r\n\r\n尾部✅';
    const first = await createResumeCandidates(raw);
    expect(first).toHaveLength(3);
    expect(await createResumeCandidates(raw)).toEqual(first);
    for (const entry of first) {
      expect(entry.status).toBe('candidate');
      expect(entry.id.length).toBeLessThanOrEqual(80);
      if (entry.source.kind !== 'resume') throw new Error('expected source');
      expect(Array.from(raw).slice(entry.source.start, entry.source.end).join('')).toBe(entry.source.quote);
    }
    expect(first[2].text).toBe('尾部✅');
    expect(activeExperienceEntries(first, { rawText: raw, expectedDigest: await sourceDigest(raw) })).toEqual([]);
  });
  it('splits a long paragraph without discarding its final evidence', async () => {
    const raw = 'x'.repeat(6_000) + 'TAIL';
    const entries = await createResumeCandidates(raw);
    expect(entries.map((entry) => entry.text).join('')).toBe(raw);
    expect(entries).toHaveLength(2);
    expect(entries[1].source).toMatchObject({ start: 6_000, end: 6_004, quote: 'TAIL' });
  });
  it('rejects too many local candidates as a whole', async () => {
    await expect(createResumeCandidates(Array.from({ length: 101 }, (_, i) => `Project ${i}`).join('\n')))
      .rejects.toMatchObject({ code: 'too_many_entries' });
  });
  it('does not treat an explicit manual add as confirmation', () => {
    expect(createManualCandidate('Built the actual device', 'manual')).toMatchObject({ status: 'candidate', revision: 1, source: { kind: 'manual' } });
  });
  it('allows rewritten confirmed text only while the original quote and digest match', async () => {
    const raw = '😀\nBuilt the robot';
    const [, candidate] = await createResumeCandidates(raw);
    const confirmed = { ...candidate, status: 'confirmed' as const, revision: 2, text: 'I built a robot.' };
    const context = { rawText: raw, expectedDigest: await sourceDigest(raw) };
    expect(isActiveExperience(confirmed, context)).toBe(true);
    expect(isActiveExperience({ ...confirmed, status: 'rejected' }, context)).toBe(false);
    expect(isActiveExperience(confirmed, { ...context, expectedDigest: 'b'.repeat(64) })).toBe(false);
    expect(isActiveExperience(confirmed, { ...context, rawText: raw.replace('robot', 'paper') })).toBe(false);
    if (confirmed.source.kind !== 'resume') throw new Error('expected resume');
    expect(isActiveExperience({ ...confirmed, source: { ...confirmed.source, start: 3, end: 18 } }, context)).toBe(false);
  });
  it('replaces resume sources by withdrawn revisions and removes only resume sources on deletion', async () => {
    const [candidate] = await createResumeCandidates('Built a robot');
    const confirmed = { ...candidate, status: 'confirmed' as const, revision: 2 };
    const own = manual({ status: 'confirmed' });
    const withdrawn = withdrawResumeEntries([confirmed, own]);
    expect(withdrawn[0]).toMatchObject({ status: 'withdrawn', revision: 3, source: confirmed.source });
    expect(withdrawn[1]).toEqual(own);
    expect(withdrawResumeEntries(withdrawn)).toEqual(withdrawn);
    expect(removeResumeEntries(withdrawn)).toEqual([own]);
    expect(isActiveExperience(own, { rawText: '', expectedDigest: '' })).toBe(true);
  });
  it('drops unconfirmed résumé proposals on replacement so the next extraction still fits the cap', async () => {
    const lines = (tag: string) => Array.from({ length: 60 }, (_, i) => `${tag} project ${i}`).join('\n');
    const [kept, refused, ...unreviewed] = await createResumeCandidates(lines('Old'));
    const own = manual({ status: 'confirmed' });
    const replaced = withdrawResumeEntries([{ ...kept, status: 'confirmed', revision: 2 }, { ...refused, status: 'rejected', revision: 2 }, ...unreviewed, own]);
    expect(replaced).toEqual([{ ...kept, status: 'withdrawn', revision: 3 }, own]);
    expect(withdrawResumeEntries(replaced)).toEqual(replaced);
    const next = await createResumeCandidates(lines('New'));
    expect(validateExperienceEntries([...replaced, ...next])).toMatchObject({ ok: true });
  });

  it('groups a dense line-per-row résumé by bullets instead of failing past the cap', async () => {
    // PDF text of a two-page résumé: 150 lines and no blank lines. One
    // proposal per line would exceed the 100-entry cap and fail the upload.
    const role = (i: number) => [
      `EXPERIENCE ${i}`,
      `Research Assistant ${i}, Example Lab (2025 - 2026)`,
      `• Built parser ${i} for the lab's EEG`,
      `recordings and documented it`,
      `• Analyzed ${i}0 samples with Python`,
    ];
    const raw = Array.from({ length: 30 }, (_, i) => role(i).join('\n')).join('\n');
    const entries = await createResumeCandidates(raw);
    expect(entries.length).toBeLessThanOrEqual(100);
    const points = Array.from(raw);
    for (const entry of entries) {
      if (entry.source.kind !== 'resume') throw new Error('expected resume');
      expect(points.slice(entry.source.start, entry.source.end).join('')).toBe(entry.source.quote);
    }
    const quotes = entries.map((entry) => entry.text);
    expect(quotes).toContain("• Built parser 7 for the lab's EEG\nrecordings and documented it");
    expect(quotes.join('\n')).toBe(raw);
  });
  it('offers no section heading, contact line or name as an experience, and keeps every other line whole', async () => {
    const raw = readFileSync(join(__dirname, '__fixtures__/resume-pdf/persona.txt'), 'utf8');
    const entries = await createResumeCandidates(raw);
    const kept = raw.split('\n').filter((line) => !/^(?:[A-Z]+|JORDAN AVERY LEE \|.*)$/.test(line));
    expect(entries.map((entry) => entry.text)).toEqual(kept);
    expect(kept).toHaveLength(11);
    for (const entry of entries) {
      if (entry.source.kind !== 'resume') throw new Error('expected resume');
      expect(Array.from(raw).slice(entry.source.start, entry.source.end).join('')).toBe(entry.source.quote);
    }
  });
  it('drops the header block of a sidebar résumé but not a summary sentence above the first heading', async () => {
    const raw = ['Priya Natarajan', 'priya.natarajan.test@example.com', '(217) 555-0142', 'Champaign, IL',
      'github.com/priya-test', 'Bioengineering student who builds low-cost medical sensors.', 'Education',
      'University of Illinois Urbana-Champaign', 'Skills', 'Python, MATLAB'].join('\n');
    expect((await createResumeCandidates(raw)).map((entry) => entry.text)).toEqual([
      'Bioengineering student who builds low-cost medical sensors.', 'University of Illinois Urbana-Champaign', 'Python, MATLAB',
    ]);
  });
  it('ends the header block at a Title Case heading with "&" or an unknown one, keeping the role lines below it', async () => {
    const lines = (heading: string) => ['Jordan Lee', 'jordan.lee@example.com', heading, 'Research Assistant', 'Health Imaging Lab',
      '- Built a PyTorch pipeline that trains a ResNet-18 baseline.', 'EDUCATION', 'University of Illinois'].join('\n');
    const below = ['Research Assistant', 'Health Imaging Lab', '- Built a PyTorch pipeline that trains a ResNet-18 baseline.', 'University of Illinois'];
    for (const heading of ['Research & Projects', 'Experience & Leadership', 'Honors & Awards', 'Selected Experience']) {
      expect((await createResumeCandidates(lines(heading))).map((entry) => entry.text)).toEqual(below);
    }
    // A heading the list does not name still ends the header block, and is
    // offered like any other line rather than hiding what follows it.
    expect((await createResumeCandidates(lines('Campus Leadership'))).map((entry) => entry.text)).toEqual(['Campus Leadership', ...below]);
  });
  it('ends the header block at the first line that is not the name, a contact line or a place, whatever heading follows', async () => {
    // A heading the title list does not name must not hide the role lines
    // under it: only the name and the contact and place lines are header.
    const role = ['Course Assistant', 'CS 124 Staff', '- Held weekly office hours for 120 students in the intro course.'];
    for (const heading of ['Teaching & Mentoring', 'Outreach', 'Mentorship', 'PATENTS', 'Lab Work']) {
      const raw = ['Jordan Lee', 'jordan.lee@example.com', 'Champaign, IL', 'github.com/jlee', heading, ...role,
        'EDUCATION', 'University of Illinois'].join('\n');
      expect((await createResumeCandidates(raw)).map((entry) => entry.text)).toEqual([heading, ...role, 'University of Illinois']);
    }
    // Without any heading there is no header block to drop.
    expect((await createResumeCandidates(['Course Assistant', 'Champaign, IL', ...role.slice(1)].join('\n')))
      .map((entry) => entry.text)).toEqual(['Course Assistant', 'Champaign, IL', ...role.slice(1)]);
    // The same with blank lines between paragraphs.
    const raw = ['Jordan Lee\njordan.lee@example.com\nChampaign, IL', `Outreach\n${role[0]}\n${role[1]}`, role[2],
      'EDUCATION\nUniversity of Illinois'].join('\n\n');
    expect((await createResumeCandidates(raw)).map((entry) => entry.text)).toEqual([
      `Outreach\n${role[0]}\n${role[1]}`, role[2], 'EDUCATION\nUniversity of Illinois',
    ]);
  });
  it('reads a first line that names a role as the name only when contact details or a place follow it', async () => {
    // A layout that prints the main column first opens with a role.
    const role = ['Research Assistant', 'Health Imaging Lab', '- Built a baseline.', 'EDUCATION', 'University of Illinois'];
    expect((await createResumeCandidates(role.join('\n'))).map((entry) => entry.text)).toEqual([
      'Research Assistant', 'Health Imaging Lab', '- Built a baseline.', 'University of Illinois',
    ]);
    for (const below of ['jordan.chair@example.com', 'Champaign, IL']) {
      const raw = ['Jordan Chair', below, 'EXPERIENCE', 'Research Assistant', '- Built a baseline.'].join('\n');
      expect((await createResumeCandidates(raw)).map((entry) => entry.text)).toEqual(['Research Assistant', '- Built a baseline.']);
    }
  });
  it('reads a labelled place line as part of the header block', async () => {
    const raw = ['Jordan Lee', 'Location: Champaign, IL', 'jordan.lee@example.com', 'EXPERIENCE', 'Research Assistant'].join('\n');
    expect((await createResumeCandidates(raw)).map((entry) => entry.text)).toEqual(['Research Assistant']);
  });
  it('treats a first line in capitals as the name, not as the heading that ends the header block', async () => {
    const raw = ['PRIYA NATARAJAN', 'Champaign, IL', 'priya.natarajan.test@example.com', 'SKILLS', 'SQL', 'MATLAB'].join('\n');
    expect((await createResumeCandidates(raw)).map((entry) => entry.text)).toEqual(['SQL', 'MATLAB']);
  });
  it('keeps a stored bullet together with its wrapped lowercase rows', async () => {
    const raw = ['EXPERIENCE', 'Research Assistant, Imaging Lab - Jan 2026 - Present',
      '- Built a PyTorch pipeline that trains a ResNet-18 baseline,', 'reaching 0.87 AUC on a held-out split.',
      '- Compared Grad-CAM and integrated-gradients', 'saliency maps; I wrote the evaluation scripts.',
      'Software Engineering Intern, Prairie Analytics'].join('\n');
    expect((await createResumeCandidates(raw)).map((entry) => entry.text)).toEqual([
      'Research Assistant, Imaging Lab - Jan 2026 - Present',
      '- Built a PyTorch pipeline that trains a ResNet-18 baseline,\nreaching 0.87 AUC on a held-out split.',
      '- Compared Grad-CAM and integrated-gradients\nsaliency maps; I wrote the evaluation scripts.',
      'Software Engineering Intern, Prairie Analytics',
    ]);
  });
  it('joins a stored bullet with the rows that only wrap it on words that cannot end or open an item', async () => {
    // Text the old PDF reader stored for the target-résumé walk: one row per
    // printed line. "maps;" starts in lowercase, so it finishes its bullet.
    // "AUC" is capitalized; only the page's geometry showed that it wrapped,
    // and with the page gone that row stays apart.
    const raw = [
      'EXPERIENCE',
      'Undergraduate Research Assistant, Health Imaging Lab (UIUC) - Jan 2026 - Present',
      '- Built a PyTorch pipeline that preprocesses 12,000 chest X-ray images and trains a ResNet-18 baseline, reaching 0.87',
      'AUC on a held-out split.',
      '- Worked with a PhD mentor as part of a four-person team to compare Grad-CAM and integrated-gradients saliency',
      'maps; I wrote the evaluation scripts.',
      "- Wrote SQL and Python ETL jobs that cut a nightly report's runtime from 40 minutes to 9 minutes.",
      '- Added unit tests (pytest) for 14 data-validation functions.',
    ].join('\n');
    expect((await createResumeCandidates(raw)).map((entry) => entry.text)).toEqual([
      'Undergraduate Research Assistant, Health Imaging Lab (UIUC) - Jan 2026 - Present',
      '- Built a PyTorch pipeline that preprocesses 12,000 chest X-ray images and trains a ResNet-18 baseline, reaching 0.87',
      'AUC on a held-out split.',
      '- Worked with a PhD mentor as part of a four-person team to compare Grad-CAM and integrated-gradients saliency\nmaps; I wrote the evaluation scripts.',
      "- Wrote SQL and Python ETL jobs that cut a nightly report's runtime from 40 minutes to 9 minutes.",
      '- Added unit tests (pytest) for 14 data-validation functions.',
    ]);
  });
  it('reads stored rows the way the reflow reads a page, with widths counted in characters', () => {
    expect(storedWraps([
      '- Built a gait-analysis toolkit in Python used by eleven graduate students across two labs and',
      'three clinics',
      'Research Intern, Biomechanics Lab\tJun 2025 - Aug 2025',
      '- Collected force-plate recordings from twenty volunteers under an approved protocol with the',
      'lab manager.',
      'EDUCATION',
    ])).toEqual([false, true, false, false, true, false]);
    // A list cut inside a name reads on only where the page shows it.
    expect(storedWraps(['- Tools: Python, MATLAB, NumPy, SolidWorks, LabVIEW, COMSOL, Arduino, ImageJ, Excel, Power',
      'BI, Tableau, Excel'])).toEqual([false, false]);
    // A row with a column gap is a row of its own, even after a word that goes on.
    expect(storedWraps(['- Calibrated the motion capture system and wrote the setup guide for new lab staff and',
      'Python\tSpring 2025'])).toEqual([false, false]);
    // A Chinese character is as wide as two Latin ones.
    expect(storedWraps([
      'JORDAN AVERY LEE | jordan.lee.test@example.com | Urbana, IL | github.com/jlee',
      '• 负责后端接口设计与数据库建模，使用 Flask 与 PostgreSQL 实现用户、商品与订单模块，',
      '并编写部署文档。',
    ])).toEqual([false, false, true]);
  });
  it('keeps every row of reflowed text that the reflow left on its own line', async () => {
    // Text the PDF reflow already joined: an organization line, a section
    // title the list does not name and a row of names each sit under a full
    // bullet that ends without a full stop.
    const texts = JSON.parse(readFileSync(join(__dirname, '__fixtures__/resume-pdf/resume-texts.json'), 'utf8')) as Record<string, string>;
    for (const key of ['reflowed-org-lines', 'reflowed-unlisted-title']) {
      const rows = texts[key].split('\n');
      expect((await createResumeCandidates(texts[key])).map((entry) => entry.text))
        .toEqual(rows.slice(2).filter((row) => !/^[A-Z]+$/.test(row)));
    }
  });
  it('joins a stored row to its bullet only on words that cannot end or open an item', async () => {
    // Stored by the old PDF reader, one row per printed line. A lowercase
    // row or a row after "a" finishes its bullet; a role row after a list
    // or after "rely on" opens the next role.
    const texts = JSON.parse(readFileSync(join(__dirname, '__fixtures__/resume-pdf/resume-texts.json'), 'utf8')) as Record<string, string>;
    const quotes = (await createResumeCandidates(texts['stored-particle-then-role'])).map((entry) => entry.text);
    expect(quotes.slice(3, 15)).toEqual([
      'Software Engineering Intern, Prairie Analytics - Jun 2024 - Aug 2024',
      "• Migrated the lab's analysis scripts from MATLAB to Python and added unit tests for each function",
      '• Interviewed fourteen local restaurant owners about delivery fees and summarized the fi ndings for student\ngovernment',
      '• Tech stack: PyTorch, NumPy, pandas, scikit-learn, OpenCV, CUDA, Slurm, Linux, Git',
      'Hardware Lead, Illini Solar Car - Jun 2024 - Aug 2024',
      '• Assembled a low-cost air quality monitor with an ESP32 and logged readings from six dorm rooms for a\nmonth',
      '• Built a Flask service that matches tutoring requests to volunteer tutors by course and availability',
      '• Cleaned and merged three years of county health records and built a dashboard in Tableau',
      '• Maintained the equipment checkout system that the photography club and two other groups rely on',
      'Volunteer Coordinator, Eastern Illinois Foodbank - Jun 2024 - Aug 2024',
      '• Analyzed 2 million taxi trips with Spark and presented fare patterns to the transportation group',
      '• Organized a hackathon for 150 students with sponsors from four local companies',
    ]);
    const listed = (await createResumeCandidates(texts['stored-list-then-role'])).map((entry) => entry.text);
    expect(listed).toContain('• Tech stack: PyTorch, NumPy, pandas, scikit-learn, OpenCV, CUDA, Slurm, Linux, Git');
    expect(listed).toContain('Undergraduate Research Assistant, Plant Phenomics Lab');
    expect(listed).toContain('• Automated the weekly inventory report for the chemistry stockroom so staff no longer copy numbers between\nspreadsheets');
  });
  it('keeps a lowercase row apart from a stored bullet that stopped well short of the widest rows', async () => {
    // A bullet this short did not wrap, so the row after it is not its rest.
    const raw = ['EXPERIENCE', '- Built a thermal sensor in Java for the ME 270 capstone with a team of four',
      '- Wrote a 12-page final lab report', 'iterated on the enclosure design with the machine shop'].join('\n');
    expect((await createResumeCandidates(raw)).map((entry) => entry.text)).toEqual([
      '- Built a thermal sensor in Java for the ME 270 capstone with a team of four',
      '- Wrote a 12-page final lab report',
      'iterated on the enclosure design with the machine shop',
    ]);
  });
  it('keeps a widowed lowercase word with its bullet even when it is also a section title', async () => {
    const raw = ['EXPERIENCE', '- Assisted a PhD student with literature reviews and data collection for autonomous driving',
      'research', '- Wrote SQL and Python ETL jobs'].join('\n');
    expect((await createResumeCandidates(raw)).map((entry) => entry.text)).toEqual([
      '- Assisted a PhD student with literature reviews and data collection for autonomous driving\nresearch',
      '- Wrote SQL and Python ETL jobs',
    ]);
  });
  it('offers school, employer and skill lines set in capitals, and reads a heading on the first line as a heading', async () => {
    // A layout that prints the main column first opens with a heading, not a name.
    const raw = ['EXPERIENCE', 'PRAIRIE ANALYTICS', 'Research Intern, Lab', '- Wrote SQL jobs.', 'EDUCATION',
      'UNIVERSITY OF MICHIGAN', 'SKILLS', 'HTML, CSS, SQL', 'TECHNICAL SKILLS & TOOLS', 'Git', 'HONORS AND AWARDS',
      "Dean's List"].join('\n');
    expect((await createResumeCandidates(raw)).map((entry) => entry.text)).toEqual([
      'PRAIRIE ANALYTICS', 'Research Intern, Lab', '- Wrote SQL jobs.', 'UNIVERSITY OF MICHIGAN', 'HTML, CSS, SQL', 'Git', "Dean's List",
    ]);
  });
  it('keeps one proposal per line when a line-per-row résumé fits the cap', async () => {
    const raw = ['Built a robot', 'wrote a report', 'Led a team'].join('\n');
    expect((await createResumeCandidates(raw)).map((entry) => entry.text)).toEqual(['Built a robot', 'wrote a report', 'Led a team']);
  });
});
