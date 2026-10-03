import type { EvidenceLink, RewriteOp } from '@/lib/types';

type Replier = (path: string, vars?: Record<string, string | number>) => string;

// Nothing to adapt, versus a suggestion the checks turned down.
const NO_CHANGE = new Set(['no_link', 'already_aligned', 'no_safe_change', 'cosmetic_only', 'target_has_no_text', 'no_change']);
const KEPT = new Set([...NO_CHANGE, 'beyond_allowed_edit', 'rewrite_rejected', 'review_rejected', 'review_unavailable', 'model_unavailable']);

/** The badge and reason for a bullet kept as written, or null for a code this client does not know. */
export function keptExplanation(code: string | null | undefined, t: Replier): { label: string; reason: string; neutral: boolean } | null {
  if (!code || !KEPT.has(code)) return null;
  const neutral = NO_CHANGE.has(code);
  return { label: t(neutral ? 'tailor.keptNoChange' : 'tailor.keptYourWording'), reason: t(`tailor.keep.${code}`), neutral };
}

/** What a reviewed rewrite changed, and why. A link reads as a match only when the
 * faithfulness review confirmed it; otherwise only the opportunity's own words are quoted. */
export default function RewriteWhy({ links = [], ops = [], t }: { links?: EvidenceLink[]; ops?: RewriteOp[]; t: Replier }) {
  const lines = [...new Set(links.map((link) => link.entailed
    ? t('tailor.whyMatch', { term: link.target_evidence.quote, source: link.source_evidence.quote })
    : t('tailor.whyQuote', { quote: link.target_evidence.quote })))];
  if (!ops.length && !lines.length) return null;
  return (
    <div className="mt-2 space-y-1">
      {ops.length > 0 && (
        <ul className="flex flex-wrap gap-1" aria-label={t('tailor.changesLabel')}>
          {ops.map((op) => (
            <li key={op} className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700">{t(`tailor.ops.${op}`)}</li>
          ))}
        </ul>
      )}
      {lines.map((line) => <p key={line} className="text-[11.5px] text-gray-500">{line}</p>)}
    </div>
  );
}
