import type { ResumeParseResponse } from './types';

const KNOWN_SKILLS = [
  'Python', 'Java', 'C++', 'C#', 'C', 'JavaScript', 'TypeScript',
  'R', 'MATLAB', 'SQL', 'Rust', 'Go', 'Kotlin', 'Swift',
  'PyTorch', 'TensorFlow', 'scikit-learn', 'pandas', 'NumPy',
  'OpenCV', 'HuggingFace', 'transformers',
  'machine learning', 'deep learning', 'NLP',
  'data analysis', 'data visualization',
  'Linux', 'Git', 'Docker', 'Kubernetes',
  'React', 'Flask', 'FastAPI', 'Django', 'Node.js',
  'AWS', 'GCP', 'Azure',
  'LaTeX', 'Excel', 'SPSS', 'SAS', 'Stata',
];

// A skill token must not be flanked by a letter or the tech punctuation
// +/# (so "C" is rejected inside "C++"/"C#" and "Go" inside "Algorithms").
// Digits and '.' are intentionally excluded so "Docker." (sentence end) and
// "Python3" still match, while "Node.js"/"scikit-learn" match via the literal.
const SKILL_BOUNDARY = '[A-Za-z+#]';

const SKILL_PATTERNS = KNOWN_SKILLS.map((skill) => ({
  skill,
  pattern: new RegExp(
    `(?<!${SKILL_BOUNDARY})${skill.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?!${SKILL_BOUNDARY})`,
    'i',
  ),
}));

const COURSE_PATTERN = /\b([A-Z]{2,4})\s+(\d{3,4})\b/g;

// Matches a "Coursework:" / "Relevant Courses -" label and captures the rest
// of the line, so named courses ("Data Structures") are extracted, not just
// department codes ("CS 124"). Requires the label to be followed by : - or —.
const COURSEWORK_LABEL = /\b(?:relevant\s+)?(?:course\s?work|courses)\b\s*[:\-—]\s*(.+)/i;

// Matches an "Areas of Interest" / "Research Interests" / "Research Areas" label.
// PDF extraction often flattens the whole resume onto one line, so the value is
// cut at the next "Capitalized Label:" (e.g. "Languages:") rather than running to
// end-of-line — the stop pattern is case SENSITIVE so it isn't tripped by
// lowercase hyphenated words ("full-stack"). Hobby/"Personal Interests" lines are
// deliberately excluded — this seeds a research-matching signal, not pastimes.
const INTERESTS_LABEL = /\b(?:areas?\s+of\s+interest|research\s+interests?|research\s+areas?)\b\s*[:\-—]\s*/i;
const INTERESTS_STOP = /\s+[A-Z][A-Za-z][A-Za-z &/]*\s*[:—]/;

/** The longest excerpt shown back to the student per skill. PDF extraction
 *  routinely flattens a whole resume onto one line, so without a cap every
 *  skill would carry a copy of the entire document. */
const EVIDENCE_CAP = 200;

/** The line a match sits on, trimmed and capped around the match itself so the
 *  skill stays visible even when the "line" is the whole document. */
function evidenceFor(text: string, index: number, length: number): string {
  const start = text.lastIndexOf('\n', index) + 1;
  const nl = text.indexOf('\n', index);
  const end = nl === -1 ? text.length : nl;
  const line = text.slice(start, end).trim();
  if (line.length <= EVIDENCE_CAP) return line;
  // Centre the window on the match rather than truncating from the left, or a
  // skill near the end of a flattened resume would be cut out of its own
  // evidence.
  const rel = index - start;
  const from = Math.max(0, Math.min(rel - (EVIDENCE_CAP - length) / 2,
                                    line.length - EVIDENCE_CAP));
  return line.slice(Math.floor(from), Math.floor(from) + EVIDENCE_CAP).trim();
}

function extractSkills(text: string): { skill: string; line: string }[] {
  const hits: { skill: string; line: string }[] = [];
  for (const { skill, pattern } of SKILL_PATTERNS) {
    const m = pattern.exec(text);
    if (m && m.index !== undefined) {
      hits.push({ skill, line: evidenceFor(text, m.index, m[0].length) });
    }
  }
  return hits;
}

// A résumé's address block and grant citations have the same shape as a course
// code, so "Urbana IL 61801 / APT 402" was reaching a student's profile as
// coursework and from there into the sentence a cold email makes about what
// they have studied. These prefixes are never a department.
const NOT_A_DEPARTMENT = new Set([
  'APT', 'STE', 'RM', 'BOX', 'PO', 'POB', 'FL', 'UNIT', 'NO', 'BLDG', 'DEPT',
  'EXT', 'TEL', 'FAX', 'ISBN', 'DOI', 'GPA', 'ID', 'SSN', 'ZIP',
]);

function trimCourse(s: string): string {
  return s.replace(/^[ .\t]+/, '').replace(/[ .\t]+$/, '');
}

function extractCoursework(text: string): string[] {
  const courses: string[] = [];
  for (const m of text.matchAll(COURSE_PATTERN)) {
    // A number in the calendar band is a venue or a date ("CVPR 2026",
    // "MAY 2027"), not a catalog number — publications and graduation dates
    // share the course-code shape, and a venue cited as coursework becomes a
    // false claim in generated emails. Catalog numbers in the band ("CS 2050")
    // are sacrificed; a labeled "Coursework:" line still captures them below.
    const num = Number(m[2]);
    if (num >= 1950 && num <= 2049) continue;
    if (NOT_A_DEPARTMENT.has(m[1].toUpperCase())) continue;
    courses.push(`${m[1]} ${m[2]}`);
  }
  for (const line of text.split('\n')) {
    const label = COURSEWORK_LABEL.exec(line);
    if (!label) continue;
    for (const item of label[1].split(/[;,]/)) {
      const name = trimCourse(item);
      if (name && /[A-Za-z]/.test(name) && name.length >= 3 && name.length <= 40) {
        courses.push(name);
      }
    }
  }
  return Array.from(new Set(courses)).sort();
}

/** Capture a labeled research-interests line from a resume. The form's only
 * semantic-match lever is research_interests_text, so a resume-only user
 * otherwise contributes no topical signal. Returns '' when no section exists. */
function extractResearchInterests(text: string): string {
  for (const line of text.split('\n')) {
    const label = INTERESTS_LABEL.exec(line);
    if (!label) continue;
    const rest = line.slice(label.index + label[0].length);
    const stop = INTERESTS_STOP.exec(rest);
    const phrase = trimCourse(stop ? rest.slice(0, stop.index) : rest);
    if (phrase.length >= 3 && phrase.length <= 300) return phrase;
  }
  return '';
}

export async function parseResumePDF(file: File): Promise<ResumeParseResponse> {
  const pdfjsLib = await import('pdfjs-dist');
  pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
    'pdfjs-dist/build/pdf.worker.min.mjs',
    import.meta.url,
  ).toString();

  const arrayBuffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;

  const textParts: string[] = [];
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const content = await page.getTextContent();
    const pageText = content.items
      .map((item: unknown) => (item as { str: string }).str)
      .join(' ');
    textParts.push(pageText);
  }

  const rawText = textParts.join('\n');

  if (!rawText.trim()) {
    return {
      extracted_skills: [],
      skill_evidence: [],
      extracted_coursework: [],
      raw_text: '',
      success: false,
      message: 'Could not extract text from PDF. The file may be image-based.',
    };
  }

  const hits = extractSkills(rawText);
  const coursework = extractCoursework(rawText);
  const interests = extractResearchInterests(rawText);

  return {
    extracted_skills: hits.map((h) => h.skill),
    skill_evidence: hits,
    extracted_coursework: coursework,
    raw_text: rawText.slice(0, 8000),
    success: true,
    message: `Extracted ${hits.length} skills, ${coursework.length} courses from resume.`,
    suggested_interests: interests,
  };
}
