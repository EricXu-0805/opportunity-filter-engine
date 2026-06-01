'use client';

import { useState, useEffect, useRef, useMemo } from 'react';
import {
  X,
  Copy,
  Loader2,
  AlertCircle,
  Sparkles,
  CheckCircle,
  RefreshCw,
  Info,
} from 'lucide-react';
import { tailorResume } from '@/lib/api';
import type { ProfileData, TailorResponse, TailoredBullet } from '@/lib/types';
import { useT } from '@/i18n/client';

/**
 * R71 resume-tailor modal — side-by-side originals vs AI rewrite.
 *
 * Contract:
 *  - User pastes bullets into the left textarea (auto-prefilled from
 *    `profile.resume_text` via bullet-line heuristic if present).
 *  - Clicking "Tailor with AI" calls POST /api/tailor. The backend
 *    NEVER raises 5xx for LLM issues — it returns `method: "fallback"`
 *    plus warnings on every failure mode (no provider, malformed JSON,
 *    anti-fabrication catch). The UI translates each warning into a
 *    user-facing message via i18n.
 *  - When `method === "ai"`, the right panel renders each AI bullet
 *    with its `source_evidence` quote.
 *  - When `method === "fallback"`, the right panel renders the user's
 *    own originals with a "showing originals" chip + the relevant
 *    warning hint.
 *
 * State lives in this component (modal-local). Parent only owns the
 * open/close boolean — mirrors ColdEmailModal's pattern.
 */
interface TailorModalProps {
  isOpen: boolean;
  onClose: () => void;
  profile: ProfileData;
  opportunityId: string;
  opportunityTitle: string;
}

// Heuristic to pre-fill bullets from a parsed resume's `raw_text`. We
// don't want to invoke an LLM here — just look for lines that look
// resume-bullet-shaped (start with •, -, *, –, —, +, or a digit).
// Keeps the bar low: any string with a leading bullet glyph counts.
const BULLET_PREFIX_RE = /^\s*([•\-*–—+]|\d+[.)])\s+(.+)$/;

function extractBulletLines(resumeText: string | undefined, limit = 12): string[] {
  if (!resumeText) return [];
  const out: string[] = [];
  for (const raw of resumeText.split(/\r?\n/)) {
    const m = raw.match(BULLET_PREFIX_RE);
    if (m) {
      const cleaned = m[2].trim();
      if (cleaned.length >= 10) out.push(cleaned);
    }
    if (out.length >= limit) break;
  }
  return out;
}

function parseBullets(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .map((l) => {
      // Tolerate user pasting raw "• " or "- " prefixes — strip them.
      const m = l.match(BULLET_PREFIX_RE);
      return m ? m[2].trim() : l;
    })
    .filter((l) => l.length > 0);
}

type Replier = (path: string, vars?: Record<string, string | number>) => string;

/**
 * Map a backend `warnings[]` entry to a user-facing i18n key. Order
 * matters — we return the first match because the route appends
 * `bullet_<i>_rejected_fabrication: ...` warnings BEFORE the catch-all
 * `all_bullets_rejected`, and the more-specific "fabrication caught"
 * message gives the user actionable info.
 */
function pickWarningMessage(warnings: string[], t: Replier): string | null {
  if (warnings.length === 0) return null;
  if (warnings.some((w) => w.startsWith('bullet_') && w.includes('rejected_fabrication'))) {
    return t('tailor.warnings.fabricationCaught');
  }
  if (warnings.includes('all_bullets_rejected')) {
    return t('tailor.warnings.allRejected');
  }
  if (warnings.includes('llm_not_configured')) {
    return t('tailor.warnings.llmUnavailable');
  }
  if (warnings.includes('llm_failed_or_invalid_json')) {
    return t('tailor.warnings.llmFailed');
  }
  if (warnings.includes('no_bullets_provided')) {
    return t('tailor.warnings.noBullets');
  }
  return null;
}

export default function TailorModal({
  isOpen,
  onClose,
  profile,
  opportunityId,
  opportunityTitle,
}: TailorModalProps) {
  // R71-D: `locale` flows from the i18n context all the way down to the
  // backend so the LLM returns bullets in the user's current display
  // language. The backend tolerates unknown / region-tagged values by
  // falling back to 'en', so we can pipe `useT().locale` through raw.
  const { t, locale } = useT();

  // Pre-fill from `profile.resume_text` if we can pluck bullet-shaped
  // lines; otherwise leave the textarea empty so the user pastes their
  // own. `useMemo` so the auto-prefill is stable per profile but doesn't
  // re-run on every keystroke.
  const initialBullets = useMemo(
    () => extractBulletLines(profile.resume_text).join('\n'),
    [profile.resume_text],
  );

  const [draft, setDraft] = useState(initialBullets);
  const [loading, setLoading] = useState(false);
  const [resp, setResp] = useState<TailorResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  // R71-E: snapshot the bullets actually submitted to the backend so
  // we can render each tailored bullet next to its source. We can't
  // just re-parse `draft` because the user might edit the textarea
  // *after* clicking Generate and we'd then pair the wrong originals.
  const [submittedBullets, setSubmittedBullets] = useState<string[]>([]);

  const modalRef = useRef<HTMLDivElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  // Reset modal-local state every time the modal opens. Splitting this
  // into two effects would race a stale `resp` against the next open's
  // setDraft, so we batch it here.
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect --
       Modal-lifecycle effect mirroring ColdEmailModal — reset every
       internal slice on open so the next render starts from a known
       state and clears any leftover AI result. */
    if (isOpen) {
      setDraft(initialBullets);
      setResp(null);
      setError(null);
      setCopied(false);
      setLoading(false);
      setSubmittedBullets([]);
    }
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [isOpen, initialBullets]);

  // Focus trap + escape + body-overflow lock. Lifted verbatim from
  // ColdEmailModal so the two modals feel identical to keyboard users.
  useEffect(() => {
    if (!isOpen) return;
    previouslyFocusedRef.current = document.activeElement as HTMLElement;

    const modal = modalRef.current;
    if (modal) {
      const focusable = modal.querySelector<HTMLElement>(
        'button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])',
      );
      focusable?.focus();
    }

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== 'Tab' || !modalRef.current) return;
      const focusables = modalRef.current.querySelectorAll<HTMLElement>(
        'button, [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = prevOverflow;
      previouslyFocusedRef.current?.focus();
    };
  }, [isOpen, onClose]);

  async function handleGenerate() {
    const bullets = parseBullets(draft);
    if (bullets.length === 0) {
      setError(t('tailor.fillBulletsFirst'));
      return;
    }
    setLoading(true);
    setError(null);
    setCopied(false);
    // R71-E: snapshot before the await so a textarea edit during the
    // request can't desync the rendered pairing.
    setSubmittedBullets(bullets);
    try {
      const data = await tailorResume(profile, opportunityId, bullets, { locale });
      setResp(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('tailor.failedToTailor'));
    } finally {
      setLoading(false);
    }
  }

  async function handleCopyAll() {
    if (!resp || resp.tailored_bullets.length === 0) return;
    const text = resp.tailored_bullets.map((b) => `• ${b.text}`).join('\n');
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (!isOpen) return null;

  const warningMessage = resp ? pickWarningMessage(resp.warnings, t) : null;
  const isFallback = resp?.method === 'fallback';
  const hasResults = resp !== null && resp.tailored_bullets.length > 0;

  return (
    <div
      className="fixed inset-0 z-50 flex sm:items-center sm:justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tailor-modal-title"
    >
      <div
        className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      <div
        ref={modalRef}
        className="relative w-full sm:max-w-5xl sm:mx-4 bg-white sm:rounded-2xl shadow-2xl h-full sm:h-auto sm:max-h-[90vh] flex flex-col overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-start justify-between px-4 sm:px-6 py-3 sm:py-4 border-b border-gray-100 shrink-0">
          <div className="flex items-start gap-3 min-w-0">
            <div className="w-9 h-9 rounded-xl bg-indigo-50 flex items-center justify-center shrink-0" aria-hidden="true">
              <Sparkles className="w-5 h-5 text-indigo-600" />
            </div>
            <div className="min-w-0">
              <h2
                id="tailor-modal-title"
                className="text-lg font-bold text-gray-900"
              >
                {t('tailor.title')}
              </h2>
              <p className="text-sm text-gray-500 truncate max-w-md">
                {opportunityTitle}
              </p>
              <p className="text-xs text-gray-400 mt-1 max-w-md hidden sm:block">
                {t('tailor.subtitle')}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 transition-colors shrink-0"
            aria-label={t('tailor.closeAria')}
          >
            <X className="w-5 h-5 text-gray-400" aria-hidden="true" />
          </button>
        </div>

        {/* Body — two panel layout */}
        <div className="flex-1 flex flex-col md:flex-row min-h-0">
          {/* Left panel — originals */}
          <div className="flex-1 flex flex-col md:border-r border-gray-100 min-w-0">
            <div className="px-5 pt-4 pb-2 shrink-0">
              <label
                htmlFor="tailor-bullets-input"
                className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5"
              >
                {t('tailor.originalHeading')}
              </label>
              <p className="text-xs text-gray-400 mb-2">
                {t('tailor.bulletsHint')}
              </p>
            </div>
            <div className="flex-1 px-5 pb-4 min-h-0">
              <textarea
                id="tailor-bullets-input"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder={t('tailor.bulletsPlaceholder')}
                rows={12}
                className="w-full h-full min-h-[200px] px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-700 leading-relaxed focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none transition-all resize-none"
              />
            </div>
          </div>

          {/* Right panel — tailored output */}
          <div className="w-full md:w-1/2 lg:w-[480px] flex flex-col bg-gray-50/60 min-w-0 border-t md:border-t-0 border-gray-100">
            <div className="flex items-center justify-between gap-2 px-5 pt-4 pb-2 shrink-0">
              <label
                className="block text-xs font-semibold text-gray-500 uppercase tracking-wider"
              >
                {t('tailor.tailoredHeading')}
              </label>
              {resp && (
                <span
                  className={`text-[10px] font-semibold px-2 py-0.5 rounded-full uppercase tracking-wider ${
                    isFallback
                      ? 'bg-amber-50 text-amber-700'
                      : 'bg-indigo-100 text-indigo-700'
                  }`}
                >
                  {isFallback ? t('tailor.methodFallback') : t('tailor.methodAi')}
                </span>
              )}
            </div>

            <div className="flex-1 overflow-y-auto px-5 pb-4 space-y-3">
              {loading && (
                <div className="flex flex-col items-center justify-center py-16 gap-3">
                  <Loader2 className="w-7 h-7 text-indigo-500 animate-spin" />
                  <p className="text-sm text-gray-500">
                    {t('tailor.generating')}
                  </p>
                </div>
              )}

              {!loading && error && (
                <div className="flex flex-col items-center justify-center py-12 gap-3">
                  <AlertCircle className="w-7 h-7 text-red-500" />
                  <p className="text-sm text-red-600 text-center">{error}</p>
                  <button
                    type="button"
                    onClick={handleGenerate}
                    className="text-sm text-indigo-600 underline hover:text-indigo-700"
                  >
                    {t('tailor.tryAgain')}
                  </button>
                </div>
              )}

              {!loading && !error && !resp && (
                <div className="flex flex-col items-center justify-center py-16 gap-3 text-center">
                  <Sparkles className="w-7 h-7 text-indigo-300" />
                  <p className="text-sm text-gray-500 max-w-xs">
                    {t('tailor.noBulletsYet')}
                  </p>
                </div>
              )}

              {!loading && !error && resp && warningMessage && (
                <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200 text-[12.5px] text-amber-800">
                  <Info className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" aria-hidden="true" />
                  <span>{warningMessage}</span>
                </div>
              )}

              {!loading && !error && resp && isFallback && (
                <p className="text-xs text-gray-500 px-1">
                  {t('tailor.fallbackHint')}
                </p>
              )}

              {!loading && !error && hasResults && (
                <ul className="space-y-3">
                  {resp.tailored_bullets.map((b: TailoredBullet, i: number) => {
                    // R71-E: pair each tailored bullet with its source.
                    // `source_index` is set by the backend and clamped to
                    // the submitted-bullets length, so this access is
                    // always safe; the `??` is a defensive belt-and-
                    // suspenders for stale snapshots.
                    const original = submittedBullets[b.source_index] ?? '';
                    const isFallbackBullet = b.source_evidence === 'original';
                    const sameAsOriginal =
                      isFallbackBullet || original.trim() === b.text.trim();

                    return (
                      <li
                        key={i}
                        className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden"
                      >
                        {/* Original (R71-E side-by-side). Hidden when the
                            backend echoed the original verbatim — showing
                            the same text twice adds noise without value. */}
                        {original && !sameAsOriginal && (
                          <div className="px-4 py-2.5 bg-gray-50/80 border-b border-gray-100">
                            <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1">
                              {t('tailor.originalRowLabel')}
                            </p>
                            <p className="text-[12.5px] text-gray-500 leading-relaxed line-through decoration-gray-300/70">
                              {original}
                            </p>
                          </div>
                        )}
                        <div className="px-4 py-3">
                          {!sameAsOriginal && (
                            <p className="text-[10px] font-semibold uppercase tracking-wider text-indigo-500 mb-1">
                              {t('tailor.tailoredRowLabel')}
                            </p>
                          )}
                          <p className="text-[13.5px] text-gray-800 leading-relaxed">
                            {b.text}
                          </p>
                          {b.source_evidence && (
                            <p className="mt-2 text-[11.5px] text-gray-500 italic">
                              <span className="font-medium not-italic uppercase tracking-wider text-[10px] text-gray-400">
                                {t('tailor.sourceLabel')}:
                              </span>{' '}
                              {isFallbackBullet
                                ? t('tailor.sourceOriginal')
                                : `"${b.source_evidence}"`}
                            </p>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-3 border-t border-gray-100 bg-gray-50/50 shrink-0">
          {resp && hasResults && (
            <button
              type="button"
              onClick={handleCopyAll}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors"
            >
              {copied ? (
                <>
                  <CheckCircle className="w-4 h-4 text-emerald-500" />
                  {t('tailor.copied')}
                </>
              ) : (
                <>
                  <Copy className="w-4 h-4" />
                  {t('tailor.copyAll')}
                </>
              )}
            </button>
          )}
          <button
            type="button"
            onClick={handleGenerate}
            disabled={loading || draft.trim().length === 0}
            className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-semibold text-white bg-gradient-to-r from-indigo-600 to-fuchsia-500 rounded-xl hover:from-indigo-700 hover:to-fuchsia-600 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm transition-all"
          >
            {resp ? (
              <>
                <RefreshCw className="w-4 h-4" />
                {t('tailor.regenerate')}
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4" />
                {t('tailor.generate')}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
