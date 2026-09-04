'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import { captureOwnerToken, isTokenOwnerStillCurrent } from '@/lib/identity-owner';
import { canDeliverReminder } from '@/lib/reminders';
import {
  X,
  Copy,
  ExternalLink,
  Loader2,
  CheckCircle,
  AlertCircle,
  BellRing,
  Mail,
  Send,
  Sparkles,
  UserRound,
} from 'lucide-react';
import {
  generateColdEmail,
  generateColdEmailStream,
  getEmailVariants,
  refineEmail,
  extractResumeBullets,
  type ColdEmailStage,
} from '@/lib/api';
import {
  confirmInteractionContact,
  onAuthChange,
  updateInteractionDetails,
} from '@/lib/supabase';
import type { InteractionRecord, InteractionType } from '@/lib/supabase';
import { useAuthModal } from '@/lib/auth-modal-context';
import type { ProfileData, EmailVariant, LabType, EmailStyle, ColdEmailFallbackReason, ColdEmailResponse, ContactEmailStatus } from '@/lib/types';
import { useT } from '@/i18n/client';
import LabTypeBadge from './LabTypeBadge';
import EmailTipsPanel from './EmailTipsPanel';

const AI_VARIANT_ID = 'ai';
// W12: a cached AI draft is re-served for at most this long — beyond it the
// professor record may have moved (email nulled, works revoked) and the
// draft must regenerate from the live corpus.
export const AI_CACHE_TTL_MS = 30 * 60 * 1000;

/** W12 draft-freshness rule for the in-tab AI cache: an entry is stale once
 *  it outlives the TTL or once the backend's corpus generation moves past
 *  the one that produced it. Exported for tests. */
export function aiCacheEntryIsStale(
  entry: { response: { corpus_version?: string | null }; at: number },
  nowMs: number,
  currentCorpusVersion: string | null,
): boolean {
  if (nowMs - entry.at > AI_CACHE_TTL_MS) return true;
  return (
    !!entry.response.corpus_version &&
    !!currentCorpusVersion &&
    entry.response.corpus_version !== currentCorpusVersion
  );
}
const STYLE_KEYS: readonly EmailStyle[] = ['professional', 'warm', 'friendly', 'lively'];

interface ColdEmailModalProps {
  isOpen: boolean;
  onClose: () => void;
  profile: ProfileData;
  opportunityId: string;
  opportunityTitle: string;
  /** Slug of the opportunity's host school — lets the no-email explainer link
   *  the student to their campus' official self-lookup directory. */
  opportunitySchool?: string | null;
  /**
   * The canonical record this dialog is about, as the caller currently sees
   * it — used for one thing only: deciding whether a follow-up reminder would
   * actually be delivered.
   *
   * Optional, and `undefined` FAILS CLOSED — no chips, no write. That is the
   * honest reading of "the caller cannot presently prove anything about this
   * target": a results refetch in flight, the row gone from the page, or a
   * caller that never supplied one. All three production call sites pass it
   * explicitly; a test that omits it simply gets no follow-up controls, which
   * is the correct default rather than something to paper over.
   *
   * `id` is required and must equal `opportunityId`. A caller resolving the
   * row by a stale id — a results list mid-swap, a favorites page whose
   * modal id moved on — would otherwise hand over a perfectly live record
   * that describes a DIFFERENT target, and this dialog would write a
   * reminder for it.
   */
  reminderTarget?: NonNullable<Parameters<typeof canDeliverReminder>[0]> & { id: string };
  /**
   * Called with the row the confirmation actually wrote, so the surface that
   * opened this dialog can stop contradicting it.
   *
   * The write is atomic and this dialog owns it, but the host page's own
   * interaction read re-runs only on mount and on a real identity change —
   * closing the modal triggers neither. Without this the detail page shows
   * "Pick a status above first" and a disabled notes box for a contact it just
   * recorded, and the results list keeps the pre-contact chip for the session.
   *
   * Fires only inside the same post-await ownership check that paints the
   * confirmed state, so a confirmation released after the owner moved tells
   * the caller nothing, exactly as it paints nothing.
   */
  onContactConfirmed?: (record: InteractionRecord | null) => void;
  /** The follow-up chips write remind_at straight to the row. Without this the
   *  page that owns the tracker panel never learns, so its date field renders
   *  empty and its status-change suggestion — gated on remind_at being unset —
   *  offers to set a reminder that already exists, overwriting it on one
   *  click. */
  onReminderSet?: (date: string) => void;
}

/*
 * Schools whose faculty emails we cannot (or may not) harvest, but whose
 * OFFICIAL directory lets the student look one up themselves — with their own
 * campus login where required. Individual lookup is exactly the use these
 * directories permit (UW's directory ToS restricts bulk/commercial use, which
 * is why we don't harvest it — but the student searching one professor is the
 * intended use).
 */
const SELF_LOOKUP_DIRECTORIES: Record<string, { name: string; url: string }> = {
  uw: { name: 'UW Directory', url: 'https://directory.uw.edu/' },
  umich: { name: 'MCommunity', url: 'https://mcommunity.umich.edu/' },
  princeton: { name: 'Princeton Directory', url: 'https://directory.princeton.edu/' },
  stanford: { name: 'Stanford Directory', url: 'https://stanfordwho.stanford.edu/' },
};

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

const QUICK_ACTION_KEYS = ['formal', 'shorter', 'enthusiastic', 'coursework'] as const;
type QuickActionKey = typeof QUICK_ACTION_KEYS[number];

// Pipeline-stage labels shown inside the AI pill while streaming — the
// multi-call pipeline takes noticeably longer than the old single call, so
// the UI says WHICH stage is running instead of one opaque spinner.
const STAGE_LABEL_KEYS: Record<ColdEmailStage, string> = {
  drafting: 'coldEmail.stageDrafting',
  judging: 'coldEmail.stageJudging',
  critiquing: 'coldEmail.stageCritiquing',
  revising: 'coldEmail.stageRevising',
};

type Replier = (path: string, vars?: Record<string, string | number>) => string;

// The backend 422s every cold-email entry point with this error code when the
// profile has no name (emails must never go out addressed from "Student").
// Structured API errors retain the Pydantic error code without exposing the
// full validation body to the UI. Legacy/custom callers are tolerated too.
function isStudentNameRequiredError(err: unknown): boolean {
  return (
    typeof err === 'object'
    && err !== null
    && 'code' in err
    && err.code === 'student_name_required'
  ) || (
    err instanceof Error
    && err.message.includes('student_name_required')
  );
}

// R72-A: pick the truthful fallback outcome for both generation and refine.
// 'fabrication' means a model result was rejected; 'insufficient_evidence'
// means the evidence gate rebuilt a safe template without running AI. Neither
// may be described as a provider outage or a routine local tone edit.
function aiFallbackMessage(
  reason: ColdEmailFallbackReason | null | undefined,
  t: Replier,
): string {
  if (reason === 'fabrication') return t('coldEmail.aiFallbackFabrication');
  if (reason === 'insufficient_evidence') return t('coldEmail.aiFallbackInsufficientEvidence');
  if (reason === 'not_configured') return t('coldEmail.aiFallback');
  return t('coldEmail.aiFallbackGeneric');
}

// Tone quick-actions (formal / shorter / enthusiastic) are canned refine
// instructions routed through POST /cold-email/refine — the backend's
// email_modes.EDIT_OPS registry is the single source of tone truth (LLM when
// configured, its deterministic edit ops otherwise). Keeping a client-side
// tone table here was the third copy of those semantics and had already
// drifted from the backend's.
const QUICK_ACTION_INSTRUCTIONS: Record<Exclude<QuickActionKey, 'coursework'>, string> = {
  formal: 'Make it more formal and professional',
  shorter: 'Make it shorter and more concise',
  enthusiastic: 'Make it more enthusiastic',
};

// Pre-W10b cached/skewed responses lack recipient_status; a present address
// means it was revealed, an absent one means there is nothing to offer.
function statusOf(
  status: ContactEmailStatus | undefined,
  email: string,
): ContactEmailStatus {
  return status ?? (email ? 'revealed' : 'unavailable');
}

// Coursework stays client-side: it inserts the student's own courses verbatim
// (naturally grounded), so a network round-trip buys nothing.
function applyQuickEdit(
  body: string,
  action: QuickActionKey,
  profile: ProfileData,
  t: Replier,
): { body: string; reply: string } {
  switch (action) {
    case 'coursework': {
      const courses = profile.coursework ?? [];
      if (courses.length === 0) {
        return { body, reply: t('coldEmail.replies.courseworkNone') };
      }
      const courseStr = courses.slice(0, 4).join(', ');
      const insertion = `\n\nI have completed relevant coursework including ${courseStr}.`;
      // FE-4: insert before the sign-off. The template closes with "Best
      // regards"/"Respectfully", but an AI draft can drift to "Sincerely",
      // "Warm regards", etc. — matching only Best/Respectfully appended the line
      // BELOW the signature in that case. Match a broad set of closings and use
      // the last one.
      const closingRe = /\n\n(?:Best regards|Best|Sincerely|Respectfully|Warm(?:est)? regards|Warmly|Kind regards|Regards|Thank you|Thanks|Cheers)\b/gi;
      let insertAt = -1;
      for (const m of body.matchAll(closingRe)) {
        if (m.index !== undefined) insertAt = m.index;
      }
      const reply = t('coldEmail.replies.courseworkAdded', { list: courseStr });
      if (insertAt > 0) {
        return {
          body: body.slice(0, insertAt) + insertion + body.slice(insertAt),
          reply,
        };
      }
      return { body: body + insertion, reply };
    }
    default:
      return { body, reply: t('coldEmail.replies.noChanges') };
  }
}

export default function ColdEmailModal({
  isOpen,
  onClose,
  profile,
  opportunityId,
  opportunityTitle,
  opportunitySchool,
  reminderTarget,
  onContactConfirmed,
  onReminderSet,
}: ColdEmailModalProps) {
  const { t } = useT();
  const { openModal } = useAuthModal();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Missing sender identity is its own state (not a generic error): the fix is
  // "add your name to your profile", so the UI links there instead of offering
  // a pointless retry.
  const [nameRequired, setNameRequired] = useState(false);
  const missingStudentName = !(profile.name ?? '').trim();
  const [variants, setVariants] = useState<EmailVariant[]>([]);
  const [aiVariant, setAiVariant] = useState<EmailVariant | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  // Which pipeline stage the streaming generation is in (null = not streaming
  // or stage unknown); drives the AI pill's progress label.
  const [aiStage, setAiStage] = useState<ColdEmailStage | null>(null);
  const [activeVariant, setActiveVariant] = useState(0);
  const [labType, setLabType] = useState<LabType | null>(null);
  // Voice overlay for the AI draft. `selectedStyle` seeds from the lab-type
  // recommendation once variants load; the picker re-generates on change.
  const [selectedStyle, setSelectedStyle] = useState<EmailStyle>('professional');
  const [recommendedStyle, setRecommendedStyle] = useState<EmailStyle | null>(null);

  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [recipient, setRecipient] = useState('');
  // W10b contact bar: why the To field is (or isn't) prefilled. 'sign_in_required'
  // renders the sign-in-to-reveal affordance; 'unavailable' the honest
  // no-verified-address state. Pre-W10b cached responses lack the field —
  // derive from whether an address arrived.
  const [recipientStatus, setRecipientStatus] = useState<ContactEmailStatus>('unavailable');
  // Evidence honesty (one value per opportunity, from the backend): when the
  // posting carries no research signal at all, every draft is necessarily
  // generic, and presenting one as tailored would be a lie. Absent field
  // (older cached responses) ⇒ 'specific', the pre-existing behaviour.
  const [grounding, setGrounding] = useState<'specific' | 'no_target_data'>('specific');
  // How current the corpus record behind this draft is. The backend has
  // always computed and shipped it ("the UI must not present the draft as
  // current outreach" — _source_freshness) and nothing read it, so a draft to
  // a professor whose record was retired looked identical to one to a
  // currently-listed professor. Default 'unknown' shows nothing: an older
  // cached response without the field must not manufacture a warning OR a
  // false all-clear.
  const [freshness, setFreshness] =
    useState<'fresh' | 'stale' | 'inactive' | 'unknown'>('unknown');
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  // Copying/opening a draft only REVEALS the follow-up strip — it is not
  // evidence the email was sent (the user may close the compose window), so
  // nothing is recorded yet. Only the explicit "I sent it" confirmation below
  // creates the interaction — as 'contacted', since a send is outreach and
  // not an application claim made on the student's behalf; the reminder chips
  // then follow, when the returned status is one the cron actually sends for.
  const [contacted, setContacted] = useState(false);
  // Same stamping as confirmedForId below, for the same reason: the
  // copy/open strip must not carry A's "did you send it?" question onto B.
  const [contactedForId, setContactedForId] = useState<string | null>(null);
  const contactedHere = contacted && contactedForId === opportunityId;
  const [sendConfirmed, setSendConfirmed] = useState(false);
  const [followUpDate, setFollowUpDate] = useState<string | null>(null);
  // The status the confirm RPC actually landed on. It is an upsert that
  // PRESERVES an existing status, so a row already marked rejected or
  // dismissed stays that way — and the reminders cron never selects those.
  // Assuming 'contacted' here is how a confirmed send still produced a
  // reminder nothing would ever deliver.
  const [confirmedStatus, setConfirmedStatus] = useState<InteractionType | undefined>();
  // Which opportunity that status belongs to. The reset below is a passive
  // effect, so between a rerender onto target B and that cleanup flushing,
  // A's confirmation would already have painted B's chips — and the handler
  // would have written against them. Stamping the id at creation makes the
  // state unusable for anyone else by construction rather than by timing.
  const [confirmedForId, setConfirmedForId] = useState<string | null>(null);
  const confirmedHere = sendConfirmed && confirmedForId === opportunityId;
  // Identity first, then deliverability. A live record for a different id is
  // still a live record — canDeliverReminder would happily say yes to it.
  const followUpDeliverable = confirmedHere
    && reminderTarget?.id === opportunityId
    && canDeliverReminder(reminderTarget, confirmedStatus);
  const [confirming, setConfirming] = useState(false);
  // Which persistence failed, so the strip can say the honest thing: a failed
  // confirmation recorded NOTHING, a failed reminder left a real contact
  // record in place, and an identity that moved mid-write recorded nothing for
  // whoever is signed in now. `null` = nothing has failed in this session.
  const [sendError, setSendError] = useState<'confirm' | 'reminder' | 'owner-changed' | null>(null);

  const allVariants: EmailVariant[] = aiVariant ? [...variants, aiVariant] : variants;

  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const chatEndRef = useRef<HTMLDivElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  // Cache the resume experience bullets extracted from the profile's resume
  // text so every AI (re)generation reuses one extraction. Keyed by the text
  // it was extracted from — the modal stays mounted across open/close cycles,
  // so an unkeyed cache would keep serving bullets from a résumé the user has
  // since replaced. null = not yet attempted.
  const resumeBulletsRef = useRef<{ forText: string; bullets: string[] } | null>(null);
  // How many résumé bullets the currently-shown variants were generated from.
  const variantsBuiltWithRef = useRef(0);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  // AI is the default engine: one automatic pipeline run per open, kicked off
  // once the template variants land. Reset on close.
  const autoFiredRef = useRef(false);
  // Mirrors `body` so async completions can tell whether the user edited or
  // switched away from the draft that was showing when generation started.
  const bodyRef = useRef('');
  // Real AI drafts per (opportunity, style): reopening the same opportunity
  // reuses the draft instead of re-billing the pipeline. Fallback responses
  // are never cached (they retry on the next open). Cleared when the profile
  // prop changes — a draft must not outlive a profile edit. W12: entries
  // also expire after AI_CACHE_TTL_MS and whenever the backend's
  // corpus_version moves, so a long-lived tab can never re-serve a draft
  // built from a superseded professor record.
  const aiCacheRef = useRef<Map<string, { response: ColdEmailResponse; at: number }>>(new Map());
  const corpusVersionRef = useRef<string | null>(null);
  // Which send session an in-flight persistence belongs to. Bumped on every
  // close and every target change, so a completion that comes back after the
  // modal moved on can be identified as belonging to a session that no longer
  // exists. An immutable number, not object identity: the modal stays mounted
  // across open/close and target switches, so there is no object to compare.
  const sendSessionRef = useRef(0);
  // Which confirmation attempt within that session. A retry supersedes the
  // attempt it retried, so a straggler cannot paint over the newer answer.
  const confirmAttemptRef = useRef(0);
  // One atomic call per attestation: held for the duration of the round trip
  // and released by whoever set it, so a double click cannot open a second.
  const confirmInFlightRef = useRef(false);

  useEffect(() => { bodyRef.current = body; }, [body]);
  useEffect(() => { aiCacheRef.current.clear(); }, [profile]);

  const fetchVariants = useCallback(async () => {
    if (missingStudentName) {
      setLoading(false);
      setNameRequired(true);
      return;
    }
    setLoading(true);
    setError(null);
    setNameRequired(false);
    try {
      // The bullets this fetch was built with, so the re-fetch below happens
      // exactly once — when extraction turns [] into real work.
      const bullets = resumeBulletsRef.current?.bullets ?? [];
      variantsBuiltWithRef.current = bullets.length;
      const data = await getEmailVariants(profile, opportunityId, bullets);
      setVariants(data.variants);
      const inferredLabType =
        data.lab_type
        ?? (data.variants.find((v) => v.lab_type)?.lab_type ?? null);
      setLabType(inferredLabType);
      const rec = data.recommended_style ?? null;
      setRecommendedStyle(rec);
      if (rec) setSelectedStyle(rec);
      setRecipientStatus(
        statusOf(data.recipient_status, data.variants[0]?.recipient_email ?? ''),
      );
      setGrounding(data.grounding ?? 'specific');
      setFreshness(data.source_freshness ?? 'unknown');
      // W12: variants regenerate on every open, so their corpus_version is
      // the "current" mark that decides whether a cached AI draft survives.
      if (data.corpus_version) corpusVersionRef.current = data.corpus_version;
      if (data.variants.length > 0) {
        const first = data.variants[0];
        setSubject(first.subject);
        setBody(first.body);
        setRecipient(first.recipient_email);
        setActiveVariant(0);
      }
      setChatMessages([
        { role: 'assistant', content: t('coldEmail.generated', { count: data.variants.length }) },
      ]);
    } catch (err) {
      if (isStudentNameRequiredError(err)) {
        setNameRequired(true);
      } else {
        setError(err instanceof Error ? err.message : t('coldEmail.failedGenerate'));
      }
    } finally {
      setLoading(false);
    }
  }, [profile, opportunityId, t, missingStudentName]);

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect --
       Modal-lifecycle effect. Open path calls fetchVariants() whose
       sync prefix flips setLoading(true) before any await. Cleanup
       path resets every internal state slice so the next open()
       starts from a known-empty surface — splitting this into two
       effects would race the next open's fetchVariants() with stale
       residue from the previous session. */
    if (isOpen) fetchVariants();
    return () => {
      autoFiredRef.current = false;
      // Close or target change ends the send session. Bumping the id first
      // means any persistence still in flight can no longer reach this
      // component's state, so the resets below cannot be undone by a
      // straggler landing a moment later.
      sendSessionRef.current += 1;
      confirmInFlightRef.current = false;
      setContacted(false);
      setContactedForId(null);
      setSendConfirmed(false);
      setFollowUpDate(null);
      // Reset with the rest: a status confirmed for the previous target must
      // never decide whether the NEXT one may take a reminder. The id stamps
      // make that true from the first render rather than from this cleanup.
      setConfirmedStatus(undefined);
      setConfirmedForId(null);
      setConfirming(false);
      setSendError(null);
      setVariants([]);
      setAiVariant(null);
      setAiLoading(false);
      setLabType(null);
      setSelectedStyle('professional');
      setRecommendedStyle(null);
      setSubject('');
      setBody('');
      setRecipient('');
      setRecipientStatus('unavailable');
      setGrounding('specific');
      setFreshness('unknown');
      setCopied(false);
      setCopyFailed(false);
      setError(null);
      setNameRequired(false);
      setChatMessages([]);
      setChatInput('');
    };
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [isOpen, fetchVariants]);

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

  useEffect(() => {
    if (isOpen) document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, [isOpen]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  // W10b: once the user signs in from the reveal affordance, fetch the
  // recipient once via the (cheap) variants endpoint and fill the To field —
  // WITHOUT regenerating or touching the draft they may have edited. The
  // subscription also fires with the current session on mount, which
  // self-heals the stale-token case where the api-level refresh-retry failed.
  useEffect(() => {
    if (!isOpen || recipientStatus !== 'sign_in_required') return;
    const unsubscribe = onAuthChange((state) => {
      if (!state.session || state.isAnonymous) return;
      void (async () => {
        try {
          const data = await getEmailVariants(profile, opportunityId);
          const email = data.variants[0]?.recipient_email ?? '';
          setRecipientStatus(statusOf(data.recipient_status, email));
          if (email) setRecipient((prev) => prev || email);
        } catch { /* keep the sign-in affordance */ }
      })();
    });
    return unsubscribe;
  }, [isOpen, recipientStatus, profile, opportunityId]);

  function selectVariant(idx: number) {
    const v = allVariants[idx];
    if (!v) return;
    setActiveVariant(idx);
    setSubject(v.subject);
    setBody(v.body);
    // Variants share one server-resolved recipient; when the reveal is locked
    // they carry "" — never wipe an address the user typed themselves.
    setRecipient((prev) => v.recipient_email || prev);
    setChatMessages((prev) => [
      ...prev,
      { role: 'assistant', content: t('coldEmail.switched', { label: v.label }) },
    ]);
  }

  // Generate (or re-generate) the AI draft in a given voice. Used by the
  // automatic run on open (AI is the default engine; `auto: true`), the ✨ AI
  // pill, and the tone picker. Auto mode differs in three ways: it reports
  // nothing until it succeeds (a fallback the user never asked for stays
  // silent), it never clobbers a draft the user has meanwhile edited or
  // switched away from, and it seeds/serves the per-open cache.
  const generateAi = useCallback(async (style: EmailStyle, opts?: { auto?: boolean }) => {
    if (aiLoading || missingStudentName) return;
    const auto = opts?.auto ?? false;
    const aiIdx = variants.length;
    setSelectedStyle(style);

    const applyResponse = (
      resp: ColdEmailResponse,
      select: boolean,
      contactIsCurrent = true,
    ) => {
      const v: EmailVariant = {
        id: AI_VARIANT_ID,
        label: t('coldEmail.aiVariantLabel'),
        subject: resp.subject,
        body: resp.body,
        recipient_email: resp.recipient_email,
        mailto_link: resp.mailto_link,
        lab_type: resp.lab_type ?? labType ?? null,
        method: resp.method,
        fallback_reason: resp.fallback_reason,
      };
      setAiVariant(v);
      if (contactIsCurrent) {
        setRecipientStatus(statusOf(resp.recipient_status, resp.recipient_email));
      }
      if (resp.lab_type && resp.lab_type !== labType) setLabType(resp.lab_type);
      if (select) {
        setActiveVariant(aiIdx);
        setSubject(v.subject);
        setBody(v.body);
        if (contactIsCurrent) {
          setRecipient((prev) => v.recipient_email || prev);
        }
      }
    };

    // W12 draft freshness: a cached AI draft is only re-served while young
    // AND while the backend corpus that produced it is still current — a
    // superseded professor record must not keep personalizing from the cache.
    const cached = aiCacheRef.current.get(`${opportunityId}|${style}`);
    if (cached) {
      if (aiCacheEntryIsStale(cached, Date.now(), corpusVersionRef.current)) {
        aiCacheRef.current.delete(`${opportunityId}|${style}`);
      } else {
        // Cache only the AI writing value. Recipient truth was refreshed by
        // getEmailVariants for the current auth session and must never be
        // overwritten by a reveal cached before logout/token expiry.
        applyResponse(cached.response, true, false);
        setChatMessages((prev) => [...prev, { role: 'assistant', content: t('coldEmail.aiGenerated') }]);
        return;
      }
    }

    setAiLoading(true);
    if (!auto) {
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: t('coldEmail.tone.generating', { style: t(`coldEmail.tone.${style}`) }) },
      ]);
    }
    const baselineBody = bodyRef.current;

    try {
      // Extract the student's real resume bullets once per résumé text, so the
      // AI draft can cite their actual experience (the backend grounds them).
      // Best-effort: a failure just falls back to skills/coursework-only
      // grounding. Re-extracts when the résumé text changes (stale-cache fix).
      const resumeText = profile.resume_text ?? '';
      if (
        grounding !== 'no_target_data'
        && (resumeBulletsRef.current === null || resumeBulletsRef.current.forText !== resumeText)
      ) {
        try {
          resumeBulletsRef.current = {
            forText: resumeText,
            bullets: resumeText
              ? (await extractResumeBullets(resumeText)).bullets ?? []
              : [],
          };
        } catch {
          resumeBulletsRef.current = { forText: resumeText, bullets: [] };
        }
      }
      // No target-side research facts means the backend will deliberately
      // serve its honest insufficient-evidence template.  Resume extraction
      // cannot improve that target grounding, so skip this separate provider
      // path for both automatic and user-triggered AI attempts.
      const bullets = grounding === 'no_target_data'
        ? []
        : (resumeBulletsRef.current?.bullets ?? []);
      // The templates are fetched before extraction has run, so the first set
      // is always built without the student's own work — and those are what a
      // variant tab shows, and what the student sends whenever the AI pass
      // degrades. Refetch once, when extraction turns [] into real bullets.
      if (bullets.length > 0 && variantsBuiltWithRef.current === 0) {
        void fetchVariants();
      }
      const opts = {
        engine: 'ai' as const,
        style,
        ...(bullets.length > 0 ? { resumeBullets: bullets } : {}),
      };
      let resp;
      try {
        // Stream-first: shows which pipeline stage is running. Any transport
        // failure (old backend, proxy buffering, network hiccup mid-stream)
        // falls back to the blocking route.
        resp = await generateColdEmailStream(profile, opportunityId, opts, setAiStage);
      } catch {
        setAiStage(null);
        resp = await generateColdEmail(profile, opportunityId, opts);
      }
      if (resp.method === 'ai') {
        aiCacheRef.current.set(`${opportunityId}|${style}`, {
          // Recipient truth stripped before caching — same reason as the
          // cached-serve path above.
          response: {
            ...resp,
            recipient_email: '',
            recipient_status: 'unavailable',
            mailto_link: '',
          },
          at: Date.now(),
        });
        if (resp.corpus_version) corpusVersionRef.current = resp.corpus_version;
      }
      if (auto && resp.method !== 'ai') return; // silent — the user never asked
      applyResponse(resp, !auto || bodyRef.current === baselineBody);
      setChatMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: resp.method === 'ai' ? t('coldEmail.aiGenerated') : aiFallbackMessage(resp.fallback_reason, t),
        },
      ]);
    } catch {
      if (!auto) {
        setChatMessages((prev) => [
          ...prev,
          { role: 'assistant', content: t('coldEmail.aiFailed') },
        ]);
      }
    } finally {
      setAiLoading(false);
      setAiStage(null);
    }
  }, [aiLoading, missingStudentName, variants.length, profile, opportunityId, labType, grounding, t, fetchVariants]);

  // AI is the default engine: once the template variants land, run the
  // pipeline once automatically. The template is the instant placeholder; the
  // AI draft takes over on success (unless the user already started editing).
  useEffect(() => {
    if (!isOpen || loading || variants.length === 0 || autoFiredRef.current) return;
    autoFiredRef.current = true;
    generateAi(selectedStyle, { auto: true });
  }, [isOpen, loading, variants.length, selectedStyle, generateAi]);

  function handleAiPillClick() {
    if (aiLoading) return;
    if (aiVariant) {
      selectVariant(variants.length);
      return;
    }
    generateAi(selectedStyle);
  }

  function handleToneClick(style: EmailStyle) {
    if (aiLoading) return;
    generateAi(style);
  }

  // Shared grounded-refine runner for typed chat instructions AND the tone
  // quick-actions. Appends the "editing…" assistant message, calls the backend
  // (which grounds the result and degrades to its deterministic EDIT_OPS when
  // no LLM is configured), then replaces the placeholder with the outcome.
  async function runRefine(instruction: string) {
    setChatMessages((prev) => [...prev, { role: 'assistant', content: t('coldEmail.editing') }]);
    try {
      const result = await refineEmail(body, instruction, profile, opportunityId, {
        resumeBullets: resumeBulletsRef.current?.bullets,
      });
      setBody(result.body);
      setChatMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: 'assistant',
          content:
            result.method === 'llm'
              ? t('coldEmail.doneLlm')
              : result.fallback_reason === 'insufficient_evidence'
                ? aiFallbackMessage('insufficient_evidence', t)
                : result.fallback_reason === 'fabrication'
                  ? t('coldEmail.refineFabrication')
                  : t('coldEmail.doneFallback'),
        };
        return updated;
      });
    } catch {
      setChatMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: 'assistant',
          content: t('coldEmail.editFailed'),
        };
        return updated;
      });
    }
  }

  function handleQuickAction(key: QuickActionKey) {
    const label = t(`coldEmail.quickActions.${key}`);
    setChatMessages((prev) => [...prev, { role: 'user', content: label }]);
    if (key === 'coursework') {
      // Client-side: inserts the student's own courses verbatim.
      const { body: newBody, reply } = applyQuickEdit(body, key, profile, t);
      setBody(newBody);
      setChatMessages((prev) => [...prev, { role: 'assistant', content: reply }]);
      return;
    }
    void runRefine(QUICK_ACTION_INSTRUCTIONS[key]);
  }

  async function handleChatSubmit() {
    const msg = chatInput.trim();
    if (!msg) return;
    setChatInput('');
    setChatMessages((prev) => [...prev, { role: 'user', content: msg }]);
    await runRefine(msg);
  }

  // Reveal the strip without recording anything — a draft opened/copied is
  // not a verified send. No evidence = no tracking event.
  const markContacted = useCallback(() => {
    setContacted(true);
    setContactedForId(opportunityId);
    // opportunityId is now READ here, so it has to be a dep. An empty array
    // would freeze the stamp at whatever id existed on first mount, and a
    // copy on target B would file itself under target A forever.
  }, [opportunityId]);

  // The user's explicit attestation that the email went out — the ONLY path
  // that records the contact, and it records it with one atomic call.
  //
  // The old flow read the interaction, conditionally inserted 'applied', then
  // updated the metadata: three round trips a concurrent status change could
  // interleave with, and it painted `sent` before any of them had landed.
  // confirmInteractionContact is one INSERT ... ON CONFLICT DO UPDATE
  // (migration 027) that creates the row as 'contacted' or, when any status
  // already exists, only refreshes last_contacted_at. That preservation is
  // why the RETURNED status is read below rather than assumed: a row already
  // marked rejected or dismissed comes back unchanged, and the reminders cron
  // selects neither.
  const confirmSent = useCallback(async () => {
    if (confirmInFlightRef.current) return;
    // Captured at the click, before any await: the capability belongs to the
    // identity that attested, not to whoever owns the browser by the time the
    // round trip finishes.
    const token = captureOwnerToken();
    const session = sendSessionRef.current;
    const attempt = (confirmAttemptRef.current += 1);
    confirmInFlightRef.current = true;
    setSendError(null);
    setConfirming(true);
    // Same session, same attempt: this completion is still the current one.
    // A newer attempt, a target change or a close all retire it.
    const stillCurrent = () =>
      sendSessionRef.current === session && confirmAttemptRef.current === attempt;
    try {
      const record = await confirmInteractionContact(opportunityId, token);
      // The owner check is re-read AFTER the await, against the token captured
      // BEFORE it. Same uid at a new epoch is a different capability.
      if (!stillCurrent()) return;
      if (isTokenOwnerStillCurrent(token)) {
        setConfirmedStatus(record?.type);
        setConfirmedForId(opportunityId);
        setSendConfirmed(true);
        onContactConfirmed?.(record ?? null);
      }
      else setSendError('owner-changed');
    } catch {
      if (!stillCurrent()) return;
      // A confirmation whose identity moved is neither this account's success
      // nor its failure: it is void here. Saying so beats a click that appears
      // to do nothing — while still painting no U1 outcome into U2's session.
      setSendError(isTokenOwnerStillCurrent(token) ? 'confirm' : 'owner-changed');
    } finally {
      if (stillCurrent()) {
        confirmInFlightRef.current = false;
        setConfirming(false);
      }
    }
  }, [opportunityId, onContactConfirmed]);

  // Reminder-only. It must never call the contact recorder: that would move
  // last_contacted_at and record a second outreach the student never made.
  const setFollowUp = useCallback(async (days: number) => {
    // Both halves of the reminders cron's predicate, checked here and not
    // only where the chips render. Hiding a button stops a click; it does
    // nothing about a retained handler or a status that changed between the
    // render and the click.
    // Re-derived here rather than reading `followUpDeliverable`: this is the
    // sink, and it must hold even when the DOM gate above passed against an
    // older render of the same target object.
    if (confirmedForId !== opportunityId) return;
    if (reminderTarget?.id !== opportunityId) return;
    if (!canDeliverReminder(reminderTarget, confirmedStatus)) return;
    const token = captureOwnerToken();
    const session = sendSessionRef.current;
    // The student's own calendar day, not UTC's. After 7pm in Chicago the UTC
    // date has already rolled over, so "in 1 week" landed on the eighth day —
    // the same arithmetic the tracker's presets had.
    const d = new Date();
    d.setDate(d.getDate() + days);
    const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const stillCurrent = () =>
      sendSessionRef.current === session && isTokenOwnerStillCurrent(token);
    try {
      await updateInteractionDetails(opportunityId, { remind_at: date }, token);
    } catch {
      if (stillCurrent()) setSendError('reminder');
      return;
    }
    if (stillCurrent()) {
      setSendError(null);
      setFollowUpDate(date);
      onReminderSet?.(date);
    }
  }, [opportunityId, reminderTarget, confirmedStatus, confirmedForId, onReminderSet]);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`);
    } catch {
      // The clipboard genuinely refuses in the field: permission denied, the
      // document not focused, an insecure context. Nothing was copied, so
      // nothing may report that it was — and with no draft in hand there is
      // nothing the student could have sent, so the attestation question
      // stays away too.
      setCopyFailed(true);
      return;
    }
    setCopyFailed(false);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    markContacted();
  }

  function getMailtoLink(provider: 'default' | 'gmail' | 'outlook' = 'default'): string {
    const to = encodeURIComponent(recipient || '');
    const subj = encodeURIComponent(subject);
    const b = encodeURIComponent(body);
    if (provider === 'gmail') return `https://mail.google.com/mail/?view=cm&to=${to}&su=${subj}&body=${b}`;
    if (provider === 'outlook') return `https://outlook.office365.com/mail/deeplink/compose?to=${to}&subject=${subj}&body=${b}`;
    return `mailto:${to}?subject=${subj}&body=${b}`;
  }

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[55] flex sm:items-center sm:justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="email-modal-title"
    >
      <div className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm" onClick={onClose} aria-hidden="true" />

      <div
        ref={modalRef}
        className="relative w-full sm:max-w-5xl sm:mx-4 bg-white sm:rounded-2xl shadow-2xl h-full sm:h-auto sm:max-h-[90vh] flex flex-col overflow-hidden animate-in"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 sm:px-6 py-3 sm:py-4 border-b border-gray-100 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-50 flex items-center justify-center" aria-hidden="true">
              <Mail className="w-5 h-5 text-indigo-600" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2 id="email-modal-title" className="text-lg font-bold text-gray-900">{t('coldEmail.title')}</h2>
                <LabTypeBadge labType={labType} />
              </div>
              <p className="text-sm text-gray-500 truncate max-w-md">{opportunityTitle}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 transition-colors"
            aria-label={t('coldEmail.closeAria')}
          >
            <X className="w-5 h-5 text-gray-400" aria-hidden="true" />
          </button>
        </div>

        {/* Loading / Error */}
        {loading && (
          <div className="flex flex-col items-center justify-center py-20 gap-4">
            <Loader2 className="w-8 h-8 text-indigo-500 animate-spin" />
            <p className="text-sm text-gray-500">{t('coldEmail.generating')}</p>
          </div>
        )}
        {nameRequired && !loading && (
          <div className="flex flex-col items-center justify-center py-20 gap-4 px-6 text-center" data-testid="cold-email-name-required">
            <div className="w-12 h-12 rounded-2xl bg-amber-50 flex items-center justify-center">
              <UserRound className="w-6 h-6 text-amber-600" aria-hidden="true" />
            </div>
            <p className="text-base font-semibold text-gray-900">{t('coldEmail.nameRequiredTitle')}</p>
            <p className="text-sm text-gray-500 max-w-md">{t('coldEmail.nameRequiredBody')}</p>
            <Link
              href="/"
              onClick={onClose}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors"
            >
              {t('coldEmail.nameRequiredCta')}
            </Link>
          </div>
        )}
        {error && !nameRequired && (
          <div className="flex flex-col items-center justify-center py-20 gap-4">
            <AlertCircle className="w-8 h-8 text-red-500" />
            <p className="text-sm text-red-600">{error}</p>
            <button type="button" onClick={fetchVariants} className="text-sm text-indigo-600 underline hover:text-indigo-700">{t('coldEmail.tryAgain')}</button>
          </div>
        )}

        {/* Two-panel layout */}
        {!loading && !error && !nameRequired && (
          <>
            <div className="flex-1 flex flex-col lg:flex-row min-h-0">
              <div className="flex-1 flex flex-col lg:border-r border-gray-100 min-w-0">
                {/* Variant tabs */}
                <div className="flex items-center gap-1 px-5 pt-4 pb-2 shrink-0">
                  {variants.map((v, i) => (
                    <button
                      key={v.id}
                      type="button"
                      onClick={() => selectVariant(i)}
                      className={`px-3 py-1.5 rounded-full text-[12px] font-medium transition-all duration-200 ${
                        activeVariant === i
                          ? 'bg-indigo-600 text-white'
                          : 'bg-black/[0.04] text-gray-500 hover:bg-black/[0.08]'
                      }`}
                    >
                      {v.label}
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={handleAiPillClick}
                    disabled={aiLoading}
                    title={t('coldEmail.aiVariantTitle')}
                    className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-[12px] font-medium transition-all duration-200 disabled:opacity-60 disabled:cursor-wait ${
                      activeVariant === variants.length && aiVariant
                        ? 'bg-gradient-to-r from-indigo-600 to-fuchsia-500 text-white shadow-sm'
                        : 'bg-indigo-50 text-indigo-600 hover:bg-indigo-100'
                    }`}
                  >
                    {aiLoading ? (
                      <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />
                    ) : null}
                    {aiLoading && aiStage
                      ? t(STAGE_LABEL_KEYS[aiStage])
                      : t('coldEmail.aiVariantLabel')}
                  </button>
                </div>

                {/* Tone picker — drives the AI draft's voice. The recommended
                    tone is derived from the detected lab type (no scraping). */}
                <div className="flex items-center gap-1.5 px-5 pb-2 shrink-0 flex-wrap">
                  <span className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mr-0.5">
                    {t('coldEmail.tone.label')}
                  </span>
                  {STYLE_KEYS.map((s) => {
                    const isActive = activeVariant === variants.length && aiVariant != null && selectedStyle === s;
                    const isRecommended = recommendedStyle === s;
                    return (
                      <button
                        key={s}
                        type="button"
                        onClick={() => handleToneClick(s)}
                        disabled={aiLoading}
                        className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium transition-all duration-200 disabled:opacity-60 disabled:cursor-wait ${
                          isActive
                            ? 'bg-indigo-600 text-white shadow-sm'
                            : 'bg-indigo-50/70 text-indigo-600 hover:bg-indigo-100'
                        }`}
                      >
                        {t(`coldEmail.tone.${s}`)}
                        {isRecommended && (
                          <span
                            className={`text-[9px] font-semibold uppercase tracking-wide px-1 py-px rounded ${
                              isActive ? 'bg-white/25 text-white' : 'bg-indigo-100 text-indigo-500'
                            }`}
                          >
                            {t('coldEmail.tone.recommended')}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>

                <div className="flex-1 overflow-y-auto px-5 pb-4 space-y-4">
                  <div>
                    <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                      {t('coldEmail.to')}
                    </label>
                    <input
                      type="email"
                      value={recipient}
                      onChange={(e) => setRecipient(e.target.value)}
                      placeholder={t('coldEmail.toPlaceholder')}
                      className={`w-full px-3.5 py-2.5 border rounded-xl text-sm text-gray-900 placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none transition-all ${!recipient ? 'border-amber-300 bg-amber-50/30' : 'border-gray-200'}`}
                    />
                    {!recipient && recipientStatus === 'sign_in_required' ? (
                      /* W10b: a verified address exists behind the sign-in
                         gate — offer sign-in instead of the "we couldn't find
                         one" state, which would be a lie here. */
                      <div className="mt-2 rounded-lg bg-indigo-50 border border-indigo-200 px-3 py-2" data-testid="recipient-sign-in">
                        <p className="text-[12px] font-medium text-indigo-900">
                          {t('coldEmail.signInToRevealTitle')}
                        </p>
                        <p className="mt-0.5 text-[12px] leading-snug text-indigo-700">
                          {t('coldEmail.signInToRevealBody')}
                        </p>
                        <button
                          type="button"
                          onClick={() => openModal({ reason: 'contact-reveal' })}
                          className="mt-1.5 inline-flex items-center px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-[12px] font-semibold hover:bg-indigo-700 transition-colors"
                        >
                          {t('coldEmail.signInToRevealCta')}
                        </button>
                      </div>
                    ) : !recipient ? (
                      <div className="mt-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2">
                        <p className="text-[12px] font-medium text-amber-800">
                          {t('coldEmail.emailUnavailableTitle')}
                        </p>
                        <p className="mt-0.5 text-[12px] leading-snug text-amber-700">
                          {t('coldEmail.emailUnavailableBody')}
                        </p>
                        {opportunitySchool && SELF_LOOKUP_DIRECTORIES[opportunitySchool] && (
                          <a
                            href={SELF_LOOKUP_DIRECTORIES[opportunitySchool].url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="mt-1 inline-block text-[12px] font-medium text-amber-800 underline underline-offset-2 hover:text-amber-900"
                          >
                            {t('coldEmail.emailLookupDirectory', {
                              directory: SELF_LOOKUP_DIRECTORIES[opportunitySchool].name,
                            })}
                          </a>
                        )}
                      </div>
                    ) : (
                      <p className="mt-1.5 text-[11px] text-gray-400">
                        {t('coldEmail.verifyBeforeSend')}
                      </p>
                    )}
                  </div>
                  <div>
                    {/* Above the grounding notice: whether the person still
                        holds this post outranks how well-tailored the draft
                        is. 'inactive' is red because the record was actually
                        retired (departed faculty, expired posting); 'stale' is
                        amber because it is only past the re-verification TTL. */}
                    {(freshness === 'inactive' || freshness === 'stale') && (
                      <div
                        className={`mb-3 rounded-lg border px-3 py-2 ${
                          freshness === 'inactive'
                            ? 'bg-red-50 border-red-200'
                            : 'bg-amber-50 border-amber-200'
                        }`}
                        data-testid="freshness-notice"
                      >
                        <p className={`text-[12px] font-medium ${
                          freshness === 'inactive' ? 'text-red-800' : 'text-amber-800'
                        }`}>
                          {freshness === 'inactive'
                            ? t('coldEmail.sourceInactiveTitle')
                            : t('coldEmail.sourceStaleTitle')}
                        </p>
                        <p className={`mt-0.5 text-[12px] leading-snug ${
                          freshness === 'inactive' ? 'text-red-700' : 'text-amber-700'
                        }`}>
                          {freshness === 'inactive'
                            ? t('coldEmail.sourceInactiveBody')
                            : t('coldEmail.sourceStaleBody')}
                        </p>
                      </div>
                    )}
                    {grounding === 'no_target_data' && (
                      /* Evidence honesty: nothing in this record could
                         personalize a draft, so say so instead of letting a
                         generic email pass as tailored homework. */
                      <div className="mb-3 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2" data-testid="grounding-notice">
                        <p className="text-[12px] font-medium text-amber-800">
                          {t('coldEmail.noTargetDataTitle')}
                        </p>
                        <p className="mt-0.5 text-[12px] leading-snug text-amber-700">
                          {t('coldEmail.noTargetDataBody')}
                        </p>
                      </div>
                    )}
                    <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">{t('coldEmail.subject')}</label>
                    <input
                      type="text"
                      value={subject}
                      onChange={(e) => setSubject(e.target.value)}
                      className="w-full px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm font-medium text-gray-900 focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none transition-all"
                    />
                  </div>
                  <div className="flex-1 flex flex-col">
                    <div className="flex items-center gap-2 mb-1.5">
                      <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('coldEmail.body')}</label>
                      {/* FE-5: durable provenance — the active variant is the AI
                          pill but the backend served the template; say so here so
                          the signal survives chat-scroll and reopen. */}
                      {activeVariant === variants.length && aiVariant && aiVariant.method !== 'ai' && (
                        <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-amber-50 text-amber-700">
                          {t('coldEmail.templateFallbackBadge')}
                        </span>
                      )}
                    </div>
                    <textarea
                      value={body}
                      onChange={(e) => setBody(e.target.value)}
                      rows={12}
                      className="w-full flex-1 px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-700 leading-relaxed focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none transition-all resize-y"
                    />
                  </div>
                </div>
              </div>

              <div className="w-full lg:w-80 flex flex-col bg-gray-50/60 min-w-0 border-t lg:border-t-0 border-gray-100">
                <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 shrink-0">
                  <Sparkles className="w-4 h-4 text-indigo-500" />
                  <span className="text-sm font-semibold text-gray-700">{t('coldEmail.refine')}</span>
                </div>

                {labType && (
                  <div className="px-4 pt-3 shrink-0">
                    <EmailTipsPanel labType={labType} />
                  </div>
                )}

                {/* Chat messages */}
                <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
                  {chatMessages.map((msg, i) => (
                    <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div
                        className={`max-w-[90%] px-3 py-2 rounded-xl text-[13px] leading-relaxed ${
                          msg.role === 'user'
                            ? 'bg-indigo-600 text-white rounded-br-sm'
                            : 'bg-white text-gray-700 border border-gray-200 rounded-bl-sm shadow-sm'
                        }`}
                      >
                        {msg.content}
                      </div>
                    </div>
                  ))}
                  <div ref={chatEndRef} />
                </div>

                {/* Quick actions */}
                <div className="px-4 pb-2 shrink-0">
                  <div className="flex flex-wrap gap-1.5">
                    {QUICK_ACTION_KEYS.map((key) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => handleQuickAction(key)}
                        className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-white border border-gray-200 text-gray-600 hover:bg-gray-100 transition-colors"
                      >
                        {t(`coldEmail.quickActions.${key}`)}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Chat input */}
                <div className="px-4 pb-4 pt-2 shrink-0">
                  <form
                    onSubmit={(e) => { e.preventDefault(); handleChatSubmit(); }}
                    className="flex items-center gap-2"
                  >
                    <input
                      type="text"
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      placeholder={t('coldEmail.refinePlaceholder')}
                      className="flex-1 px-3 py-2 border border-gray-200 rounded-xl text-sm bg-white placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500/20 outline-none transition-all"
                    />
                    <button
                      type="submit"
                      disabled={!chatInput.trim()}
                      className="p-2 rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
                    >
                      <Send className="w-4 h-4" />
                    </button>
                  </form>
                </div>
              </div>
            </div>

            {/* Post-draft strip — appears once the email is copied/opened.
                First asks for explicit confirmation that the email was
                actually sent (copying/opening a draft is not a send); only
                after the user confirms is the contact recorded and the
                follow-up reminder offered. */}
            {contactedHere && (
              <div className="flex flex-wrap items-center gap-2 px-6 py-2.5 border-t border-gray-100 bg-amber-50/60 shrink-0 text-sm">
                {!confirmedHere ? (
                  <>
                    <span className="inline-flex items-center gap-1.5 text-gray-600">
                      <Send className="w-4 h-4 text-amber-500" />
                      {t('coldEmail.sentQuestion')}
                    </span>
                    <button
                      type="button"
                      onClick={() => { void confirmSent(); }}
                      disabled={confirming}
                      data-testid="cold-email-confirm-sent"
                      className="px-2.5 py-1 rounded-lg border border-amber-200 bg-white text-[12px] font-medium text-amber-700 hover:bg-amber-100 transition-colors disabled:opacity-60 disabled:cursor-wait"
                    >
                      {confirming
                        ? t('coldEmail.confirming')
                        : sendError === 'confirm'
                          ? t('coldEmail.confirmRetry')
                          : t('coldEmail.confirmSent')}
                    </button>
                    {(sendError === 'confirm' || sendError === 'owner-changed') && (
                      <span className="inline-flex items-center gap-1.5 text-red-600" role="status">
                        <AlertCircle className="w-4 h-4 shrink-0" aria-hidden="true" />
                        {t(sendError === 'confirm'
                          ? 'coldEmail.confirmFailed'
                          : 'coldEmail.confirmOwnerChanged')}
                      </span>
                    )}
                  </>
                ) : confirmedStatus === 'dismissed' || confirmedStatus === 'rejected' ? (
                  // The confirm RPC never downgrades a status, so a row the
                  // student had already marked reaches here after a perfectly
                  // real send and comes back unchanged. Saying only that a
                  // reminder is unavailable left them believing the outreach
                  // was on their board — and for 'dismissed' the tracker omits
                  // the row from every column, so it is nowhere at all.
                  <span className="inline-flex items-center gap-1.5 text-gray-500">
                    <BellRing className="w-4 h-4 text-gray-400" />
                    {t(
                      confirmedStatus === 'dismissed'
                        ? 'coldEmail.confirmedKeptDismissed'
                        : 'coldEmail.confirmedKeptStatus',
                    )}
                  </span>
                ) : !followUpDeliverable ? (
                  // The whole reminder block, not just the chips. Offering
                  // "want a reminder?" and then having nothing to offer is
                  // the same false capability one step earlier.
                  <span className="inline-flex items-center gap-1.5 text-gray-500">
                    <BellRing className="w-4 h-4 text-gray-400" />
                    {t('coldEmail.reminderUnavailable')}
                  </span>
                ) : (
                  <>
                    {followUpDate ? (
                      <span className="inline-flex items-center gap-1.5 font-medium text-amber-700">
                        <BellRing className="w-4 h-4" />
                        {t('coldEmail.reminderSet', { date: followUpDate })}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-gray-600">
                        <BellRing className="w-4 h-4 text-amber-500" />
                        {t('coldEmail.remindPrompt')}
                      </span>
                    )}
                    {/* The chips stay after a date is chosen: a reminder is
                        changeable, and changing it must go through the same
                        reminder-only write rather than another confirmation. */}
                    {([['coldEmail.remind3', 3], ['coldEmail.remind7', 7], ['coldEmail.remind14', 14]] as const).map(
                      ([key, days]) => (
                        <button
                          key={days}
                          type="button"
                          onClick={() => { void setFollowUp(days); }}
                          className="px-2.5 py-1 rounded-lg border border-amber-200 bg-white text-[12px] font-medium text-amber-700 hover:bg-amber-100 transition-colors"
                        >
                          {t(key)}
                        </button>
                      ),
                    )}
                    {sendError === 'reminder' && (
                      <span className="inline-flex items-center gap-1.5 text-red-600" role="status">
                        <AlertCircle className="w-4 h-4" aria-hidden="true" />
                        {t('coldEmail.reminderFailed')}
                      </span>
                    )}
                  </>
                )}
              </div>
            )}

            {/* Footer */}
            <div className="flex items-center justify-end gap-3 px-6 py-3 border-t border-gray-100 bg-gray-50/50 shrink-0">
              {copyFailed && (
                <span className="inline-flex items-center gap-1.5 text-[12px] text-red-600" role="status">
                  <AlertCircle className="w-4 h-4 shrink-0" aria-hidden="true" />
                  {t('coldEmail.copyFailed')}
                </span>
              )}
              <button
                type="button"
                onClick={handleCopy}
                className="inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors"
              >
                {copied ? (
                  <><CheckCircle className="w-4 h-4 text-emerald-500" />{t('coldEmail.copied')}</>
                ) : (
                  <><Copy className="w-4 h-4" />{t('coldEmail.copy')}</>
                )}
              </button>
              {/* FE-2: the deep-link send buttons open a real compose window, so
                  disable them when no recipient is resolved — otherwise the user
                  is dropped into a draft addressed to nobody with no warning. The
                  amber "To" hint above guides them to add an address; the Copy
                  button stays enabled since pasting elsewhere is still useful. */}
              <div
                className="flex items-stretch rounded-xl overflow-hidden shadow-sm"
                title={!recipient.trim() ? t('coldEmail.toHint') : undefined}
              >
                <button
                  type="button"
                  disabled={!recipient.trim()}
                  onClick={() => { window.open(getMailtoLink('default'), '_blank'); markContacted(); }}
                  className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-semibold text-white bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-700 hover:to-indigo-600 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ExternalLink className="w-4 h-4" />
                  {t('coldEmail.openInEmail')}
                </button>
                <div className="w-px bg-indigo-400" />
                <button
                  type="button"
                  disabled={!recipient.trim()}
                  onClick={() => { window.open(getMailtoLink('gmail'), '_blank'); markContacted(); }}
                  className="inline-flex items-center justify-center px-3 py-2.5 text-[11px] font-semibold text-indigo-100 bg-indigo-600 hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  title={t('coldEmail.openGmailTitle')}
                >
                  {t('coldEmail.gmail')}
                </button>
                <button
                  type="button"
                  disabled={!recipient.trim()}
                  onClick={() => { window.open(getMailtoLink('outlook'), '_blank'); markContacted(); }}
                  className="inline-flex items-center justify-center px-3 py-2.5 text-[11px] font-semibold text-indigo-100 bg-indigo-600 hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  title={t('coldEmail.openOutlookTitle')}
                >
                  {t('coldEmail.outlook')}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
