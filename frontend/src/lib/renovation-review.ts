import type { RenovatedBullet, RenovatedSection, RenovatedVariant, RenovationDoc } from './types';

/**
 * Which renovation wording may be shown as a bullet's current text.
 *
 * Rewrites pass the faithfulness review from the w14 tailor rules on, each in its
 * own bullet's language. Main (w13) wrote every renovation rewrite in the UI
 * language with no review, and docs saved under it hold such variants; a browser
 * can also meet a w13 backend while a deploy is in flight (docs/RELEASE.md).
 */

const CJK = /[一-鿿]/;
const RULES = /^w(\d+)(?:\.\d+)*$/;

/** Whether a tailor pipeline version runs the faithfulness review (w14 or later). */
export const isReviewedRules = (version: unknown): version is string =>
  typeof version === 'string' && Number(RULES.exec(version)?.[1] ?? 0) >= 14;

/** The student's own edit, or a rewrite a w14 review accepted, in the script of its bullet.
 * A "translate" op (w14.0) is never reviewed wording: every rewrite now stays in its own language. */
export function isReviewedVariant(variant: RenovatedVariant, baseText: string): boolean {
  if (variant.source === 'user') return true;
  return isReviewedRules(variant.reviewed) && Array.isArray(variant.ops) && variant.ops.length > 0
    && !(variant.ops as string[]).includes('translate') && CJK.test(variant.text) === CJK.test(baseText);
}

/** The text a bullet shows, copies and sends as its current wording: its current variant when a
 * review accepted it or the student wrote it, else the bullet's own text. Every view of a saved
 * doc reads it: the editor, copy-all, the history preview and the save-conflict preview. */
export function shownText(bullet: RenovatedBullet): string {
  const variant = bullet.current >= 0 ? bullet.variants[bullet.current] : undefined;
  return variant && isReviewedVariant(variant, bullet.base_text) ? variant.text : bullet.base_text;
}

/** The variant one step back (-1) or forward (+1) shows: the nearest one a review accepted or the
 * student wrote, or -1 (the bullet's own text) going back. null when there is no such step. An
 * unreviewed variant stays in the stored history but is never stepped onto. */
export function reviewedStep(bullet: RenovatedBullet, direction: 1 | -1): number | null {
  const from = Math.min(bullet.current, bullet.variants.length);
  for (let index = from + direction; index >= 0 && index < bullet.variants.length; index += direction) {
    if (isReviewedVariant(bullet.variants[index], bullet.base_text)) return index;
  }
  return direction < 0 && from >= 0 ? -1 : null;
}

/** A saved doc as it may open: a bullet whose current variant no review accepted opens at its own
 * text, and the variant stays in its stored history, where no step reaches it (reviewedStep). */
export function reviewedRenovation(doc: RenovationDoc): RenovationDoc {
  return {
    ...doc,
    sections: doc.sections.map((section) => ({
      ...section,
      bullets: section.bullets.map((bullet) => {
        const shown = bullet.current >= 0 ? bullet.variants[bullet.current] : undefined;
        return shown && !isReviewedVariant(shown, bullet.base_text) ? { ...bullet, current: -1 } : bullet;
      }),
    })),
  };
}

/** A renovation response's sections: its rewrites only from reviewed (w14+) rules, each stamped
 * with them; a bullet whose rewrite is dropped stays at its own text. */
export function reviewedSections(sections: RenovatedSection[], rules: unknown): RenovatedSection[] {
  return sections.map((section) => ({
    ...section,
    bullets: section.bullets.map((bullet) => {
      const variants = isReviewedRules(rules)
        ? bullet.variants.filter((variant) => (variant.ops?.length ?? 0) > 0).map((variant) => ({ ...variant, reviewed: rules }))
        : [];
      if (variants.length === bullet.variants.length) return { ...bullet, variants };
      return { ...bullet, variants, current: -1, note: bullet.note ?? 'review_unavailable' };
    }),
  }));
}

// The names /tailor/structure gives a section the student did not head in the résumé: the closed
// set the full-target export prints (backend/lib/target_resume_export.py HEADINGS), in the
// language of the section's lines. Research, projects and leadership print as activities.
const STANDARD_HEADINGS = {
  en: { education: 'Education', activities: 'Experience', skills: 'Skills', other: 'Additional information' },
  zh: { education: '教育经历', activities: '项目与经历', skills: '技能', other: '其他信息' },
} as const;
const KIND_HEADING: Record<string, keyof typeof STANDARD_HEADINGS.en> = {
  education: 'education', skills: 'skills', other: 'other',
  experience: 'activities', projects: 'activities', research: 'activities', leadership: 'activities',
};
const headingKey = (value: string) => value.normalize('NFKC').replace(/\s+/gu, ' ').trim().toLowerCase().replace(/[\s:]+$/u, '');
// A row's text as backend _resume_rows reads it: NFKC, its spaces collapsed.
const rowText = (value: string) => value.normalize('NFKC').replace(/\s+/gu, ' ').trim();
// A row that opens with a bullet glyph or a number (backend _LINE_GLYPH: resume-input.ts BULLET_LINE's
// glyphs and "+"), and an inline glyph (_INLINE_GLYPH).
const LINE_GLYPH = /^(?:[•\-*–—+▪●◦·‣∙■►➢✓◆\uf0b7\uf0a7\uf076\uf0d8\uf0fc]|\(?\d{1,2}[.)]|\d+[.)])\s+/u;
// What else may stand before a line's first word (backend _LEAD_MARKS): a list number, Word's "o", or a
// run of marks, with or without a space; never a sign before its number ("~40") or a digit run's inside ("1.5x").
const LEAD_MARKS = /^(?:\(\d{1,2}\)|\(?\d{1,2}[.)、]|\(?[a-z]\)|[a-z]\.(?=\s)|o(?=\s)|[^\p{L}\p{N}_\s]+)\s*/iu;
const SIGNS = /[~≈<>≤≥±+=−-]/u;
const INLINE_GLYPH = /\s*[•▪●◦]\s*/u;
const LINE_END = /[\s.;,:。；，：!?！？]+$/u;

/** "zh" when Chinese carries the text, as backend language() reads it. */
function textLanguage(text: string): 'en' | 'zh' {
  const han = text.match(/[\u4e00-\u9fff]/gu)?.length ?? 0;
  if (!han) return 'en';
  const runs = text.match(/[\u4e00-\u9fff]+/gu)?.length ?? 0;
  const leading = /^[^A-Za-z\u4e00-\u9fff]*[\u4e00-\u9fff]/u.test(text);
  return (runs >= 2 || leading) && han >= (text.match(/[A-Za-z]+/gu)?.length ?? 0) ? 'zh' : 'en';
}

/** A row of its own (backend _own_row): a row in capitals, or a short heading in title case. */
function ownRow(line: string): boolean {
  const letters = Array.from(line).filter((character) => /\p{L}/u.test(character));
  if (letters.filter((character) => character !== character.toLowerCase()).length >= 2
      && !letters.some((character) => character !== character.toUpperCase())) return true;
  const bare = line.replace(/:+$/u, '');
  const words = bare.split(/\s+/u).filter((word) => word && word !== '&' && word !== '/');
  return words.length > 0 && words.length <= 4 && line.length <= 40 && /^[A-Za-z &/'-]*$/u.test(bare)
    && /^[A-Z]/u.test(words[0]) && /^[A-Z]/u.test(words[words.length - 1])
    && words.every((word) => /^[A-Z]/u.test(word) || word.length <= 3);
}

/** A row without what stands before its first word (backend _lead_ends): its glyph, list number,
 * circled number ("①", which NFKC reads as "1") or marks, each with what follows it ("• 1. Built"). */
function withoutLead(raw: string, row: string): string {
  let rest = /^\p{No}/u.test(raw) && !/^[\x00-\x7f]/u.test(raw) ? row.slice(raw[0].normalize('NFKC').length).trimStart() : row;
  for (let step = 0; step < 3; step++) {
    const lead = (LINE_GLYPH.exec(rest) ?? LEAD_MARKS.exec(rest))?.[0] ?? '';
    if (!lead || lead.length >= rest.length) break;
    if (/\d/u.test(rest[lead.length]) && (lead === lead.trimEnd() || SIGNS.test(lead))) break;
    rest = rest.slice(lead.length);
  }
  return rest;
}

/** The résumé row a section's line starts on: a row (after its glyph, list number or marks), or a
 * piece after an inline glyph, that is the line or opens it. A glyph row is preferred over another
 * row that only opens it. -1 when no row does. */
function lineRow(raw: string[], rows: string[], line: string): number {
  const key = headingKey(line).replace(LINE_END, '');
  if (key.length < 4) return -1;
  let fallback = -1;
  for (let index = 0; index < rows.length; index++) {
    const bare = withoutLead(raw[index], rows[index]);
    const pieces = bare.split(INLINE_GLYPH).map((piece) => headingKey(piece).replace(LINE_END, ''));
    for (const piece of pieces) {
      if (piece.length < 4 || !key.startsWith(piece)) continue;
      if (piece === key || bare !== rows[index] || INLINE_GLYPH.test(rows[index])) return index;
      if (fallback < 0) fallback = index;
    }
  }
  return fallback;
}

/** The heading a renovated section shows and copies. The model wrote each section's heading and
 * nothing reviewed it; on main /tailor/structure returned it as written, and docs saved then hold
 * it. It is shown only as the student wrote it, by the rule backend _section_heading applies: the
 * heading row nearest above the section's first line, with no row in capitals or a short title-case
 * heading (_own_row), and no row another section of the doc is headed by, in between; never a glyph
 * row; in the résumé's own spelling. Any other heading shows as the standard name of the section's
 * kind, in the language of its lines (of the résumé when it has none). ``sections`` are the doc's
 * sections, whose headings stop the search as backend ``named`` does. */
export function shownHeading(
  section: Pick<RenovatedSection, 'heading' | 'kind' | 'bullets'>,
  resumeText: string,
  sections: readonly Pick<RenovatedSection, 'heading'>[] = [section],
): string {
  const key = headingKey(section.heading ?? '');
  const named = new Set(sections.map((other) => headingKey(other.heading ?? '')).filter(Boolean));
  const raw = resumeText.split(/\r?\n/u).map((line) => line.trim()).filter((line) => rowText(line));
  const rows = raw.map(rowText);
  // The section's first line in the résumé: the earliest row any of its lines starts on.
  const starts = key ? section.bullets.map((bullet) => lineRow(raw, rows, bullet.base_text)).filter((row) => row >= 0) : [];
  const first = starts.length ? Math.min(...starts) : -1;
  for (let index = first - 1; first > 0 && index >= 0; index--) {
    if (headingKey(rows[index]) === key && !LINE_GLYPH.test(rows[index])) return raw[index].replace(/[\s:：]+$/u, '');
    if (named.has(headingKey(rows[index])) || ownRow(rows[index])) break;
  }
  const lines = section.bullets.map((bullet) => bullet.base_text).join(' ');
  return STANDARD_HEADINGS[textLanguage(lines || resumeText)][KIND_HEADING[section.kind] ?? 'other'];
}
