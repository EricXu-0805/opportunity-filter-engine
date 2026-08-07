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

const EXP_KEYWORDS: Record<string, string[]> = {
  strong: ['led', 'managed', 'architected', 'published', 'co-author', 'principal'],
  some: ['assisted', 'contributed', 'developed', 'implemented', 'designed', 'built'],
  beginner: ['coursework', 'class project', 'learning', 'familiar'],
};

function extractSkills(text: string): string[] {
  return SKILL_PATTERNS.filter(({ pattern }) => pattern.test(text)).map(({ skill }) => skill);
}

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

function inferExperienceLevel(text: string): string {
  const lower = text.toLowerCase();
  for (const level of ['strong', 'some', 'beginner'] as const) {
    const hits = EXP_KEYWORDS[level].filter(kw => lower.includes(kw)).length;
    if (level === 'strong' && hits >= 2) return 'strong';
    if (level === 'some' && hits >= 2) return 'some';
  }
  return 'beginner';
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
      extracted_coursework: [],
      experience_level: 'beginner',
      raw_text: '',
      success: false,
      message: 'Could not extract text from PDF. The file may be image-based.',
    };
  }

  const skills = extractSkills(rawText);
  const coursework = extractCoursework(rawText);
  const experience = inferExperienceLevel(rawText);
  const interests = extractResearchInterests(rawText);

  return {
    extracted_skills: skills,
    extracted_coursework: coursework,
    experience_level: experience,
    raw_text: rawText.slice(0, 8000),
    success: true,
    message: `Extracted ${skills.length} skills, ${coursework.length} courses from resume.`,
    suggested_interests: interests,
  };
}
