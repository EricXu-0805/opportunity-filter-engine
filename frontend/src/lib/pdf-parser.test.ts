import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import type { createPdfResourceLoaders } from './pdf-resources';
type Loaders = ReturnType<typeof createPdfResourceLoaders>;
type DocumentOptions = {
  data: ArrayBuffer; cMapUrl: string; cMapPacked: boolean; standardFontDataUrl: string;
  CMapReaderFactory: Loaders['CMapReaderFactory']; StandardFontDataFactory: Loaders['StandardFontDataFactory'];
  useWorkerFetch: boolean;
};

const globalWorkerOptions = { workerSrc: '' };
const mockGetDocument = vi.fn<(opts: DocumentOptions) => { promise: Promise<MockPdf> }>();

vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: globalWorkerOptions,
  getDocument: (opts: DocumentOptions) => mockGetDocument(opts),
}));

import { parseResumePDF } from './pdf-parser';
import { MAX_RESUME_TEXT_CHARACTERS, weakWrapEvidence, wrapEvidence } from './resume-input';

type MockPdf = {
  numPages: number;
  destroy: () => Promise<void>;
  getPage: (n: number) => Promise<{
    cleanup: () => void;
    getTextContent: () => Promise<{ items: Array<{ str: string; hasEOL?: boolean } | { type: string }> }>;
  }>;
};

function fakePdf(pages: string[]): MockPdf {
  return {
    numPages: pages.length,
    destroy: async () => {},
    getPage: async (n: number) => ({
      cleanup: () => {},
      getTextContent: async () => ({ items: [{ str: pages[n - 1] ?? '' }] }),
    }),
  };
}

function fakeFile(): File {
  const buf = new Uint8Array([0x25, 0x50, 0x44, 0x46]).buffer;
  const f = new File([buf], 'resume.pdf', { type: 'application/pdf' });
  Object.defineProperty(f, 'arrayBuffer', { value: async () => buf });
  return f;
}

beforeEach(() => {
  globalWorkerOptions.workerSrc = '';
  mockGetDocument.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('parseResumePDF — worker bootstrap + IO', () => {
  it('configures GlobalWorkerOptions.workerSrc to the self-hosted bundled worker (no CDN)', async () => {
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(fakePdf(['hello'])) });
    await parseResumePDF(fakeFile());
    expect(globalWorkerOptions.workerSrc).toMatch(/pdf\.worker\.min\.mjs$/);
    expect(globalWorkerOptions.workerSrc).not.toMatch(/cdnjs|cloudflare/);
  });

  it('passes the file.arrayBuffer() result through to getDocument({data})', async () => {
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(fakePdf(['hi'])) });
    await parseResumePDF(fakeFile());
    expect(mockGetDocument).toHaveBeenCalledTimes(1);
    const arg = mockGetDocument.mock.calls[0][0];
    expect(arg).toHaveProperty('data');
    expect(arg.data).toBeInstanceOf(ArrayBuffer);
    expect(arg).toMatchObject({
      cMapUrl: '/pdfjs/cmaps/',
      cMapPacked: true,
      standardFontDataUrl: '/pdfjs/standard_fonts/',
      useWorkerFetch: false,
    });
    expect(arg.cMapUrl).not.toMatch(/https?:|cdn/);
    expect(arg.standardFontDataUrl).not.toMatch(/https?:|cdn/);
  });

  it('concatenates page texts across every page returned by numPages', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['page1-Python', 'page2-React', 'page3-Docker'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.success).toBe(true);
    expect(res.extracted_skills).toEqual(expect.arrayContaining(['Python', 'React', 'Docker']));
  });
});

describe('parseResumePDF — image-only PDF', () => {
  it('returns success=false with the documented image-based message when no text is extracted', async () => {
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(fakePdf(['   '])) });
    const res = await parseResumePDF(fakeFile());
    expect(res.success).toBe(false);
    expect(res.message).toMatch(/image-based/i);
    expect(res.extracted_skills).toEqual([]);
    expect(res.extracted_coursework).toEqual([]);
    expect(res.skill_evidence).toEqual([]);
    expect(res.raw_text).toBe('');
  });

  it('treats a multi-page PDF where every page is whitespace as image-only', async () => {
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(fakePdf(['  ', '', '\t'])) });
    const res = await parseResumePDF(fakeFile());
    expect(res.success).toBe(false);
  });
});

describe('parseResumePDF — skill extraction', () => {
  it('detects the documented hard skills via case-insensitive token match', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['Skilled in python, javascript, REACT and pyTorch'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.extracted_skills).toEqual(
      expect.arrayContaining(['Python', 'JavaScript', 'React', 'PyTorch']),
    );
  });

  it('does NOT false-match short skills inside words (algorithms/career/scary)', async () => {
    // Regression for the old substring matcher: 'Go' matched 'algorithms',
    // 'R' matched 'career', 'C' matched any word containing a c.
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['advanced algorithms for scary career growth'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.extracted_skills).not.toContain('C');
    expect(res.extracted_skills).not.toContain('R');
    expect(res.extracted_skills).not.toContain('Go');
    expect(res.extracted_skills).toEqual([]);
  });

  it('matches standalone C / R / Go tokens and keeps C distinct from C++/C#', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['Languages: Go, R, C, C++ and C#'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.extracted_skills).toEqual(expect.arrayContaining(['C', 'C++', 'C#', 'R', 'Go']));
  });

  it('does not report C when only C++ is present, nor Java inside JavaScript', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['Proficient in C++ and JavaScript'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.extracted_skills).toContain('C++');
    expect(res.extracted_skills).toContain('JavaScript');
    expect(res.extracted_skills).not.toContain('C');
    expect(res.extracted_skills).not.toContain('Java');
  });

  it('still matches a skill at a sentence boundary ("Docker.")', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['Deployed with Docker.'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.extracted_skills).toContain('Docker');
  });

  it('returns an empty skills array when the text mentions no known skills', async () => {
    // 'blah blah blah' deliberately avoids 'c' and 'r' (the single-letter
    // skills 'C' and 'R' in KNOWN_SKILLS), plus all multi-char skill prefixes
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['blah blah blah'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.extracted_skills).toEqual([]);
  });

  it('does not double-count when a skill is mentioned multiple times', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['Python Python python PYTHON'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.extracted_skills.filter((s) => s === 'Python')).toHaveLength(1);
  });
});

describe('parseResumePDF — coursework extraction', () => {
  it('an address block is not coursework', async () => {
    // "APT 402" and "BLDG 210" have the exact shape of a course code, and a
    // résumé's address sits a few lines above its education section. They were
    // reaching the profile as courses, and from there into what a cold email
    // claims the student has studied.
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf([
        'Guoyi Xu',
        '1203 W Main St APT 402',
        'Urbana IL 61801',
        'Office BLDG 210 RM 315',
        'EDUCATION',
        'Relevant Coursework: MATH 241, PHYS 211',
      ])),
    });
    const out = await parseResumePDF(fakeFile());
    expect(out.extracted_coursework).toContain('MATH 241');
    expect(out.extracted_coursework).toContain('PHYS 211');
    expect(out.extracted_coursework).not.toContain('APT 402');
    expect(out.extracted_coursework).not.toContain('BLDG 210');
    expect(out.extracted_coursework).not.toContain('RM 315');
  });

  it('matches the COURSE_PATTERN (2-4 letter prefix + 3-4 digit number)', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['Took CS 225, MATH 241, and ECE 220 last term'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.extracted_coursework).toEqual(['CS 225', 'ECE 220', 'MATH 241']);
  });

  it('rejects venue/date entries whose number is a calendar year', async () => {
    // Publications and dates share the course-code shape: "CVPR 2026",
    // "AAAI 2025", "MAY 2027" are not courses, and citing one as coursework
    // is a false claim downstream (observed live in a generated email).
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(
        fakePdf(['Publications: paper at CVPR 2026, AAAI 2025 workshop. Graduating MAY 2027. Took ECE 391 and CS 2110.']),
      ),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.extracted_coursework).toEqual(['CS 2110', 'ECE 391']);
  });

  it('dedupes repeated course mentions across the document', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['CS 225 — Data Structures; later TA for CS 225'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.extracted_coursework.filter((c) => c === 'CS 225')).toHaveLength(1);
  });

  it('returns coursework sorted alphabetically (stable across runs)', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['MATH 241, AERO 199, CS 225, BIOL 150'])),
    });
    const res = await parseResumePDF(fakeFile());
    const sorted = [...res.extracted_coursework].sort();
    expect(res.extracted_coursework).toEqual(sorted);
  });

  it('returns an empty coursework array when no course codes are present', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['narrative paragraph mentioning Python only'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.extracted_coursework).toEqual([]);
  });

  it('extracts named courses from a labeled "Coursework:" list', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['Coursework: Data Structures, Linear Algebra; Operating Systems'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.extracted_coursework).toEqual(['Data Structures', 'Linear Algebra', 'Operating Systems']);
  });

  it('combines labeled named courses with department codes', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['Relevant Courses: Databases, CS 233'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.extracted_coursework).toContain('CS 233');
    expect(res.extracted_coursework).toContain('Databases');
  });

  it('does not treat unlabeled prose as named courses', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['I enjoy data structures and building things'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.extracted_coursework).toEqual([]);
  });
});

describe('parseResumePDF — research interests capture', () => {
  it('captures a labeled "Research Interests" line into suggested_interests', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['Research Interests: machine learning, computational neuroscience'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.suggested_interests).toBe('machine learning, computational neuroscience');
  });

  it('stops the capture at the next Capitalized section label on a flattened line', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf([
        'Areas of Interest: AI systems, computer vision Languages: Mandarin (native), English',
      ])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.suggested_interests).toBe('AI systems, computer vision');
  });

  it('ignores hobby "Personal Interests" lines and returns empty when unlabeled', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['Personal Interests: hiking, chess. Python.'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.suggested_interests).toBe('');
  });
});

describe('parseResumePDF — success response shape', () => {
  it('retains text and evidence beyond 8,000 and 20,000 characters across pages', async () => {
    const pages = ['Earlier experience. '.repeat(1200), 'Research: Python 数据分析\nFinal source marker'];
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(fakePdf(pages)) });
    const res = await parseResumePDF(fakeFile());
    expect(res.success).toBe(true);
    expect(res.raw_text).toBe(pages.join('\n'));
    expect(res.raw_text).toContain('Final source marker');
    expect(res.skill_evidence.find((hit) => hit.skill === 'Python')?.line).toContain('数据分析');
  });

  it('builds the success message with the extracted counts', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['Python React. CS 225 MATH 241'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.message).toMatch(/Extracted \d+ skills, \d+ courses/);
  });
});

describe('parseResumePDF — every skill carries where it was found', () => {
  it('reports the resume line each skill matched on', async () => {
    // The extractor is a bare presence test over a fixed list, so a match says
    // only that the word appears — not that the student can do it. Carrying the
    // line makes a spurious hit visible to them instead of silently becoming a
    // skill on their profile.
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf([
        'Relevant coursework: Introduction to Python and Data Structures',
      ])),
    });
    const out = await parseResumePDF(fakeFile());
    const hit = out.skill_evidence?.find((e) => e.skill === 'Python');
    expect(hit).toBeDefined();
    expect(hit!.line).toContain('Relevant coursework');
    expect(hit!.line).toContain('Python');
  });

  it('gives each skill its own line when they sit on different ones', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf([
        'Skills: Docker',
        'Interests: hoping to learn PyTorch someday',
      ])),
    });
    const out = await parseResumePDF(fakeFile());
    const byName = Object.fromEntries(
      (out.skill_evidence ?? []).map((e) => [e.skill, e.line]),
    );
    expect(byName['Docker']).toContain('Skills:');
    expect(byName['PyTorch']).toContain('hoping to learn');
  });

  it('reports one entry per extracted skill, in the same order', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['Built with Python, Docker and React'])),
    });
    const out = await parseResumePDF(fakeFile());
    expect((out.skill_evidence ?? []).map((e) => e.skill))
      .toEqual(out.extracted_skills);
  });

  it('caps a runaway line so a one-line PDF cannot ship the whole resume per skill', async () => {
    // PDF extraction often flattens a resume onto a single line; without a cap
    // every skill would carry a copy of the entire document.
    const long = 'Python ' + 'x'.repeat(2000);
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(fakePdf([long])) });
    const out = await parseResumePDF(fakeFile());
    const hit = out.skill_evidence!.find((e) => e.skill === 'Python')!;
    expect(hit.line.length).toBeLessThanOrEqual(200);
    expect(hit.line).toContain('Python');
  });
});

describe('parseResumePDF — the inferred experience level is gone', () => {
  it('no longer reports an experience_level nobody chose', async () => {
    // It was computed from counting verbs ("led", "built") and then discarded:
    // handleResumeParsed never read it. Measured on the real corpus, feeding it
    // to the ranker would not reorder a single result — it shifts every score by
    // the same constant — but it WOULD move opportunities between the
    // High Priority / Good Match / Reach labels a student is shown, on the
    // strength of a word appearing twice. And no control lets them correct it.
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf([
        'Led the team, managed the rollout, published two papers',
      ])),
    });
    const out = await parseResumePDF(fakeFile());
    expect('experience_level' in out).toBe(false);
  });

});


describe('complete supported resume input', () => {
  it.each(['文', '🧪'])('counts %s as one Unicode character and accepts the exact limit', async (character) => {
    const text = character.repeat(MAX_RESUME_TEXT_CHARACTERS);
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(fakePdf([text])) });
    const res = await parseResumePDF(fakeFile());
    expect(res.success).toBe(true);
    expect(res.raw_text).toBe(text);
  });

  it('refuses oversize text without a partial replacement and releases PDF resources', async () => {
    const pdf = fakePdf(['x'.repeat(MAX_RESUME_TEXT_CHARACTERS), 'tail']);
    const destroy = vi.spyOn(pdf, 'destroy');
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdf) });
    const res = await parseResumePDF(fakeFile());
    expect(res).toMatchObject({ success: false, error_code: 'text_too_long', raw_text: '', extracted_skills: [] });
    expect(destroy).toHaveBeenCalledTimes(1);
  });

  it('preserves PDF.js line/page boundaries and ignores non-text marked content', async () => {
    const cleanup = vi.fn();
    const pdf: MockPdf = {
      numPages: 2, destroy: vi.fn(async () => {}),
      getPage: async (page) => ({ cleanup, getTextContent: async () => ({ items: page === 1 ? [
        { type: 'beginMarkedContent' }, { str: 'Experience', hasEOL: true },
        { str: '• Built' }, { str: 'a Python parser', hasEOL: true },
        { str: '• 分析研究数据', hasEOL: true },
      ] : [{ str: 'Final page' }] }) }),
    };
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdf) });
    const res = await parseResumePDF(fakeFile());
    expect(res.raw_text).toBe('Experience\n• Built a Python parser\n• 分析研究数据\n\nFinal page');
    expect(cleanup).toHaveBeenCalledTimes(2);
    expect(pdf.destroy).toHaveBeenCalledTimes(1);
  });

  it('reports pages without text rather than claiming the whole PDF was read', async () => {
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(fakePdf(['Readable page', '', 'Tail'])) });
    const res = await parseResumePDF(fakeFile());
    expect(res.success).toBe(true);
    expect(res.pages_without_text).toEqual([2]);
    expect(res.raw_text).toBe('Readable page\n\nTail');
  });

  it('releases the document when a later page fails; no partial result is returned', async () => {
    const pdf = fakePdf(['First', 'Second']);
    const destroy = vi.spyOn(pdf, 'destroy');
    vi.spyOn(pdf, 'getPage').mockRejectedValue(new Error('corrupt page'));
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdf) });
    await expect(parseResumePDF(fakeFile())).rejects.toThrow('corrupt page');
    expect(destroy).toHaveBeenCalledTimes(1);
  });
});


describe('PDF resource failures cannot become a partial successful upload', () => {
  it.each(['cmap', 'standard-font'] as const)('rejects nonempty text after PDF.js swallows a %s failure', async (resource) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    const pdf = fakePdf(['English survives while Chinese disappears']);
    const destroy = vi.spyOn(pdf, 'destroy');
    mockGetDocument.mockImplementation((options) => {
      pdf.getPage = async () => ({
        cleanup: () => {},
        getTextContent: async () => {
          const read = resource === 'cmap'
            ? new options.CMapReaderFactory({ baseUrl: options.cMapUrl, isCompressed: options.cMapPacked })
              .fetch({ name: 'UniGB-UCS2-H' })
            : new options.StandardFontDataFactory({ baseUrl: options.standardFontDataUrl })
              .fetch({ filename: 'FoxitSerif.pfb' });
          // This is the installed PDF.js ErrorFont path: the resource promise
          // rejects, but the page still resolves with the remaining text.
          await read.catch(() => undefined);
          return { items: [{ str: 'English survives while Chinese disappears' }] };
        },
      });
      return { promise: Promise.resolve(pdf) };
    });
    try {
      const result = await parseResumePDF(fakeFile());
      expect(result).toMatchObject({
        success: false, error_code: 'pdf_resources_unavailable', raw_text: '', extracted_skills: [],
      });
      expect(result.message).not.toContain('/pdfjs');
      expect(destroy).toHaveBeenCalledTimes(1);
    } finally { vi.unstubAllGlobals(); }
  });
});


// Chromium-printed résumés (see __fixtures__/resume-pdf/generate.mjs), read by
// the real PDF.js. Only the worker and resource loading differ from the
// browser: the legacy build runs in Node and reads fonts from node_modules.
describe('real résumé PDFs keep every word and bullet intact', () => {
  const FIXTURES = join(__dirname, '__fixtures__/resume-pdf');
  const PDFJS = join(__dirname, '../../node_modules/pdfjs-dist');
  const PERSONA = readFileSync(join(FIXTURES, 'persona.txt'), 'utf8');
  let pdfjs: typeof import('pdfjs-dist');

  beforeAll(async () => {
    const worker = 'pdfjs-dist/legacy/build/pdf.worker.mjs';
    const library = 'pdfjs-dist/legacy/build/pdf.mjs';
    (globalThis as { pdfjsWorker?: unknown }).pdfjsWorker = await import(/* @vite-ignore */ worker);
    pdfjs = await import(/* @vite-ignore */ library) as typeof import('pdfjs-dist');
  });

  async function parseFixture(name: string) {
    const bytes = readFileSync(join(FIXTURES, name));
    mockGetDocument.mockImplementation((options) => pdfjs.getDocument({
      data: new Uint8Array(options.data), cMapUrl: `${PDFJS}/cmaps/`, cMapPacked: true,
      standardFontDataUrl: `${PDFJS}/standard_fonts/`, useSystemFonts: false, isEvalSupported: false,
    }) as unknown as { promise: Promise<MockPdf> });
    const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    const file = new File([buffer], name, { type: 'application/pdf' });
    Object.defineProperty(file, 'arrayBuffer', { value: async () => buffer.slice(0) });
    const result = await parseResumePDF(file);
    expect(result.success).toBe(true);
    return result.raw_text;
  }

  // One file per stranger-walk report. Each wraps different lines: after
  // "baseline," and "(MATH" (CE-2), before "AUC", "& Statistics", "maps;" and
  // "78%" (TR-04), and inside "integrated-gradients" (tailor-renovate-02).
  // Helvetica also prints "fi" as a separate ligature glyph run.
  it.each(['resume-ce2.pdf', 'resume-tr04.pdf'])(
    '%s reads back line for line as the résumé text it was printed from', async (name) => {
      expect(await parseFixture(name)).toBe(PERSONA);
    });

  it('reads back the renovate walk line for line, except a number after "on" that could open the next item', async () => {
    // "…a multilingual BERT on" / "3,000 labeled tweets" wraps here, but an
    // item can end in "on" ("…two other groups rely on") and the next one
    // open with a number ("25% fewer tickets…"), so the line stays split.
    expect(await parseFixture('resume-renovate.pdf'))
      .toBe(PERSONA.replace('BERT on 3,000 labeled tweets', 'BERT on\n3,000 labeled tweets'));
  });

  it('offers the tailor prefill the four complete bullets', async () => {
    const bullets = (await parseFixture('resume-renovate.pdf')).split('\n')
      .filter((line) => /^\s*([•\-*–—+]|\d+[.)])\s+/.test(line));
    expect(bullets).toEqual(PERSONA.split('\n').filter((line) => line.startsWith('- ')));
  });

  it('keeps sidebar and main columns, graphic list bullets, right-aligned rows and one-item lists apart', async () => {
    // A right-aligned date or location is separated by a tab, not a space.
    expect((await parseFixture('resume-layouts.pdf')).split('\n')).toEqual([
      'Priya Natarajan',
      'priya.natarajan.test@example.com',
      '(217) 555-0142',
      'Champaign, IL',
      'github.com/priya-test',
      'EDUCATION',
      'University of Illinois Urbana-Champaign',
      'B.S. in Bioengineering, Aug 2024 - May 2028',
      // A list cut inside a name stays split: the row under a list is as
      // often an organization or an honors line.
      'Relevant coursework: Signals and Systems, Biomedical',
      'Imaging, Fluid Mechanics, Differential Equations',
      'SKILLS',
      'Python, MATLAB, NumPy, SolidWorks, LabVIEW, Git',
      'RESEARCH EXPERIENCE',
      'Undergraduate Researcher, Tissue Mechanics Lab\tSep 2025 - Present',
      'University of Illinois Urbana-Champaign\tUrbana, IL',
      'Designed an efficient finite-element workflow that reduced the fluid-flow simulation time of affine tissue models from six hours to forty minutes.',
      'Profiled official offline benchmarks and flagged five configuration files with conflicting boundary conditions.',
      'WORK EXPERIENCE',
      'Engineering Intern, Midwest Medical Devices\tMay 2025 - Aug 2025',
      'Automated the calibration log for twelve flow sensors and cut the weekly review from three hours to thirty minutes.',
      'Wrote first-draft test fixtures.',
      'TOOLS',
      'Python',
      'SolidWorks',
      'LabVIEW',
      'MATLAB',
      'Git',
      'LANGUAGES',
      'English',
      'Spanish',
      'EXPERIENCE',
      'Research Intern, Biomechanics Lab\tJun 2025 - Aug 2025',
      'University of Illinois\tUrbana, IL',
      'Built a gait-analysis toolkit in Python used by eleven graduate students across two labs and three',
      'Collected force-plate recordings from twenty volunteers under an approved protocol with the lab manager',
      'Presented weekly results',
      'SUMMARY',
      'Mechanical engineering student who compares wearable sensors for rehabilitation robotics and reports calibration, robustness and interpretability results with counterfactual checks for every study.',
      'Seeking a research position for Summer 2026',
    ]);
  });

  it('keeps items that end without a period on their own lines when their last line nearly fills the column', async () => {
    // Several items here end within a word of the right edge, so geometry
    // alone would read the next item as the rest of the line. A lone
    // capitalized last word ("X-rays") stays apart for the same reason.
    const roles = JSON.parse(readFileSync(join(FIXTURES, 'noperiod-roles.json'), 'utf8')) as Array<[string, string, string[]]>;
    const paragraphs = readFileSync(join(FIXTURES, 'noperiod-paragraphs.txt'), 'utf8').trimEnd().split('\n');
    expect((await parseFixture('resume-noperiod.pdf')).split('\n')).toEqual([
      'Jordan Avery Lee',
      'jordan.lee.test@example.com | (217) 555-0142 | Urbana, IL',
      'EXPERIENCE',
      ...roles.flatMap(([title, dates, bullets]) => [`${title}\t${dates}`, ...bullets]),
      'SKILLS',
      'Python, PyTorch, SQL, C++, Git, Linux, pandas, scikit-learn',
      ...paragraphs.flatMap((paragraph) => (paragraph.endsWith(' on chest X-rays') ? [paragraph.slice(0, -' X-rays'.length), 'X-rays'] : [paragraph])),
    ]);
  });

  it('keeps apart the next item, role row, title or sentence that a nearly full last line could absorb', async () => {
    // Every item ends within about one word of the column edge, so the next
    // line's first word "could not have fitted" on any of them: "• " items
    // followed by same-font rows, a title, a project row and a sentence;
    // list items that end in ", SQL", ", IL", "C++", ";" or ", Node.js";
    // Chinese items with no final 。, under a glyph or none; organization
    // and honors rows after a list; items that open with a measure; and a
    // program's name after "check in".
    const pages = JSON.parse(readFileSync(join(FIXTURES, 'boundaries.json'), 'utf8')) as Array<{ lines: Array<[string, string]> }>;
    expect((await parseFixture('resume-boundaries.pdf')).split('\n'))
      .toEqual(pages.flatMap((page) => page.lines.map(([, text]) => text)));
  });
});

describe('positioned text items', () => {
  const at = (str: string, x: number, width: number, y = 700, extra: Record<string, unknown> = {}) => ({
    str, width, height: 10, transform: [10, 0, 0, 10, x, y], fontName: 'f1', dir: 'ltr', hasEOL: false, ...extra,
  });
  function pdfOf(items: unknown[]): MockPdf {
    return {
      numPages: 1, destroy: async () => {},
      getPage: async () => ({ cleanup: () => {}, getTextContent: async () => ({ items: items as never }) }),
    };
  }

  it('joins glyph runs that touch and spaces runs that a gap separates', async () => {
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Classi', 50, 30), at('fi', 80, 5), at('er', 85, 10), at('for', 100, 15),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text).toBe('Classifier for');
  });

  it('never joins a line into a bullet, a heading or a line in another font, size or column', async () => {
    const wide = 'x '.repeat(40).trim();
    const full = 'Measured the latency of a quantized model on a Raspberry Pi against a laptop and';
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at(wide, 50, 500, 700, { hasEOL: true }), at('- next bullet', 50, 60, 688, { hasEOL: true }),
      at(wide, 50, 500, 676, { hasEOL: true }), at('EXPERIENCE', 50, 60, 664, { hasEOL: true }),
      at(wide, 50, 500, 652, { hasEOL: true }), at('bold words', 50, 50, 640, { fontName: 'f2', hasEOL: true }),
      at(full, 50, 500, 628, { hasEOL: true }), at('small words', 50, 45, 616, { height: 8, transform: [8, 0, 0, 8, 50, 616], hasEOL: true }),
      at(full, 50, 500, 604, { hasEOL: true }), at('words in the next column', 300, 110, 592),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      wide, '- next bullet', wide, 'EXPERIENCE', wide, 'bold words', full, 'small words', full, 'words in the next column',
    ]);
  });

  it('rejoins a word broken at its own hyphen without a space', async () => {
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Compared Grad-CAM and integrated-', 50, 500, 700, { hasEOL: true }),
      at('gradients saliency maps.', 50, 120, 688),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text).toBe('- Compared Grad-CAM and integrated-gradients saliency maps.');
  });

  it('keeps a capitalized line that no glyph or wording ties to the full line before it as the next item', async () => {
    // Graphic list bullets leave no glyph in the text, so the next item's
    // first word not fitting on the line above says nothing on its own. A
    // glyph bullet earlier on the page does not carry over to these items.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Built a parser for the lab', 50, 120, 712, { hasEOL: true }),
      at('Reduced nightly runtime by rewriting the joins and adding indexes', 50, 500, 700, { hasEOL: true }),
      at('Wrote unit tests for fourteen functions', 50, 200, 688, { hasEOL: true }),
      at('Configured CI to run linting, type checks and tests on every pull request', 50, 500, 676, { hasEOL: true }),
      at('Mentored three students', 50, 110, 664),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '- Built a parser for the lab',
      'Reduced nightly runtime by rewriting the joins and adding indexes',
      'Wrote unit tests for fourteen functions',
      'Configured CI to run linting, type checks and tests on every pull request',
      'Mentored three students',
    ]);
  });

  it('still joins a capitalized word that wraps inside a glyph bullet, after a word that goes on, or alone ending the sentence', async () => {
    // The first item shows that this list ends its items with a full stop. A
    // lone capitalized word that does not end a sentence could be a name or
    // a title of its own, so it stays apart, and so does a list cut inside a
    // name ("Biomedical" / "Imaging, …"), whose rest reads like a row of names.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Wrote unit tests for the parser.', 50, 160, 712, { hasEOL: true }),
      at('- Trained a baseline that reached 0.87', 50, 500, 700, { hasEOL: true }),
      at('AUC on a held-out split.', 50, 110, 688, { hasEOL: true }),
      at('Compared saliency maps computed with', 50, 500, 676, { hasEOL: true }),
      at('Grad-CAM on chest X-rays.', 50, 120, 664, { hasEOL: true }),
      at('Coursework: Signals and Systems, Biomedical', 50, 500, 652, { hasEOL: true }),
      at('Imaging, Fluid Mechanics', 50, 120, 640, { hasEOL: true }),
      at('Automated the calibration log with a shared Google', 50, 500, 628, { hasEOL: true }),
      at('Sheet', 50, 25, 616, { hasEOL: true }),
      at('Logged the flow sensor readings of every test run in a shared Google', 50, 500, 604, { hasEOL: true }),
      at('Sheet.', 50, 28, 592),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '- Wrote unit tests for the parser.',
      '- Trained a baseline that reached 0.87 AUC on a held-out split.',
      'Compared saliency maps computed with Grad-CAM on chest X-rays.',
      'Coursework: Signals and Systems, Biomedical',
      'Imaging, Fluid Mechanics',
      'Automated the calibration log with a shared Google',
      'Sheet',
      'Logged the flow sensor readings of every test run in a shared Google Sheet.',
    ]);
  });

  it('keeps a same-font role row, title or sentence apart from a glyph item whose last line fills the column', async () => {
    // A glyph list ends at some line. After an item with no full stop, a
    // capitalized line in the same font opens what follows, even when its
    // first word would not have fitted and even when it ends a sentence.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Debugged intermittent CAN bus faults on a solar car battery management board with a logic analyzer', 50, 500, 712, { hasEOL: true }),
      at('Software Engineering Intern, Greenhouse Analytics - May 2025 - Aug 2025', 50, 330, 700, { hasEOL: true }),
      at('• Mentored three first-year students in data structures during weekly office hours in Siebel', 50, 500, 688, { hasEOL: true }),
      at('Machine Learning Reading Group', 50, 140, 676, { hasEOL: true }),
      at('• Tested a quantized MobileNet model on a Raspberry Pi and measured its latency against a GPU', 50, 500, 664, { hasEOL: true }),
      at('Presented the results at the Undergraduate Research Symposium in April.', 50, 320, 652),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '- Debugged intermittent CAN bus faults on a solar car battery management board with a logic analyzer',
      'Software Engineering Intern, Greenhouse Analytics - May 2025 - Aug 2025',
      '• Mentored three first-year students in data structures during weekly office hours in Siebel',
      'Machine Learning Reading Group',
      '• Tested a quantized MobileNet model on a Raspberry Pi and measured its latency against a GPU',
      'Presented the results at the Undergraduate Research Symposium in April.',
    ]);
  });

  it('reads glyph items as ending with a full stop only where more item ends have one than not, rows aside', async () => {
    // One item with a full stop and one without say nothing either way, and
    // neither do project rows that end with one. The role row's date shows
    // where the column ends.
    const page = (...lines: unknown[]) => pdfOf([
      at('Research Intern, Robotics Lab', 50, 140, 760), at('Jun 2025 - Aug 2025', 460, 90, 760, { hasEOL: true }),
      ...lines,
      at('- Trained a convolutional baseline on chest X-rays from the hospital and reached a test score of 0.87', 50, 500, 712, { hasEOL: true }),
      at('AUC on a held-out split.', 50, 110, 700),
    ]);
    const tail = ['- Trained a convolutional baseline on chest X-rays from the hospital and reached a test score of 0.87',
      'AUC on a held-out split.'];
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(page(
      at('- Wrote unit tests for the parser.', 50, 160, 748, { hasEOL: true }),
      at('- Added a nightly job that checks the backups', 50, 220, 736, { hasEOL: true }),
    )) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Research Intern, Robotics Lab\tJun 2025 - Aug 2025', '- Wrote unit tests for the parser.', '- Added a nightly job that checks the backups', ...tail,
    ]);
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(page(
      at('Campus Bus Tracker - React and Flask web app.', 50, 210, 748, { hasEOL: true }),
      at('- Built the backend in Flask', 50, 140, 736, { hasEOL: true }),
      at('Soil Moisture Logger - custom PCB and firmware.', 50, 220, 724, { hasEOL: true }),
    )) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Research Intern, Robotics Lab\tJun 2025 - Aug 2025', 'Campus Bus Tracker - React and Flask web app.', '- Built the backend in Flask',
      'Soil Moisture Logger - custom PCB and firmware.', ...tail,
    ]);
  });

  it('keeps reading a glyph item as one past the lines joined to it', async () => {
    // The third line belongs to the glyph item through the second, so on a
    // page whose glyph items end with a full stop it may finish it.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Wrote unit tests for the parser.', 50, 160, 736, { hasEOL: true }),
      at('- Added a nightly job that checks the backups.', 50, 220, 724, { hasEOL: true }),
      at('- Trained a convolutional baseline on chest X-rays from the hospital archive and evaluated it with the', 50, 500, 712, { hasEOL: true }),
      at('held-out split of the hospital data, where it reached a test score of 0.87 and a sensitivity of 0.81', 50, 500, 700, { hasEOL: true }),
      at('AUC on the held-out split.', 50, 120, 688),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '- Wrote unit tests for the parser.',
      '- Added a nightly job that checks the backups.',
      '- Trained a convolutional baseline on chest X-rays from the hospital archive and evaluated it with the held-out split of the hospital data, where it reached a test score of 0.87 and a sensitivity of 0.81 AUC on the held-out split.',
    ]);
  });

  it('carries a line that ends in a colon on into the next', async () => {
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Built a dashboard for the county health department and the city transit office with three tools:', 50, 500, 712, { hasEOL: true }),
      at('Python, SQL, Tableau', 50, 90, 700, { hasEOL: true }),
      at('Mentored three students', 50, 110, 688),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Built a dashboard for the county health department and the city transit office with three tools: Python, SQL, Tableau',
      'Mentored three students',
    ]);
  });

  it('keeps a short line in a narrow column apart even where an indent brings its end near the edge', async () => {
    // A sidebar line that wraps runs most of the column's width; a short
    // indented entry that ends near the edge is a list entry of its own.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Machine learning with PyTorch and', 40, 150, 748, { hasEOL: true }),
      at('scikit-learn on lab data', 40, 100, 736, { hasEOL: true }),
      at('Data cleaning with', 52, 100, 724, { hasEOL: true }),
      at('pandas', 52, 30, 712),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Machine learning with PyTorch and scikit-learn on lab data', 'Data cleaning with', 'pandas',
    ]);
  });

  it('reads a full stop on the next line as the end of a glyph item only where glyph items end with one', async () => {
    // One-line items here end with a full stop, so a capitalized line that
    // ends one finishes the item before it, unless it is a row of its own.
    // The role row's right-aligned date shows where the column ends.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Research Intern, Robotics Lab', 50, 140, 724), at('Jun 2025 - Aug 2025', 460, 90, 724, { hasEOL: true }),
      at('- Wrote unit tests for the parser.', 50, 160, 712, { hasEOL: true }),
      at('- Trained a baseline that reached 0.87', 50, 500, 700, { hasEOL: true }),
      at('AUC on a held-out split.', 50, 110, 688, { hasEOL: true }),
      at('- Compared three saliency methods for the clinical team and the lab manager', 50, 500, 676, { hasEOL: true }),
      at('Campus Bus Tracker - React and Flask web app used by 200 students.', 50, 300, 664),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Research Intern, Robotics Lab\tJun 2025 - Aug 2025',
      '- Wrote unit tests for the parser.',
      '- Trained a baseline that reached 0.87 AUC on a held-out split.',
      '- Compared three saliency methods for the clinical team and the lab manager',
      'Campus Bus Tracker - React and Flask web app used by 200 students.',
    ]);
    // A lone item says nothing about how items end.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Reproduced the main experiment of a published reinforcement learning paper and wrote up two settings', 50, 500, 700, { hasEOL: true }),
      at('Presented the results at the Undergraduate Research Symposium in April.', 50, 320, 688),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '- Reproduced the main experiment of a published reinforcement learning paper and wrote up two settings',
      'Presented the results at the Undergraduate Research Symposium in April.',
    ]);
  });

  it('judges how glyph items end by the item ends, not by the rows or headings before them', async () => {
    // "Organization<tab>Place" rows, project rows and headings come before
    // items without saying how items end; the one-line item before the
    // second item does.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Research Intern, Biomechanics Lab', 50, 160, 736), at('Urbana, IL', 490, 50, 736, { hasEOL: true }),
      at('- Wrote a calibration script.', 50, 130, 724, { hasEOL: true }),
      at('- Tested the script on twenty recordings.', 50, 190, 712, { hasEOL: true }),
      at('Teaching Assistant, Statistics Department', 50, 190, 700), at('Champaign, IL', 480, 60, 700, { hasEOL: true }),
      at('- Trained a baseline that reached 0.87', 50, 500, 688, { hasEOL: true }),
      at('AUC on a held-out split.', 50, 110, 676, { hasEOL: true }),
      at('HONORS', 50, 50, 664, { hasEOL: true }),
      at("- Dean's List for five semesters.", 50, 150, 652),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Research Intern, Biomechanics Lab\tUrbana, IL',
      '- Wrote a calibration script.',
      '- Tested the script on twenty recordings.',
      'Teaching Assistant, Statistics Department\tChampaign, IL',
      '- Trained a baseline that reached 0.87 AUC on a held-out split.',
      'HONORS',
      "- Dean's List for five semesters.",
    ]);
    // Nor do role rows dated without a separator. (The second item's wrap
    // after "the" shows where the column ends.)
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Research Intern, Biomechanics Lab, Summer 2025', 50, 220, 736, { hasEOL: true }),
      at('- Wrote a calibration script.', 50, 130, 724, { hasEOL: true }),
      at('- Tested the script on twenty recordings from the gait lab and compared each one with the', 50, 500, 712, { hasEOL: true }),
      at('reference system.', 50, 80, 700, { hasEOL: true }),
      at('Teaching Assistant, Statistics Department, 2024', 50, 230, 688, { hasEOL: true }),
      at('- Trained a baseline that reached 0.87', 50, 500, 676, { hasEOL: true }),
      at('AUC on a held-out split.', 50, 110, 664),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Research Intern, Biomechanics Lab, Summer 2025',
      '- Wrote a calibration script.',
      '- Tested the script on twenty recordings from the gait lab and compared each one with the reference system.',
      'Teaching Assistant, Statistics Department, 2024',
      '- Trained a baseline that reached 0.87 AUC on a held-out split.',
    ]);
    // Project rows that end with a full stop do not make items without one
    // read as finished by the next sentence.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Campus Bus Tracker - React and Flask web app.', 50, 210, 712, { hasEOL: true }),
      at('- Built the backend in Flask', 50, 140, 700, { hasEOL: true }),
      at('Soil Moisture Logger - custom PCB and firmware.', 50, 220, 688, { hasEOL: true }),
      at('- Designed the logger board and wrote firmware that wakes up once an hour to save battery', 50, 500, 676, { hasEOL: true }),
      at('Presented the results at the Undergraduate Research Symposium in April.', 50, 320, 664),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Campus Bus Tracker - React and Flask web app.',
      '- Built the backend in Flask',
      'Soil Moisture Logger - custom PCB and firmware.',
      '- Designed the logger board and wrote firmware that wakes up once an hour to save battery',
      'Presented the results at the Undergraduate Research Symposium in April.',
    ]);
  });

  it('keeps a no-glyph item that ends in C++, a short comma tail or a semicolon apart from the next item', async () => {
    // ", SQL" or ", IL" ends a sentence with a short list or a place, and the
    // next line is a sentence or a role row, not the rest of a list.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Graded weekly programming assignments for 180 students and wrote autograder tests in C++', 50, 500, 712, { hasEOL: true }),
      at('Led two review sessions before each midterm exam', 50, 230, 700, { hasEOL: true }),
      at('Built an internal dashboard that tracks weekly sales with Python, SQL and Tableau, Power BI', 50, 500, 688, { hasEOL: true }),
      at('Presented findings to the regional director', 50, 200, 676, { hasEOL: true }),
      at('Drafted grant budget tables for a successful NIH R21 application in Champaign, IL', 50, 500, 664, { hasEOL: true }),
      at('Research Intern, Microfluidics Lab', 50, 160, 652, { hasEOL: true }),
      at('Ran weekly code reviews for the robotics team and kept notes on recurring bugs;', 50, 500, 640, { hasEOL: true }),
      at('Mentored two new members', 50, 120, 628, { hasEOL: true }),
      at('Languages: Python, Java, C++, SQL, R, Go, Rust, MATLAB, Julia, Swift, Kotlin', 50, 500, 616, { hasEOL: true }),
      at('Frameworks: React, Flask, Django', 50, 150, 604, { hasEOL: true }),
      at('Tools: Git, Docker, Jira, Tableau, Excel, Stata, SPSS, LaTeX, Figma, Power BI', 50, 500, 592, { hasEOL: true }),
      at('Presented findings to the regional director', 50, 200, 580, { hasEOL: true }),
      at('Wrote ETL jobs in Python, SQL, Airflow, dbt, Docker, Kubernetes, Terraform, AWS Lambda, Redshift, Looker', 50, 500, 568, { hasEOL: true }),
      at('Research Intern, Microfluidics Lab', 50, 160, 556),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Graded weekly programming assignments for 180 students and wrote autograder tests in C++',
      'Led two review sessions before each midterm exam',
      'Built an internal dashboard that tracks weekly sales with Python, SQL and Tableau, Power BI',
      'Presented findings to the regional director',
      'Drafted grant budget tables for a successful NIH R21 application in Champaign, IL',
      'Research Intern, Microfluidics Lab',
      'Ran weekly code reviews for the robotics team and kept notes on recurring bugs;',
      'Mentored two new members',
      'Languages: Python, Java, C++, SQL, R, Go, Rust, MATLAB, Julia, Swift, Kotlin',
      'Frameworks: React, Flask, Django',
      'Tools: Git, Docker, Jira, Tableau, Excel, Stata, SPSS, LaTeX, Figma, Power BI',
      'Presented findings to the regional director',
      'Wrote ETL jobs in Python, SQL, Airflow, dbt, Docker, Kubernetes, Terraform, AWS Lambda, Redshift, Looker',
      'Research Intern, Microfluidics Lab',
    ]);
  });

  it('still joins a line after a lone plus, and keeps a list cut inside a name split', async () => {
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Built the campus bus tracker as a React +', 50, 500, 712, { hasEOL: true }),
      at('Flask web app used by about 200 students', 50, 200, 700, { hasEOL: true }),
      at('Skills: Python, MATLAB, NumPy, SolidWorks, Power', 50, 500, 688, { hasEOL: true }),
      at('BI, Tableau, Excel', 50, 90, 676, { hasEOL: true }),
      at('Relevant coursework: Introduction to Computer Science, Data', 50, 500, 664, { hasEOL: true }),
      at('Structures and Algorithms, Discrete Mathematics', 50, 210, 652),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Built the campus bus tracker as a React + Flask web app used by about 200 students',
      'Skills: Python, MATLAB, NumPy, SolidWorks, Power',
      'BI, Tableau, Excel',
      'Relevant coursework: Introduction to Computer Science, Data',
      'Structures and Algorithms, Discrete Mathematics',
    ]);
  });

  it('keeps a line that opens with a mixed-case name, an ordinal or a model number apart', async () => {
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Ported a legacy spreadsheet of lab inventory into a searchable web page for four research groups', 50, 500, 712, { hasEOL: true }),
      at('iOS app that reminds students of office hours', 50, 210, 700, { hasEOL: true }),
      at('Designed a printed circuit board for a soil moisture logger and wrote firmware for long battery life', 50, 500, 688, { hasEOL: true }),
      at('3D-printed a prosthetic hand for a local clinic', 50, 220, 676, { hasEOL: true }),
      at('Organized weekly study sessions for an introductory statistics course and wrote practice problems', 50, 500, 664, { hasEOL: true }),
      at('2nd place at HackIllinois for an accessibility tool', 50, 230, 652),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Ported a legacy spreadsheet of lab inventory into a searchable web page for four research groups',
      'iOS app that reminds students of office hours',
      'Designed a printed circuit board for a soil moisture logger and wrote firmware for long battery life',
      '3D-printed a prosthetic hand for a local clinic',
      'Organized weekly study sessions for an introductory statistics course and wrote practice problems',
      '2nd place at HackIllinois for an accessibility tool',
    ]);
  });

  it('keeps a one-word line apart from a full line above it unless its words carry it on', async () => {
    // An organization, a section title the list does not name, a project
    // name: a capitalized word alone on a line says nothing about the line
    // above, even where that line ends at the column edge.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Rewrote the club website in Next.js so officers can post events without asking the webmaster', 50, 500, 736, { hasEOL: true }),
      at('Caterpillar', 50, 55, 724, { hasEOL: true }),
      at('Data Science Intern, Summer 2025', 50, 150, 712, { hasEOL: true }),
      at('• Trained a gradient boosting model to predict which library books will be requested next term', 50, 500, 700, { hasEOL: true }),
      at('Accomplishments', 50, 80, 688, { hasEOL: true }),
      at('• Reviewed pull requests for a student-run open-source project and wrote contributor guidelines', 50, 500, 676, { hasEOL: true }),
      at('COMPETITIONS', 50, 70, 664, { hasEOL: true }),
      at('• Organized a hackathon for 150 students with sponsors from four local companies and a city office', 50, 500, 652, { hasEOL: true }),
      at('PantryPal', 50, 45, 640),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '- Rewrote the club website in Next.js so officers can post events without asking the webmaster',
      'Caterpillar',
      'Data Science Intern, Summer 2025',
      '• Trained a gradient boosting model to predict which library books will be requested next term',
      'Accomplishments',
      '• Reviewed pull requests for a student-run open-source project and wrote contributor guidelines',
      'COMPETITIONS',
      '• Organized a hackathon for 150 students with sponsors from four local companies and a city office',
      'PantryPal',
    ]);
  });

  it('keeps a row that names a role, an award, a year or a place apart from a list that ends near the edge', async () => {
    // A list cut a name or two after a comma reads like it goes on, but the
    // row under it is the next role, award or organization, with or without
    // a glyph on the list.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Tools: Python, SQL, Airflow, dbt, Docker, Kubernetes, Terraform, AWS Lambda, Redshift, Looker', 50, 500, 736, { hasEOL: true }),
      at('Teaching Assistant, Statistics Department', 50, 190, 724, { hasEOL: true }),
      at('Tools: SolidWorks, MATLAB, LabVIEW, COMSOL, Arduino, ImageJ, Excel, Python, Simulink, KiCad', 50, 500, 712, { hasEOL: true }),
      at('Research Intern, Microfluidics Lab', 50, 160, 700, { hasEOL: true }),
      at('Technologies: React, TypeScript, Node.js, Express, PostgreSQL, Redis, Docker, GitHub Actions, Jest', 50, 500, 688, { hasEOL: true }),
      at('Finalist, Illinois Innovation Prize', 50, 160, 676, { hasEOL: true }),
      at('Tools: Python, SQL, Airflow, dbt, Docker, Terraform, AWS Lambda, Redshift, Looker, Git, Excel, Bash', 50, 500, 664, { hasEOL: true }),
      at('Campus Bus Tracker, HackIllinois 2025', 50, 170, 652, { hasEOL: true }),
      at('Skills used: SolidWorks, MATLAB, LabVIEW, COMSOL, Arduino, ImageJ, Simulink, KiCad, Altium, Git', 50, 500, 640, { hasEOL: true }),
      at('Caterpillar, Peoria, IL', 50, 110, 628, { hasEOL: true }),
      at('Tech stack: PyTorch, NumPy, pandas, scikit-learn, OpenCV, CUDA, Slurm, Linux, Git, LaTeX, Jupyter', 50, 500, 616, { hasEOL: true }),
      at('Caterpillar', 50, 55, 604, { hasEOL: true }),
      at('Tools: Python, SQL, Airflow, dbt, Docker, Kubernetes, Terraform, AWS Lambda, Redshift, Tableau', 50, 500, 592, { hasEOL: true }),
      at('Quill | TypeScript, Electron', 50, 130, 580, { hasEOL: true }),
      at('Tools: SolidWorks, MATLAB, LabVIEW, COMSOL, Arduino, ImageJ, Excel, Python, Simulink, Altium', 50, 500, 568, { hasEOL: true }),
      at('Statistics Department, Teaching Assistant', 50, 190, 556, { hasEOL: true }),
      at('Tools: Python, SQL, Airflow, dbt, Docker, Kubernetes, Terraform, AWS Lambda, Redshift, Looker', 50, 500, 544, { hasEOL: true }),
      at('Presented the findings to the city council, which approved the plan', 50, 300, 532),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '- Tools: Python, SQL, Airflow, dbt, Docker, Kubernetes, Terraform, AWS Lambda, Redshift, Looker',
      'Teaching Assistant, Statistics Department',
      'Tools: SolidWorks, MATLAB, LabVIEW, COMSOL, Arduino, ImageJ, Excel, Python, Simulink, KiCad',
      'Research Intern, Microfluidics Lab',
      'Technologies: React, TypeScript, Node.js, Express, PostgreSQL, Redis, Docker, GitHub Actions, Jest',
      'Finalist, Illinois Innovation Prize',
      'Tools: Python, SQL, Airflow, dbt, Docker, Terraform, AWS Lambda, Redshift, Looker, Git, Excel, Bash',
      'Campus Bus Tracker, HackIllinois 2025',
      'Skills used: SolidWorks, MATLAB, LabVIEW, COMSOL, Arduino, ImageJ, Simulink, KiCad, Altium, Git',
      'Caterpillar, Peoria, IL',
      'Tech stack: PyTorch, NumPy, pandas, scikit-learn, OpenCV, CUDA, Slurm, Linux, Git, LaTeX, Jupyter',
      'Caterpillar',
      'Tools: Python, SQL, Airflow, dbt, Docker, Kubernetes, Terraform, AWS Lambda, Redshift, Tableau',
      'Quill | TypeScript, Electron',
      'Tools: SolidWorks, MATLAB, LabVIEW, COMSOL, Arduino, ImageJ, Excel, Python, Simulink, Altium',
      'Statistics Department, Teaching Assistant',
      'Tools: Python, SQL, Airflow, dbt, Docker, Kubernetes, Terraform, AWS Lambda, Redshift, Looker',
      'Presented the findings to the city council, which approved the plan',
    ]);
  });

  it('carries a line that ends in a preposition on only into a name that cannot open an item', async () => {
    // "rely on", "signed up for" and "log in" end their items; the role row
    // or item after them opens with an ordinary word. A name such as "NIH
    // ChestX-ray14" carries the line on, unless its row names a role.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Maintained the equipment checkout system that the photography club and two other groups rely on', 50, 500, 736, { hasEOL: true }),
      at('Research Intern, Microfluidics Lab', 50, 160, 724, { hasEOL: true }),
      at('- Set up the tutoring schedule and the waitlist form that students in the physics course signed up for', 50, 500, 712, { hasEOL: true }),
      at('Volunteer Coordinator, Eastern Illinois Foodbank - Jun 2024 - Aug 2024', 50, 330, 700, { hasEOL: true }),
      at('Built a self-service sign-in portal for the makerspace that all 300 members now use to log in', 50, 500, 688, { hasEOL: true }),
      at('Mentored two new members through their first pull requests', 50, 260, 676, { hasEOL: true }),
      at('Cleaned a shared dataset of campus energy use that two later class projects could build on', 50, 500, 664, { hasEOL: true }),
      at('NSF REU Fellow, Purdue University', 50, 160, 652, { hasEOL: true }),
      at('Kept the build scripts and the release checklist that two other student teams now rely on', 50, 500, 640, { hasEOL: true }),
      at('NVIDIA', 50, 40, 628, { hasEOL: true }),
      at('Wrote the onboarding guide for the summer research program that every new student signed up for', 50, 500, 616, { hasEOL: true }),
      at('2025 Summer Research Program, Purdue University', 50, 220, 604, { hasEOL: true }),
      at('Trained a ResNet-18 baseline on chest X-rays from the hospital and evaluated it on', 50, 500, 592, { hasEOL: true }),
      at('NIH ChestX-ray14 and a held-out split', 50, 180, 580),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '- Maintained the equipment checkout system that the photography club and two other groups rely on',
      'Research Intern, Microfluidics Lab',
      '- Set up the tutoring schedule and the waitlist form that students in the physics course signed up for',
      'Volunteer Coordinator, Eastern Illinois Foodbank - Jun 2024 - Aug 2024',
      'Built a self-service sign-in portal for the makerspace that all 300 members now use to log in',
      'Mentored two new members through their first pull requests',
      'Cleaned a shared dataset of campus energy use that two later class projects could build on',
      'NSF REU Fellow, Purdue University',
      'Kept the build scripts and the release checklist that two other student teams now rely on',
      'NVIDIA',
      'Wrote the onboarding guide for the summer research program that every new student signed up for',
      '2025 Summer Research Program, Purdue University',
      'Trained a ResNet-18 baseline on chest X-rays from the hospital and evaluated it on NIH ChestX-ray14 and a held-out split',
    ]);
    // The hint is weak, so the page must show that the name did not fit
    // without the slack that words which cannot end a line get.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Cleaned the shared dataset of campus energy use and documented every column and unit for the team', 50, 500, 712, { hasEOL: true }),
      at('Trained a ResNet-18 baseline on chest X-rays from the hospital and then evaluated it on', 50, 481, 700, { hasEOL: true }),
      at('NIH ChestX-ray14 and a held-out split', 50, 180, 688, { hasEOL: true }),
      at('Trained a ResNet-18 baseline on chest X-rays from the hospital and then evaluated it with the', 50, 481, 676, { hasEOL: true }),
      at('NIH ChestX-ray14 test split', 50, 130, 664),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Cleaned the shared dataset of campus energy use and documented every column and unit for the team',
      'Trained a ResNet-18 baseline on chest X-rays from the hospital and then evaluated it on',
      'NIH ChestX-ray14 and a held-out split',
      'Trained a ResNet-18 baseline on chest X-rays from the hospital and then evaluated it with the NIH ChestX-ray14 test split',
    ]);
    // Nor in a narrow sidebar, where a short line is as likely a list item.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Coursework in machine learning built on', 40, 150, 712, { hasEOL: true }),
      at('PyTorch', 40, 35, 700),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Coursework in machine learning built on', 'PyTorch',
    ]);
  });

  it('reads a full stop as the end of a glyph item only on a line that opens with a name', async () => {
    // These items end with a full stop, but a description sentence can
    // follow an item that lacks one: an ordinary first word ("A", "Custom")
    // opens a line of its own, an acronym or a model number goes on.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Wrote unit tests for the parser.', 50, 160, 736, { hasEOL: true }),
      at('- Added a nightly job that checks the backups.', 50, 220, 724, { hasEOL: true }),
      at('- Mapped bike lane gaps around campus with QGIS and presented the map to the facilities office', 50, 500, 712, { hasEOL: true }),
      at('A web app that shows live bus positions to about 200 students.', 50, 300, 700, { hasEOL: true }),
      at('- Designed the logger board and wrote firmware that wakes up once an hour to save battery power', 50, 500, 688, { hasEOL: true }),
      at('Custom firmware that logs soil moisture every hour on battery power.', 50, 310, 676, { hasEOL: true }),
      at('- Trained a convolutional baseline on chest X-rays from the hospital and reached a test score of 0.87', 50, 500, 664, { hasEOL: true }),
      at('AUC on a held-out split.', 50, 110, 652, { hasEOL: true }),
      at('- Drafted the budget tables and the data management plan for a successful NIH', 50, 500, 640, { hasEOL: true }),
      at('R21 application.', 50, 70, 628, { hasEOL: true }),
      at('- Led weekly stand-ups for the six-person capstone team and tracked every sprint task in', 50, 500, 616, { hasEOL: true }),
      at('Jira with the course staff.', 50, 120, 604, { hasEOL: true }),
      at('- Built the volunteer check-in kiosk that the food pantry and two shelters now rely on', 50, 500, 592, { hasEOL: true }),
      at('A web app that shows live bus positions to about 200 students.', 50, 300, 580, { hasEOL: true }),
      at('- Compared three saliency methods for the clinical team and wrote up the results for the lab manager', 50, 500, 568, { hasEOL: true }),
      at('PantryPal - React and Flask app used by 200 students.', 50, 250, 556),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '- Wrote unit tests for the parser.',
      '- Added a nightly job that checks the backups.',
      '- Mapped bike lane gaps around campus with QGIS and presented the map to the facilities office',
      'A web app that shows live bus positions to about 200 students.',
      '- Designed the logger board and wrote firmware that wakes up once an hour to save battery power',
      'Custom firmware that logs soil moisture every hour on battery power.',
      '- Trained a convolutional baseline on chest X-rays from the hospital and reached a test score of 0.87 AUC on a held-out split.',
      '- Drafted the budget tables and the data management plan for a successful NIH R21 application.',
      '- Led weekly stand-ups for the six-person capstone team and tracked every sprint task in Jira with the course staff.',
      '- Built the volunteer check-in kiosk that the food pantry and two shelters now rely on',
      'A web app that shows live bus positions to about 200 students.',
      '- Compared three saliency methods for the clinical team and wrote up the results for the lab manager',
      'PantryPal - React and Flask app used by 200 students.',
    ]);
    // Without a glyph, the full line could just as well end the item before.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Wrote unit tests for the parser.', 50, 160, 736, { hasEOL: true }),
      at('- Added a nightly job that checks the backups.', 50, 220, 724, { hasEOL: true }),
      at('Trained a convolutional baseline on chest X-rays from the hospital and reached a test score of 0.87', 50, 500, 712, { hasEOL: true }),
      at('AUC on a held-out split.', 50, 110, 700),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '- Wrote unit tests for the parser.',
      '- Added a nightly job that checks the backups.',
      'Trained a convolutional baseline on chest X-rays from the hospital and reached a test score of 0.87',
      'AUC on a held-out split.',
    ]);
  });

  it('carries a line on into a measure, an open bracket or the rest of a date range, and not into a bare count', async () => {
    // "12 students mentored…" can open an item; "12,000", "0.87" or "78%"
    // was moved down by a wrap. A count goes on after a word that takes one.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Ran gel electrophoresis and PCR for a plant genetics lab and kept the sample database consistent', 50, 500, 760, { hasEOL: true }),
      at('12 students mentored through their first research projects', 50, 260, 748, { hasEOL: true }),
      at('Summarized the answers of a county survey of commuters and presented the main findings to', 50, 500, 736, { hasEOL: true }),
      at('12 local school principals', 50, 110, 724, { hasEOL: true }),
      at('Built a pipeline that preprocesses and labels the chest X-ray images of the hospital archive, about', 50, 500, 712, { hasEOL: true }),
      at('12,000 in total', 50, 70, 700, { hasEOL: true }),
      at('Fine-tuned a multilingual BERT model on labeled tweets from the Swahili news corpus, 3,000 tweets;', 50, 500, 688, { hasEOL: true }),
      at('78% accuracy vs 71% baseline', 50, 140, 676, { hasEOL: true }),
      at('Relevant coursework: Data Structures (CS 225), Computer Architecture (CS 233), Linear Algebra (MATH', 50, 500, 664, { hasEOL: true }),
      at('257), Probability and Statistics', 50, 150, 652, { hasEOL: true }),
      at('B.S. in Computer Engineering with a minor in Statistics and Data Science, Aug 2024', 50, 500, 640, { hasEOL: true }),
      at('- May 2028', 50, 50, 628, { hasEOL: true }),
      at('Wrote the style guide and the onboarding checklist for new members of the robotics team each fall', 50, 500, 616, { hasEOL: true }),
      at('- Summer 2025 outreach: ran two coding workshops', 50, 210, 604, { hasEOL: true }),
      at('Calibrated the motion capture cameras and wrote the setup guide for new staff of the gait lab', 50, 500, 592, { hasEOL: true }),
      at('2024.09 - 2025.05 Research Assistant, Biomechanics Lab', 50, 250, 580, { hasEOL: true }),
      at('University of Illinois Urbana-Champaign, B.S. in Computer Science, expected May 2028. GPA', 50, 500, 568, { hasEOL: true }),
      at('3.7/4.0', 50, 35, 556),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Ran gel electrophoresis and PCR for a plant genetics lab and kept the sample database consistent',
      '12 students mentored through their first research projects',
      'Summarized the answers of a county survey of commuters and presented the main findings to 12 local school principals',
      'Built a pipeline that preprocesses and labels the chest X-ray images of the hospital archive, about 12,000 in total',
      'Fine-tuned a multilingual BERT model on labeled tweets from the Swahili news corpus, 3,000 tweets; 78% accuracy vs 71% baseline',
      'Relevant coursework: Data Structures (CS 225), Computer Architecture (CS 233), Linear Algebra (MATH 257), Probability and Statistics',
      'B.S. in Computer Engineering with a minor in Statistics and Data Science, Aug 2024 - May 2028',
      'Wrote the style guide and the onboarding checklist for new members of the robotics team each fall',
      '- Summer 2025 outreach: ran two coding workshops',
      'Calibrated the motion capture cameras and wrote the setup guide for new staff of the gait lab',
      '2024.09 - 2025.05 Research Assistant, Biomechanics Lab',
      'University of Illinois Urbana-Champaign, B.S. in Computer Science, expected May 2028. GPA 3.7/4.0',
    ]);
  });

  it('keeps an organization or honors row apart from a list that ends near the edge, with a glyph or none', async () => {
    // A list cut a name after a comma reads as if it could go on, but a row
    // of names under it is just as likely the next role's organization or an
    // honors line, and nothing in the words tells the two apart.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Tools: SolidWorks, MATLAB, LabVIEW, COMSOL, Arduino, ImageJ, Excel, Python, Simulink, KiCad', 50, 500, 736, { hasEOL: true }),
      at('Beckman Institute, University of Illinois', 50, 180, 724, { hasEOL: true }),
      at('Tools: SolidWorks, MATLAB, LabVIEW, COMSOL, Arduino, ImageJ, Excel, Python, Simulink, KiCad', 50, 500, 712, { hasEOL: true }),
      at('Microfluidics Lab, Beckman Institute', 50, 160, 700, { hasEOL: true }),
      at('• Skills: Python, SQL, Airflow, dbt, Docker, Kubernetes, Terraform, AWS Lambda, Jira, Confluence', 50, 500, 688, { hasEOL: true }),
      at('Caterpillar Inc., Peoria', 50, 110, 676, { hasEOL: true }),
      at('Relevant Coursework: Data Structures, Algorithms, Linear Algebra, Computer Architecture', 50, 500, 664, { hasEOL: true }),
      at("Dean's List, James Scholar", 50, 120, 652, { hasEOL: true }),
      at('- Languages: Python, Java, C++, SQL, R, Go, Rust, MATLAB, Julia, Swift, Kotlin', 50, 500, 640, { hasEOL: true }),
      at('Argonne National Laboratory, Lemont', 50, 170, 628, { hasEOL: true }),
      at('Tech stack: PyTorch, NumPy, pandas, scikit-learn, OpenCV, CUDA, Slurm, Linux, Git, LaTeX', 50, 500, 616, { hasEOL: true }),
      at('Department of Physics, UIUC', 50, 130, 604),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '- Tools: SolidWorks, MATLAB, LabVIEW, COMSOL, Arduino, ImageJ, Excel, Python, Simulink, KiCad',
      'Beckman Institute, University of Illinois',
      'Tools: SolidWorks, MATLAB, LabVIEW, COMSOL, Arduino, ImageJ, Excel, Python, Simulink, KiCad',
      'Microfluidics Lab, Beckman Institute',
      '• Skills: Python, SQL, Airflow, dbt, Docker, Kubernetes, Terraform, AWS Lambda, Jira, Confluence',
      'Caterpillar Inc., Peoria',
      'Relevant Coursework: Data Structures, Algorithms, Linear Algebra, Computer Architecture',
      "Dean's List, James Scholar",
      '- Languages: Python, Java, C++, SQL, R, Go, Rust, MATLAB, Julia, Swift, Kotlin',
      'Argonne National Laboratory, Lemont',
      'Tech stack: PyTorch, NumPy, pandas, scikit-learn, OpenCV, CUDA, Slurm, Linux, Git, LaTeX',
      'Department of Physics, UIUC',
    ]);
  });

  it('keeps an item that opens with a measure apart from a full line that takes no number at its end', async () => {
    // "40% faster builds…" and "3.92/4.00 GPA" open items of their own; with no
    // glyph, only "by", "to", "about", "GPA" or the like before the number
    // says that it is the rest of the line above.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('• Tutored three first-year students in calculus and physics during the weekly office hours every week', 50, 500, 736, { hasEOL: true }),
      at("3.92/4.00 GPA, Dean's List", 50, 120, 724, { hasEOL: true }),
      at('- Rewrote the ordering page of the campus coffee shop and moved its database to a hosted provider', 50, 500, 712, { hasEOL: true }),
      at('100% of orders now processed online', 50, 160, 700, { hasEOL: true }),
      at('Profiled the image preprocessing step of a crop disease classifier and cut its runtime in half', 50, 500, 688, { hasEOL: true }),
      at('40% faster nightly builds after moving the test suite to parallel runners', 50, 330, 676, { hasEOL: true }),
      at('Organized a hackathon for 150 students with sponsors from four local companies and ran the judging', 50, 500, 664, { hasEOL: true }),
      at('1,200 survey responses coded for a campus housing study', 50, 250, 652, { hasEOL: true }),
      at('Fine-tuned the classifier on the new labels and compared it with the old baseline on the held-out set', 50, 500, 640, { hasEOL: true }),
      at('0.92 F1 after tuning the decision threshold', 50, 190, 628, { hasEOL: true }),
      at('Rewrote the nightly image job of the crop disease classifier and cut the runtime of each run by', 50, 500, 616, { hasEOL: true }),
      at('40% after caching resized tiles', 50, 140, 604, { hasEOL: true }),
      at('- Set up the tutoring schedule and the waitlist form that students in the physics course signed up for', 50, 500, 592, { hasEOL: true }),
      at('25% fewer support tickets after the help page redesign', 50, 250, 580, { hasEOL: true }),
      at('Ran weekly code reviews for the twelve members of the robotics team and kept notes on recurring bugs;', 50, 500, 568, { hasEOL: true }),
      at('12 students mentored through their first research projects', 50, 260, 556, { hasEOL: true }),
      at('Calibrated the motion capture cameras and wrote the setup guide that the staff of the gait lab refer to', 50, 500, 544, { hasEOL: true }),
      at('2024.09 - 2025.05 Research Assistant, Biomechanics Lab', 50, 250, 532),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '• Tutored three first-year students in calculus and physics during the weekly office hours every week',
      "3.92/4.00 GPA, Dean's List",
      '- Rewrote the ordering page of the campus coffee shop and moved its database to a hosted provider',
      '100% of orders now processed online',
      'Profiled the image preprocessing step of a crop disease classifier and cut its runtime in half',
      '40% faster nightly builds after moving the test suite to parallel runners',
      'Organized a hackathon for 150 students with sponsors from four local companies and ran the judging',
      '1,200 survey responses coded for a campus housing study',
      'Fine-tuned the classifier on the new labels and compared it with the old baseline on the held-out set',
      '0.92 F1 after tuning the decision threshold',
      'Rewrote the nightly image job of the crop disease classifier and cut the runtime of each run by 40% after caching resized tiles',
      '- Set up the tutoring schedule and the waitlist form that students in the physics course signed up for',
      '25% fewer support tickets after the help page redesign',
      'Ran weekly code reviews for the twelve members of the robotics team and kept notes on recurring bugs;',
      '12 students mentored through their first research projects',
      'Calibrated the motion capture cameras and wrote the setup guide that the staff of the gait lab refer to',
      '2024.09 - 2025.05 Research Assistant, Biomechanics Lab',
    ]);
  });

  it('carries a line that ends in a preposition on into a number only where the page shows that the number did not fit', async () => {
    // "refer to" and "worked with" can end an item, and the next item can
    // open with a count or a measure ("12 students mentored…"). After such a
    // word a number is a weak hint: another line must show where the column
    // ends, and the number must not have fitted even without the slack that
    // words which cannot end a line get. Here no line shows the edge.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Research Assistant, Biomechanics Lab, Jun 2025 - Aug 2025', 50, 280, 736, { hasEOL: true }),
      at('Calibrated the motion capture cameras and wrote the setup guide that the staff of the gait lab refer to', 50, 480, 724, { hasEOL: true }),
      at('12 students mentored through their first research projects', 50, 260, 712, { hasEOL: true }),
      at('Wrote unit tests for the parser', 50, 160, 700),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Research Assistant, Biomechanics Lab, Jun 2025 - Aug 2025',
      'Calibrated the motion capture cameras and wrote the setup guide that the staff of the gait lab refer to',
      '12 students mentored through their first research projects',
      'Wrote unit tests for the parser',
    ]);
    // The role row's right-aligned date shows the edge. "40%" would have
    // fitted after "worked with", which ends 18pt short of it; after "by",
    // at the edge, it goes on.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Research Assistant, Plant Phenomics Lab', 50, 180, 736), at('Jun 2025 - Aug 2025', 460, 90, 736, { hasEOL: true }),
      at('Co-wrote the imaging protocol and the analysis notebooks with the two graduate students I worked with', 50, 482, 724, { hasEOL: true }),
      at('40% faster nightly builds after moving the test suite to parallel runners', 50, 330, 712, { hasEOL: true }),
      at('Rewrote the nightly image preprocessing job of the crop classifier and cut the runtime of each run by', 50, 500, 700, { hasEOL: true }),
      at('40% after caching resized tiles', 50, 140, 688),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Research Assistant, Plant Phenomics Lab\tJun 2025 - Aug 2025',
      'Co-wrote the imaging protocol and the analysis notebooks with the two graduate students I worked with',
      '40% faster nightly builds after moving the test suite to parallel runners',
      'Rewrote the nightly image preprocessing job of the crop classifier and cut the runtime of each run by 40% after caching resized tiles',
    ]);
  });

  it('takes a number after the words that take one, and a measure after a semicolon', () => {
    for (const word of ['about', 'around', 'nearly', 'almost', 'approximately', 'roughly', 'reaching', 'reached', 'GPA']) {
      expect(wrapEvidence(`Cut the runtime of the nightly job ${word}`, '40% after caching resized tiles')).toBe(true);
      expect(wrapEvidence(`Cut the runtime of the nightly job ${word}`, '12 students in the course')).toBe(true);
      expect(wrapEvidence(`Labeled the chest X-ray images of the archive, ${word}`, '12,000, most of them by hand')).toBe(true);
    }
    expect(wrapEvidence('Raised the test accuracy of the classifier by 12', '% over the baseline')).toBe(true);
    // A preposition among those words can also end an item ("…the staff of
    // the gait lab refer to"), so a number after it is only a weak hint.
    for (const word of ['by', 'to', 'from', 'over', 'under', 'at', 'with']) {
      expect(wrapEvidence(`Cut the runtime of the nightly job ${word}`, '40% after caching resized tiles')).toBe(false);
      expect(weakWrapEvidence(`Cut the runtime of the nightly job ${word}`, '40% after caching resized tiles', false)).toBe(true);
    }
    // "rely on", "log in", "signed up for" can end an item; a year opens a row.
    for (const word of ['on', 'in', 'for', 'into', 'across', 'week', 'gpa']) {
      expect(wrapEvidence(`Cut the runtime of the nightly job ${word}`, '40% after caching resized tiles')).toBe(false);
      expect(weakWrapEvidence(`Cut the runtime of the nightly job ${word}`, '40% after caching resized tiles', false)).toBe(false);
    }
    expect(wrapEvidence('Presented the poster to', '2025 Undergraduate Research Symposium judges')).toBe(false);
    expect(wrapEvidence('Labeled 3,000 tweets;', '78% accuracy vs 71% baseline')).toBe(true);
    expect(wrapEvidence('Labeled 3,000 tweets;', '0.91 F1 on the test split')).toBe(true);
    expect(wrapEvidence('Labeled 3,000 tweets;', '12 students mentored')).toBe(false);
    expect(wrapEvidence('Labeled 3,000 tweets', '78% accuracy vs 71% baseline')).toBe(false);
  });

  it('lets a weak hint join a line only where the page shows where its column ends', async () => {
    // In a column where no line wraps, the longest line only looks full: the
    // edge may lie further right. A role row's right-aligned date, a line
    // that the words carry on, or two other lines that end exactly where
    // this one does (justified text) show the edge.
    const page = (...others: unknown[]) => pdfOf([
      ...others,
      at('Kept the build scripts and the release checklist that two other teams now rely on', 50, 400, 712, { hasEOL: true }),
      at('NVIDIA Jetson boards in the robotics lab', 50, 170, 700, { hasEOL: true }),
      at('Wrote unit tests for the parser', 50, 160, 688),
    ]);
    const kept = ['Kept the build scripts and the release checklist that two other teams now rely on',
      'NVIDIA Jetson boards in the robotics lab'];
    const joined = [kept.join(' ')];
    const cases: Array<[unknown[], string[], string[]]> = [
      [[], [], kept],
      [[at('Mentored three students in the robotics club', 50, 396, 724, { hasEOL: true })],
        ['Mentored three students in the robotics club'], kept],
      // One other line that ends there can be a coincidence of ragged text.
      [[at('Mentored three students in the robotics club', 50, 400.2, 724, { hasEOL: true })],
        ['Mentored three students in the robotics club'], kept],
      [[at('Organized the weekly reading group for new members', 50, 399.8, 736, { hasEOL: true }),
        at('Mentored three students in the robotics club', 50, 400.2, 724, { hasEOL: true })],
      ['Organized the weekly reading group for new members', 'Mentored three students in the robotics club'], joined],
      // The same line printed twice says nothing about the edge, and neither
      // does a line that cannot wrap (a long link).
      [[at('Kept the build scripts and the release checklist that two other teams now rely on', 50, 400, 724, { hasEOL: true })],
        ['Kept the build scripts and the release checklist that two other teams now rely on'], kept],
      [[at('github.com/jordan-lee/robotics-lab-build-scripts-and-release-checklists', 50, 400, 724, { hasEOL: true })],
        ['github.com/jordan-lee/robotics-lab-build-scripts-and-release-checklists'], kept],
      [[at('Research Intern, Robotics Lab', 50, 140, 724), at('Jun 2025 - Aug 2025', 360, 90, 724, { hasEOL: true })],
        ['Research Intern, Robotics Lab\tJun 2025 - Aug 2025'], joined],
      // A right-aligned field ends within about a word of the edge; a label
      // column's gap does not bring its row anywhere near it.
      [[at('Research Intern, Robotics Lab', 50, 140, 724), at('Jun 2025 - Aug 2025', 350, 90, 724, { hasEOL: true })],
        ['Research Intern, Robotics Lab\tJun 2025 - Aug 2025'], joined],
      [[at('Languages', 50, 45, 724), at('Python, SQL, Git', 160, 80, 724, { hasEOL: true })],
        ['Languages\tPython, SQL, Git'], kept],
      [[at('Ported the lab inventory spreadsheet to a small web app and', 50, 380, 736, { hasEOL: true }),
        at('trained the staff to use it', 50, 120, 724, { hasEOL: true })],
      ['Ported the lab inventory spreadsheet to a small web app and trained the staff to use it'], joined],
      // Words that carry a line on show the edge only where the line also ran
      // out of room: these end far short of it.
      [[at('Mentored three first-year students,', 50, 160, 724, { hasEOL: true })], ['Mentored three first-year students,'], kept],
      [[at('Ran the robotics club workshops and', 50, 170, 724, { hasEOL: true })], ['Ran the robotics club workshops and'], kept],
    ];
    for (const [others, head, lines] of cases) {
      mockGetDocument.mockReturnValue({ promise: Promise.resolve(page(...others)) });
      expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([...head, ...lines, 'Wrote unit tests for the parser']);
    }
    // A line in another column shows that column's edge, not this one's.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Machine learning with PyTorch and', 40, 150, 736, { hasEOL: true }),
      at('scikit-learn on lab data', 40, 100, 724, { hasEOL: true }),
      at('Kept the build scripts and the release checklist that two other teams now rely on', 220, 330, 736, { hasEOL: true }),
      at('NVIDIA Jetson boards in the robotics lab', 220, 170, 724),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Machine learning with PyTorch and scikit-learn on lab data', ...kept,
    ]);
    // A line that only a weak hint joins does not show the edge to others:
    // the second item ends 2pt short of the three justified lines.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Organized the weekly reading group and kept the shared notes for new members', 50, 400, 748, { hasEOL: true }),
      at('Mentored three students in the robotics club and reviewed their weekly notes', 50, 400, 736, { hasEOL: true }),
      at('Wrote unit tests for the parser', 50, 160, 724, { hasEOL: true }),
      at('Built the badge scanner that the volunteers at the food pantry use whenever they check in', 50, 398, 712, { hasEOL: true }),
      at('GitHub Actions workflow for the team repository', 50, 200, 700, { hasEOL: true }),
      at('Kept the build scripts and the release checklist that two other teams now rely on', 50, 400, 688, { hasEOL: true }),
      at('NVIDIA Jetson boards in the robotics lab', 50, 170, 676),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Organized the weekly reading group and kept the shared notes for new members',
      'Mentored three students in the robotics club and reviewed their weekly notes',
      'Wrote unit tests for the parser',
      'Built the badge scanner that the volunteers at the food pantry use whenever they check in',
      'GitHub Actions workflow for the team repository',
      joined[0],
    ]);
  });

  it('carries a line on into a lowercase first word only where another line shows the column edge', async () => {
    // A tool written in lowercase can open an item ("pandas pipeline…",
    // "scikit-learn baseline…"). In a column where no line wraps, the
    // longest items only look full, and joins of this kind do not show the
    // edge to each other.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Research Assistant, Plant Phenomics Lab, Jun 2025 - Aug 2025', 50, 300, 736, { hasEOL: true }),
      at('Prototyped a wearable gait sensor and streamed its data to a phone', 50, 310, 724, { hasEOL: true }),
      at('pandas pipeline that cleans the sensor logs every night', 50, 250, 712, { hasEOL: true }),
      at('Wrote unit tests for the parser', 50, 160, 700, { hasEOL: true }),
      at('Kept the lab inventory in a shared spreadsheet for the team', 50, 290, 688, { hasEOL: true }),
      at('scikit-learn baseline for the plant imaging study', 50, 230, 676),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Research Assistant, Plant Phenomics Lab, Jun 2025 - Aug 2025',
      'Prototyped a wearable gait sensor and streamed its data to a phone',
      'pandas pipeline that cleans the sensor logs every night',
      'Wrote unit tests for the parser',
      'Kept the lab inventory in a shared spreadsheet for the team',
      'scikit-learn baseline for the plant imaging study',
    ]);
    // A right-aligned date shows the edge, and so does a line that "and"
    // carries on; the next line's lowercase words then go on.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Research Assistant, Plant Phenomics Lab', 50, 180, 736), at('Jun 2025 - Aug 2025', 460, 90, 736, { hasEOL: true }),
      at('Prototyped a wearable gait sensor with an IMU and streamed the readings to a phone app every', 50, 500, 724, { hasEOL: true }),
      at('night over the campus network', 50, 140, 712, { hasEOL: true }),
      at('pandas pipeline that cleans the sensor logs every night', 50, 250, 700),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Research Assistant, Plant Phenomics Lab\tJun 2025 - Aug 2025',
      'Prototyped a wearable gait sensor with an IMU and streamed the readings to a phone app every night over the campus network',
      'pandas pipeline that cleans the sensor logs every night',
    ]);
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Ported the lab inventory spreadsheet to a small web app and', 50, 380, 736, { hasEOL: true }),
      at('trained the staff to use it', 50, 120, 724, { hasEOL: true }),
      at('Prototyped a wearable gait sensor and streamed its readings to a phone', 50, 375, 712, { hasEOL: true }),
      at('every night over the campus network', 50, 160, 700, { hasEOL: true }),
      at('Wrote unit tests for the parser', 50, 160, 688),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Ported the lab inventory spreadsheet to a small web app and trained the staff to use it',
      'Prototyped a wearable gait sensor and streamed its readings to a phone every night over the campus network',
      'Wrote unit tests for the parser',
    ]);
    // A line that hangs under a glyph item's text continues it: the next item
    // would open at the glyph. A flat list shows no such thing, so with
    // nothing else on the page to show the edge, its line stays apart.
    const glyphItem = (glyph: string, indent: number) => pdfOf([
      at(`${glyph} Prototyped a wearable gait sensor and streamed its readings to a phone over`, 50, 360, 736, { hasEOL: true }),
      at('the campus network every night', 50 + indent, 140, 724, { hasEOL: true }),
      at(`${glyph} Wrote unit tests for the parser`, 50, 160, 712),
    ]);
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(glyphItem('•', 9)) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '• Prototyped a wearable gait sensor and streamed its readings to a phone over the campus network every night',
      '• Wrote unit tests for the parser',
    ]);
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(glyphItem('-', 0)) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '- Prototyped a wearable gait sensor and streamed its readings to a phone over',
      'the campus network every night',
      '- Wrote unit tests for the parser',
    ]);
    // A line hangs under the item right above it: not under a nested item's
    // parent, and not after a line that does not hang.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('• Built the volunteer scheduling tool for the food pantry and kept it running', 50, 360, 736, { hasEOL: true }),
      at('◦ Wrote a calendar sync that the coordinators use to check open slots on their', 59, 345, 724, { hasEOL: true }),
      at('phones before each shift', 59, 110, 712, { hasEOL: true }),
      at('• Wrote unit tests for the parser', 50, 160, 700, { hasEOL: true }),
      at('Kept the lab inventory and the order history in a shared spreadsheet', 50, 355, 688, { hasEOL: true }),
      at('pandas pipeline that cleans the sensor logs every night', 59, 250, 676),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '• Built the volunteer scheduling tool for the food pantry and kept it running',
      '◦ Wrote a calendar sync that the coordinators use to check open slots on their',
      'phones before each shift',
      '• Wrote unit tests for the parser',
      'Kept the lab inventory and the order history in a shared spreadsheet',
      'pandas pipeline that cleans the sensor logs every night',
    ]);
  });

  it('carries a line that ends in a preposition on into a name only when lowercase words follow it', async () => {
    // "GitHub Campus Expert Program" and "IBM Research" are rows of names: an
    // organization or a program under the item, not the rest of its sentence.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Built the badge scanner that the volunteers at the food pantry use whenever they check in', 50, 500, 724, { hasEOL: true }),
      at('GitHub Campus Expert Program', 50, 130, 712, { hasEOL: true }),
      at('- Kept the shuttle schedule and the route maps that the dispatch coordinators and drivers rely on', 50, 500, 700, { hasEOL: true }),
      at('IBM Research', 50, 60, 688, { hasEOL: true }),
      at('- Trained a ResNet-18 baseline on chest X-rays from the hospital and then evaluated it on', 50, 500, 676, { hasEOL: true }),
      at('NIH ChestX-ray14 and a held-out split', 50, 180, 664),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '- Built the badge scanner that the volunteers at the food pantry use whenever they check in',
      'GitHub Campus Expert Program',
      '- Kept the shuttle schedule and the route maps that the dispatch coordinators and drivers rely on',
      'IBM Research',
      '- Trained a ResNet-18 baseline on chest X-rays from the hospital and then evaluated it on NIH ChestX-ray14 and a held-out split',
    ]);
  });

  it('keeps a row of names joined by small words apart from a line that ends in a preposition', async () => {
    // "of", "at", "for", "the" and the like join the words of a name ("UIUC
    // Department of Physics"); only another lowercase word reads as the rest
    // of a sentence ("NIH ChestX-ray14 and a held-out split").
    const item = '- Built the badge scanner that the volunteers at the food pantry use whenever they check in';
    // The role row's right-aligned date shows where the column ends.
    const page = (row: string) => pdfOf([
      at('Research Intern, Robotics Lab', 50, 140, 736), at('Jun 2025 - Aug 2025', 460, 90, 736, { hasEOL: true }),
      at('- Kept the shuttle schedule and the route maps that the dispatch coordinators and drivers rely on', 50, 500, 724, { hasEOL: true }),
      at(item, 50, 500, 712, { hasEOL: true }),
      at(row, 50, 160, 700),
    ]);
    for (const row of ['UIUC Department of Physics', 'NCSA at the University of Illinois', 'NSF Center for Digital Agriculture',
      'IEEE Robotics and Automation Society', 'NIH National Institute on Aging', 'REU Program in Applied Mathematics',
      'UNAM Facultad de Ciencias', 'UdelaR Universidad de la República']) {
      mockGetDocument.mockReturnValue({ promise: Promise.resolve(page(row)) });
      expect((await parseResumePDF(fakeFile())).raw_text.split('\n').slice(2)).toEqual([item, row]);
    }
    for (const row of ['NIH ChestX-ray14 and a held-out split', 'NIH ChestX-ray14 labels', 'ImageNet and a held-out split']) {
      mockGetDocument.mockReturnValue({ promise: Promise.resolve(page(row)) });
      expect((await parseResumePDF(fakeFile())).raw_text.split('\n').slice(2)).toEqual([`${item} ${row}`]);
    }
  });

  it('reads a full stop as the end of a glyph item after an acronym only where a measure comes before it', async () => {
    // "…a test score of 0.87" / "AUC on a held-out split." is a score and its
    // metric. After an item that lacks its period, "NASA outreach day…" or
    // "IEEE paper on…" is a line of its own.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Wrote unit tests for the parser.', 50, 160, 736, { hasEOL: true }),
      at('- Added a nightly job that checks the backups.', 50, 220, 724, { hasEOL: true }),
      at('- Mapped bike lane gaps around campus with QGIS and presented the map to the facilities office', 50, 500, 712, { hasEOL: true }),
      at('NASA outreach day for local middle schools.', 50, 200, 700, { hasEOL: true }),
      at('- Built the bike map site, cut its load time by 40% and shared the survey form with the council', 50, 500, 688, { hasEOL: true }),
      at('IEEE paper on the bike map accepted at a regional workshop.', 50, 270, 676, { hasEOL: true }),
      at('- Trained a convolutional baseline on chest X-rays from the hospital and reached a test score of 0.87', 50, 500, 664, { hasEOL: true }),
      at('AUC on a held-out split.', 50, 110, 652),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '- Wrote unit tests for the parser.',
      '- Added a nightly job that checks the backups.',
      '- Mapped bike lane gaps around campus with QGIS and presented the map to the facilities office',
      'NASA outreach day for local middle schools.',
      '- Built the bike map site, cut its load time by 40% and shared the survey form with the council',
      'IEEE paper on the bike map accepted at a regional workshop.',
      '- Trained a convolutional baseline on chest X-rays from the hospital and reached a test score of 0.87 AUC on a held-out split.',
    ]);
  });

  it('reads a full stop as the end of a glyph item after an acronym or a model number, not after a product name', async () => {
    // On a page whose glyph items end with a full stop, "AUC on a held-out
    // split." finishes the item that lacks one; "PantryPal is an inventory
    // tracker…" is a description of its own that opens with the product.
    // The role row's right-aligned date shows where the column ends.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Research Intern, Robotics Lab', 50, 140, 748), at('Jun 2025 - Aug 2025', 460, 90, 748, { hasEOL: true }),
      at('- Wrote unit tests for the parser.', 50, 160, 736, { hasEOL: true }),
      at('- Added a nightly job that checks the backups.', 50, 220, 724, { hasEOL: true }),
      at('- Mapped bike lane gaps around campus with QGIS and presented the map to the facilities office', 50, 500, 712, { hasEOL: true }),
      at('PantryPal is an inventory tracker for the campus food pantry.', 50, 290, 700, { hasEOL: true }),
      at('- Trained a convolutional baseline on chest X-rays from the hospital and reached a test score of 0.87', 50, 500, 688, { hasEOL: true }),
      at('AUC on a held-out split.', 50, 110, 676),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Research Intern, Robotics Lab\tJun 2025 - Aug 2025',
      '- Wrote unit tests for the parser.',
      '- Added a nightly job that checks the backups.',
      '- Mapped bike lane gaps around campus with QGIS and presented the map to the facilities office',
      'PantryPal is an inventory tracker for the campus food pantry.',
      '- Trained a convolutional baseline on chest X-rays from the hospital and reached a test score of 0.87 AUC on a held-out split.',
    ]);
  });

  it('keeps a space between runs painted out of order on one line', async () => {
    // A right-floated date printed before its title: PDF.js jumps back on
    // the same baseline without a line end.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Jan 2026 - Present', 491.5, 84.5, 700), at('Research Assistant, Health Imaging Lab', 36, 177.8, 700, { hasEOL: true }),
      at('Built a PyTorch pipeline for chest X-ray images.', 50, 210, 688),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Jan 2026 - Present Research Assistant, Health Imaging Lab',
      'Built a PyTorch pipeline for chest X-ray images.',
    ]);
  });

  it('rejoins the hanging lines of a bullet whose glyph is printed in the same run as its text', async () => {
    // "• " takes about one em; the wrapped lines hang at the text, 1.2 em in.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('• Characterized perovskite thin films with X-ray diffraction and UV-Vis', 50, 500, 700, { hasEOL: true }),
      at('spectroscopy for a funded project', 62, 160, 688, { hasEOL: true }),
      at('• Trained a U-Net model', 50, 110, 676),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '• Characterized perovskite thin films with X-ray diffraction and UV-Vis spectroscopy for a funded project',
      '• Trained a U-Net model',
    ]);
  });

  it('rejoins a widowed last word even when it is a section title', async () => {
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Assisted a PhD student with literature reviews and data collection for autonomous driving', 50, 500, 700, { hasEOL: true }),
      at('research', 50, 40, 688, { hasEOL: true }),
      at('- Wrote SQL jobs', 50, 80, 676),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '- Assisted a PhD student with literature reviews and data collection for autonomous driving research',
      '- Wrote SQL jobs',
    ]);
  });

  it('keeps apart two lines that a paragraph gap separates', async () => {
    // The role row's right-aligned date shows where the column ends.
    const full = 'the first paragraph wraps here and its words run to the edge';
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Research Intern, Robotics Lab', 50, 140, 712), at('Jun 2025 - Aug 2025', 460, 90, 712, { hasEOL: true }),
      at(`Summary: ${full}`, 50, 500, 700, { hasEOL: true }),
      at(full, 50, 500, 688, { hasEOL: true }),
      at('and this line opens the next paragraph', 50, 180, 670),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Research Intern, Robotics Lab\tJun 2025 - Aug 2025',
      `Summary: ${full} ${full}`,
      'and this line opens the next paragraph',
    ]);
  });

  it('never continues a line that ends a sentence, even into a lowercase line', async () => {
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Reached 0.87 AUC on a held-out split of the chest X-ray images.', 50, 500, 700, { hasEOL: true }),
      at('iOS app for tracking lab inventory', 50, 160, 688),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Reached 0.87 AUC on a held-out split of the chest X-ray images.',
      'iOS app for tracking lab inventory',
    ]);
  });

  it('separates two runs on one line by a tab when a column gap lies between them', async () => {
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Research Intern, Biomechanics Lab', 50, 160), at('Jun 2025 - Aug 2025', 450, 90),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text).toBe('Research Intern, Biomechanics Lab\tJun 2025 - Aug 2025');
  });
});

describe('positioned CJK text', () => {
  it('keeps a short Chinese title apart from a full item, and joins a lone character or a Latin word that ends the item', async () => {
    // A two-character line can be a section title; a single character
    // cannot stand alone. In Chinese text a capitalized Latin word says
    // nothing about where an item starts.
    const run = (str: string, y: number, width = 500, hasEOL = true) => ({
      str, width, height: 10, transform: [10, 0, 0, 10, 50, y], fontName: 'f1', dir: 'ltr', hasEOL,
    });
    mockGetDocument.mockReturnValue({ promise: Promise.resolve({
      numPages: 1, destroy: async () => {},
      getPage: async () => ({ cleanup: () => {}, getTextContent: async () => ({ items: [
        run('• 维护实验室网站。', 736, 90),
        run('• 整理实验数据。', 724, 80),
        run('• 基于深度学习的医学影像分割系统：使用 PyTorch 训练 U-Net 模型，在公开数据集上将', 712),
        run('Dice 系数从 0.81 提升到 0.88。', 700, 150),
        run('• 负责后端接口设计与数据库建模，使用 Flask 与 PostgreSQL 实现用户、商品与订单模块并编写部署文档', 688),
        run('荣誉', 676, 20),
        run('• 在暑期实习中重写夜间数据处理任务，运行时间从四十分钟降到九分', 664),
        run('钟', 652, 10, false),
      ] as never }) }),
    } as MockPdf) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '• 维护实验室网站。',
      '• 整理实验数据。',
      '• 基于深度学习的医学影像分割系统：使用 PyTorch 训练 U-Net 模型，在公开数据集上将 Dice 系数从 0.81 提升到 0.88。',
      '• 负责后端接口设计与数据库建模，使用 Flask 与 PostgreSQL 实现用户、商品与订单模块并编写部署文档',
      '荣誉',
      '• 在暑期实习中重写夜间数据处理任务，运行时间从四十分钟降到九分钟',
    ]);
  });

  it('joins a wrapped Chinese line without a space, across font subsets, and reads Kangxi radicals as ideographs', async () => {
    const run = (str: string, x: number, width: number, y: number, fontName: string, hasEOL = false) => ({
      str, width, height: 10, transform: [10, 0, 0, 10, x, y], fontName, dir: 'ltr', hasEOL,
    });
    mockGetDocument.mockReturnValue({ promise: Promise.resolve({
      numPages: 1, destroy: async () => {},
      getPage: async () => ({ cleanup: () => {}, getTextContent: async () => ({ items: [
        // The first item shows that this list ends its items with 。, and
        // its wrap after "，" shows where the column ends.
        run('- 维护实验室网站并整理每周组会的实验记录，', 50, 500, 728, 'f1', true),
        run('撰写组会报告。', 50, 70, 714, 'f1', true),
        run('- 基于深度学习的医学影像', 50, 120, 700, 'f1'), run('分割系统：使⽤', 170, 380, 700, 'f2', true),
        run('模型复现', 50, 40, 686, 'f3'), run('⽂档。', 90, 30, 686, 'f2'),
      ] as never }) }),
    } as MockPdf) });
    expect((await parseResumePDF(fakeFile())).raw_text)
      .toBe('- 维护实验室网站并整理每周组会的实验记录，撰写组会报告。\n- 基于深度学习的医学影像分割系统：使用模型复现文档。');
  });

  it('keeps Chinese items that end without 。 apart, under a glyph or none', async () => {
    // Chinese wraps between any two characters and has no capitals, so a
    // line that fills the column says nothing about where the next one
    // belongs: the longest item would otherwise absorb the next.
    const run = (str: string, y: number, width = 500, hasEOL = true) => ({
      str, width, height: 10, transform: [10, 0, 0, 10, 50, y], fontName: 'f1', dir: 'ltr', hasEOL,
    });
    mockGetDocument.mockReturnValue({ promise: Promise.resolve({
      numPages: 1, destroy: async () => {},
      getPage: async () => ({ cleanup: () => {}, getTextContent: async () => ({ items: [
        run('组织校园编程工作坊，面向一百五十名同学讲授 Python 基础', 712),
        run('参与医学影像标注项目，按照临床医生制定的规范标注四千张图像', 700),
        run('• 负责后端接口设计与数据库建模，实现用户、商品与订单模块', 688),
        run('本科生研究助理，生物力学实验室 2024.09 - 2025.05', 676, 260),
        run('• 协助导师完成文献综述并整理实验数据，撰写组会报告', 664),
        run('校园活动', 652, 40, false),
      ] as never }) }),
    } as MockPdf) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '组织校园编程工作坊，面向一百五十名同学讲授 Python 基础',
      '参与医学影像标注项目，按照临床医生制定的规范标注四千张图像',
      '• 负责后端接口设计与数据库建模，实现用户、商品与订单模块',
      '本科生研究助理，生物力学实验室 2024.09 - 2025.05',
      '• 协助导师完成文献综述并整理实验数据，撰写组会报告',
      '校园活动',
    ]);
  });
});

describe('wrap joins that depend on the characters at the break', () => {
  const line = (str: string, width: number, y: number, hasEOL = true) => ({
    str, width, height: 10, transform: [10, 0, 0, 10, 50, y], fontName: 'f1', dir: 'ltr', hasEOL,
  });
  const parse = async (items: unknown[]) => {
    mockGetDocument.mockReturnValue({ promise: Promise.resolve({
      numPages: 1, destroy: async () => {},
      getPage: async () => ({ cleanup: () => {}, getTextContent: async () => ({ items: items as never }) }),
    } as MockPdf) });
    return (await parseResumePDF(fakeFile())).raw_text;
  };

  it('rejoins a hyphen break before a number without a space', async () => {
    expect(await parse([line('- Trained a baseline convolutional model called ResNet-', 500, 700), line('18 on chest X-rays.', 90, 688, false)]))
      .toBe('- Trained a baseline convolutional model called ResNet-18 on chest X-rays.');
  });

  it('joins a Chinese wrap after full-width punctuation without a space, and stops at a Chinese full stop', async () => {
    expect(await parse([line('负责后端接口设计与数据库建模，', 500, 700), line('并编写部署文档。', 80, 688), line('校园二手交易平台', 80, 676, false)]))
      .toBe('负责后端接口设计与数据库建模，并编写部署文档。\n校园二手交易平台');
  });
});
