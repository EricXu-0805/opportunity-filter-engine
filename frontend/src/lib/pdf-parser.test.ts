import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const globalWorkerOptions = { workerSrc: '' };
const mockGetDocument = vi.fn<(opts: { data: ArrayBuffer }) => { promise: Promise<MockPdf> }>();

vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: globalWorkerOptions,
  getDocument: (opts: { data: ArrayBuffer }) => mockGetDocument(opts),
}));

import { parseResumePDF } from './pdf-parser';

type MockPdf = {
  numPages: number;
  getPage: (n: number) => Promise<{ getTextContent: () => Promise<{ items: Array<{ str: string }> }> }>;
};

function fakePdf(pages: string[]): MockPdf {
  return {
    numPages: pages.length,
    getPage: async (n: number) => ({
      getTextContent: async () => ({
        items: (pages[n - 1] ?? '').split(' ').map((str) => ({ str })),
      }),
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
    expect(res.experience_level).toBe('beginner');
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

describe('parseResumePDF — experience-level inference', () => {
  it('returns "strong" when 2+ strong keywords appear', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['I led the team and architected the solution. Python.'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.experience_level).toBe('strong');
  });

  it('returns "some" when 2+ "some" keywords appear and no strong markers', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['I contributed to the project and implemented the parser. Python.'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.experience_level).toBe('some');
  });

  it('returns "beginner" when only beginner-level cues appear', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['Coursework included a class project; familiar with Python.'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.experience_level).toBe('beginner');
  });

  it('returns "beginner" by default when no level markers are present', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['Python pandas numpy with no verbs at all.'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.experience_level).toBe('beginner');
  });

  it('prefers "strong" over "some" when both signals are present', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf([
        'I led and architected the rewrite. I also assisted and implemented bugfixes. Python.',
      ])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.experience_level).toBe('strong');
  });
});

describe('parseResumePDF — success response shape', () => {
  it('caps raw_text at 8000 characters (multi-page resumes feed the tailor flow)', async () => {
    const longBody = 'Python '.repeat(2000);
    mockGetDocument.mockReturnValue({ promise: Promise.resolve(fakePdf([longBody])) });
    const res = await parseResumePDF(fakeFile());
    expect(res.success).toBe(true);
    expect(res.raw_text.length).toBe(8000);
  });

  it('builds the success message with the extracted counts', async () => {
    mockGetDocument.mockReturnValue({
      promise: Promise.resolve(fakePdf(['Python React. CS 225 MATH 241'])),
    });
    const res = await parseResumePDF(fakeFile());
    expect(res.message).toMatch(/Extracted \d+ skills, \d+ courses/);
  });
});
