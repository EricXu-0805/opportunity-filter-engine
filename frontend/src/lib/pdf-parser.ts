import type { ResumeParseResponse } from './types';
import {
  BULLET_LINE, firstWord, glyphItemsEndWithStop, glyphLine, lineBreakText, MAX_RESUME_TEXT_CHARACTERS,
  resumeTextCharacters, wrapEvidence, wrapJoin, wrapsWithoutEvidence,
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
const SLACK = 1.3;
const PITCH_SLACK = 1.15;

const BULLET_GLYPH = /^[•●▪◦‣∙·*–—\-■►➢✓◆\uf0b7\uf0a7\uf076\uf0d8\uf0fc]$/u;
const WRAPPABLE = /\S\s+\S|[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]./u;
// Fonts that map CJK glyphs to Kangxi radicals instead of the ideographs
// ("使⽤" for "使用") print correctly but extract as different characters.
const KANGXI_RADICAL = /[\u2f00-\u2fd5]/gu;

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

/** The separator for a visual line break that is only a wrap, or null for a
 *  real one. A wrap continues the same paragraph: same style, size and
 *  alignment, ordinary line pitch, and the previous line stops where the next
 *  line's first word could not have fitted. Bullets, headings, table-like
 *  rows, contact details and finished sentences always start a new line, and
 *  the words at the break must carry the line on (resume-input.ts).
 *  `periodItem` says the previous line belongs to an item that opened with a
 *  bullet glyph or number, on a page whose glyph items end with a full stop,
 *  so a next line that ends a sentence finishes that item. */
function wrapSeparator(
  shapes: Array<LineShape | null>, index: number, texts: string[], pitch: Map<number, number>, periodItem: boolean,
): string | null {
  const prev = shapes[index - 1];
  const next = shapes[index];
  const before = texts[index - 1].trim();
  const after = texts[index].trim();
  if (!prev || !next || !before || !after || prev.tabular || next.tabular || lineBreakText(before, after)) return null;
  if (![...next.fonts].some((font) => prev.fonts.has(font)) || Math.abs(prev.size - next.size) > 0.05 * prev.size) return null;
  const step = prev.baseline - next.baseline;
  if (step < 0.8 * prev.size || step > PITCH_SLACK * (pitch.get(Math.round(prev.size * 2)) ?? Infinity)) return null;
  if (Math.abs(next.left - prev.left) > ALIGN * prev.size && Math.abs(next.left - prev.textLeft) > ALIGN * prev.size) return null;
  const evidence = wrapEvidence(before, after);
  if (!evidence && !wrapsWithoutEvidence(after, periodItem)) return null;
  // The column's right edge, from the lines aligned with this one. A line
  // with no space in it cannot wrap and may overflow (a long email address).
  let left = prev.left;
  let right = -Infinity;
  for (const other of shapes) {
    if (!other) continue;
    const tolerance = COLUMN * Math.max(other.size, prev.size);
    if (Math.abs(other.left - prev.left) > tolerance && Math.abs(other.left - prev.textLeft) > tolerance) continue;
    left = Math.min(left, other.left);
    if (other.wrappable || other.tabular) right = Math.max(right, other.right);
  }
  if (right === -Infinity) right = prev.right;
  // Glyph widths are unknown, so the first word's width is estimated from
  // the next line's average character width. Where the text itself says it
  // goes on, a generous estimate decides; otherwise the plain one must.
  const room = right - prev.right;
  const space = SPACE * next.size;
  const word = Array.from(firstWord(after)).length * (next.right - next.left) / Array.from(after).length;
  if (right - left < NARROW * prev.size) {
    // A narrow column of short items ("Python" / "SolidWorks") is a list, not
    // a paragraph, unless the text itself says it goes on.
    if (!prev.wrappable || prev.right - prev.left < 0.75 * (right - left) || !evidence || space + word * SLACK <= room) return null;
  } else if (space + word <= room && !(evidence && space + word * SLACK > room)) return null;
  return wrapJoin(before, after);
}

/** Page text in PDF.js reading order. Runs are spaced by their geometry, so a
 *  word printed as several glyph runs ("Classi" "fi" "er") stays one word, and
 *  a line that only wraps is joined back into its paragraph. Items without a
 *  usable position keep the positionless rules: a space between items, a
 *  newline at every PDF.js line end. This does not reorder multi-column text. */
function pageText(items: readonly unknown[]): string {
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
  const periodItems = glyphItemsEndWithStop(texts, (index) => !!shapes[index]?.tabular);
  let out = texts[0];
  let bulletItem = glyph[0];
  for (let index = 1; index < texts.length; index++) {
    const separator = wrapSeparator(shapes, index, texts, pitch, bulletItem && periodItems);
    // A joined line stays in the item it continues; any other line opens one.
    if (separator === null) bulletItem = glyph[index];
    out += separator ?? '\n';
    out += texts[index];
  }
  return out;
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
  const pagesWithoutText: number[] = [];
  let characterCount = 0;
  try {
    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      try {
        const content = await page.getTextContent();
        if (resources.hasFailure()) return resourceFailure();
        // PDF.js includes marked-content objects without str.
        const text = pageText(content.items);
        characterCount += resumeTextCharacters(text) + (i > 1 ? 1 : 0);
        if (characterCount > MAX_RESUME_TEXT_CHARACTERS) {
          return {
            extracted_skills: [], skill_evidence: [], extracted_coursework: [], raw_text: '',
            success: false, error_code: 'text_too_long',
            message: 'The PDF exceeds the supported 60,000 text characters. The saved resume has not been replaced.',
          };
        }
        if (!text.trim()) pagesWithoutText.push(i);
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
  const coursework = extractCoursework(rawText);
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
