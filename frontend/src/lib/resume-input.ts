// Keep the accepted raw-text limit aligned with backend/lib/resume_input.py.
// Count Unicode code points, matching Pydantic/Python, rather than UTF-16 units.
export const MAX_RESUME_TEXT_CHARACTERS = 60_000;
export const RESUME_AI_CHUNK_CHARACTERS = 8_000;

export function resumeTextCharacters(text: string): number {
  return Array.from(text).length;
}

/** A bullet glyph or list number opening a résumé line. The private-use
 *  characters are the Symbol/Wingdings bullets Word-made PDFs extract as. */
export const BULLET_LINE = /^[\t ]*(?:[•●▪◦‣∙·*–—\-■►➢✓◆\uf0b7\uf0a7\uf076\uf0d8\uf0fc]|\(?\d{1,2}[.)])\s/u;

export type ResumeSectionKind = 'education' | 'experience' | 'projects' | 'skills' | 'publications' | 'other';

const SECTION_TITLES: ReadonlyArray<[ResumeSectionKind, readonly string[]]> = [
  ['education', ['education', 'academic background', 'education and coursework']],
  ['experience', ['experience', 'work experience', 'research experience', 'professional experience',
    'relevant experience', 'employment', 'work history', 'internships', 'teaching experience',
    'leadership', 'leadership experience', 'activities', 'leadership and activities',
    'extracurricular activities', 'volunteer experience', 'volunteering', 'research']],
  ['projects', ['projects', 'selected projects', 'technical projects', 'personal projects',
    'academic projects', 'research projects', 'course projects']],
  ['skills', ['skills', 'technical skills', 'skills and interests', 'skills & interests',
    'technologies', 'tools', 'languages', 'programming languages']],
  ['publications', ['publications', 'papers', 'presentations', 'publications and presentations']],
  ['other', ['summary', 'profile', 'objective', 'awards', 'honors', 'honors and awards', 'awards and honors',
    'certifications', 'coursework', 'relevant coursework', 'interests', 'references']],
  ['education', ['教育背景', '教育经历']],
  ['experience', ['工作经历', '实习经历', '科研经历', '研究经历', '实践经历', '社会实践', '校园经历']],
  ['projects', ['项目经历', '项目经验']],
  ['skills', ['专业技能', '技能', '技能特长']],
  ['publications', ['论文', '发表论文', '学术成果']],
  ['other', ['获奖情况', '荣誉奖项', '个人简介', '自我评价']],
];

/** The section a whole line names: a known title in any case ("Skills:"), or
 *  a short all-capitals label ("WORK EXPERIENCE"). Anything longer, or with
 *  digits, is content. */
export function resumeSectionHeading(line: string): ResumeSectionKind | null {
  const label = line.trim().replace(/:$/u, '').trim();
  if (!label || label.length > 40 || /\d/u.test(label)) return null;
  const lower = label.toLowerCase().replace(/\s+/gu, ' ');
  for (const [kind, titles] of SECTION_TITLES) if (titles.includes(lower)) return kind;
  const letters = label.replace(/[^\p{L}]/gu, '');
  if (letters.length < 2 || letters !== letters.toUpperCase() || letters === letters.toLowerCase()
    || label.split(/\s+/u).length > 5 || !/^[\p{L}\s&/,'’-]+$/u.test(label)) return null;
  return 'other';
}

export const RESUME_EMAIL = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/u;
export const RESUME_PHONE = /(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)|\d{2,4})[\s.-]?\d{3,4}[\s.-]?\d{3,4}/u;
export const RESUME_URL = /(?:https?:\/\/|www\.)\S+|\b[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|edu|io|dev|ai|me|co)(?:\/\S*)?/iu;

/** A line of contact details: an email, phone or profile link with at most a
 *  name and a place around it. A project line that cites its URL is not one. */
export function resumeContactLine(line: string): boolean {
  const personal = RESUME_EMAIL.test(line) || RESUME_PHONE.test(line);
  if (!personal && !RESUME_URL.test(line)) return false;
  const rest = line.replace(new RegExp(RESUME_EMAIL.source, 'gu'), ' ')
    .replace(new RegExp(RESUME_PHONE.source, 'gu'), ' ')
    .replace(new RegExp(RESUME_URL.source, 'giu'), ' ')
    .replace(/[|•·,;:/()–—-]+/gu, ' ').trim();
  return (rest ? rest.split(/\s+/u).length : 0) <= (personal ? 6 : 2);
}
