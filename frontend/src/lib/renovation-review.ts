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
