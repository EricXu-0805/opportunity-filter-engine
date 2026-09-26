'use client';

import { useId, useLayoutEffect, useRef, useState } from 'react';
import type { EmailContactContext, Opportunity } from '@/lib/types';
import { emailPaperKey, emailPaperOptions, type EmailPaperOption } from '@/lib/email-paper-reading';
import { parseEmailContactDraftSnapshot, type EmailContactDraftSnapshot, type EmailContactDraftFields, type EmailContactDraftConfirmations } from '@/lib/email-contact-draft';
import { defaultEmailContactContext, normalizeEmailContactContext, serializeEmailContactContext } from '@/lib/email-contact-context';
import { parseResearchContext } from '@/lib/research-context';
import styles from './EmailContactContextPanel.module.css';

export interface EmailContactContextPanelProps {
  context?: EmailContactContext;
  /** Read once for this keyed session; never applied automatically. */
  initialDraft?: EmailContactDraftSnapshot | null;
  /** Null means the current full draft exceeds the storage contract. Input stays intact. */
  onDraftSnapshotChange?: (snapshot: EmailContactDraftSnapshot | null) => void;
  opportunity?: Opportunity | null;
  /** Current writing target version/fingerprint. Changes require a fresh reading confirmation. */
  targetKey?: string;
  /** Increase after a server rejection; preserve answers and ask for a fresh confirmation. */
  reviewRequested?: number;
  onDraftChange: () => void;
  onApply: (context: EmailContactContext) => void;
  /** Change for a new owner/open/target session, not an ordinary render. */
  resetKey: string;
  disabled?: boolean;
  language: 'en' | 'zh';
}

type Purpose = EmailContactContext['purpose'];
type Fields = EmailContactDraftFields;
type Confirmations = EmailContactDraftConfirmations;
type ReplyStatus = Fields['replyStatus'];
type PanelError = 'required' | 'confirmation' | 'invalid' | 'blocked' | 'apply' | 'paper';
type Supplied = { value: EmailContactContext; key: string; valid: boolean };
type State = {
  sourceKey: string;
  paperSourceKey: string;
  reviewRequested: number;
  fields: Fields;
  confirmed: Confirmations;
  dirty: boolean;
  expanded: boolean;
  appliedKey: string | null;
  error: PanelError | null;
};
const unconfirmed = (): Confirmations => ({ referral: false, sent: false, availability: false, paper: false });

function supplied(value: EmailContactContext | undefined): Supplied {
  try {
    const normalized = normalizeEmailContactContext(value);
    return { value: normalized, key: serializeEmailContactContext(normalized), valid: true };
  } catch {
    return { value: defaultEmailContactContext(), key: 'invalid', valid: false };
  }
}

function fromSupplied(source: Supplied, paperSourceKey: string, reviewRequested: number): State {
  const value = source.value;
  return {
    sourceKey: source.key,
    paperSourceKey,
    reviewRequested,
    fields: {
      purpose: value.purpose,
      referrerName: value.referral?.referrer_name ?? '',
      referralNote: value.referral?.referral_note ?? '',
      previousMessage: value.follow_up?.previous_message ?? '',
      sentOn: value.follow_up?.sent_on ?? '',
      replyStatus: value.follow_up?.reply_status ?? 'unknown',
      replyText: value.follow_up?.reply_text ?? '',
      availability: value.availability?.text ?? '',
      paperKey: value.paper_reading ? emailPaperKey(value.paper_reading) : '',
      readingLevel: value.paper_reading?.level ?? '',
    },
    confirmed: {
      referral: value.referral?.confirmed === true,
      sent: value.follow_up?.sent_confirmed === true,
      availability: value.availability?.confirmed === true,
      paper: value.paper_reading?.confirmed === true,
    },
    dirty: !source.valid,
    expanded: value.purpose !== 'first_contact',
    appliedKey: source.valid ? source.key : null,
    error: source.valid ? null : 'invalid',
  };
}

function prepare(fields: Fields, confirmed: Confirmations, papers: EmailPaperOption[]):
  { value: EmailContactContext; key: string; error: null } | { error: PanelError } {
  const selectedPaper = papers.find(paper => emailPaperKey(paper) === fields.paperKey);
  if (fields.paperKey && (!selectedPaper || !fields.readingLevel)) return { error: 'paper' };
  if (fields.purpose === 'follow_up' && ['declined', 'do_not_contact'].includes(fields.replyStatus)) return { error: 'blocked' };
  if (fields.purpose === 'referral' && (!fields.referrerName.trim() || !fields.referralNote.trim())) return { error: 'required' };
  if (fields.purpose === 'follow_up' && (!fields.previousMessage.trim() || (fields.replyStatus === 'received' && !fields.replyText.trim()))) return { error: 'required' };
  if ((fields.purpose === 'referral' && !confirmed.referral)
    || (fields.purpose === 'follow_up' && !confirmed.sent)
    || (fields.availability.trim() && !confirmed.availability)
    || (fields.paperKey && !confirmed.paper)) return { error: 'confirmation' };
  const candidate = {
    version: 1,
    purpose: fields.purpose,
    ...(fields.purpose === 'referral' ? { referral: {
      referrer_name: fields.referrerName, referral_note: fields.referralNote, confirmed: true,
    } } : {}),
    ...(fields.purpose === 'follow_up' ? { follow_up: {
      sent_confirmed: true, previous_message: fields.previousMessage,
      ...(fields.sentOn.trim() ? { sent_on: fields.sentOn } : {}),
      reply_status: fields.replyStatus,
      ...(fields.replyStatus === 'received' ? { reply_text: fields.replyText } : {}),
    } } : {}),
    ...(fields.availability.trim() ? { availability: { text: fields.availability, confirmed: true } } : {}),
    ...(selectedPaper ? { paper_reading: { ...selectedPaper, level: fields.readingLevel, confirmed: true } } : {}),
  };
  try {
    const value = normalizeEmailContactContext(candidate);
    return { value, key: serializeEmailContactContext(value), error: null };
  } catch {
    return { error: 'invalid' };
  }
}

function fromInitialDraft(source: Supplied, paperSourceKey: string, reviewRequested: number,
  papers: EmailPaperOption[], opportunityId: string | null, initialDraft: unknown): State {
  const fallback = fromSupplied(source, paperSourceKey, reviewRequested);
  const draft = parseEmailContactDraftSnapshot(initialDraft);
  if (!draft || draft.opportunityId !== opportunityId) return fallback;
  const staleReading = !!draft.fields.paperKey && draft.paperSourceKey !== paperSourceKey;
  const confirmed = { ...draft.confirmed, ...(staleReading ? { paper: false } : {}) };
  const prepared = prepare(draft.fields, confirmed, papers);
  // A stored "applied" marker is not authority: the current accepted context
  // must independently agree. Pending edits never become accepted on restore.
  const applied = !draft.pending && !staleReading && source.valid
    && prepared.error === null && prepared.key === source.key;
  return { ...fallback, fields: draft.fields, confirmed, expanded: draft.expanded,
    dirty: !applied, appliedKey: applied ? source.key : null, error: null };
}

/** Context confirmation is local preparation only. This component cannot send,
 * generate, save a profile, or record a contacted/reminder event. */
export default function EmailContactContextPanel(props: EmailContactContextPanelProps) {
  return <ContextSession key={props.resetKey} {...props} />;
}

function ContextSession({ context, initialDraft, onDraftSnapshotChange, opportunity, targetKey, reviewRequested = 0, onDraftChange, onApply, disabled = false, language }: EmailContactContextPanelProps) {
  const copy = (en: string, zh: string) => language === 'zh' ? zh : en;
  const id = useId();
  const source = supplied(context);
  const papers = emailPaperOptions(opportunity);
  const paperSourceKey = JSON.stringify([opportunity?.id ?? null, targetKey ?? null, papers]);
  const previousPaperSource = useRef(paperSourceKey);
  const [state, setState] = useState(() => fromInitialDraft(source, paperSourceKey, reviewRequested, papers, opportunity?.id ?? null, initialDraft));
  // Adopt an external accepted context only when it cannot erase unfinished
  // answers. A real owner/target reset uses the keyed session above.
  if (state.sourceKey !== source.key || state.paperSourceKey !== paperSourceKey || state.reviewRequested !== reviewRequested) {
    const adopted = state.sourceKey !== source.key
      ? (!state.dirty || state.appliedKey === source.key ? { ...fromSupplied(source, paperSourceKey, reviewRequested), expanded: state.expanded } : { ...state, sourceKey: source.key, appliedKey: null })
      : state;
    const reviewing = state.reviewRequested !== reviewRequested;
    setState({ ...adopted, paperSourceKey, reviewRequested, ...(reviewing ? { expanded: true } : {}),
      ...((state.paperSourceKey !== paperSourceKey || reviewing) && adopted.fields.paperKey
        ? { confirmed: { ...adopted.confirmed, paper: false }, dirty: true, appliedKey: null, error: null } : {}),
    });
  }
  const hasPaper = !!state.fields.paperKey;
  useLayoutEffect(() => {
    if (previousPaperSource.current !== paperSourceKey) {
      previousPaperSource.current = paperSourceKey;
      if (hasPaper) onDraftChange();
    }
  }, [paperSourceKey, hasPaper, onDraftChange]);
  const fields = state.fields;
  const selectedPaper = papers.find(paper => emailPaperKey(paper) === fields.paperKey);
  const research = parseResearchContext(opportunity?.research_context);
  const selectedWork = research?.status === 'available' ? research.snapshot?.works.find(work => work.work_id === selectedPaper?.work_id) : undefined;
  const prepared = prepare(fields, state.confirmed, papers);
  const blocked = prepared.error === 'blocked';
  const applied = !state.dirty && state.appliedKey !== null && prepared.error === null && state.appliedKey === prepared.key;
  useLayoutEffect(() => {
    onDraftSnapshotChange?.(parseEmailContactDraftSnapshot({
      version: 1, opportunityId: opportunity?.id ?? null, paperSourceKey: state.paperSourceKey,
      fields: state.fields, confirmed: state.confirmed, pending: !applied, expanded: state.expanded,
    }));
  }, [state, applied, opportunity?.id, onDraftSnapshotChange]);
  const error = state.error ?? (blocked ? 'blocked' : null);
  const errors: Record<PanelError, string> = {
    required: copy('Fill in the required details, or choose First contact. Your answers are kept.', '请补齐必要信息，或选择“首次联系”。已填内容会保留。'),
    confirmation: copy('Confirm the details you want to use. Optional details can be cleared or skipped.', '请确认要使用的信息。选填内容可清空或跳过。'),
    invalid: copy('Some details are invalid or too long. Check the date and character counts. Your full text is kept.', '部分信息格式不正确或过长，请检查日期和字数。完整输入仍保留。'),
    blocked: copy('Do not prepare a follow-up after a refusal or a request not to contact them. Your current email and answers are kept.', '对方已拒绝或要求不再联系时，不准备跟进邮件。当前邮件和填写内容仍保留。'),
    paper: copy('Choose a current verified paper and your reading level, or skip paper reading.', '请选择当前已核实的论文和阅读程度，或跳过论文阅读。'),
    apply: copy('The background could not be applied. Your answers are kept; please try again.', '背景信息未能应用，填写内容仍保留，请重试。'),
  };
  const update = <K extends keyof Fields>(key: K, value: Fields[K]) => {
    if (disabled) return;
    onDraftChange();
    setState(previous => ({ ...previous, fields: { ...previous.fields, [key]: value, ...(key === 'paperKey' ? { readingLevel: '' as const } : {}) },
      confirmed: unconfirmed(), dirty: true, appliedKey: null, error: null }));
  };
  const confirm = (key: keyof Confirmations, value: boolean) => {
    if (disabled) return;
    onDraftChange();
    setState(previous => ({ ...previous, confirmed: { ...previous.confirmed, [key]: value },
      dirty: true, appliedKey: null, error: null }));
  };
  const apply = () => {
    if (disabled || applied) return;
    const result = prepare(fields, state.confirmed, papers);
    if (result.error !== null) { setState(previous => ({ ...previous, error: result.error })); return; }
    try {
      onApply(result.value);
      setState(previous => ({ ...previous, dirty: false, appliedKey: result.key, error: null }));
    } catch {
      setState(previous => ({ ...previous, error: 'apply' }));
    }
  };
  const count = (text: string, max: number) => <span className={styles.count} aria-live="off">
    {Array.from(text).length.toLocaleString(language)} / {max.toLocaleString(language)} {copy('characters', '字符')}
  </span>;
  const textArea = (key: 'referralNote' | 'previousMessage' | 'replyText' | 'availability', label: string, max: number, rows = 3) =>
    <div className={styles.field}>
      <label htmlFor={id + '-' + key}>{label}</label>
      <textarea id={id + '-' + key} value={fields[key]} rows={rows}
        aria-describedby={id + '-' + key + '-count'}
        onChange={event => update(key, event.target.value)} />
      <div id={id + '-' + key + '-count'}>{count(fields[key], max)}</div>
    </div>;
  return <details className={styles.panel} open={state.expanded} onToggle={event => {
    const expanded = event.currentTarget.open;
    setState(previous => previous.expanded === expanded ? previous : { ...previous, expanded });
  }}
    data-testid="email-contact-context-panel">
    <summary className={styles.summary}>
      <span>{copy('Contact purpose and background', '联系目的与背景')}</span>
      <span className={styles.badge}>{applied ? copy('Applied', '已应用') : copy('Needs confirmation', '待确认')}</span>
    </summary>
    <div className={styles.content}>
      <p className={styles.help}>{copy('Use only details you know are accurate. Applying background prepares this draft; it does not generate or send an email, or mark anyone as contacted.', '只填写你确认属实的信息。应用背景仅用于准备这份草稿，不会生成或发送邮件，也不会标记已联系。')}</p>
      <fieldset disabled={disabled} className={styles.fields}>
        <legend className={styles.visuallyHidden}>{copy('Background details', '背景信息')}</legend>
        <div className={styles.field}>
          <label htmlFor={id + '-purpose'}>{copy('Contact purpose', '联系目的')}</label>
          <select id={id + '-purpose'} value={fields.purpose} onChange={event => update('purpose', event.target.value as Purpose)}>
            <option value="first_contact">{copy('First contact', '首次联系')}</option>
            <option value="referral">{copy('Referred by someone', '经人介绍')}</option>
            <option value="follow_up">{copy('Follow up on a sent email', '跟进已发邮件')}</option>
          </select>
        </div>
        {fields.purpose === 'first_contact' && <p className={styles.help}>{copy('The opportunity information determines whether this is an application or an inquiry. You can leave optional details out; no vacancy, prior relationship or attachment is assumed.', '根据机会资料区分申请岗位与探索联系。选填信息可跳过，不会据此假定有空缺、已有关系或已附材料。')}</p>}
        {fields.purpose === 'referral' && <>
          <div className={styles.field}>
            <label htmlFor={id + '-referrer'}>{copy('Who referred you? (required)', '谁介绍你联系？（必填）')}</label>
            <input id={id + '-referrer'} value={fields.referrerName} onChange={event => update('referrerName', event.target.value)} />
            {count(fields.referrerName, 120)}
          </div>
          {textArea('referralNote', copy('What did they actually say or suggest? (required)', '对方具体怎样介绍或建议联系？（必填）'), 1500)}
          <p className={styles.help}>{copy('An introduction does not imply an endorsement. Include only what the person actually said.', '介绍不等于推荐或背书，只使用对方实际表达的内容。')}</p>
          <label className={styles.checkbox}><input type="checkbox" checked={state.confirmed.referral} onChange={event => confirm('referral', event.target.checked)} />
            <span>{copy('I confirm these referral details are accurate and I may mention this person in the draft.', '我确认这些介绍信息属实，且可以在草稿中提及此人。')}</span>
          </label>
        </>}
        {fields.purpose === 'follow_up' && <>
          {textArea('previousMessage', copy('Previous email you sent (required)', '你实际发出的前一封邮件（必填）'), 4000, 5)}
          <div className={styles.field}>
            <label htmlFor={id + '-sentOn'}>{copy('Date sent (optional, YYYY-MM-DD)', '实际发送日期（选填，YYYY-MM-DD）')}</label>
            <input id={id + '-sentOn'} type="text" inputMode="numeric" placeholder="YYYY-MM-DD" value={fields.sentOn}
              onChange={event => update('sentOn', event.target.value)} />
            <p className={styles.help}>{copy('Leave this blank if you are unsure; no date will be invented.', '不确定可留空，不会推测发送日期。')}</p>
          </div>
          <div className={styles.field}>
            <label htmlFor={id + '-replyStatus'}>{copy('Reply status', '回复情况')}</label>
            <select id={id + '-replyStatus'} value={fields.replyStatus} onChange={event => update('replyStatus', event.target.value as ReplyStatus)}>
              <option value="unknown">{copy('Not sure', '不确定')}</option>
              <option value="no_reply">{copy('No reply received', '尚未收到回复')}</option>
              <option value="received">{copy('Reply received', '已收到回复')}</option>
              <option value="declined">{copy('They declined', '对方已拒绝')}</option>
              <option value="do_not_contact">{copy('They asked me not to contact them', '对方要求不再联系')}</option>
            </select>
          </div>
          {fields.replyStatus === 'received' && textArea('replyText', copy('Reply you received (required)', '收到的回复（必填）'), 2000, 4)}
          <label className={styles.checkbox}><input type="checkbox" checked={state.confirmed.sent} onChange={event => confirm('sent', event.target.checked)} />
            <span>{copy('I confirm I actually sent this email to this target and these details are accurate. This does not record a new send.', '我确认这封邮件确实已发给当前目标，且这些信息属实。这不会记录一次新的发送。')}</span>
          </label>
        </>}
        <div className={styles.field} data-testid="email-paper-reading">
          <label htmlFor={id + '-paper'}>{copy('Paper you looked at (optional)', '你看过的论文（选填）')}</label>
          <select id={id + '-paper'} value={fields.paperKey} disabled={!papers.length && !fields.paperKey}
            onChange={event => update('paperKey', event.target.value)}>
            <option value="">{copy('Skip paper reading', '跳过论文阅读')}</option>
            {fields.paperKey && !selectedPaper && <option value={fields.paperKey} disabled>{copy('Previous paper is no longer available', '之前选择的论文已不可用')}</option>}
            {papers.map(paper => <option key={emailPaperKey(paper)} value={emailPaperKey(paper)}>{paper.title}{paper.year != null ? ` (${paper.year})` : ''}</option>)}
          </select>
          <p className={styles.help}>{papers.length
            ? copy('Choose from papers attributed to this researcher. Confirm only what you actually read; this does not claim understanding or expertise.', '只能选择已核对作者归属的论文资料。按实际阅读程度确认，不据此宣称理解或掌握。')
            : copy('No papers matched to this researcher are available. You can continue without a reading claim.', '当前没有可选的已核对作者归属的论文资料。可以继续，不写阅读声明。')}</p>
          {research?.status === 'stale' && <p role="status" data-testid="email-research-stale" className={styles.help}>
            {copy('Research sources are out of date and are not used for writing. You can continue without a paper claim.', '研究资料已过期，暂不用于写作。可以继续，不写论文声明。')}
          </p>}
          {research?.status === 'stale' && <details className={styles.help}><summary>{copy('View previous sources', '查看此前来源')}</summary>
            {research.snapshot!.works.map(work => <p key={work.work_id}><a href={work.source_url} target="_blank" rel="noopener noreferrer">{work.title}</a></p>)}
          </details>}
          {selectedWork && <div className={styles.help} data-testid="email-paper-source">
            <a href={selectedWork.source_url} target="_blank" rel="noopener noreferrer" style={{ display: 'block', overflowWrap: 'anywhere' }}>{selectedWork.title}</a>
            <p>{copy('Metadata checked: ', '资料核对时间：')}{research!.snapshot!.checked_at}</p>
            {selectedWork.abstract_status === 'present'
              ? <details><summary>{copy('Source abstract', '来源摘要')}</summary><p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{selectedWork.abstract}</p></details>
              : <p>{copy('No usable abstract is stored. Read the source before confirming your reading level.', '暂无可用摘要。请阅读来源后按实际情况确认。')}</p>}
            <p>{copy('Opening this source does not confirm reading. You may confirm full text you read elsewhere.', '打开来源不会自动确认阅读。若你在别处读过全文，可以按实际情况确认。')}</p>
          </div>}
          {fields.paperKey && <>
            <label htmlFor={id + '-readingLevel'}>{copy('How much did you read?', '你读到了哪一步？')}</label>
            <select id={id + '-readingLevel'} value={fields.readingLevel} onChange={event => update('readingLevel', event.target.value as Fields['readingLevel'])}>
              <option value="">{copy('Choose reading level', '选择阅读程度')}</option>
              <option value="title_only">{copy('Title only', '只看过标题')}</option>
              <option value="abstract">{copy('Abstract', '读过摘要')}</option>
              <option value="full_text">{copy('Full text', '读过全文')}</option>
            </select>
            <label className={styles.checkbox}><input type="checkbox" checked={state.confirmed.paper} onChange={event => confirm('paper', event.target.checked)} />
              <span>{copy('I confirm this reading level for the selected paper.', '我确认自己对这篇论文的阅读程度。')}</span>
            </label>
            <button type="button" className={styles.secondary} onClick={() => update('paperKey', '')}>{copy('Skip paper reading', '跳过论文阅读')}</button>
          </>}
        </div>
        {textArea('availability', copy('When could you participate? (optional)', '可投入的时间（选填）'), 500)}
        <p className={styles.help}>{copy('You may skip this. Unanswered details are omitted, not guessed.', '可以跳过。未回答的信息会省略，不会推测补写。')}</p>
        {fields.availability.length > 0 && <>
          <label className={styles.checkbox}><input type="checkbox" checked={state.confirmed.availability} onChange={event => confirm('availability', event.target.checked)} />
            <span>{copy('I confirm this availability is accurate.', '我确认这些可投入时间属实。')}</span>
          </label>
          <button type="button" className={styles.secondary} onClick={() => update('availability', '')}>{copy('Skip availability', '跳过可投入时间')}</button>
        </>}
      </fieldset>
      <p role="status" data-testid="email-contact-context-status" className={styles.help}>{applied
        ? copy('Background confirmed for the next draft.', '背景已确认，生成新稿时使用。')
        : copy('Changes are not applied. Your current email is kept; confirm and apply the background before generating again.', '改动尚未应用。当前邮件仍保留，请确认并应用背景后再生成。')}</p>
      {disabled && <p className={styles.help}>{copy('Background changes are paused. Your answers are kept.', '背景修改暂时暂停，填写内容仍保留。')}</p>}
      {error && <p role="alert" className={styles.error}>{errors[error]}</p>}
      <button type="button" className={styles.apply} disabled={disabled || applied || blocked} onClick={apply}>
        {copy('Apply background to this draft', '将背景应用于草稿')}
      </button>
    </div>
  </details>;
}
