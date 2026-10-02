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

// Matched in any case, with "&" read as "and".
const SECTION_TITLES: ReadonlyArray<[ResumeSectionKind, readonly string[]]> = [
  ['education', ['education', 'academic background', 'education and coursework', 'education and honors']],
  ['experience', ['experience', 'work experience', 'research experience', 'professional experience',
    'relevant experience', 'selected experience', 'additional experience', 'other experience',
    'employment', 'work history', 'internships', 'teaching experience', 'research and teaching',
    'leadership', 'leadership experience', 'activities', 'leadership and activities', 'involvement',
    'experience and leadership', 'leadership and experience', 'leadership and service',
    'extracurricular activities', 'volunteer experience', 'volunteering', 'research', 'teaching']],
  ['projects', ['projects', 'selected projects', 'technical projects', 'personal projects',
    'academic projects', 'research projects', 'course projects', 'relevant projects',
    'research and projects', 'projects and research']],
  ['skills', ['skills', 'technical skills', 'skills and interests', 'skills and tools',
    'technologies', 'tools', 'languages', 'programming languages']],
  ['publications', ['publications', 'papers', 'presentations', 'publications and presentations']],
  ['other', ['summary', 'profile', 'objective', 'about', 'about me', 'contact', 'contact information',
    'professional summary', 'career objective', 'research interests', 'additional information',
    'awards', 'honors', 'honors and awards', 'awards and honors', 'awards and achievements', 'achievements',
    'scholarships', 'certifications', 'certificates', 'coursework', 'relevant coursework', 'interests', 'hobbies',
    'service', 'affiliations', 'memberships', 'references']],
  ['education', ['教育', '教育背景', '教育经历']],
  ['experience', ['工作经历', '实习经历', '科研经历', '研究经历', '实践经历', '社会实践', '校园经历', '项目与经历', '经历与项目']],
  ['projects', ['项目经历', '项目经验']],
  ['skills', ['专业技能', '技能', '技能特长']],
  ['publications', ['论文', '发表论文', '学术成果', '论文与出版物']],
  ['other', ['获奖情况', '荣誉奖项', '个人简介', '自我评价', '姓名与联系方式']],
];
const SECTION_WORDS: ReadonlyArray<[ResumeSectionKind, RegExp]> = [
  ['education', /\bEDUCATION(?:AL)?\b/u], ['projects', /\bPROJECTS?\b/u],
  ['experience', /\b(?:EXPERIENCES?|EMPLOYMENT|INTERNSHIPS?|ACTIVITIES|INVOLVEMENT|LEADERSHIP|VOLUNTEERING)\b/u],
  ['skills', /\b(?:SKILLS?|SKILLSETS?|TECHNOLOGIES|TOOLS|LANGUAGES)\b/u],
  ['publications', /\b(?:PUBLICATIONS|PAPERS|PRESENTATIONS)\b/u],
  ['other', /\b(?:SUMMARY|OBJECTIVE|PROFILE|AWARDS|HONOU?RS|ACHIEVEMENTS|SCHOLARSHIPS|CERTIFICATIONS|CERTIFICATES|COURSEWORK|INTERESTS|HOBBIES|AFFILIATIONS|MEMBERSHIPS|REFERENCES)\b/u],
];

/** The section a whole line names: a known title in any case ("Skills:"), or
 *  an all-capitals label with a section word in it ("TECHNICAL SKILLS &
 *  TOOLS", "RESEARCH INTERESTS"). Capitals without one are content: a name,
 *  a school or employer, a skills list ("UNIVERSITY OF MICHIGAN", "HTML, CSS,
 *  SQL"). So is a line that starts in lowercase (a wrapped last word such as
 *  "research"), anything longer, and anything with digits. */
export function resumeSectionHeading(line: string): ResumeSectionKind | null {
  const label = line.trim().replace(/[:：]$/u, '').trim();
  if (!label || label.length > 40 || /\d/u.test(label) || /^\p{Ll}/u.test(label)) return null;
  const lower = label.toLowerCase().replace(/\s*&\s*/gu, ' and ').replace(/\s+/gu, ' ');
  for (const [kind, titles] of SECTION_TITLES) if (titles.includes(lower)) return kind;
  const letters = label.replace(/[^\p{L}]/gu, '');
  if (letters.length < 2 || letters !== letters.toUpperCase() || letters === letters.toLowerCase()
    || !/^[\p{L}\s&/,'’-]+$/u.test(label)) return null;
  const words = label.split(/\s+/u).length;
  for (const [kind, pattern] of SECTION_WORDS) if (words <= 5 && pattern.test(label)) return kind;
  return null;
}

export const RESUME_EMAIL = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/u;
export const RESUME_PHONE = /(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)|\d{2,4})[\s.-]?\d{3,4}[\s.-]?\d{3,4}/u;
export const RESUME_URL = /(?:https?:\/\/|www\.)\S+|\b[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|edu|io|dev|ai|me|co)(?:\/\S*)?/iu;
/** A place as a résumé prints it: "Champaign, IL", "Shanghai, China". */
export const RESUME_PLACE = String.raw`[\p{Lu}][\p{L}.' -]*,\s*(?:[A-Z]{2}|USA|China|Canada|United States|United Kingdom|UK|India|Japan|Korea|South Korea|Singapore|Germany|France|Hong Kong|Taiwan|Australia)`;
/** A name as the first line of a résumé prints it: two to five capitalized
 *  words, or two to four Chinese characters. */
export const RESUME_PERSON = /^(?:[\p{Lu}][\p{L}.'’-]*)(?:\s+[\p{Lu}][\p{L}.'’-]*){1,4}$|^\p{Script=Han}{2,4}$/u;
/** A word that names a role in a role row ("Teaching Assistant, …"). */
export const RESUME_ROLE = /\b(?:intern|assistant|engineer|researcher|developer|analyst|manager|lead|leader|fellow|tutor|consultant|scientist|coordinator|director|president|officer|volunteer|member|designer|associate|specialist|technician|founder|chair|captain|mentor|instructor|grader|programmer|trainee|editor|writer)s?\b/iu;
/** What separates the fields of a role row: a column gap, a spaced bar or
 *  dash, a comma, or "at". */
export const RESUME_FIELD_SEPARATOR = /\t|\s[|–—]\s|\s-\s|,\s|\s(?:at|@)\s/u;

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

// Where a visual line break falls inside an item. The PDF reflow
// (pdf-parser.ts) and text stored before it, which keeps a row per visual
// line, read the words at a break the same way. A split wrap costs less than
// two items glued into one, so only words that cannot end or open an item
// carry a line on by themselves.

const SENTENCE_END = /[.!?。！？]["'”’)\]）」』]*$/u;
// A wrapped "Aug 2024 - May 2028" puts the range dash at the start of the next
// line, where it reads like a bullet. A dash before words stays a bullet.
const DASH_CONTINUATION = /^[-–—]\s+(?:(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?|spring|summer|fall|autumn|winter)\s+\d{4}|present\b|current\b)/iu;
const YEAR_END = /\b(?:19|20)\d{2}$/u;
// A line that cannot end an item: a word broken at its hyphen, a comma, colon
// or opening bracket (full-width too), a spaced dash or lone "+" ("React +";
// the one in "C++" ends a word), or a word that needs more after it. A ";"
// can end an item, and so can a preposition ("…two other groups rely on").
const CONTINUES_AFTER = /(?:\p{L}[-\u2010\u2011]|[,:&/(，、：（《「『]|\s[-–—+]|(?:^|\s)(?:and|or|of|the|a|an|as|via|using|including|between|than|that|which|while|per))$/u;
const PARTICLE = /(?:^|\s)(?:to|for|in|on|with|by|at|from|over|under|into|across)$/u;
// A line that cannot open an item: a lowercase word that is not a name
// ("iOS"), "&" or a bracket.
const CONTINUES_BEFORE = /^(?:\p{Ll}(?![\p{L}\p{N}]*\p{Lu})|[&()%])/u;
// A number opens an item as often as it goes on one ("12 students
// mentored…", "40% faster builds…", "3.92/4.00 GPA, Dean's List"). It goes
// on a line that ends in a word that takes a number ("cut its runtime by" /
// "40%", "about" / "12,000", "GPA" / "3.7/4.0"), and a measure goes on
// after ";" ("3,000 tweets;" / "78% accuracy"). A year is a date of its own.
const NUMBER_START = /^(?!(?:19|20)\d{2}\b)\d+(?:[,.]\d+)*(?:\/\d+(?:[,.]\d+)*)?%?(?=[\s,)]|$)/u;
const MEASURE_START = /^(?!(?:19|20)\d{2}\b)(?:\d+(?:[,.]\d+)+(?:\/\d+(?:[,.]\d+)*)?%?|\d+%)(?=[\s)]|$)/u;
const TAKES_NUMBER = /(?:^|\s)(?:by|to|from|over|under|at|with|about|around|nearly|almost|approximately|roughly|reaching|reached|GPA)$/u;
const LABEL = /^[^,:：]{1,40}(?::\s|：)/u;
// A row of its own rather than the rest of a sentence: a title and its
// description split by a spaced dash or bar, or a label ("Coursework: …").
const ROW = new RegExp(String.raw`\s[-–—|]\s|${LABEL.source}`, 'u');
const YEAR = /\b(?:19|20)\d{2}\b/u;
const ARTICLE = /^(?:a|an|the|this|these|our|my)\s/iu;
const AWARD = /\b(?:finalist|semifinalist|winner|recipient|award|prize|scholarship|fellowship|honou?rs?|medal(?:ist)?|champion|runner-up|mention)\b/iu;
const CJK = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u;
// CJK text and its full-width punctuation wrap with no space at the break.
const CJK_BREAK = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}\u3000-\u303f\uff00-\uffef]/u;
// A stored row that only wraps ends within a word of the widest rows; glyph
// widths vary, so character counts are compared with some slack.
const STORED_SLACK = 0.85;

/** A line that opens an item with a bullet glyph or number. */
export function glyphLine(line: string): boolean {
  return BULLET_LINE.test(line) && !DASH_CONTINUATION.test(line.trim());
}

/** A line's first word; in CJK text, its first character. */
export function firstWord(line: string): string {
  const head = Array.from(line)[0];
  return CJK.test(head) ? head : line.split(/\s+/u)[0];
}

/** Text that always starts a new line: a bullet, a heading on either side,
 *  a finished sentence, or contact details at the break. */
export function lineBreakText(before: string, after: string): boolean {
  const lastWord = before.split(/\s+/u).pop()!;
  const first = firstWord(after);
  return glyphLine(after) || resumeSectionHeading(before) !== null || resumeSectionHeading(after) !== null
    || SENTENCE_END.test(before) || RESUME_EMAIL.test(lastWord) || RESUME_URL.test(lastWord)
    || RESUME_EMAIL.test(first) || RESUME_URL.test(first) || RESUME_PHONE.exec(after)?.index === 0;
}

/** A row that names a role or an award in its first two fields
 *  ("Teaching Assistant, Statistics Department", "Finalist, …"). */
function roleRow(line: string): boolean {
  return line.split(RESUME_FIELD_SEPARATOR).slice(0, 2).some((field) => RESUME_ROLE.test(field) || AWARD.test(field));
}

/** A bracket the line opens and does not close ("…Linear Algebra (MATH"). */
function openBracket(line: string): boolean {
  return (line.match(/[([（]/gu)?.length ?? 0) > (line.match(/[)\]）]/gu)?.length ?? 0);
}

/** The words at the break say the line goes on: the line before cannot end
 *  an item, the next line cannot open one, a number follows a word that
 *  takes one, or the break falls inside a bracket or a date range. A list
 *  cut after a comma and a name says nothing: the row of names under it is
 *  as likely an organization ("Caterpillar Inc., Peoria") or an honors line
 *  ("Dean's List, James Scholar") as the rest of the list. */
export function wrapEvidence(before: string, after: string): boolean {
  return CONTINUES_AFTER.test(before) || CONTINUES_BEFORE.test(after) || openBracket(before)
    || (NUMBER_START.test(after) && TAKES_NUMBER.test(before)) || (MEASURE_START.test(after) && before.endsWith(';'))
    || (DASH_CONTINUATION.test(after) && YEAR_END.test(before));
}

/** A first word that is a name in itself, not one that opens an item: an
 *  acronym, or a word with a digit or a capital inside ("AUC", "R21",
 *  "Grad-CAM", "PyTorch"). A number is not one ("25% fewer tickets…"). */
function nameStart(after: string): boolean {
  const word = firstWord(after).replace(/^[^\p{L}\p{N}]+/u, '');
  return /^\p{L}/u.test(word) && (/\p{N}/u.test(word) || (word.match(/\p{Lu}/gu)?.length ?? 0) > 1);
}

/** Hints too weak to carry a line on by themselves, so the page's geometry
 *  must agree without slack. A lone word or CJK character that cannot stand
 *  as a line of its own ("GPU.", "钟"). A preposition that could also end
 *  the item, before a name rather than an ordinary word ("ImageNet", not
 *  "Research Intern, …" or "Mentored…"). In a glyph item on a page whose
 *  glyph items end with a full stop, a next line that ends the sentence and
 *  opens with a name, or after a preposition, with any word but an article
 *  ("A web app…"). None of them carries a line on into a role row. */
export function weakWrapEvidence(before: string, after: string, periodItem: boolean): boolean {
  const ends = periodItem && SENTENCE_END.test(after) && !ROW.test(after);
  const characters = Array.from(after);
  // CJK text has no capitals to tell a name from an item's first word.
  if (CJK.test(characters[0]) || CJK.test(Array.from(before).pop()!)) return ends || characters.length === 1;
  if (roleRow(after)) return false;
  if (!/\s/u.test(after) && SENTENCE_END.test(after)) return true;
  if (nameStart(after)) return ends || (PARTICLE.test(before) && /\p{Ll}/u.test(after));
  return ends && PARTICLE.test(before) && !ARTICLE.test(after);
}

/** Whether glyph items end with a full stop, judged by the lines right before
 *  a glyph line: the end of the previous item, unless it is a heading or a
 *  row (a column gap, a title and its description, or a year with no full
 *  stop). A lone item says nothing. */
export function glyphItemsEndWithStop(lines: readonly string[], tabular: (index: number) => boolean): boolean {
  let stops = 0;
  for (let index = 1; index < lines.length; index++) {
    const end = lines[index - 1].trim();
    if (!glyphLine(lines[index]) || !end || resumeSectionHeading(end) || tabular(index - 1) || ROW.test(end)) continue;
    if (SENTENCE_END.test(end)) stops += 1;
    else if (!YEAR.test(end)) stops -= 1;
  }
  return stops > 0;
}

/** What joins a wrapped line to the one before: nothing inside a word broken
 *  at its hyphen or inside CJK text, a space otherwise. */
export function wrapJoin(before: string, after: string): string {
  if (/\p{L}[-\u2010\u2011]$/u.test(before) && /^[\p{L}\p{N}]/u.test(after)) return '';
  return CJK_BREAK.test(Array.from(before).pop()!) && CJK_BREAK.test(Array.from(after)[0]) ? '' : ' ';
}

/** A row's width in characters, a CJK character counting as two. */
function rowWidth(row: string): number {
  return Array.from(row).reduce((width, character) => width + (CJK_BREAK.test(character) ? 2 : 1), 0);
}

/** Text stored before the PDF reflow keeps a row per visual line. Whether
 *  each row only wraps the one before. With the page gone, only the words
 *  that cannot end or open an item join a row, and only when the row before
 *  ran to the column edge: it and the next row's first word would not fit
 *  in the widest rows' width, counted in characters with slack for glyph
 *  widths. */
export function storedWraps(rows: readonly string[]): boolean[] {
  const width = rows.reduce((widest, row) => Math.max(widest, rowWidth(row.trim())), 0);
  return rows.map((row, index) => {
    const before = index > 0 ? rows[index - 1].trim() : '';
    const after = row.trim();
    return !!before && !!after && !before.includes('\t') && !after.includes('\t') && !lineBreakText(before, after)
      && wrapEvidence(before, after) && rowWidth(before) + 1 + rowWidth(firstWord(after)) > STORED_SLACK * width;
  });
}
