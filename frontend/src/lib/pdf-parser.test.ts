import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

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
