'use client';

import { canFallbackColdEmailStream } from '@/lib/cold-email-stream';
import { writingTargetVersion } from '@/lib/writing-target-version';
import { isPublicDetail } from '@/lib/public-target-shape';
import { defaultEmailContactContext, serializeEmailContactContext, emailContactContextSignature, requireEmailContactContextReceipt } from '@/lib/email-contact-context';
import type { EmailContactContext } from '@/lib/types';
import EmailContactContextPanel from './EmailContactContextPanel';
import { createContactEventInput, contactMaterialVersion, ContactEventError } from '@/lib/contact-ledger';

import { useState, useEffect, useLayoutEffect, useCallback, useMemo, useRef } from 'react';
import Link from 'next/link';
import { captureOwnerToken, isTokenOwnerStillCurrent, onLocalOwnerStateChange } from '@/lib/identity-owner';
import { canDeliverReminder } from '@/lib/reminders';
import { getPushStatus, isPushSupported, subscribeToPush } from '@/lib/push';
import { getVapidPublicKey } from '@/lib/api';
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
  type ColdEmailStage,
} from '@/lib/api';
import {
  confirmContactEvent,
  onAuthChange,
  updateInteractionDetails,
} from '@/lib/supabase';
import type { InteractionRecord, InteractionType } from '@/lib/supabase';
import { useAuthModal } from '@/lib/auth-modal-context';
import { isActiveExperience, sourceDigest, validateExperienceEntries } from '@/lib/experience-evidence';
import type { Opportunity, ProfileData, EmailVariant, LabType, EmailStyle, ColdEmailFallbackReason, ColdEmailResponse, ContactEmailStatus, ExperienceUsage } from '@/lib/types';
import { useT } from '@/i18n/client';
import type { ProfileRefreshState } from '@/lib/use-profile-refresh';
import type { WritingTargetState } from '@/lib/use-writing-target';
import { useProfileAction } from '@/lib/use-profile-action';
import ProfileRefreshBanner, { profileRefreshReady } from './ProfileRefreshBanner';
import LabTypeBadge from './LabTypeBadge';
import EmailTipsPanel from './EmailTipsPanel';
import styles from './ColdEmailModal.module.css';

const AI_VARIANT_ID = 'ai';
// W12: a cached AI draft is re-served for at most this long — beyond it the
// professor record may have moved (email nulled, works revoked) and the
// draft must regenerate from the live corpus.
export const AI_CACHE_TTL_MS = 30 * 60 * 1000;

/** In-tab reuse needs the pipeline version freshly returned by variants.
 *  Missing versions cannot establish compatibility. Corpus changes and the
 *  TTL still expire an otherwise compatible draft. Exported for tests. */
export function aiCacheEntryIsStale(
  entry: { response: { corpus_version?: string | null; pipeline_version?: string | null; target_version?: string | null }; at: number },
  nowMs: number,
  currentCorpusVersion: string | null,
  currentPipelineVersion: string | null,
  currentTargetVersion: string | null,
): boolean {
  if (!currentTargetVersion || entry.response.target_version !== currentTargetVersion) return true;
  if (nowMs - entry.at > AI_CACHE_TTL_MS) return true;
  if (!entry.response.pipeline_version?.trim() || !currentPipelineVersion?.trim()
    || entry.response.pipeline_version !== currentPipelineVersion) return true;
  return (
    !!entry.response.corpus_version &&
    !!currentCorpusVersion &&
    entry.response.corpus_version !== currentCorpusVersion
  );
}
type TargetVersionFailure = 'unavailable' | 'changed';
function targetVersionFailure(error: unknown): TargetVersionFailure | null {
  if (!error || typeof error !== 'object' || !('code' in error)) return null;
  return error.code === 'WRITING_TARGET_CHANGED' ? 'changed'
    : error.code === 'INVALID_WRITING_TARGET_RECEIPT' ? 'unavailable' : null;
}
function requireTargetReceipt(response: unknown, id: string, version: string) {
  if (!response || typeof response !== 'object' || Array.isArray(response)
    || !('opportunity_id' in response) || response.opportunity_id !== id
    || !('target_version' in response) || response.target_version !== version) {
    throw Object.assign(new Error('Invalid writing target receipt'), { code: 'INVALID_WRITING_TARGET_RECEIPT' });
  }
}
async function requireContactReceipt(response: unknown, context: EmailContactContext) {
  const expected = { purpose: context.purpose, context_sig: await emailContactContextSignature(context) };
  requireEmailContactContextReceipt(response, expected);
  if (response && typeof response === 'object' && 'variants' in response && Array.isArray(response.variants)) {
    for (const variant of response.variants) requireEmailContactContextReceipt(variant, expected);
  }
}
const STYLE_KEYS: readonly EmailStyle[] = ['professional', 'warm', 'friendly', 'lively'];

interface ColdEmailModalProps {
  isOpen: boolean;
  targetReady?: boolean;
  targetChecking?: boolean;
  /** False keeps the open draft; the retained profile is not current material. */
  profileAvailable?: boolean;
  profileRefresh?: ProfileRefreshState;
  target?: Opportunity | null;
  targetRefresh?: WritingTargetState;
  targetMembershipReady?: boolean;
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
  requestId?: number;
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
  targetReady = true,
  targetChecking = false,
  profileAvailable = true,
  profileRefresh,
  target,
  targetRefresh,
  targetMembershipReady,
}: ColdEmailModalProps) {
  const { t, locale } = useT();
  const expectedTargetVersion = isPublicDetail(target, opportunityId) ? writingTargetVersion(target) : null;
  const sourceReady = profileAvailable && targetReady && profileRefreshReady(profileRefresh) && (!targetRefresh || targetRefresh.status === 'ready');
  const sourceReadyRef = useRef(sourceReady);
  useLayoutEffect(() => { sourceReadyRef.current = sourceReady; }, [sourceReady]);
  const { openModal } = useAuthModal();
  // Bind requests and cache lifetime to all factual inputs, including entry
  // status/revision/source changes and an in-place profile update by a caller.
  const profileFingerprint = JSON.stringify(profile);
  // A list refresh may temporarily withdraw the target. That is unknown,
  // not a change to its facts. Keep the last observed content for comparison.
  const [knownTarget, setKnownTarget] = useState({ id: opportunityId, fingerprint: JSON.stringify(target ?? reminderTarget ?? null) });
  const targetFingerprint = target || reminderTarget ? JSON.stringify(target ?? reminderTarget)
    : knownTarget.id === opportunityId ? knownTarget.fingerprint : 'null';
  if (knownTarget.id !== opportunityId || knownTarget.fingerprint !== targetFingerprint) {
    setKnownTarget({ id: opportunityId, fingerprint: targetFingerprint });
  }
  const [contactState, setContactState] = useState(() => ({
    id: opportunityId, value: defaultEmailContactContext(), revision: 0, dirty: false,
  }));
  // Stamp private background to its target before the new target can request.
  const effectiveContact = contactState.id === opportunityId ? contactState : {
    id: opportunityId, value: defaultEmailContactContext(), revision: 0, dirty: false,
  };
  if (contactState.id !== opportunityId) setContactState(effectiveContact);
  const contactSerialized = serializeEmailContactContext(effectiveContact.value);
  const requestContactContext = useMemo(() => JSON.parse(contactSerialized) as EmailContactContext, [contactSerialized]);
  const contextDirty = effectiveContact.dirty;
  const contextDirtyRef = useRef(contextDirty);
  useLayoutEffect(() => { contextDirtyRef.current = contextDirty; }, [contextDirty]);
  // Once the user opens a background edit, only an explicit new-draft action
  // may generate, including when the first response has not arrived yet.
  const contextEditedRef = useRef(false);
  const [contextChanged, setContextChanged] = useState(false);
  const contactFingerprint = `${effectiveContact.revision}\n${contactSerialized}`;
  const materialFingerprint = `${profileFingerprint}\n${targetFingerprint}\n${contactFingerprint}`;
  const requestProfile = useMemo(() => JSON.parse(profileFingerprint) as ProfileData, [profileFingerprint]);
  const draftSourcesRef = useRef<{ profile: string; target: string | null; contact: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [targetVersionError, setTargetVersionError] = useState<TargetVersionFailure | null>(null);
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
  const [actualSentAt, setActualSentAt] = useState('');
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
  const [experienceUsage, setExperienceUsage] = useState<ExperienceUsage | null>(null);
  const [experienceNeedsReview, setExperienceNeedsReview] = useState(false);
  const experienceBudgetOmission = experienceUsage?.notices.some((notice) =>
    notice === 'experience_prompt_budget_omission' || notice === 'experience_template_budget_omission',
  ) ?? false;
  const experienceReceiptLimited = experienceUsage?.notices.includes('experience_usage_receipt_limit') ?? false;
  const [freshness, setFreshness] =
    useState<'fresh' | 'stale' | 'inactive' | 'unknown'>('unknown');
  const [copiedFor, setCopiedFor] = useState<{ contents: string } | null>(null);
  const [copyFailedFor, setCopyFailedFor] = useState<string | null>(null);
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
  const [sendDraftEpoch, setSendDraftEpoch] = useState(0);
  const sendDraftEpochRef = useRef(0);
  // Clipboard feedback belongs to the exact displayed draft, independently
  // of whether an edit starts a new send-confirmation epoch.
  const copyContentKey = JSON.stringify([subject, body, recipient, sendDraftEpoch]);
  const copyContentKeyRef = useRef(copyContentKey);
  useLayoutEffect(() => { copyContentKeyRef.current = copyContentKey; }, [copyContentKey]);
  const copied = copiedFor?.contents === copyContentKey;
  const copyFailed = copyFailedFor === copyContentKey;
  const [contactedDraftEpoch, setContactedDraftEpoch] = useState<number | null>(null);
  const [confirmedDraftEpoch, setConfirmedDraftEpoch] = useState<number | null>(null);
  const [contactedContentKey, setContactedContentKey] = useState<string | null>(null);
  const [confirmedContentKey, setConfirmedContentKey] = useState<string | null>(null);
  const confirmationKey = JSON.stringify([copyContentKey, actualSentAt]);
  const confirmationKeyRef = useRef(confirmationKey);
  useLayoutEffect(() => { confirmationKeyRef.current = confirmationKey; }, [confirmationKey]);
  const contactedHere = contacted && contactedForId === opportunityId && contactedDraftEpoch === sendDraftEpoch
    && contactedContentKey === copyContentKey;
  const [sendConfirmed, setSendConfirmed] = useState(false);
  const [followUpDate, setFollowUpDate] = useState<string | null>(null);
  // The reminders cron has a third filter the reminder controls never checked:
  // a channel to reach this student. push.py counts `no_channel` when there is
  // no push_subscriptions row for the device AND _account_email returns None,
  // which is always true for an anonymous one. Those students still get the
  // reminder — it renders on the Tracker card and flips to "Follow-up due" —
  // but nothing arrives outside the app, and nothing offered to change that.
  // null = not determined yet; the offer stays hidden until it is known.
  const [pushOffer, setPushOffer] = useState<'available' | 'subscribed' | null>(null);
  const [pushBusy, setPushBusy] = useState(false);
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
  const confirmedHere = sendConfirmed && confirmedForId === opportunityId && confirmedDraftEpoch === sendDraftEpoch
    && confirmedContentKey === confirmationKey;
  // Identity first, then deliverability. A live record for a different id is
  // still a live record — canDeliverReminder would happily say yes to it.
  const followUpDeliverable = confirmedHere
    && reminderTarget?.id === opportunityId
    && canDeliverReminder(reminderTarget, confirmedStatus);
  const [confirming, setConfirming] = useState(false);
  // Which persistence outcome could not be confirmed. A rejected response
  // does not prove that the server wrote nothing; a failed reminder also does
  // not undo a confirmed contact. An owner move must not report the old
  // operation as success for the current account. Errors belong to this session AND
  // draft epoch: rebuilding clears them, and old writers cannot restore them.
  type SendError = 'confirm' | 'reminder' | 'owner-changed' | 'invalid-contact' | 'contact-conflict';
  const [sendFailure, setSendFailure] = useState<{ key: string; error: SendError } | null>(null);
  const sendError = sendFailure?.key === confirmationKey ? sendFailure.error : null;
  const setSendError = useCallback((error: SendError | null) => {
    setSendFailure(error ? { key: confirmationKeyRef.current, error } : null);
  }, []);

  const allVariants: EmailVariant[] = aiVariant ? [...variants, aiVariant] : variants;

  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [userEditRevision, setUserEditRevision] = useState(0);
  const noteUserEdit = () => setUserEditRevision((value) => value + 1);
  const [refining, setRefining] = useState(false);
  const [retired, setRetired] = useState(false);
  const [profileChanged, setProfileChanged] = useState(false);
  // Layout can flush a queued intent before its state update is rendered.
  // Retire the old draft synchronously before that executor can consume it.
  const profileChangedRef = useRef(false);
  const [profileRegenerating, setProfileRegenerating] = useState(false);
  const [profileRegenerateError, setProfileRegenerateError] = useState<'failed' | 'edited' | 'name-required' | null>(null);
  const chatHistoryRef = useRef<HTMLDivElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  // AI is the default engine: one automatic pipeline run per open, kicked off
  // once the template variants land. Reset on close.
  const autoFiredRef = useRef(false);
  // A failed receipt may be checked again without spending generation or
  // replacing a draft. Only an explicit generation intent clears this fence.
  const targetCheckOnlyRef = useRef(false);
  // Real AI drafts per (opportunity, style): reopening the same opportunity
  // reuses the draft instead of re-billing the pipeline. Fallback responses
  // are never cached (they retry on the next open). Cleared when the profile
  // prop changes — a draft must not outlive a profile edit. W12: entries
  // also expire after AI_CACHE_TTL_MS and whenever the backend's
  // corpus_version or pipeline_version moves, so a long-lived tab does not
  // reuse superseded research or writing rules.
  const aiCacheRef = useRef<Map<string, { response: ColdEmailResponse; at: number }>>(new Map());
  const corpusVersionRef = useRef<string | null>(null);
  // Only the current session's variants may set the comparison version. An
  // AI response may come from an older worker; it cannot certify itself.
  const pipelineVersionRef = useRef<string | null>(null);
  // A target change flushes old passive effects after layout cleanup. They
  // must not start AI from the previous render's variants/loading values.
  const variantsReadyRef = useRef(false);
  // Which send session an in-flight persistence belongs to. Bumped on every
  // close and every target change, so a completion that comes back after the
  // modal moved on can be identified as belonging to a session that no longer
  // exists. An immutable number, not object identity: the modal stays mounted
  // across open/close and target switches, so there is no object to compare.
  const sendSessionRef = useRef(0);
  // Material changes retire writing, but are not a new contact/target session.
  const profileSessionRef = useRef(0);
  const sessionProfileRef = useRef(materialFingerprint);
  // Which confirmation attempt within that session. A retry supersedes the
  // attempt it retried, so a straggler cannot paint over the newer answer.
  const confirmAttemptRef = useRef(0);
  // One atomic call per attestation: held for the duration of the round trip
  // and released by whoever set it, so a double click cannot open a second.
  const confirmInFlightRef = useRef(false);
  const draftRevisionRef = useRef(0);
  const editorUsedRef = useRef(false);
  const variantRequestRef = useRef(0);
  const aiRequestRef = useRef(0);
  const aiInFlightRef = useRef(false);
  const refineRequestRef = useRef(0);
  const refineInFlightRef = useRef<number | null>(null);

  const captureDraftSession = useCallback(() => {
    const session = sendSessionRef.current;
    const materials = profileSessionRef.current;
    const owner = captureOwnerToken();
    return () => sourceReadyRef.current && !contextDirtyRef.current && sendSessionRef.current === session && profileSessionRef.current === materials && isTokenOwnerStillCurrent(owner);
  }, []);

  const closeDraft = useCallback(() => {
    // End the session at the click/escape, even if the parent closes later.
    sendSessionRef.current += 1;
    setRetired(true);
    onClose();
  }, [onClose]);

  // The epoch changes synchronously, before a parent's new profile reaches
  // this dialog. End the old draft session instead of generating with that
  // old profile under the next account. Same-owner token refresh is harmless.
  useEffect(() => {
    const owner = captureOwnerToken();
    return onLocalOwnerStateChange(() => {
      if (isTokenOwnerStillCurrent(owner)) return;
      sendSessionRef.current += 1;
      aiCacheRef.current.clear();
      if (isOpen) {
        closeDraft();
      }
    });
  }, [isOpen, closeDraft]);

  useLayoutEffect(() => { aiCacheRef.current.clear(); }, [materialFingerprint]);

  const reportTargetVersionFailure = useCallback((failure: TargetVersionFailure) => {
    // Reveal can fail concurrently with AI/refine. Retire every writing
    // callback synchronously, not the human editor or confirmed send state.
    profileSessionRef.current += 1;
    variantRequestRef.current += 1; aiRequestRef.current += 1;
    const retiredRefine = refineInFlightRef.current;
    refineInFlightRef.current = null; aiInFlightRef.current = false;
    setLoading(false); setAiLoading(false); setAiStage(null);
    setRefining(false); setProfileRegenerating(false);
    if (retiredRefine !== null) setChatMessages(messages => messages.map(message =>
      message.requestId === retiredRefine ? { ...message, content: t('coldEmail.editFailed') } : message));
    targetCheckOnlyRef.current = true;
    variantsReadyRef.current = false;
    aiCacheRef.current.clear();
    setTargetVersionError(failure);
  }, [t]);

  const fetchVariants = useCallback(async (preserveDraft = false, keepEditor = false) => {
    if (!sourceReadyRef.current || contextDirtyRef.current) return;
    const sessionCurrent = captureDraftSession();
    const request = ++variantRequestRef.current;
    const current = () => sessionCurrent() && request === variantRequestRef.current;
    const revision = draftRevisionRef.current;
    if (!preserveDraft) variantsReadyRef.current = false;
    if (!expectedTargetVersion) { reportTargetVersionFailure('unavailable'); setLoading(false); return; }
    if (missingStudentName) {
      setLoading(false);
      if (keepEditor) setProfileRegenerateError('name-required');
      else setNameRequired(true);
      return;
    }
    if (keepEditor) { setProfileRegenerating(true); setProfileRegenerateError(null); }
    else if (!preserveDraft) setLoading(true);
    setError(null);
    setNameRequired(false);
    try {
      const data = await getEmailVariants(requestProfile, opportunityId, undefined, { expectedTargetVersion, contactContext: requestContactContext });
      if (!current()) return;
      requireTargetReceipt(data, opportunityId, expectedTargetVersion);
      await requireContactReceipt(data, requestContactContext);
      if (!current()) return;
      if (data.variants.length === 0) throw new Error(t('coldEmail.failedGenerate'));
      if (keepEditor && revision !== draftRevisionRef.current) {
        setProfileRegenerateError('edited');
        return;
      }
      variantsReadyRef.current = true;
      setTargetVersionError(null);
      setVariants(data.variants);
      const inferredLabType =
        data.lab_type
        ?? (data.variants.find((v) => v.lab_type)?.lab_type ?? null);
      setLabType(inferredLabType);
      const rec = data.recommended_style ?? null;
      setRecommendedStyle(rec);
      if (rec && !preserveDraft) setSelectedStyle(rec);
      setRecipientStatus(
        statusOf(data.recipient_status, data.variants[0]?.recipient_email ?? ''),
      );
      setGrounding(data.grounding ?? 'specific');
      setFreshness(data.source_freshness ?? 'unknown');
      // W12: variants regenerate on every open, so their corpus_version is
      // the "current" mark that decides whether a cached AI draft survives.
      if (data.corpus_version) corpusVersionRef.current = data.corpus_version;
      pipelineVersionRef.current = data.pipeline_version ?? null;
      if (!preserveDraft && revision === draftRevisionRef.current && data.variants.length > 0) {
        const first = data.variants[0];
        setSubject(first.subject);
        setBody(first.body);
        draftSourcesRef.current = { profile: JSON.stringify(requestProfile), target: expectedTargetVersion, contact: serializeEmailContactContext(requestContactContext) };
        if (!keepEditor) setRecipient(first.recipient_email);
        editorUsedRef.current = true;
        setActiveVariant(0);
        setExperienceUsage(first.experience_usage ?? null);
        profileChangedRef.current = false;
        setProfileChanged(false);
        contextEditedRef.current = false;
        setContextChanged(false);
        // Explicit regeneration runs the normal AI pipeline after fresh templates.
        if (keepEditor) {
          autoFiredRef.current = false;
          // A newly built draft needs its own explicit send attestation.
          // Keep the historical contact/reminder record and allow its pending
          // receipt to update the parent, without confirming this new draft.
          sendDraftEpochRef.current += 1;
          setSendDraftEpoch(sendDraftEpochRef.current);
          setActualSentAt('');
          setCopiedFor(null); setCopyFailedFor(null);
          setSendError(null);
        }
      }
      if (!preserveDraft) setChatMessages([
        { role: 'assistant', content: t('coldEmail.generated', { count: data.variants.length }) },
      ]);
    } catch (err) {
      if (!current()) return;
      const targetFailure = targetVersionFailure(err);
      if (targetFailure) { reportTargetVersionFailure(targetFailure); }
      else if (keepEditor) {
        setProfileRegenerateError(isStudentNameRequiredError(err) ? 'name-required' : 'failed');
      } else if (isStudentNameRequiredError(err)) {
        setNameRequired(true);
      } else {
        setError(err instanceof Error ? err.message : t('coldEmail.failedGenerate'));
      }
    } finally {
      if (current()) {
        if (keepEditor) setProfileRegenerating(false);
        else if (!preserveDraft) setLoading(false);
      }
    }
  }, [requestProfile, requestContactContext, opportunityId, expectedTargetVersion, t, missingStudentName, captureDraftSession, reportTargetVersionFailure, setSendError]);

  type WritingIntent = { kind: 'variants'; preserveDraft?: boolean; keepEditor?: boolean }
    | { kind: 'ai'; style: EmailStyle; selectExisting?: boolean }
    | { kind: 'refine'; instruction: string; typed?: boolean; label?: string }
    | { kind: 'coursework' };
  const action = useProfileAction<WritingIntent>({
    isOpen: isOpen && !retired, profile: requestProfile, profileAvailable,
    scopeKey: `${opportunityId}\n${targetFingerprint}\n${contactFingerprint}`, editRevision: userEditRevision, refresh: profileRefresh, target, targetRefresh,
    readiness: contextDirty ? 'blocked' : sourceReady ? 'ready'
      : profileAvailable && (targetChecking || profileRefresh?.status === 'checking') ? 'waiting' : 'blocked',
    execute: (intent) => {
      if (contextDirtyRef.current) return;
      if (intent.kind === 'variants') { targetCheckOnlyRef.current = false; void fetchVariants(intent.preserveDraft, intent.keepEditor); return; }
      if (intent.kind !== 'coursework' && !expectedTargetVersion) { reportTargetVersionFailure('unavailable'); return; }
      if (intent.kind !== 'coursework' && targetVersionError) return;
      // A source change keeps the existing manual draft. Its user must choose
      // to rebuild it before new generation or refinement can use that draft.
      if (profileChangedRef.current || profileChanged || profileRegenerating) return;
      if (intent.kind === 'ai') {
        if (intent.selectExisting && aiVariant) selectVariant(variants.length);
        else void generateAi(intent.style);
        return;
      }
      if (intent.kind === 'coursework') {
        const { body: next, reply } = applyQuickEdit(body, 'coursework', requestProfile, t);
        draftRevisionRef.current += 1;
        setBody(next);
        draftSourcesRef.current = { profile: JSON.stringify(requestProfile), target: expectedTargetVersion, contact: serializeEmailContactContext(requestContactContext) };
        setChatMessages((messages) => [...messages, { role: 'user', content: t('coldEmail.quickActions.coursework') }, { role: 'assistant', content: reply }]);
        return;
      }
      if (intent.typed) setChatInput('');
      setChatMessages((messages) => [...messages, { role: 'user', content: intent.label ?? intent.instruction }]);
      void runRefine(intent.instruction);
    },
  });
  const retireContactDraft = () => {
    action.cancel();
    contextDirtyRef.current = true;
    contextEditedRef.current = true;
    profileChangedRef.current = true;
    profileSessionRef.current += 1;
    variantRequestRef.current += 1; aiRequestRef.current += 1;
    draftRevisionRef.current += 1;
    variantsReadyRef.current = false;
    const retiredRefine = refineInFlightRef.current;
    if (retiredRefine !== null) setChatMessages(messages => messages.map(message =>
      message.requestId === retiredRefine ? { ...message, content: t('coldEmail.profileEditRetired') } : message));
    aiInFlightRef.current = false; refineInFlightRef.current = null;
    aiCacheRef.current.clear(); autoFiredRef.current = true;
    setLoading(false); setAiLoading(false); setAiStage(null); setRefining(false);
    setProfileRegenerating(false); setProfileChanged(true); setContextChanged(true);
    setContactState(previous => ({ ...previous, dirty: true, revision: previous.revision + 1 }));
  };
  const applyContactContext = (value: EmailContactContext) => {
    action.cancel();
    contextDirtyRef.current = false;
    setContactState(previous => ({ id: opportunityId, value, dirty: false, revision: previous.revision + 1 }));
  };
  const requestAction = action.request;
  const fetchVariantsRef = useRef<(preserveDraft?: boolean, keepEditor?: boolean) => void>(() => {});
  useLayoutEffect(() => {
    fetchVariantsRef.current = (preserveDraft, keepEditor) => requestAction({ kind: 'variants', preserveDraft, keepEditor });
  }, [requestAction]);

  useLayoutEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect --
       Modal-lifecycle effect. Open path calls fetchVariants() whose
       sync prefix flips setLoading(true) before any await. Cleanup
       path resets every internal state slice so the next open()
       starts from a known-empty surface — splitting this into two
       effects would race the next open's fetchVariants() with stale
       residue from the previous session. */
    setRetired(false);
    sessionProfileRef.current = materialFingerprint;
    if (isOpen) void fetchVariantsRef.current();
    return () => {
      autoFiredRef.current = false;
      contextDirtyRef.current = false; contextEditedRef.current = false;
      setContactState({ id: opportunityId, value: defaultEmailContactContext(), revision: 0, dirty: false });
      setContextChanged(false);
      targetCheckOnlyRef.current = false;
      pipelineVersionRef.current = null;
      variantsReadyRef.current = false;
      // Close or target change ends the send session. Bumping the id first
      // means any persistence still in flight can no longer reach this
      // component's state, so the resets below cannot be undone by a
      // straggler landing a moment later.
      sendSessionRef.current += 1;
      profileSessionRef.current += 1;
      aiInFlightRef.current = false;
      refineInFlightRef.current = null;
      draftRevisionRef.current += 1;
      confirmInFlightRef.current = false;
      sendDraftEpochRef.current = 0; setSendDraftEpoch(0);
      setContactedDraftEpoch(null); setConfirmedDraftEpoch(null);
      setContactedContentKey(null); setConfirmedContentKey(null); setActualSentAt('');
      setContacted(false);
      setContactedForId(null);
      setSendConfirmed(false);
      setFollowUpDate(null);
      setPushOffer(null);
      setPushBusy(false);
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
      setAiStage(null);
      setRefining(false);
      setLabType(null);
      setSelectedStyle('professional');
      setRecommendedStyle(null);
      editorUsedRef.current = false;
      setSubject('');
      setBody('');
      setRecipient('');
      draftSourcesRef.current = null;
      setRecipientStatus('unavailable');
      setGrounding('specific');
      setFreshness('unknown');
      setExperienceUsage(null);
      setExperienceNeedsReview(false);
      setCopiedFor(null);
      setCopyFailedFor(null);
      setError(null);
      setTargetVersionError(null);
      setNameRequired(false);
      setChatMessages([]);
      setChatInput('');
      profileChangedRef.current = false;
      setProfileChanged(false); setProfileRegenerating(false); setProfileRegenerateError(null);
    };
    /* eslint-enable react-hooks/set-state-in-effect */
    // Full reset belongs only to the open/target lifetime. The latest callback
    // is read through a layout-updated ref; material changes are handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, opportunityId]);

  useLayoutEffect(() => {
    if (!isOpen || sessionProfileRef.current === materialFingerprint) return;
    sessionProfileRef.current = materialFingerprint;
    profileSessionRef.current += 1;
    variantRequestRef.current += 1; aiRequestRef.current += 1;
    const retiredRefine = refineInFlightRef.current;
    refineInFlightRef.current = null; aiInFlightRef.current = false;
    draftRevisionRef.current += 1;
    variantsReadyRef.current = false; pipelineVersionRef.current = null; corpusVersionRef.current = null;
    aiCacheRef.current.clear();
    const hasDraft = contextEditedRef.current || editorUsedRef.current || !!(subject || body || recipient);
    profileChangedRef.current = hasDraft;
    autoFiredRef.current = hasDraft;
    // New material must not erase an editor or let an old response overwrite it.
    setVariants([]); setAiVariant(null); setAiLoading(false); setAiStage(null); setRefining(false);
    setLoading(!hasDraft); setError(null); if (!targetCheckOnlyRef.current) setTargetVersionError(null); setNameRequired(false); setExperienceUsage(null);
    setProfileRegenerating(false); setProfileRegenerateError(null); setProfileChanged(hasDraft);
    if (retiredRefine !== null) setChatMessages((messages) => messages.map((message) =>
      message.requestId === retiredRefine ? { ...message, content: t('coldEmail.profileEditRetired') } : message));
    // Initial material arriving before any draft may use the normal open flow.
    if (!hasDraft && !targetCheckOnlyRef.current) void fetchVariantsRef.current();
  }, [isOpen, materialFingerprint, subject, body, recipient, t]);

  const wasSourceReadyRef = useRef(sourceReady);
  useLayoutEffect(() => {
    const wasReady = wasSourceReadyRef.current;
    wasSourceReadyRef.current = sourceReady;
    if (!isOpen) return;
    if (!sourceReady) {
      // Retire every writing callback at the START of a read, including a
      // check that later returns unchanged data. Keep the editable fields.
      if (wasReady) {
        profileSessionRef.current += 1;
        variantRequestRef.current += 1; aiRequestRef.current += 1;
        const retiredRefine = refineInFlightRef.current;
        if (retiredRefine !== null) setChatMessages((messages) => messages.map((message) =>
          message.requestId === retiredRefine ? { ...message, content: t('coldEmail.sourceCheckRetired') } : message));
      }
      refineInFlightRef.current = null; aiInFlightRef.current = false;
      // A check may retire generation, but it is not a completed first draft.
      // Only an existing editor is kept visible while its source is checked.
      setLoading(!editorUsedRef.current && !(subject || body || recipient));
      setAiLoading(false); setAiStage(null); setRefining(false); setProfileRegenerating(false);
    } else if (!targetCheckOnlyRef.current && !profileRefresh?.checkForAction && !wasReady && !variantsReadyRef.current && !profileChanged) {
      void fetchVariantsRef.current(editorUsedRef.current);
    }
  }, [isOpen, sourceReady, profileChanged, profileRefresh?.checkForAction, subject, body, recipient, t]);

  useEffect(() => {
    if (!isOpen) return;
    const current = captureDraftSession();
    // This only supplies a review hint. Send the complete envelope unchanged;
    // the backend independently validates confirmation and current provenance.
    void Promise.resolve().then(async () => {
      const parsed = validateExperienceEntries(requestProfile.experience_entries);
      if (!parsed.ok) {
        if (current()) setExperienceNeedsReview(true);
        return;
      }
      const entries = parsed.value;
      const rawText = requestProfile.resume_text ?? '';
      let needsReview = entries.some((entry) => entry.status === 'candidate')
        || (rawText.trim().length > 0 && entries.length === 0);
      const sourced = entries.filter((entry) => entry.status === 'confirmed' && entry.source.kind === 'resume');
      if (sourced.length > 0) {
        try {
          const expectedDigest = await sourceDigest(rawText);
          needsReview ||= sourced.some((entry) => !isActiveExperience(entry, { rawText, expectedDigest }));
        } catch {
          needsReview = true;
        }
      }
      if (current()) setExperienceNeedsReview(needsReview);
    });
  }, [isOpen, requestProfile, captureDraftSession]);

  useEffect(() => {
    if (!isOpen || retired) return;
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
        closeDraft();
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
  }, [isOpen, retired, closeDraft]);

  useEffect(() => {
    if (isOpen && !retired) document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, [isOpen, retired]);

  useEffect(() => {
    // Only the history follows new messages; never scroll the workspace,
    // editor, or page away from the field the user is editing.
    const history = chatHistoryRef.current;
    if (history) history.scrollTop = history.scrollHeight;
  }, [chatMessages]);

  // W10b: once the user signs in from the reveal affordance, fetch the
  // recipient once via the (cheap) variants endpoint and fill the To field —
  // WITHOUT regenerating or touching the draft they may have edited. The
  // subscription also fires with the current session on mount, which
  // self-heals the stale-token case where the api-level refresh-retry failed.
  useEffect(() => {
    if (contextDirty || contextChanged || !sourceReady || !isOpen || !expectedTargetVersion || targetVersionError || recipientStatus !== 'sign_in_required') return;
    const current = captureDraftSession();
    const unsubscribe = onAuthChange((state) => {
      if (!current() || !state.session || state.isAnonymous) return;
      void (async () => {
        try {
          const data = await getEmailVariants(profile, opportunityId, undefined, { expectedTargetVersion, contactContext: requestContactContext });
          if (!current()) return;
          requireTargetReceipt(data, opportunityId, expectedTargetVersion);
          await requireContactReceipt(data, requestContactContext);
          if (!current()) return;
          const email = data.variants[0]?.recipient_email ?? '';
          setRecipientStatus(statusOf(data.recipient_status, email));
          if (email) setRecipient((prev) => prev || email);
        } catch (error) {
          const failure = targetVersionFailure(error);
          if (current() && failure) reportTargetVersionFailure(failure);
          // Other reveal failures keep the existing sign-in affordance.
        }
      })();
    });
    return unsubscribe;
  }, [contextDirty, contextChanged, requestContactContext, sourceReady, isOpen, recipientStatus, profile, opportunityId, expectedTargetVersion, targetVersionError, captureDraftSession, reportTargetVersionFailure]);

  function selectVariant(idx: number) {
    const v = allVariants[idx];
    if (!sourceReadyRef.current || contextDirtyRef.current || targetVersionError || profileChanged || profileRegenerating || !v) return;
    draftRevisionRef.current += 1;
    noteUserEdit();
    setActiveVariant(idx);
    setSubject(v.subject);
    setBody(v.body);
    draftSourcesRef.current = { profile: JSON.stringify(requestProfile), target: expectedTargetVersion, contact: serializeEmailContactContext(requestContactContext) };
    setExperienceUsage(v.experience_usage ?? null);
    // Variants share one server-resolved recipient; when the reveal is locked
    // they carry "" — never wipe an address the user typed themselves.
    setRecipient((prev) => prev || v.recipient_email);
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
    if (!sourceReadyRef.current || contextDirtyRef.current || profileChanged || profileRegenerating || !variantsReadyRef.current || aiInFlightRef.current || refineInFlightRef.current !== null || missingStudentName) return;
    if (!expectedTargetVersion) { reportTargetVersionFailure('unavailable'); return; }
    if (targetVersionError) return;
    const sessionCurrent = captureDraftSession();
    const request = ++aiRequestRef.current;
    const current = () => sessionCurrent() && request === aiRequestRef.current;
    const revision = draftRevisionRef.current;
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
        experience_usage: resp.experience_usage,
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
        draftSourcesRef.current = { profile: JSON.stringify(requestProfile), target: expectedTargetVersion, contact: serializeEmailContactContext(requestContactContext) };
        setExperienceUsage(v.experience_usage ?? null);
        if (contactIsCurrent) {
          setRecipient((prev) => prev || v.recipient_email);
        }
      }
    };

    // W12 draft freshness: a cached AI draft is only re-served while young
    // AND while variants confirms the same writing pipeline. A superseded
    // professor record or pipeline must not keep personalizing from cache.
    const cached = aiCacheRef.current.get(`${opportunityId}|${style}|${contactFingerprint}`);
    if (cached) {
      if (cached.response.opportunity_id !== opportunityId || aiCacheEntryIsStale(cached, Date.now(), corpusVersionRef.current, pipelineVersionRef.current, expectedTargetVersion)) {
        aiCacheRef.current.delete(`${opportunityId}|${style}|${contactFingerprint}`);
      } else {
        // Cache only the AI writing value. Recipient truth was refreshed by
        // getEmailVariants for the current auth session and must never be
        // overwritten by a reveal cached before logout/token expiry.
        applyResponse(cached.response, true, false);
        setChatMessages((prev) => [...prev, { role: 'assistant', content: t('coldEmail.aiGenerated') }]);
        return;
      }
    }

    aiInFlightRef.current = true;
    setAiLoading(true);
    if (!auto) {
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: t('coldEmail.tone.generating', { style: t(`coldEmail.tone.${style}`) }) },
      ]);
    }
    try {
      // Confirmed entries travel in the API's evidence envelope. The modal
      // never extracts raw strings or confirms an imported experience itself.
      const opts = { engine: 'ai' as const, style, expectedTargetVersion, contactContext: requestContactContext };
      let resp;
      try {
        // A definite old backend may use the blocking compatibility route.
        // Timeouts/disconnects may already have generated a draft: never replay.
        resp = await generateColdEmailStream(requestProfile, opportunityId, opts, (stage) => {
          if (current()) setAiStage(stage);
        });
      } catch (streamError) {
        if (!current()) return;
        if (!canFallbackColdEmailStream(streamError)) throw streamError;
        setAiStage(null);
        resp = await generateColdEmail(requestProfile, opportunityId, opts);
      }
      if (!current()) return;
      requireTargetReceipt(resp, opportunityId, expectedTargetVersion);
      await requireContactReceipt(resp, requestContactContext);
      if (!current()) return;
      if (resp.method === 'ai') {
        aiCacheRef.current.set(`${opportunityId}|${style}|${contactFingerprint}`, {
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
      applyResponse(resp, draftRevisionRef.current === revision);
      setChatMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: resp.method === 'ai' ? t('coldEmail.aiGenerated') : aiFallbackMessage(resp.fallback_reason, t),
        },
      ]);
    } catch (error) {
      const failure = targetVersionFailure(error);
      if (current() && failure) reportTargetVersionFailure(failure);
      else if (current() && !auto) {
        setChatMessages((prev) => [
          ...prev,
          { role: 'assistant', content: t('coldEmail.aiFailed') },
        ]);
      }
    } finally {
      if (current()) {
        aiInFlightRef.current = false;
        setAiLoading(false);
        setAiStage(null);
      }
    }
  }, [profileChanged, profileRegenerating, missingStudentName, variants.length, requestProfile, requestContactContext, contactFingerprint, opportunityId, expectedTargetVersion, targetVersionError, labType, t, captureDraftSession, reportTargetVersionFailure]);

  // AI is the default engine: once the template variants land, run the
  // pipeline once automatically. The template is the instant placeholder; the
  // AI draft takes over on success (unless the user already started editing).
  useEffect(() => {
    if (!sourceReady || !isOpen || profileChanged || profileRegenerating || !variantsReadyRef.current || loading || variants.length === 0 || autoFiredRef.current) return;
    autoFiredRef.current = true;
    generateAi(selectedStyle, { auto: true });
  }, [sourceReady, isOpen, profileChanged, profileRegenerating, loading, variants.length, selectedStyle, generateAi]);

  function handleAiPillClick() {
    if (aiLoading || action.busy) return;
    action.request({ kind: 'ai', style: selectedStyle, selectExisting: true });
  }

  function handleToneClick(style: EmailStyle) {
    if (aiLoading || action.busy) return;
    action.request({ kind: 'ai', style });
  }

  // Shared grounded-refine runner for typed chat instructions AND the tone
  // quick-actions. Appends the "editing…" assistant message, calls the backend
  // (which grounds the result and degrades to its deterministic EDIT_OPS when
  // no LLM is configured), then replaces the placeholder with the outcome.
  async function runRefine(instruction: string) {
    if (!sourceReadyRef.current || contextDirtyRef.current || profileChanged || profileRegenerating || refineInFlightRef.current !== null) return;
    if (!expectedTargetVersion) { reportTargetVersionFailure('unavailable'); return; }
    if (targetVersionError) return;
    const sessionCurrent = captureDraftSession();
    const requestId = ++refineRequestRef.current;
    refineInFlightRef.current = requestId;
    const current = () => sessionCurrent() && refineInFlightRef.current === requestId;
    const revision = ++draftRevisionRef.current;
    setRefining(true);
    const reply = (content: string) => setChatMessages((prev) => prev.map((msg) =>
      msg.requestId === requestId ? { ...msg, content } : msg));
    setChatMessages((prev) => [...prev, { requestId, role: 'assistant', content: t('coldEmail.editing') }]);
    try {
      const result = await refineEmail(body, instruction, requestProfile, opportunityId, { expectedTargetVersion, contactContext: requestContactContext });
      if (!current()) return;
      if (draftRevisionRef.current !== revision) {
        reply(t('coldEmail.editSuperseded'));
        return;
      }
      requireTargetReceipt(result, opportunityId, expectedTargetVersion);
      await requireContactReceipt(result, requestContactContext);
      if (!current()) return;
      if (draftRevisionRef.current !== revision) { reply(t('coldEmail.editSuperseded')); return; }
      setBody(result.body);
      draftSourcesRef.current = { profile: JSON.stringify(requestProfile), target: expectedTargetVersion, contact: serializeEmailContactContext(requestContactContext) };
      setExperienceUsage(result.experience_usage ?? null);
      reply(
            result.method === 'llm'
              ? t('coldEmail.doneLlm')
              : result.fallback_reason === 'insufficient_evidence'
                ? aiFallbackMessage('insufficient_evidence', t)
                : result.fallback_reason === 'fabrication'
                  ? t('coldEmail.refineFabrication')
                  : t('coldEmail.doneFallback'),
      );
    } catch (error) {
      if (current()) {
        const failure = targetVersionFailure(error);
        if (failure) { reportTargetVersionFailure(failure); reply(t('coldEmail.editFailed')); }
        else reply(t('coldEmail.editFailed'));
      }
    } finally {
      if (current()) {
        refineInFlightRef.current = null;
        setRefining(false);
      }
    }
  }

  function handleQuickAction(key: QuickActionKey) {
    if (!sourceReadyRef.current || action.busy || profileChanged || profileRegenerating || refineInFlightRef.current !== null) return;
    if (key === 'coursework') { action.request({ kind: 'coursework' }); return; }
    action.request({ kind: 'refine', instruction: QUICK_ACTION_INSTRUCTIONS[key], label: t(`coldEmail.quickActions.${key}`) });
  }

  function handleChatSubmit() {
    const msg = chatInput.trim();
    if (!sourceReadyRef.current || action.busy || !msg || profileChanged || profileRegenerating || refineInFlightRef.current !== null) return;
    // Do not erase the user's request until a successful check actually starts
    // refinement. A failed or superseded read leaves the input untouched.
    action.request({ kind: 'refine', instruction: msg, typed: true });
  }

  // Reveal the strip without recording anything — a draft opened/copied is
  // not a verified send. No evidence = no tracking event.
  const markContacted = useCallback(() => {
    setContacted(true);
    setContactedDraftEpoch(sendDraftEpochRef.current);
    setContactedForId(opportunityId);
    setContactedContentKey(copyContentKeyRef.current);
    // opportunityId is now READ here, so it has to be a dep. An empty array
    // would freeze the stamp at whatever id existed on first mount, and a
    // copy on target B would file itself under target A forever.
  }, [opportunityId]);

  // An attestation saves one immutable email snapshot. Generating, copying,
  // and opening an external composer never write an event.
  const confirmSent = useCallback(async () => {
    if (!sourceReadyRef.current || confirmInFlightRef.current) return;
    // Captured at the click, before any await: the capability belongs to the
    // identity that attested, not to whoever owns the browser by the time the
    // round trip finishes.
    const token = captureOwnerToken();
    const session = sendSessionRef.current;
    const confirmedEpoch = sendDraftEpochRef.current;
    const confirmedContents = confirmationKeyRef.current;
    const attempt = (confirmAttemptRef.current += 1);
    confirmInFlightRef.current = true;
    setSendError(null);
    setConfirming(true);
    // Same session, same attempt: this completion is still the current one.
    // A newer attempt, a target change or a close all retire it.
    const stillCurrent = () =>
      sendSessionRef.current === session && confirmAttemptRef.current === attempt;
    // A real historical write can still update the parent after rebuilding,
    // but its failure must never be attributed to the replacement draft.
    const sameDraft = () => stillCurrent() && sendDraftEpochRef.current === confirmedEpoch
      && confirmationKeyRef.current === confirmedContents;
    try {
      const sentTime = actualSentAt ? new Date(actualSentAt) : null;
      if (!recipient.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(recipient.trim())
        || !subject.trim() || !body.trim()
        || (sentTime && (!Number.isFinite(sentTime.getTime()) || sentTime.getTime() > Date.now()))) {
        setSendError('invalid-contact'); return;
      }
      // These are the source versions used when this text was last generated
      // or refined. A profile refresh can preserve an older manual draft.
      const sources = draftSourcesRef.current;
      const materialRefs = sources ? [
        { kind: 'profile' as const, version: await contactMaterialVersion(sources.profile) },
        ...(sources.target ? [{ kind: 'target' as const, version: sources.target }] : []),
        { kind: 'contact_context' as const, version: await contactMaterialVersion(sources.contact) },
      ] : [];
      if (!sameDraft() || !isTokenOwnerStillCurrent(token)) return;
      const input = await createContactEventInput(token.uid!, opportunityId, {
        recipient: recipient.trim(), subject, body, actualSentAt: sentTime?.toISOString() ?? null,
        materialRefs,
      });
      if (!sameDraft() || !isTokenOwnerStillCurrent(token)) return;
      const { interaction: record } = await confirmContactEvent(opportunityId, input, token);
      // The owner check is re-read AFTER the await, against the token captured
      // BEFORE it. Same uid at a new epoch is a different capability.
      if (!stillCurrent()) return;
      if (isTokenOwnerStillCurrent(token)) {
        setConfirmedStatus(record?.type);
        setConfirmedForId(opportunityId);
        setSendConfirmed(true);
        setConfirmedDraftEpoch(confirmedEpoch);
        setConfirmedContentKey(confirmedContents);
        onContactConfirmed?.(record ?? null);
      }
      else if (sameDraft()) setSendError('owner-changed');
    } catch (error) {
      if (!sameDraft()) return;
      // A confirmation whose identity moved cannot establish success for
      // this account. Its old-account write outcome may be unknown; show the
      // identity boundary without painting a U1 outcome into U2's session.
      setSendError(!isTokenOwnerStillCurrent(token) ? 'owner-changed'
        : error instanceof ContactEventError && error.code === 'conflict' ? 'contact-conflict'
          : error instanceof ContactEventError && error.code === 'invalid_input' ? 'invalid-contact' : 'confirm');
    } finally {
      if (stillCurrent()) {
        confirmInFlightRef.current = false;
        setConfirming(false);
      }
    }
  }, [opportunityId, onContactConfirmed, actualSentAt, recipient, subject, body, setSendError]);

  // Only asked once a reminder actually exists, so nobody is prompted about
  // notifications for a thing they have not done. 'subscribed' hides the offer;
  // an unsupported browser or a denied permission leaves it null, because
  // neither can be fixed by a button here.
  useEffect(() => {
    if (!followUpDate || pushOffer !== null) return;
    if (!isPushSupported()) return;
    let cancelled = false;
    getPushStatus().then((status) => {
      if (cancelled) return;
      if (status === 'subscribed') setPushOffer('subscribed');
      else if (status === 'default') setPushOffer('available');
    }).catch(() => { /* leave it unknown rather than offer on a guess */ });
    return () => { cancelled = true; };
  }, [followUpDate, pushOffer]);

  const enableNotifications = useCallback(async () => {
    if (!sourceReadyRef.current) return;
    // Two bindings: the draft session (closed / retargeted / re-profiled
    // ends it) and the account that clicked — the permission dialog is a long
    // window, and the endpoint must not be written under whoever is signed in
    // when it closes. The writer refuses on a switch; current() gates paints.
    const current = captureDraftSession();
    const token = captureOwnerToken();
    setPushBusy(true);
    try {
      const key = await getVapidPublicKey();
      if (!current()) return;
      if (key && await subscribeToPush(key, token) && current()) setPushOffer('subscribed');
    } catch { /* a session change, an owner change or a refused write: the offer simply stays; nothing was promised */ } finally {
      // A busy flag carries no account data; reset either way.
      setPushBusy(false);
    }
  }, [captureDraftSession]);

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
    if (!sourceReadyRef.current || confirmedForId !== opportunityId) return;
    if (reminderTarget?.id !== opportunityId) return;
    if (!canDeliverReminder(reminderTarget, confirmedStatus)) return;
    const token = captureOwnerToken();
    const session = sendSessionRef.current;
    const draftEpoch = sendDraftEpochRef.current;
    const reminderContents = confirmationKeyRef.current;
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
      if (stillCurrent() && sendDraftEpochRef.current === draftEpoch && confirmationKeyRef.current === reminderContents) setSendError('reminder');
      return;
    }
    if (stillCurrent()) {
      // Preserve the opportunity-level reminder receipt without clearing a
      // confirmation error belonging to a draft built while this write waited.
      if (sendDraftEpochRef.current === draftEpoch && confirmationKeyRef.current === reminderContents) setSendError(null);
      setFollowUpDate(date);
      onReminderSet?.(date);
    }
  }, [opportunityId, reminderTarget, confirmedStatus, confirmedForId, onReminderSet, setSendError]);

  async function handleCopy() {
    const owner = captureOwnerToken();
    const session = sendSessionRef.current;
    const draft = sendDraftEpochRef.current;
    const revision = draftRevisionRef.current;
    const contents = copyContentKey;
    const sameContents = () => sendSessionRef.current === session && sendDraftEpochRef.current === draft
      && copyContentKeyRef.current === contents && isTokenOwnerStillCurrent(owner);
    const current = () => sameContents() && draftRevisionRef.current === revision;
    try {
      await navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`);
    } catch {
      // The clipboard genuinely refuses in the field: permission denied, the
      // document not focused, an insecure context. Nothing was copied, so
      // nothing may report that it was — and with no draft in hand there is
      // nothing the student could have sent, so the attestation question
      // stays away too.
      if (current()) setCopyFailedFor(contents);
      return;
    }
    if (!current()) return;
    setCopyFailedFor(null);
    const feedback = { contents };
    setCopiedFor(feedback);
    // Expire this copy even while another body is displayed. An older timer
    // must never clear the feedback from a newer copy of the same contents.
    setTimeout(() => setCopiedFor((currentFeedback) => currentFeedback === feedback ? null : currentFeedback), 2000);
    if (sourceReadyRef.current) markContacted();
  }

  function getMailtoLink(provider: 'default' | 'gmail' | 'outlook' = 'default'): string {
    const to = encodeURIComponent(recipient || '');
    const subj = encodeURIComponent(subject);
    const b = encodeURIComponent(body);
    if (provider === 'gmail') return `https://mail.google.com/mail/?view=cm&to=${to}&su=${subj}&body=${b}`;
    if (provider === 'outlook') return `https://outlook.office365.com/mail/deeplink/compose?to=${to}&subject=${subj}&body=${b}`;
    return `mailto:${to}?subject=${subj}&body=${b}`;
  }

  if (!isOpen || retired) return null;

  const hasEditor = variants.length > 0 || profileChanged || !!(subject || body || recipient);
  const showInitialWait = loading && !error && !targetVersionError && !nameRequired && !action.error && profileAvailable
    && (targetReady || targetChecking) && profileRefresh?.status !== 'failed' && profileRefresh?.status !== 'conflict';

  return (
    <div
      className="fixed inset-0 z-[55] flex sm:items-center sm:justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="email-modal-title"
    >
      <div className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm" onClick={closeDraft} aria-hidden="true" />

      <div
        ref={modalRef}
        className="relative w-full sm:max-w-5xl sm:mx-4 bg-white sm:rounded-2xl shadow-2xl h-[100dvh] max-h-[100dvh] sm:h-[90dvh] sm:max-h-[90dvh] min-w-0 flex flex-col overflow-hidden animate-in"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-2 px-4 sm:px-6 py-3 sm:py-4 border-b border-gray-100 shrink-0">
          <div className="flex min-w-0 items-center gap-3">
            <div className="w-9 h-9 shrink-0 rounded-xl bg-indigo-50 flex items-center justify-center" aria-hidden="true">
              <Mail className="w-5 h-5 text-indigo-600" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 id="email-modal-title" className="text-lg font-bold text-gray-900">{t('coldEmail.title')}</h2>
                <LabTypeBadge labType={labType} />
              </div>
              <p className="text-sm text-gray-500 truncate max-w-md">{opportunityTitle}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={closeDraft}
            className="shrink-0 p-2 rounded-lg hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 transition-colors"
            aria-label={t('coldEmail.closeAria')}
          >
            <X className="w-5 h-5 text-gray-400" aria-hidden="true" />
          </button>
        </div>

        <ProfileRefreshBanner locale={locale} refresh={profileRefresh} targetRefresh={targetRefresh} targetReady={targetMembershipReady ?? targetReady} profileAvailable={profileAvailable} onBeforeReview={() => {
          if (editorUsedRef.current && !window.confirm(locale === 'zh'
            ? '离开会丢弃未保存的邮件草稿。确定去核对资料？'
            : 'Leaving discards this unsaved email draft. Go to your profile?')) return false;
          closeDraft(); return true;
        }} />
      {action.error && <div role="alert" className="shrink-0 border-b border-amber-200 bg-amber-50 px-5 py-2 text-sm text-amber-950">
        {locale === 'zh' ? (targetRefresh ? '本次操作未执行。草稿和请求仍保留，请核对资料及机会后重试。' : '本次操作未执行。草稿和请求仍保留，请核对资料后重试。') : (targetRefresh ? 'This action did not run. Your draft and request are kept. Review your profile and opportunity and try again.' : 'This action did not run. Your draft and request are kept. Review your profile and try again.')}
        {variants.length === 0 && !profileChanged && <button type="button" className="ml-2 font-semibold underline" disabled={action.busy || !profileAvailable}
          onClick={() => action.request({ kind: 'variants' })}>{t('coldEmail.tryAgain')}</button>}
      </div>}

        {targetVersionError && <div role="alert" className="shrink-0 border-b border-amber-200 bg-amber-50 px-5 py-2 text-sm text-amber-950">
          <p>{t(targetVersionError === 'changed' ? 'coldEmail.targetVersionChanged' : 'coldEmail.targetVersionUnavailable')}</p>
          <button type="button" disabled={action.busy || profileRegenerating || !targetRefresh || targetRefresh.status === 'checking'}
            className="mt-1 font-semibold underline disabled:opacity-50"
            onClick={() => { targetCheckOnlyRef.current = true; void targetRefresh?.refresh().catch(() => false); }}>{t('coldEmail.targetVersionRetry')}</button>
          {!profileChanged && <button type="button" disabled={action.busy || profileRegenerating || !sourceReady}
            className="ml-3 mt-1 font-semibold underline disabled:opacity-50"
            onClick={() => action.request({ kind: 'variants', keepEditor: hasEditor })}>
            {t(hasEditor ? 'coldEmail.regenerateFromProfile' : 'coldEmail.tryAgain')}</button>}
        </div>}

        {/* Loading / Error: each state has the same reachable short-screen
            scroll boundary as the editor. The inner panel grows with text. */}
        {showInitialWait && (
          <div className={styles.statePanel}>
            <div className="min-h-full flex flex-col items-center justify-center px-6 py-10 sm:py-20 gap-4 text-center">
              <Loader2 className="w-8 h-8 shrink-0 text-indigo-500 animate-spin" />
              <p className="text-sm text-gray-500">{t('coldEmail.generating')}</p>
            </div>
          </div>
        )}
        {nameRequired && !loading && (
          <div className={styles.statePanel} data-testid="cold-email-name-required">
            <div className="min-h-full flex flex-col items-center justify-center py-10 sm:py-20 gap-4 px-6 text-center">
              <div className="w-12 h-12 shrink-0 rounded-2xl bg-amber-50 flex items-center justify-center">
                <UserRound className="w-6 h-6 text-amber-600" aria-hidden="true" />
              </div>
              <p className="text-base font-semibold text-gray-900">{t('coldEmail.nameRequiredTitle')}</p>
              <p className="text-sm text-gray-500 max-w-md">{t('coldEmail.nameRequiredBody')}</p>
              <Link
                href="/"
                onClick={closeDraft}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors"
              >
                {t('coldEmail.nameRequiredCta')}
              </Link>
            </div>
          </div>
        )}
        {error && !nameRequired && (
          <div className={styles.statePanel}>
            <div className="min-h-full flex flex-col items-center justify-center px-6 py-10 sm:py-20 gap-4 text-center">
              <AlertCircle className="w-8 h-8 shrink-0 text-red-500" />
              <p className="text-sm text-red-600 break-words max-w-full">{error}</p>
              {experienceNeedsReview && (
                <Link href="/#experience-library" onClick={closeDraft} className="text-sm font-medium text-indigo-600 underline">
                  {t('coldEmail.experienceReviewCta')}
                </Link>
              )}
              <button type="button" onClick={() => action.request({ kind: 'variants' })} className="text-sm text-indigo-600 underline hover:text-indigo-700">{t('coldEmail.tryAgain')}</button>
            </div>
          </div>
        )}

        {/* Two-panel layout */}
        {hasEditor && !loading && !error && !nameRequired && (
          <div className={styles.workspace} data-testid="cold-email-workspace">
            <div className={styles.panels}>
              <div className={`${styles.editorPane} lg:border-r border-gray-100`} data-testid="cold-email-editor">
                {profileChanged && <div role="status" className="mx-5 mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                  <p>{contextChanged ? (locale === 'zh' ? '联系背景已更改。先确认背景，再生成新稿；当前草稿仍保留。' : 'Contact background changed. Confirm it, then generate a new draft. Your current draft is kept.') : t('coldEmail.profileChanged')}</p>
                  {profileRegenerateError && <p role="alert" className="mt-2">{t(profileRegenerateError === 'edited'
                    ? 'coldEmail.editSuperseded' : profileRegenerateError === 'name-required'
                      ? 'coldEmail.nameRequiredBody' : 'coldEmail.profileRegenerateFailed')}</p>}
                  {profileRegenerateError === 'name-required' && <Link href="/" onClick={closeDraft}
                    className="mt-1 inline-block font-medium underline">{t('coldEmail.nameRequiredCta')}</Link>}
                  <button type="button" className="mt-2 rounded-lg border border-amber-300 bg-white px-3 py-2 font-medium disabled:opacity-50"
                    disabled={contextDirty || !sourceReady || action.busy || profileRegenerating} onClick={() => action.request({ kind: 'variants', keepEditor: true })}>
                    {profileRegenerating ? t('coldEmail.generating') : t('coldEmail.regenerateFromProfile')}
                  </button>
                </div>}
                {/* Variant tabs */}
                <div className="flex flex-wrap items-center gap-1 px-5 pt-4 pb-2 shrink-0">
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
                    disabled={!sourceReady || action.busy || profileChanged || profileRegenerating || aiLoading || refining}
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
                        disabled={!sourceReady || action.busy || profileChanged || profileRegenerating || aiLoading || refining}
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

                <div className={`${styles.editorFields} px-5 pb-4 space-y-4`} data-testid="cold-email-editor-fields">
                  <EmailContactContextPanel context={requestContactContext} resetKey={`${opportunityId}:${isOpen}`}
                    language={locale === 'zh' ? 'zh' : 'en'} onDraftChange={retireContactDraft} onApply={applyContactContext} />
                  <section className="rounded-xl border border-gray-200 bg-gray-50 p-3 text-xs text-gray-600" data-testid="cold-email-experience">
                    <details>
                      <summary className="cursor-pointer font-semibold text-gray-800">{t('coldEmail.experienceTitle')}</summary>
                      <p className="mt-2">{t('coldEmail.experienceExplanation')}</p>
                      {!experienceUsage ? (
                        <p className="mt-2">{t('coldEmail.experienceUnavailable')}</p>
                      ) : experienceUsage.selected.length === 0 ? (
                        !experienceBudgetOmission && !experienceReceiptLimited && <p className="mt-2">{t('coldEmail.experienceNone')}</p>
                      ) : (
                        <ul className="mt-2 space-y-2">
                          {experienceUsage.selected.map((entry) => (
                            <li key={`${entry.id}:${entry.revision}`} className="break-words">
                              <p>{entry.excerpt}</p>
                              <span className="text-gray-500">{t(entry.source.kind === 'resume' ? 'coldEmail.experienceSourceResume' : 'coldEmail.experienceSourceManual')}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </details>
                    {experienceReceiptLimited && <p className="mt-2">{t('coldEmail.experienceReceiptLimit')}</p>}
                    {(experienceBudgetOmission || experienceNeedsReview || experienceUsage?.needs_review) && (
                      <div className="mt-2 border-t border-gray-200 pt-2" data-testid="cold-email-experience-review">
                        {experienceBudgetOmission && <p>{t('coldEmail.experienceBudgetNote')}</p>}
                        {(experienceNeedsReview || experienceUsage?.needs_review) && <p>{t('coldEmail.experienceReviewNeeded')}</p>}
                        <Link href="/#experience-library" onClick={closeDraft} className="mt-1 inline-block font-medium text-indigo-600 underline">
                          {t('coldEmail.experienceReviewCta')}
                        </Link>
                      </div>
                    )}
                  </section>
                  <div>
                    <label htmlFor="cold-email-to" className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                      {t('coldEmail.to')}
                    </label>
                    <input
                      id="cold-email-to"
                      type="email"
                      value={recipient}
                      onChange={(e) => { editorUsedRef.current = true; draftRevisionRef.current += 1; noteUserEdit(); setRecipient(e.target.value); }}
                      placeholder={t('coldEmail.toPlaceholder')}
                      className={`w-full min-w-0 px-3.5 py-2.5 border rounded-xl text-sm text-gray-900 placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none transition-all ${!recipient ? 'border-amber-300 bg-amber-50/30' : 'border-gray-200'}`}
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
                    <label htmlFor="cold-email-subject" className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">{t('coldEmail.subject')}</label>
                    <input
                      id="cold-email-subject"
                      type="text"
                      value={subject}
                      onChange={(e) => { editorUsedRef.current = true; draftRevisionRef.current += 1; noteUserEdit(); setSubject(e.target.value); }}
                      className="w-full min-w-0 px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm font-medium text-gray-900 focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none transition-all"
                    />
                  </div>
                  <div className="flex-1 flex flex-col">
                    <div className="flex items-center gap-2 mb-1.5">
                      <label htmlFor="cold-email-body" className="block text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('coldEmail.body')}</label>
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
                      id="cold-email-body"
                      value={body}
                      onChange={(e) => { editorUsedRef.current = true; draftRevisionRef.current += 1; noteUserEdit(); setBody(e.target.value); }}
                      rows={12}
                      className="w-full min-w-0 min-h-64 flex-1 px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-700 leading-relaxed focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none transition-all resize-y"
                    />
                  </div>
                  <details className="rounded-xl border border-gray-200 px-3.5 py-3 text-xs text-gray-600" data-testid="contact-record-details">
                    <summary className="cursor-pointer font-semibold text-gray-700">{t('coldEmail.contactRecordTitle')}</summary>
                    <p className="mt-2 leading-relaxed">{t('coldEmail.contactRecordHint')}</p>
                    <label className="mt-3 block" htmlFor="cold-email-sent-at">{t('coldEmail.actualSentAt')}</label>
                    <input id="cold-email-sent-at" type="datetime-local" value={actualSentAt}
                      onChange={(event) => setActualSentAt(event.target.value)}
                      className="mt-1 w-full min-w-0 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm" />
                    <p className="mt-1.5 leading-relaxed">{t('coldEmail.actualSentAtHint')}</p>
                  </details>
                </div>
              </div>

              <div className={`${styles.refinePane} bg-gray-50/60 border-t lg:border-t-0 border-gray-100`} data-has-guidelines={!!labType}>
                {labType && (
                  <div className={`${styles.guidelines} border-b border-gray-100`}>
                    <h3 id="cold-email-guidelines-heading" className="px-4 py-3 text-sm font-semibold text-gray-700 shrink-0">
                      {t('coldEmail.guidelinesTitle')}
                    </h3>
                    <div
                      className={`${styles.guidelinesScroll} px-4 pb-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500`}
                      role="region"
                      aria-labelledby="cold-email-guidelines-heading"
                      tabIndex={0}
                      data-testid="cold-email-guidelines"
                    >
                      <EmailTipsPanel labType={labType} />
                    </div>
                  </div>
                )}

                <section className={styles.conversation} aria-labelledby="cold-email-requests-heading">
                  <h3 id="cold-email-requests-heading" className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 shrink-0 text-sm font-semibold text-gray-700">
                    <Sparkles className="w-4 h-4 shrink-0 text-indigo-500" aria-hidden="true" />
                    {t('coldEmail.aiRequestsTitle')}
                  </h3>

                {/* Chat messages */}
                <div
                  ref={chatHistoryRef}
                  className={`${styles.history} px-4 py-3 space-y-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500`}
                  role="log"
                  aria-label={t('coldEmail.aiRequestsTitle')}
                  tabIndex={0}
                  data-testid="cold-email-chat-history"
                >
                  {chatMessages.map((msg, i) => (
                    <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div
                        className={`min-w-0 max-w-[90%] whitespace-pre-wrap break-words px-3 py-2 rounded-xl text-[13px] leading-relaxed ${
                          msg.role === 'user'
                            ? 'bg-indigo-600 text-white rounded-br-sm'
                            : 'bg-white text-gray-700 border border-gray-200 rounded-bl-sm shadow-sm'
                        }`}
                      >
                        {msg.content}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Quick actions */}
                <div className="px-4 pb-2 shrink-0">
                  <div className="flex flex-wrap gap-1.5">
                    {QUICK_ACTION_KEYS.map((key) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => handleQuickAction(key)}
                        disabled={!sourceReady || action.busy || profileChanged || profileRegenerating || refining}
                        className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-white border border-gray-200 text-gray-600 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
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
                      onChange={(e) => { noteUserEdit(); setChatInput(e.target.value); }}
                      placeholder={t('coldEmail.refinePlaceholder')}
                      aria-label={t('coldEmail.requestLabel')}
                      className="min-w-0 flex-1 px-3 py-2 border border-gray-200 rounded-xl text-sm bg-white placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500/20 outline-none transition-all"
                    />
                    <button
                      type="submit"
                      aria-label={t('coldEmail.submitRequest')}
                      disabled={!sourceReady || action.busy || !chatInput.trim() || profileChanged || profileRegenerating || refining}
                      className="p-2 rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
                    >
                      <Send className="w-4 h-4" />
                    </button>
                  </form>
                </div>
                </section>
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
                      disabled={!sourceReady || confirming}
                      data-testid="cold-email-confirm-sent"
                      className="px-2.5 py-1 rounded-lg border border-amber-200 bg-white text-[12px] font-medium text-amber-700 hover:bg-amber-100 transition-colors disabled:opacity-60 disabled:cursor-wait"
                    >
                      {confirming
                        ? t('coldEmail.confirming')
                        : sendError === 'confirm'
                          ? t('coldEmail.confirmRetry')
                          : t('coldEmail.confirmSent')}
                    </button>
                    {(sendError === 'confirm' || sendError === 'owner-changed' || sendError === 'invalid-contact' || sendError === 'contact-conflict') && (
                      <span className="inline-flex items-center gap-1.5 text-red-600" role="status">
                        <AlertCircle className="w-4 h-4 shrink-0" aria-hidden="true" />
                        {t(sendError === 'confirm' ? 'coldEmail.confirmFailed'
                          : sendError === 'invalid-contact' ? 'coldEmail.contactInvalid'
                          : sendError === 'contact-conflict' ? 'coldEmail.contactConflict'
                          : 'coldEmail.confirmOwnerChanged')}
                      </span>
                    )}
                  </>
                ) : confirmedStatus === undefined ? (
                  <span className="text-gray-600">{t('coldEmail.contactRecordedNoStatus')}</span>
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
                          disabled={!sourceReady}
                          onClick={() => { void setFollowUp(days); }}
                          className="px-2.5 py-1 rounded-lg border border-amber-200 bg-white text-[12px] font-medium text-amber-700 hover:bg-amber-100 transition-colors"
                        >
                          {t(key)}
                        </button>
                      ),
                    )}
                    {followUpDate && pushOffer === 'available' && (
                      <span className="inline-flex items-center gap-1.5 text-[12px] text-gray-500">
                        {t('coldEmail.reminderInAppOnly')}
                        <button
                          type="button"
                          disabled={!sourceReady || pushBusy}
                          onClick={() => { void enableNotifications(); }}
                          className="font-semibold text-indigo-600 hover:text-indigo-700 underline underline-offset-2 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded"
                        >
                          {t('coldEmail.reminderEnablePush')}
                        </button>
                      </span>
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
            <div className="flex flex-wrap items-center justify-end gap-2 px-4 sm:px-6 py-3 border-t border-gray-100 bg-gray-50/50 shrink-0" data-testid="cold-email-footer">
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
                className="grid w-full min-w-0 grid-cols-2 rounded-xl overflow-hidden shadow-sm sm:flex sm:w-auto"
                title={!recipient.trim() ? t('coldEmail.toHint') : undefined}
              >
                <button
                  type="button"
                  disabled={!sourceReady || !recipient.trim()}
                  onClick={() => { if (!sourceReadyRef.current) return; window.open(getMailtoLink('default'), '_blank'); markContacted(); }}
                  className="col-span-2 inline-flex items-center justify-center gap-2 px-5 py-2.5 text-sm font-semibold text-white bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-700 hover:to-indigo-600 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ExternalLink className="w-4 h-4" />
                  {t('coldEmail.openInEmail')}
                </button>
                <div className="hidden w-px bg-indigo-400 sm:block" />
                <button
                  type="button"
                  disabled={!sourceReady || !recipient.trim()}
                  onClick={() => { if (!sourceReadyRef.current) return; window.open(getMailtoLink('gmail'), '_blank'); markContacted(); }}
                  className="inline-flex items-center justify-center px-3 py-2.5 text-[11px] font-semibold text-indigo-100 bg-indigo-600 hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  title={t('coldEmail.openGmailTitle')}
                >
                  {t('coldEmail.gmail')}
                </button>
                <button
                  type="button"
                  disabled={!sourceReady || !recipient.trim()}
                  onClick={() => { if (!sourceReadyRef.current) return; window.open(getMailtoLink('outlook'), '_blank'); markContacted(); }}
                  className="inline-flex items-center justify-center px-3 py-2.5 text-[11px] font-semibold text-indigo-100 bg-indigo-600 hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  title={t('coldEmail.openOutlookTitle')}
                >
                  {t('coldEmail.outlook')}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
