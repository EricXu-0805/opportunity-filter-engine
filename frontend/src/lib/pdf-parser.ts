import type { ResumeParseResponse } from './types';
import {
  BULLET_LINE, firstWord, glyphItemsEndWithStop, glyphLine, lineBreakText, lowercaseOpening, MAX_RESUME_TEXT_CHARACTERS,
  RESUME_ROLE, resumeTextCharacters, weakWrapEvidence, wrapEvidence, wrapJoin,
} from './resume-input';
import { createPdfResourceLoaders, PDF_CMAP_URL, PDF_STANDARD_FONT_URL } from './pdf-resources';

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

// A row under a coursework list that starts something of its own: a label
// ("Honors: Dean's List") or an honor ("Dean's List, James Scholar").
const NOT_COURSEWORK = /^[^,:：]{1,40}(?::\s|：)|\b(?:dean['’]?s list|scholars?|scholarships?|honou?rs?|awards?|prizes?|fellowships?|medal(?:ist)?|cum laude|finalist|winner|recipient)\b/iu;

/** Course codes anywhere, and named courses on a labeled coursework line.
 *  The text keeps a list cut inside a name ("…, Data" / "Structures and
 *  Algorithms, …") on two lines, since the row under a list is as often an
 *  organization or an honor. A coursework label says what the list is, so
 *  the list goes on across a break the page marks as a possible wrap
 *  (`possibleWraps`, offsets of line breaks in `text`) unless the next line
 *  is a row of its own. */
function extractCoursework(text: string, possibleWraps: ReadonlySet<number> = new Set()): string[] {
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
  const lines = text.split('\n');
  let end = -1;
  for (let index = 0; index < lines.length; index++) {
    end += lines[index].length + 1;
    const label = COURSEWORK_LABEL.exec(lines[index]);
    if (!label) continue;
    let list = label[1];
    while (possibleWraps.has(end) && index + 1 < lines.length
      && !NOT_COURSEWORK.test(lines[index + 1]) && !RESUME_ROLE.test(lines[index + 1])) {
      index += 1;
      end += lines[index].length + 1;
      list += wrapJoin(list, lines[index]) + lines[index];
    }
    for (const item of list.split(/[;,]/)) {
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

interface PdfTextItem {
  str: string;
  dir?: string;
  width?: number;
  height?: number;
  transform?: unknown[];
  fontName?: string;
  hasEOL?: boolean;
}
interface Run { x: number; y: number; width: number; size: number; font?: string; str: string }
interface VisualLine { runs: Run[]; gaps: number[]; positioned: boolean }
interface LineShape {
  left: number; right: number; textLeft: number; baseline: number; size: number;
  fonts: Set<string | undefined>; tabular: boolean;
  /** Has a break opportunity: a space, or CJK text, which wraps between characters. */
  wrappable: boolean;
}

// Distances are in ems of the line's font size. PDF.js itself starts a space
// at a 0.102 em gap, so runs closer than TOUCH are one word split into glyph
// runs (a ligature, a soft-hyphen break point) and take no space between them.
const TOUCH = 0.1;
const SPACE = 0.25;
// Wider than any word space: a right-aligned date or a column gap, kept as a
// tab so "Organization<tab>Urbana, IL" stays two fields.
const WIDE = 2;
const TAB_GAP = 1.5;
const ALIGN = 1;
const COLUMN = 2;
const NARROW = 20;
const SLACK = 1.1;
const JUSTIFIED = 0.05;
// A right-aligned field ends within about a word of its column's edge; a
// label column's gap can leave its row far short of it.
const REACH = 2;
const PITCH_SLACK = 1.15;

const BULLET_GLYPH = /^[•●▪◦‣∙·*–—\-■►➢✓◆\uf0b7\uf0a7\uf076\uf0d8\uf0fc]$/u;
const WRAPPABLE = /\S\s+\S|[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]./u;
// Fonts that map CJK glyphs to Kangxi radicals instead of the ideographs
// ("使⽤" for "使用") print correctly but extract as different characters.
const KANGXI_RADICAL = /[\u2f00-\u2fd5]/gu;
const CJK_TEXT = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u;
// A Chinese line that names an award ("获得校级优秀学生奖学金。").
const CJK_AWARD = /奖|称号|荣誉/u;
// Helvetica's advance widths, in thousandths of an em, for the printable
// ASCII characters from space to "~". Fonts differ more in scale than in
// proportion, so these share a line's measured width among its characters:
// a capital or an "m" takes more of it than an "i" or a "t".
const ASCII_WIDTHS = [
  278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
  556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
  1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
  667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
  333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
  556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
];
const FULL_WIDTH = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}\u3000-\u303f\uff00-\uffef]/u;

/** Where an item sits, for horizontal left-to-right text only. Rotated,
 *  vertical or right-to-left runs keep the positionless joining rules. */
function positioned(item: PdfTextItem): Run | null {
  const t = item.transform;
  if (!Array.isArray(t) || t.length < 6 || typeof item.width !== 'number' || item.dir === 'rtl') return null;
  const [a, b, c, , x, y] = t as number[];
  if (!(a > 0) || Math.abs(b) > 1e-6 || Math.abs(c) > 1e-6 || !Number.isFinite(x) || !Number.isFinite(y)) return null;
  const size = item.height || Math.abs(t[3] as number);
  return size > 0 ? { x, y, width: item.width, size, font: item.fontName, str: item.str } : null;
}

/** A text's width by Helvetica's proportions, in thousandths of an em. An
 *  accented letter takes its base letter's width, a CJK or full-width
 *  character an em, any other character a digit's width. */
function glyphWidth(text: string): number {
  let width = 0;
  for (const character of text) {
    const code = character.codePointAt(0)!;
    if (code >= 32 && code <= 126) width += ASCII_WIDTHS[code - 32];
    else if (FULL_WIDTH.test(character)) width += 1000;
    else {
      // Decomposed only here, where an accented letter needs its base letter.
      const base = character.normalize('NFD').codePointAt(0)!;
      width += base >= 32 && base <= 126 ? ASCII_WIDTHS[base - 32] : 556;
    }
  }
  return width;
}

function median(values: number[]): number {
  const sorted = [...values].sort((p, q) => p - q);
  return sorted[Math.floor(sorted.length / 2)];
}

function shapeOf(line: VisualLine, text: string): LineShape | null {
  const { runs } = line;
  if (!line.positioned || !runs.length) return null;
  const size = runs[0].size;
  // A right-aligned date or location leaves one gap far wider than the
  // line's word spaces; justified text widens every space alike.
  const spaces = line.gaps.filter((gap) => gap > TOUCH * size && gap <= TAB_GAP * size);
  const reference = spaces.length ? median(spaces) : line.gaps.length >= 3 ? median(line.gaps) : SPACE * size;
  return {
    left: Math.min(...runs.map((run) => run.x)),
    right: Math.max(...runs.map((run) => run.x + run.width)),
    // Where a bullet's text starts, which its wrapped lines hang under. A
    // glyph printed in the same run as the text is measured by the run's
    // average character width.
    textLeft: runs.length > 1 && BULLET_GLYPH.test(runs[0].str.trim()) ? runs[1].x
      : runs[0].x + runs[0].width * (BULLET_LINE.exec(runs[0].str)?.[0].length ?? 0) / runs[0].str.length,
    baseline: runs[0].y,
    size,
    // A PDF may split one style across many font subsets (CJK glyphs are
    // spread over dozens), so a style change shows as fonts with no overlap.
    fonts: new Set(runs.map((run) => run.font)),
    tabular: line.gaps.some((gap) => gap > TAB_GAP * size && gap > 3 * reference),
    wrappable: WRAPPABLE.test(text.trim()),
  };
}

/** Whether a line could go on from the one before: the same style, size
 *  and alignment at an ordinary line pitch, with no text between them that
 *  always starts a new line (bullets, headings, table-like rows, contact
 *  details, finished sentences). */
function sameParagraph(shapes: Array<LineShape | null>, index: number, texts: string[], pitch: Map<number, number>): boolean {
  const prev = shapes[index - 1];
  const next = shapes[index];
  const before = texts[index - 1].trim();
  const after = texts[index].trim();
  if (!prev || !next || !before || !after || prev.tabular || next.tabular || lineBreakText(before, after)) return false;
  if (![...next.fonts].some((font) => prev.fonts.has(font)) || Math.abs(prev.size - next.size) > 0.05 * prev.size) return false;
  const step = prev.baseline - next.baseline;
  if (step < 0.8 * prev.size || step > PITCH_SLACK * (pitch.get(Math.round(prev.size * 2)) ?? Infinity)) return false;
  return Math.abs(next.left - prev.left) <= ALIGN * prev.size || Math.abs(next.left - prev.textLeft) <= ALIGN * prev.size;
}

/** Whether another line sits in the same column as this one: it starts at
 *  this line's left edge or where its text starts after a bullet. */
function sameColumn(other: LineShape, line: LineShape): boolean {
  const tolerance = COLUMN * Math.max(other.size, line.size);
  return Math.abs(other.left - line.left) <= tolerance || Math.abs(other.left - line.textLeft) <= tolerance;
}

interface Column { left: number; right: number }

/** The left and right edges of a line's column, from the lines in it. A line
 *  with no space in it cannot wrap and may overflow (a long email address). */
function columnOf(shapes: Array<LineShape | null>, line: LineShape): Column {
  let left = line.left;
  let right = -Infinity;
  for (const other of shapes) {
    if (!other || !sameColumn(other, line)) continue;
    left = Math.min(left, other.left);
    if (other.wrappable || other.tabular) right = Math.max(right, other.right);
  }
  return { left, right: right === -Infinity ? line.right : right };
}

/** Whether another line shows where this line's column ends: a row whose
 *  right-aligned field reaches the edge or a line that the words carry on
 *  (`edges`), or two different lines that end exactly where this one does,
 *  as justified lines do; one such line can be a coincidence of ragged
 *  text. Otherwise this line may only be the longest of lines that never
 *  wrap, not a full one. */
function edgeShown(shapes: Array<LineShape | null>, index: number, texts: string[], edges: readonly boolean[]): boolean {
  const line = shapes[index]!;
  const text = texts[index].trim();
  let aligned = 0;
  return shapes.some((other, at) => !!other && sameColumn(other, line) && (other.wrappable || other.tabular)
    && (edges[at] || (Math.abs(other.right - line.right) <= JUSTIFIED * line.size && texts[at].trim() !== text && ++aligned > 1)));
}

/** A Chinese line that names an award, at a break in Chinese text. Chinese
 *  has no capitals to tell the rest of an item from a line of its own, so
 *  the weak hints there do not check for role or award rows as English ones
 *  do; an award line names its award, and no hint carries a line into it. */
function cjkAwardRow(before: string, after: string): boolean {
  return CJK_AWARD.test(after) && (CJK_TEXT.test(Array.from(after)[0]) || CJK_TEXT.test(Array.from(before).pop()!));
}

/** The separator for a visual line break that is only a wrap, or null for a
 *  real one. A wrap continues the same paragraph, the words at the break
 *  carry the line on (resume-input.ts), and the previous line stops where the
 *  next line's first word could not have fitted. `periodItem` says the
 *  previous line belongs to an item that opened with a bullet glyph or
 *  number, on a page whose glyph items end with a full stop, so a next line
 *  that ends a sentence may finish that item. A weak hint, and a next line
 *  whose lowercase words could open an item of their own, also need the page
 *  to show where the column ends (`edges`, see edgeShown); without `edges`,
 *  only the words that settle it by themselves carry a line on. A line that
 *  hangs under the text of the glyph item above it (`hangs`) goes on with
 *  that item whatever its words, and needs no edge: the next item would
 *  open at the glyph. */
function wrapSeparator(
  shapes: Array<LineShape | null>, index: number, texts: string[], pitch: Map<number, number>, periodItem: boolean,
  column: (index: number) => Column, edges: readonly boolean[] | null, hangs: readonly boolean[],
): string | null {
  const prev = shapes[index - 1];
  const next = shapes[index];
  const before = texts[index - 1].trim();
  const after = texts[index].trim();
  if (!prev || !next || !sameParagraph(shapes, index, texts, pitch)) return null;
  const evidence = hangs[index] || wrapEvidence(before, after);
  const unsure = !hangs[index] && (evidence ? lowercaseOpening(before, after)
    : !!edges && weakWrapEvidence(before, after, periodItem) && !cjkAwardRow(before, after));
  if (!evidence && !unsure) return null;
  if (unsure && (!edges || !edgeShown(shapes, index - 1, texts, edges))) return null;
  // A narrow column of short items ("Python" / "SolidWorks") is a list, not
  // a paragraph, unless the text itself says it goes on.
  const area = column(index - 1);
  if (area.right - area.left < NARROW * prev.size && !evidence) return null;
  // The weak hints that hold on any page keep the characters' share (see
  // ranOutOfRoom): measured by its glyphs, a number or a name after a
  // preposition that can also end an item ("…we presented at" / "12
  // students…") would join more items that end within a word of the edge.
  // For a lone word the two shares are the same.
  const characterShare = !evidence && weakWrapEvidence(before, after, false);
  return ranOutOfRoom(prev, next, after, area, evidence, characterShare) ? wrapJoin(before, after) : null;
}

/** Whether the line before ran out of room: the next line's first word and
 *  the space before it could not have fitted before the column's edge.
 *  PDF.js measures runs, not glyphs, so they take their glyphs' share of the
 *  next line's measured width, or with `characterShare` their characters'
 *  share, which under-measures digits and capitals. Where the text itself
 *  says it goes on (`generous`), a generous estimate decides; otherwise the
 *  plain one must. In a narrow column, a line that wraps runs most of its
 *  width. */
function ranOutOfRoom(prev: LineShape, next: LineShape, after: string, { left, right }: Column, generous: boolean, characterShare: boolean): boolean {
  if (right - left < NARROW * prev.size && (!prev.wrappable || prev.right - prev.left < 0.75 * (right - left))) return false;
  const room = right - prev.right;
  const width = next.right - next.left;
  let space: number;
  let word: number;
  if (characterShare) {
    space = SPACE * next.size;
    word = width * Array.from(firstWord(after)).length / Array.from(after).length;
  } else {
    const glyphs = glyphWidth(after);
    space = width * glyphWidth(' ') / glyphs;
    word = width * glyphWidth(firstWord(after)) / glyphs;
  }
  return space + word > room || (generous && space + word * SLACK > room);
}

/** A break that no hint joined where the page would have let one: the next
 *  line goes on in the same paragraph, the page shows where the column
 *  ends, and the line before ran out of room. A labeled list is its own
 *  hint (see extractCoursework). */
function possibleWrap(
  shapes: Array<LineShape | null>, index: number, texts: string[], pitch: Map<number, number>,
  column: (index: number) => Column, edges: readonly boolean[],
): boolean {
  const prev = shapes[index - 1];
  const next = shapes[index];
  return !!prev && !!next && sameParagraph(shapes, index, texts, pitch)
    && ranOutOfRoom(prev, next, texts[index].trim(), column(index - 1), false, false) && edgeShown(shapes, index - 1, texts, edges);
}

/** Page text in PDF.js reading order. Runs are spaced by their geometry, so a
 *  word printed as several glyph runs ("Classi" "fi" "er") stays one word, and
 *  a line that only wraps is joined back into its paragraph. Items without a
 *  usable position keep the positionless rules: a space between items, a
 *  newline at every PDF.js line end. This does not reorder multi-column text.
 *  `possibleWraps` holds the offsets of the line breaks left in the text
 *  that the page would have let a hint join (see possibleWrap). */
function pageText(items: readonly unknown[]): { text: string; possibleWraps: number[] } {
  let text = '';
  const breaks: number[] = [];
  const lines: VisualLine[] = [];
  let line: VisualLine = { runs: [], gaps: [], positioned: true };
  for (const entry of items) {
    if (!entry || typeof entry !== 'object' || !('str' in entry)) continue;
    const item = entry as PdfTextItem;
    const run = positioned(item);
    const last = line.runs[line.runs.length - 1];
    const gap = run && last && Math.abs(run.y - last.y) <= Math.max(run.size, last.size) / 2
      ? run.x - (last.x + last.width) : null;
    const size = run && last ? Math.max(run.size, last.size) : 0;
    // A run that starts far left of where the last one ended is another
    // field painted out of order (a right-floated date before its title).
    const touching = gap !== null && Math.abs(gap) <= TOUCH * size;
    if (text && !/\s$/.test(text) && item.str && !/^\s/.test(item.str) && !touching) {
      text += gap !== null && gap > WIDE * size ? '\t' : ' ';
    }
    const wideSpace = !item.str.trim() && run && run.width > WIDE * run.size;
    text += wideSpace ? '\t' : item.str.replace(KANGXI_RADICAL, (radical) => radical.normalize('NFKC'));
    if (item.str.trim()) {
      if (!run) line.positioned = false;
      else {
        if (gap !== null) line.gaps.push(gap);
        line.runs.push(run);
      }
    }
    if (item.hasEOL && !text.endsWith('\n')) {
      breaks.push(text.length);
      text += '\n';
      lines.push(line);
      line = { runs: [], gaps: [], positioned: true };
    }
  }
  lines.push(line);
  const texts = lines.map((_, index) => text.slice(index ? breaks[index - 1] + 1 : 0, breaks[index] ?? text.length));
  const shapes = lines.map((visual, index) => shapeOf(visual, texts[index]));
  // The ordinary baseline step per font size: a larger step is a paragraph gap.
  const pitch = new Map<number, number>();
  for (let index = 1; index < shapes.length; index++) {
    const prev = shapes[index - 1];
    const next = shapes[index];
    if (!prev || !next || Math.abs(prev.size - next.size) > 0.05 * prev.size) continue;
    const step = prev.baseline - next.baseline;
    const key = Math.round(prev.size * 2);
    if (step >= 0.8 * prev.size && step < (pitch.get(key) ?? Infinity)) pitch.set(key, step);
  }
  const glyph = texts.map(glyphLine);
  // A line that hangs under the text of the glyph item above it, as that
  // item's wrapped lines do; the next item would open at the glyph.
  const hangs: boolean[] = [];
  let item: LineShape | null = null;
  for (const [index, shape] of shapes.entries()) {
    hangs.push(!glyph[index] && !!shape && !!item && Math.abs(shape.left - item.textLeft) < Math.abs(shape.left - item.left));
    if (!hangs[index]) item = glyph[index] ? shape : null;
  }
  const periodItems = glyphItemsEndWithStop(texts, (index) => !!shapes[index]?.tabular);
  // Each line's column is measured once, and only for a line that may wrap
  // or a row that may show the column's edge.
  const columns: Column[] = [];
  const column = (index: number) => (columns[index] ??= columnOf(shapes, shapes[index]!));
  const edges = shapes.map((shape, index) => !!shape && ((shape.tabular && column(index).right - shape.right <= REACH * shape.size)
    || (index + 1 < texts.length && wrapSeparator(shapes, index + 1, texts, pitch, false, column, null, hangs) !== null)));
  let out = texts[0];
  let bulletItem = glyph[0];
  const possibleWraps: number[] = [];
  for (let index = 1; index < texts.length; index++) {
    const separator = wrapSeparator(shapes, index, texts, pitch, bulletItem && periodItems, column, edges, hangs);
    // A joined line stays in the item it continues; any other line opens one.
    if (separator === null) {
      bulletItem = glyph[index];
      if (possibleWrap(shapes, index, texts, pitch, column, edges)) possibleWraps.push(out.length);
    }
    out += separator ?? '\n';
    out += texts[index];
  }
  return { text: out, possibleWraps };
}

function resourceFailure(): ResumeParseResponse {
  return {
    extracted_skills: [], skill_evidence: [], extracted_coursework: [], raw_text: '',
    success: false, error_code: 'pdf_resources_unavailable',
    message: 'Required reading resources could not load. Please try again; your saved resume has not been replaced.',
  };
}

export async function parseResumePDF(file: File): Promise<ResumeParseResponse> {
  const pdfjsLib = await import('pdfjs-dist');
  pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
    'pdfjs-dist/build/pdf.worker.min.mjs',
    import.meta.url,
  ).toString();

  const arrayBuffer = await file.arrayBuffer();
  const resources = createPdfResourceLoaders(window.location.origin);
  const pdf = await pdfjsLib.getDocument({
    data: arrayBuffer,
    // Copied from the installed PDF.js version before dev/build. CJK PDFs
    // can otherwise lose glyphs while getTextContent still resolves.
    cMapUrl: PDF_CMAP_URL,
    cMapPacked: true,
    standardFontDataUrl: PDF_STANDARD_FONT_URL,
    CMapReaderFactory: resources.CMapReaderFactory,
    StandardFontDataFactory: resources.StandardFontDataFactory,
    useWorkerFetch: false,
  }).promise;

  const textParts: string[] = [];
  const possibleWraps = new Set<number>();
  let offset = 0;
  const pagesWithoutText: number[] = [];
  let characterCount = 0;
  try {
    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      try {
        const content = await page.getTextContent();
        if (resources.hasFailure()) return resourceFailure();
        // PDF.js includes marked-content objects without str.
        const { text, possibleWraps: wraps } = pageText(content.items);
        characterCount += resumeTextCharacters(text) + (i > 1 ? 1 : 0);
        if (characterCount > MAX_RESUME_TEXT_CHARACTERS) {
          return {
            extracted_skills: [], skill_evidence: [], extracted_coursework: [], raw_text: '',
            success: false, error_code: 'text_too_long',
            message: 'The PDF exceeds the supported 60,000 text characters. The saved resume has not been replaced.',
          };
        }
        if (!text.trim()) pagesWithoutText.push(i);
        for (const at of wraps) possibleWraps.add(offset + at);
        offset += text.length + 1;
        textParts.push(text);
      } finally {
        page.cleanup();
      }
    }
  } catch (error) {
    if (resources.hasFailure()) return resourceFailure();
    throw error;
  } finally {
    await pdf.destroy();
  }

  const rawText = textParts.join('\n');
  if (!rawText.trim()) {
    return {
      extracted_skills: [],
      skill_evidence: [],
      extracted_coursework: [],
      raw_text: '',
      success: false,
      error_code: 'no_readable_text',
      message: 'Could not extract text from PDF. The file may be image-based.',
    };
  }

  const hits = extractSkills(rawText);
  const coursework = extractCoursework(rawText, possibleWraps);
  const interests = extractResearchInterests(rawText);

  return {
    extracted_skills: hits.map((h) => h.skill),
    skill_evidence: hits,
    extracted_coursework: coursework,
    raw_text: rawText,
    success: true,
    message: `Extracted ${hits.length} skills, ${coursework.length} courses from resume.`,
    suggested_interests: interests,
    pages_without_text: pagesWithoutText,
  };
}
