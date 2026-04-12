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

const COURSE_PATTERN = /\b([A-Z]{2,4})\s+(\d{3,4})\b/g;

const EXP_KEYWORDS: Record<string, string[]> = {
  strong: ['led', 'managed', 'architected', 'published', 'co-author', 'principal'],
  some: ['assisted', 'contributed', 'developed', 'implemented', 'designed', 'built'],
  beginner: ['coursework', 'class project', 'learning', 'familiar'],
};

function extractSkills(text: string): string[] {
  const lower = text.toLowerCase();
  return KNOWN_SKILLS.filter(s => lower.includes(s.toLowerCase()));
}

function extractCoursework(text: string): string[] {
  const matches: string[] = [];
  let m: RegExpExecArray | null;
  while ((m = COURSE_PATTERN.exec(text)) !== null) {
    matches.push(`${m[1]} ${m[2]}`);
  }
  return Array.from(new Set(matches)).sort();
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
  pdfjsLib.GlobalWorkerOptions.workerSrc =
    'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.worker.min.mjs';

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

  return {
    extracted_skills: skills,
    extracted_coursework: coursework,
    experience_level: experience,
    raw_text: rawText.slice(0, 3000),
    success: true,
    message: `Extracted ${skills.length} skills, ${coursework.length} courses from resume.`,
  };
}
