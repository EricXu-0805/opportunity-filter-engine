'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import {
  X,
  Copy,
  Loader2,
  AlertCircle,
  Sparkles,
  CheckCircle,
  RefreshCw,
  Info,
  Pencil,
  RotateCcw,
  Wand2,
  ArrowUpRight,
  ArrowDownRight,
  FileText,
} from 'lucide-react';
import { structureResume, renovateResume, optimizeBullet } from '@/lib/api';
import { saveRenovation, loadRenovation } from '@/lib/supabase';
import type {
  ProfileData,
  ResumeSectionInput,
  RenovationDoc,
  RenovatedBullet,
  RenovatedSection,
} from '@/lib/types';
import { useT } from '@/i18n/client';
import { diffWords, isWhitespace } from '@/lib/word-diff';
import { hashString } from '@/lib/match-utils';

/**
 * Whole-résumé renovation toward ONE opportunity (per-professor by
 * construction — the opportunity record carries pi/org/keywords).
 *
 * Flow: structure (résumé text → sections+bullets, verbatim) → renovate
 * (macro plan: reorder + foreground/keep/demote + grounded rewrites) →
 * per-bullet review on the variant chain:
 *   - Rollback  = move `current` back one step (-1 == the student's own
 *     base_text). Pure pointer move, no LLM → can never fabricate.
 *   - Edit      = append a `user` variant.
 *   - Re-optimize = POST /tailor/bullet; appends a validated `ai` variant
 *     only when the backend accepted it (changed=true).
 * The doc persists per (device, opportunity) via supabase; reopening the
 * modal restores the saved doc instead of re-billing the pipeline.
 */
interface ResumeRenovationModalProps {
  isOpen: boolean;
  onClose: () => void;
  profile: ProfileData;
  opportunityId: string;
  opportunityTitle: string;
}

type Replier = (path: string, vars?: Record<string, string | number>) => string;

function pickRenovationWarning(warnings: string[], t: Replier): string | null {
  if (warnings.length === 0) return null;
  if (warnings.some((w) => w.includes('rejected_fabrication'))) {
    return t('renovate.warnings.fabricationCaught');
  }
  if (warnings.includes('llm_not_configured')) {
    return t('renovate.warnings.llmUnavailable');
  }
  if (warnings.some((w) => w.startsWith('plan_') || w === 'macro_plan_failed')) {
    return t('renovate.warnings.planFailed');
  }
  return null;
}

/** The text a bullet currently shows: its selected variant, or the base. */
function bulletCurrentText(b: RenovatedBullet): string {
  if (b.current >= 0 && b.current < b.variants.length) {
    return b.variants[b.current].text;
  }
  return b.base_text;
}

function DiffLine({
  original,
  tailored,
  side,
}: {
  original: string;
  tailored: string;
  side: 'original' | 'tailored';
}) {
  const segments = diffWords(original, tailored);
  const skip = side === 'original' ? 'added' : 'removed';
  return (
    <>
      {segments
        .filter((s) => s.type !== skip)
        .map((s, idx) => {
          if (s.type === 'equal' || isWhitespace(s.value)) {
            return <span key={idx}>{s.value}</span>;
          }
          if (s.type === 'removed') {
            return (
              <del key={idx} className="text-red-400/90 decoration-red-300">
                {s.value}
              </del>
            );
          }
          return (
            <ins key={idx} className="no-underline bg-emerald-100 text-emerald-800 rounded px-0.5">
              {s.value}
            </ins>
          );
        })}
    </>
  );
}

const SOURCE_CHIP_STYLES: Record<string, string> = {
  base: 'bg-gray-100 text-gray-500',
  macro: 'bg-indigo-50 text-indigo-600',
  ai: 'bg-fuchsia-50 text-fuchsia-600',
  user: 'bg-amber-50 text-amber-700',
};

const ACTION_CHIP: Record<string, { className: string; icon: 'up' | 'down' | null }> = {
  foreground: { className: 'bg-emerald-50 text-emerald-700', icon: 'up' },
  demote: { className: 'bg-gray-100 text-gray-500', icon: 'down' },
  keep: { className: '', icon: null },
};

export default function ResumeRenovationModal({
  isOpen,
  onClose,
  profile,
  opportunityId,
  opportunityTitle,
}: ResumeRenovationModalProps) {
  const { t, locale } = useT();

  // Phase machine: 'idle' (no doc yet, offer to renovate) → 'working'
  // (structure+renovate in flight) → 'doc' (variant-chain review surface).
  // 'restoring' covers the initial saved-doc lookup so the CTA doesn't
  // flash before we know whether a doc exists.
  const [phase, setPhase] = useState<'restoring' | 'idle' | 'working' | 'doc'>('restoring');
  const [workingStep, setWorkingStep] = useState<'structuring' | 'renovating'>('structuring');
  const [doc, setDoc] = useState<RenovationDoc | null>(null);
  const [baseSections, setBaseSections] = useState<ResumeSectionInput[]>([]);
  const [restoredFromSave, setRestoredFromSave] = useState(false);
  const [staleResume, setStaleResume] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  // The last persist payload, so the save-failed state can offer a real
  // retry of exactly what failed (W13).
  const lastPersistRef = useRef<{ doc: RenovationDoc; sections: ResumeSectionInput[] } | null>(null);
  // Per-bullet UI state, keyed by bullet id (ids are unique doc-wide — the
  // backend 422s duplicate ids).
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState('');
  const [optimizingId, setOptimizingId] = useState<string | null>(null);
  const [bulletNotices, setBulletNotices] = useState<Record<string, string>>({});

  const modalRef = useRef<HTMLDivElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  // Reset + restore on every open: a saved doc for this opportunity wins
  // over the empty CTA. setState runs in the async callback.
  useEffect(() => {
    if (!isOpen) return;
    /* eslint-disable react-hooks/set-state-in-effect --
       Modal-lifecycle reset mirroring TailorModal: every slice returns to a
       known state on open before the async restore resolves. */
    setPhase('restoring');
    setDoc(null);
    setBaseSections([]);
    setRestoredFromSave(false);
    setError(null);
    setCopied(false);
    setSaving(false);
    setSavedFlash(false);
    setSaveFailed(false);
    setStaleResume(false);
    setEditingId(null);
    setEditDraft('');
    setOptimizingId(null);
    setBulletNotices({});
    /* eslint-enable react-hooks/set-state-in-effect */
    let ignore = false;
    loadRenovation(opportunityId)
      .then((stored) => {
        if (ignore) return;
        const storedDoc = stored?.doc as unknown as RenovationDoc | undefined;
        if (storedDoc && Array.isArray(storedDoc.sections) && storedDoc.sections.length > 0) {
          // W13 staleness: a doc built from a since-edited résumé must not
          // render as silently current. Legacy docs carry no sig — unknown,
          // so no claim either way.
          setStaleResume(
            typeof storedDoc.resume_sig === 'string' &&
            !!profile.resume_text &&
            storedDoc.resume_sig !== hashString(profile.resume_text),
          );
          setDoc(storedDoc);
          setBaseSections(
            Array.isArray((stored?.base_snapshot as { sections?: ResumeSectionInput[] })?.sections)
              ? (stored!.base_snapshot as { sections: ResumeSectionInput[] }).sections
              : [],
          );
          setRestoredFromSave(true);
          setPhase('doc');
        } else {
          setPhase('idle');
        }
      })
      .catch(() => {
        if (!ignore) setPhase('idle');
      });
    return () => {
      ignore = true;
    };
    // profile.resume_text feeds the staleness comparison — a resume edit
    // while the modal is closed must re-evaluate on the next open.
  }, [isOpen, opportunityId, profile.resume_text]);

  // Focus trap + escape + body-overflow lock, lifted from TailorModal so the
  // renovation modal feels identical to keyboard users.
  useEffect(() => {
    if (!isOpen) return;
    previouslyFocusedRef.current = document.activeElement as HTMLElement;
    const modal = modalRef.current;
    if (modal) {
      modal
        .querySelector<HTMLElement>(
          'button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])',
        )
        ?.focus();
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

  const persist = useCallback(
    async (nextDoc: RenovationDoc, sections: ResumeSectionInput[]) => {
      setSaving(true);
      setSaveFailed(false);
      if (profile.resume_text) nextDoc.resume_sig = hashString(profile.resume_text);
      lastPersistRef.current = { doc: nextDoc, sections };
      try {
        // W13 save truthfulness: "Saved" is a persistence CLAIM — it renders
        // only when the upsert confirmed. A failure (offline, signed-out
        // session, RLS denial) shows an explicit retry state instead; the
        // in-memory doc is untouched either way.
        const ok = await saveRenovation(
          opportunityId,
          nextDoc as unknown as Record<string, unknown>,
          { sections } as unknown as Record<string, unknown>,
          nextDoc.method,
          nextDoc.warnings,
        );
        if (ok) {
          setSavedFlash(true);
          setTimeout(() => setSavedFlash(false), 2000);
        } else {
          setSaveFailed(true);
        }
      } catch {
        setSaveFailed(true);
      } finally {
        setSaving(false);
      }
    },
    [opportunityId, profile.resume_text],
  );

  async function handleRenovate() {
    if (!profile.resume_text) return;
    setPhase('working');
    setWorkingStep('structuring');
    setError(null);
    setRestoredFromSave(false);
    try {
      const structured = await structureResume(profile.resume_text, { locale });
      if (structured.sections.length === 0) {
        setError(t('renovate.noSections'));
        setPhase('idle');
        return;
      }
      setWorkingStep('renovating');
      const renovated = await renovateResume(profile, opportunityId, structured.sections, {
        locale,
      });
      const nextDoc: RenovationDoc = {
        sections: renovated.sections,
        method: renovated.method,
        warnings: renovated.warnings,
      };
      setDoc(nextDoc);
      setBaseSections(structured.sections);
      setPhase('doc');
      void persist(nextDoc, structured.sections);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('renovate.failed'));
      setPhase('idle');
    }
  }

  // Immutable per-bullet doc update; persists the whole doc after each change
  // (the doc IS the rollback history, so every mutation is worth saving).
  const updateBullet = useCallback(
    (bulletId: string, updater: (b: RenovatedBullet) => RenovatedBullet) => {
      setDoc((prev) => {
        if (!prev) return prev;
        const next: RenovationDoc = {
          ...prev,
          sections: prev.sections.map((s) => ({
            ...s,
            bullets: s.bullets.map((b) => (b.id === bulletId ? updater(b) : b)),
          })),
        };
        void persist(next, baseSections);
        return next;
      });
    },
    [persist, baseSections],
  );

  function handleRollback(b: RenovatedBullet) {
    if (b.current < 0) return;
    updateBullet(b.id, (cur) => ({ ...cur, current: cur.current - 1 }));
  }

  function handleRollForward(b: RenovatedBullet) {
    if (b.current >= b.variants.length - 1) return;
    updateBullet(b.id, (cur) => ({ ...cur, current: cur.current + 1 }));
  }

  function startEdit(b: RenovatedBullet) {
    setEditingId(b.id);
    setEditDraft(bulletCurrentText(b));
  }

  function saveEdit(b: RenovatedBullet) {
    const trimmed = editDraft.trim();
    setEditingId(null);
    setEditDraft('');
    if (!trimmed || trimmed === bulletCurrentText(b)) return;
    updateBullet(b.id, (cur) => ({
      ...cur,
      variants: [...cur.variants, { source: 'user', text: trimmed, source_evidence: '' }],
      current: cur.variants.length,
    }));
  }

  async function handleReoptimize(b: RenovatedBullet) {
    if (optimizingId) return;
    setOptimizingId(b.id);
    setBulletNotices((prev) => ({ ...prev, [b.id]: '' }));
    try {
      const resp = await optimizeBullet(
        profile,
        opportunityId,
        bulletCurrentText(b),
        b.base_text,
        { locale },
      );
      if (resp.changed && resp.text.trim()) {
        updateBullet(b.id, (cur) => ({
          ...cur,
          variants: [
            ...cur.variants,
            { source: 'ai', text: resp.text, source_evidence: resp.source_evidence },
          ],
          current: cur.variants.length,
        }));
      } else {
        // Backend declined (validation or no improvement) — honest no-op.
        setBulletNotices((prev) => ({ ...prev, [b.id]: t('renovate.bulletUnchanged') }));
      }
    } catch {
      setBulletNotices((prev) => ({ ...prev, [b.id]: t('renovate.bulletFailed') }));
    } finally {
      setOptimizingId(null);
    }
  }

  async function handleCopyAll() {
    if (!doc) return;
    const lines: string[] = [];
    for (const s of doc.sections) {
      if (s.heading) lines.push(s.heading.toUpperCase());
      // "demote" is defined for the model as "kept but de-emphasized (placed
      // lower)", and the chip a student reads says "De-emphasized". This used
      // to drop those bullets, so clicking "Copy renovated résumé" silently
      // deleted the student's own experience from what they pasted back. Order
      // by rank instead, which is what the plan actually asked for.
      const rank = (action: string) =>
        action === 'foreground' ? 0 : action === 'demote' ? 2 : 1;
      for (const b of [...s.bullets].sort((a, c) => rank(a.action) - rank(c.action))) {
        lines.push(`• ${bulletCurrentText(b)}`);
      }
      lines.push('');
    }
    await navigator.clipboard.writeText(lines.join('\n').trim());
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (!isOpen) return null;

  const warningMessage = doc ? pickRenovationWarning(doc.warnings, t) : null;
  const hasResume = !!profile.resume_text;

  return (
    <div
      className="fixed inset-0 z-[55] flex sm:items-center sm:justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="renovation-modal-title"
    >
      <div
        className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      <div
        ref={modalRef}
        className="relative w-full sm:max-w-4xl sm:mx-4 bg-white sm:rounded-2xl shadow-2xl h-full sm:h-auto sm:max-h-[90vh] flex flex-col overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-start justify-between px-4 sm:px-6 py-3 sm:py-4 border-b border-gray-100 shrink-0">
          <div className="flex items-start gap-3 min-w-0">
            <div className="w-9 h-9 rounded-xl bg-indigo-50 flex items-center justify-center shrink-0" aria-hidden="true">
              <FileText className="w-5 h-5 text-indigo-600" />
            </div>
            <div className="min-w-0">
              <h2 id="renovation-modal-title" className="text-lg font-bold text-gray-900">
                {t('renovate.title')}
              </h2>
              <p className="text-sm text-gray-500 truncate max-w-md">{opportunityTitle}</p>
              <p className="text-xs text-gray-400 mt-1 max-w-md hidden sm:block">
                {t('renovate.subtitle')}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {savedFlash && (
              <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-600">
                <CheckCircle className="w-3.5 h-3.5" aria-hidden="true" />
                {t('renovate.saved')}
              </span>
            )}
            {saveFailed && !saving && (
              <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-amber-600" data-testid="renovation-save-failed">
                {t('renovate.saveFailed')}
                <button
                  type="button"
                  className="underline hover:text-amber-700"
                  onClick={() => {
                    const last = lastPersistRef.current;
                    if (last) void persist(last.doc, last.sections);
                  }}
                >
                  {t('renovate.retrySave')}
                </button>
              </span>
            )}
            {saving && !savedFlash && (
              <span className="text-[11px] text-gray-400">{t('renovate.saving')}</span>
            )}
            <button
              type="button"
              onClick={onClose}
              className="p-2 rounded-lg hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 transition-colors"
              aria-label={t('renovate.closeAria')}
            >
              <X className="w-5 h-5 text-gray-400" aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {phase === 'restoring' && (
            <div className="flex flex-col items-center justify-center py-20 gap-3">
              <Loader2 className="w-7 h-7 text-indigo-500 animate-spin" />
            </div>
          )}

          {phase === 'idle' && (
            <div className="flex flex-col items-center justify-center py-16 gap-4 px-6 text-center">
              <Sparkles className="w-8 h-8 text-indigo-300" aria-hidden="true" />
              {hasResume ? (
                <>
                  <p className="text-sm text-gray-600 max-w-md">{t('renovate.intro')}</p>
                  {error && (
                    <p className="text-sm text-red-600 flex items-center gap-1.5">
                      <AlertCircle className="w-4 h-4" aria-hidden="true" />
                      {error}
                    </p>
                  )}
                  <button
                    type="button"
                    onClick={handleRenovate}
                    className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-semibold text-white bg-gradient-to-r from-indigo-600 to-fuchsia-500 rounded-xl hover:from-indigo-700 hover:to-fuchsia-600 shadow-sm transition-all"
                  >
                    <Wand2 className="w-4 h-4" aria-hidden="true" />
                    {t('renovate.start')}
                  </button>
                </>
              ) : (
                <p className="text-sm text-gray-500 max-w-md">{t('renovate.noResume')}</p>
              )}
            </div>
          )}

          {phase === 'working' && (
            <div className="flex flex-col items-center justify-center py-20 gap-3">
              <Loader2 className="w-7 h-7 text-indigo-500 animate-spin" />
              <p className="text-sm text-gray-500">
                {workingStep === 'structuring'
                  ? t('renovate.structuring')
                  : t('renovate.renovating')}
              </p>
            </div>
          )}

          {phase === 'doc' && doc && (
            <div className="px-4 sm:px-6 py-4 space-y-5">
              {restoredFromSave && (
                <p className="text-[11.5px] text-indigo-600 bg-indigo-50 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full">
                  <Info className="w-3.5 h-3.5" aria-hidden="true" />
                  {t('renovate.restored')}
                </p>
              )}
              {staleResume && (
                <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200 text-[12.5px] text-amber-800" data-testid="renovation-stale-resume">
                  <Info className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" aria-hidden="true" />
                  <span>{t('renovate.staleResume')}</span>
                </div>
              )}
              {warningMessage && (
                <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200 text-[12.5px] text-amber-800">
                  <Info className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" aria-hidden="true" />
                  <span>{warningMessage}</span>
                </div>
              )}
              <p className="text-[11.5px] text-gray-400">{t('renovate.reviewHint')}</p>

              {doc.sections.map((section: RenovatedSection) => (
                <section key={section.id}>
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                    {section.heading || section.kind}
                  </h3>
                  <ul className="space-y-2.5">
                    {section.bullets.map((b) => {
                      const current = bulletCurrentText(b);
                      const showingVariant = b.current >= 0 ? b.variants[b.current] : null;
                      const sourceKey = showingVariant?.source ?? 'base';
                      const isEditing = editingId === b.id;
                      const isOptimizing = optimizingId === b.id;
                      const action = ACTION_CHIP[b.action] ?? ACTION_CHIP.keep;
                      const notice = bulletNotices[b.id];
                      const changed = current.trim() !== b.base_text.trim();
                      return (
                        <li
                          key={b.id}
                          className={`bg-white border rounded-xl shadow-sm px-4 py-3 ${
                            b.action === 'demote' ? 'opacity-60 border-dashed border-gray-300' : 'border-gray-200'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2 mb-1">
                            <div className="flex items-center gap-1.5 min-w-0">
                              <span
                                className={`text-[9.5px] font-semibold uppercase tracking-wide px-1.5 py-px rounded ${SOURCE_CHIP_STYLES[sourceKey] ?? SOURCE_CHIP_STYLES.base}`}
                              >
                                {t(`renovate.source.${sourceKey}`)}
                              </span>
                              {b.action !== 'keep' && (
                                <span
                                  className={`inline-flex items-center gap-0.5 text-[9.5px] font-semibold uppercase tracking-wide px-1.5 py-px rounded ${action.className}`}
                                >
                                  {action.icon === 'up' && <ArrowUpRight className="w-2.5 h-2.5" aria-hidden="true" />}
                                  {action.icon === 'down' && <ArrowDownRight className="w-2.5 h-2.5" aria-hidden="true" />}
                                  {t(`renovate.action.${b.action}`)}
                                </span>
                              )}
                            </div>
                            {!isEditing && (
                              <div className="ml-auto flex items-center gap-0.5 shrink-0">
                                <button
                                  type="button"
                                  onClick={() => handleRollback(b)}
                                  disabled={b.current < 0}
                                  className="inline-flex items-center gap-1 text-[10.5px] font-medium px-1.5 py-0.5 rounded-md text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-gray-400 transition-colors"
                                  aria-label={t('renovate.rollbackAria')}
                                >
                                  <RotateCcw className="w-3 h-3" aria-hidden="true" />
                                  {t('renovate.rollback')}
                                </button>
                                {b.current < b.variants.length - 1 && (
                                  <button
                                    type="button"
                                    onClick={() => handleRollForward(b)}
                                    className="inline-flex items-center gap-1 text-[10.5px] font-medium px-1.5 py-0.5 rounded-md text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 transition-colors"
                                    aria-label={t('renovate.rollForwardAria')}
                                  >
                                    <RefreshCw className="w-3 h-3" aria-hidden="true" />
                                    {t('renovate.rollForward')}
                                  </button>
                                )}
                                <button
                                  type="button"
                                  onClick={() => startEdit(b)}
                                  className="inline-flex items-center gap-1 text-[10.5px] font-medium px-1.5 py-0.5 rounded-md text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 transition-colors"
                                  aria-label={t('renovate.editAria')}
                                >
                                  <Pencil className="w-3 h-3" aria-hidden="true" />
                                  {t('renovate.edit')}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleReoptimize(b)}
                                  disabled={isOptimizing || optimizingId !== null}
                                  className="inline-flex items-center gap-1 text-[10.5px] font-medium px-1.5 py-0.5 rounded-md text-fuchsia-500 hover:text-fuchsia-700 hover:bg-fuchsia-50 disabled:opacity-40 transition-colors"
                                  aria-label={t('renovate.reoptimizeAria')}
                                >
                                  {isOptimizing ? (
                                    <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />
                                  ) : (
                                    <Wand2 className="w-3 h-3" aria-hidden="true" />
                                  )}
                                  {t('renovate.reoptimize')}
                                </button>
                              </div>
                            )}
                          </div>

                          {isEditing ? (
                            <div className="mt-1.5">
                              <textarea
                                value={editDraft}
                                onChange={(e) => setEditDraft(e.target.value)}
                                rows={3}
                                className="w-full px-3 py-2 border border-indigo-300 rounded-lg text-[13.5px] text-gray-800 leading-relaxed focus:ring-2 focus:ring-indigo-500/30 outline-none resize-y"
                                aria-label={t('renovate.editAria')}
                              />
                              <div className="flex items-center gap-2 mt-1.5">
                                <button
                                  type="button"
                                  onClick={() => saveEdit(b)}
                                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11.5px] font-semibold text-white bg-indigo-600 hover:bg-indigo-700 transition-colors"
                                >
                                  <CheckCircle className="w-3 h-3" aria-hidden="true" />
                                  {t('renovate.save')}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => {
                                    setEditingId(null);
                                    setEditDraft('');
                                  }}
                                  className="px-2.5 py-1 rounded-md text-[11.5px] font-medium text-gray-500 hover:bg-gray-100 transition-colors"
                                >
                                  {t('renovate.cancel')}
                                </button>
                              </div>
                            </div>
                          ) : (
                            <p className="text-[13.5px] leading-relaxed text-gray-800">
                              {changed ? (
                                <DiffLine original={b.base_text} tailored={current} side="tailored" />
                              ) : (
                                current
                              )}
                            </p>
                          )}

                          {showingVariant?.source_evidence && !isEditing && (
                            <p className="mt-1.5 text-[11.5px] text-gray-500 italic">
                              <span className="font-medium not-italic uppercase tracking-wider text-[10px] text-gray-400">
                                {t('renovate.sourceLabel')}:
                              </span>{' '}
                              &quot;{showingVariant.source_evidence}&quot;
                            </p>
                          )}
                          {notice && (
                            <p className="mt-1.5 text-[11.5px] text-amber-700">{notice}</p>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        {phase === 'doc' && doc && (
          <div className="flex items-center justify-end gap-3 px-6 py-3 border-t border-gray-100 bg-gray-50/50 shrink-0">
            <button
              type="button"
              onClick={handleRenovate}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-indigo-700 bg-indigo-50 border border-indigo-100 rounded-xl hover:bg-indigo-100 transition-colors mr-auto"
            >
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
              {t('renovate.rerun')}
            </button>
            <button
              type="button"
              onClick={handleCopyAll}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors"
            >
              {copied ? (
                <>
                  <CheckCircle className="w-4 h-4 text-emerald-500" aria-hidden="true" />
                  {t('renovate.copied')}
                </>
              ) : (
                <>
                  <Copy className="w-4 h-4" aria-hidden="true" />
                  {t('renovate.copyAll')}
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
