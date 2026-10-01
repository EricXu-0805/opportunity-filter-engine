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
import { MAX_RESUME_TEXT_CHARACTERS } from './resume-input';

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
  it.each(['resume-ce2.pdf', 'resume-tr04.pdf', 'resume-renovate.pdf'])(
    '%s reads back line for line as the résumé text it was printed from', async (name) => {
      expect(await parseFixture(name)).toBe(PERSONA);
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
      'Relevant coursework: Signals and Systems, Biomedical Imaging, Fluid Mechanics, Differential Equations',
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
    // alone would read the next item as the rest of the line.
    const roles = JSON.parse(readFileSync(join(FIXTURES, 'noperiod-roles.json'), 'utf8')) as Array<[string, string, string[]]>;
    const paragraphs = readFileSync(join(FIXTURES, 'noperiod-paragraphs.txt'), 'utf8').trimEnd().split('\n');
    expect((await parseFixture('resume-noperiod.pdf')).split('\n')).toEqual([
      'Jordan Avery Lee',
      'jordan.lee.test@example.com | (217) 555-0142 | Urbana, IL',
      'EXPERIENCE',
      ...roles.flatMap(([title, dates, bullets]) => [`${title}\t${dates}`, ...bullets]),
      'SKILLS',
      'Python, PyTorch, SQL, C++, Git, Linux, pandas, scikit-learn',
      ...paragraphs,
    ]);
  });

  it('keeps apart the next item, role row, title or sentence that a nearly full last line could absorb', async () => {
    // Every item ends within about one word of the column edge, so the next
    // line's first word "could not have fitted" on any of them: "• " items
    // followed by same-font rows, a title, a project row and a sentence;
    // list items that end in ", SQL", ", IL", "C++", ";" or ", Node.js";
    // and Chinese items with no final 。, under a glyph or none.
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

  it('never joins a line into a bullet, a heading or a line in another font', async () => {
    const wide = 'x '.repeat(40).trim();
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at(wide, 50, 500, 700, { hasEOL: true }), at('- next bullet', 50, 60, 688, { hasEOL: true }),
      at(wide, 50, 500, 676, { hasEOL: true }), at('EXPERIENCE', 50, 60, 664, { hasEOL: true }),
      at(wide, 50, 500, 652, { hasEOL: true }), at('bold words', 50, 50, 640, { fontName: 'f2' }),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      wide, '- next bullet', wide, 'EXPERIENCE', wide, 'bold words',
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

  it('still joins a capitalized word that wraps inside a glyph bullet, after a word that goes on, inside a list, or alone', async () => {
    // The first item shows that this list ends its items with a full stop.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Wrote unit tests for the parser.', 50, 160, 712, { hasEOL: true }),
      at('- Trained a baseline that reached 0.87', 50, 500, 700, { hasEOL: true }),
      at('AUC on a held-out split.', 50, 110, 688, { hasEOL: true }),
      at('Compared saliency maps computed with', 50, 500, 676, { hasEOL: true }),
      at('Grad-CAM on chest X-rays.', 50, 120, 664, { hasEOL: true }),
      at('Coursework: Signals and Systems, Biomedical', 50, 500, 652, { hasEOL: true }),
      at('Imaging, Fluid Mechanics', 50, 120, 640, { hasEOL: true }),
      at('Automated the calibration log with a shared Google', 50, 500, 628, { hasEOL: true }),
      at('Sheet', 50, 25, 616),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      '- Wrote unit tests for the parser.',
      '- Trained a baseline that reached 0.87 AUC on a held-out split.',
      'Compared saliency maps computed with Grad-CAM on chest X-rays.',
      'Coursework: Signals and Systems, Biomedical Imaging, Fluid Mechanics',
      'Automated the calibration log with a shared Google Sheet',
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

  it('reads a full stop on the next line as the end of a glyph item only where glyph items end with one', async () => {
    // One-line items here end with a full stop, so a capitalized line that
    // ends one finishes the item before it, unless it is a row of its own.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('- Wrote unit tests for the parser.', 50, 160, 712, { hasEOL: true }),
      at('- Trained a baseline that reached 0.87', 50, 500, 700, { hasEOL: true }),
      at('AUC on a held-out split.', 50, 110, 688, { hasEOL: true }),
      at('- Compared three saliency methods for the clinical team and the lab manager', 50, 500, 676, { hasEOL: true }),
      at('Campus Bus Tracker - React and Flask web app used by 200 students.', 50, 300, 664),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
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
    // Nor do role rows dated without a separator.
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at('Research Intern, Biomechanics Lab, Summer 2025', 50, 220, 724, { hasEOL: true }),
      at('- Wrote a calibration script.', 50, 130, 712, { hasEOL: true }),
      at('- Tested the script on twenty recordings.', 50, 190, 700, { hasEOL: true }),
      at('Teaching Assistant, Statistics Department, 2024', 50, 230, 688, { hasEOL: true }),
      at('- Trained a baseline that reached 0.87', 50, 500, 676, { hasEOL: true }),
      at('AUC on a held-out split.', 50, 110, 664),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
      'Research Intern, Biomechanics Lab, Summer 2025',
      '- Wrote a calibration script.',
      '- Tested the script on twenty recordings.',
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

  it('still joins a line after a lone plus, and a list that wraps inside a name', async () => {
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
      'Skills: Python, MATLAB, NumPy, SolidWorks, Power BI, Tableau, Excel',
      'Relevant coursework: Introduction to Computer Science, Data Structures and Algorithms, Discrete Mathematics',
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
    const full = 'the first paragraph wraps here and its words run to the edge';
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(pdfOf([
      at(`Summary: ${full}`, 50, 500, 700, { hasEOL: true }),
      at(full, 50, 500, 688, { hasEOL: true }),
      at('and this line opens the next paragraph', 50, 180, 670),
    ])) });
    expect((await parseResumePDF(fakeFile())).raw_text.split('\n')).toEqual([
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
  it('joins a wrapped Chinese line without a space, across font subsets, and reads Kangxi radicals as ideographs', async () => {
    const run = (str: string, x: number, width: number, y: number, fontName: string, hasEOL = false) => ({
      str, width, height: 10, transform: [10, 0, 0, 10, x, y], fontName, dir: 'ltr', hasEOL,
    });
    mockGetDocument.mockReturnValue({ promise: Promise.resolve({
      numPages: 1, destroy: async () => {},
      getPage: async () => ({ cleanup: () => {}, getTextContent: async () => ({ items: [
        // The first item shows that this list ends its items with 。.
        run('- 维护实验室网站。', 50, 90, 714, 'f1', true),
        run('- 基于深度学习的医学影像', 50, 120, 700, 'f1'), run('分割系统：使⽤', 170, 380, 700, 'f2', true),
        run('模型复现', 50, 40, 686, 'f3'), run('⽂档。', 90, 30, 686, 'f2'),
      ] as never }) }),
    } as MockPdf) });
    expect((await parseResumePDF(fakeFile())).raw_text).toBe('- 维护实验室网站。\n- 基于深度学习的医学影像分割系统：使用模型复现文档。');
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
