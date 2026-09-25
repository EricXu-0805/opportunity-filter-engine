'use client';

import { useId, useState } from 'react';
import type { EmailContactContext } from '@/lib/types';
import { defaultEmailContactContext, normalizeEmailContactContext, serializeEmailContactContext } from '@/lib/email-contact-context';
import styles from './EmailContactContextPanel.module.css';

export interface EmailContactContextPanelProps {
  context?: EmailContactContext;
  onDraftChange: () => void;
  onApply: (context: EmailContactContext) => void;
  /** Change for a new owner/open/target session, not an ordinary render. */
  resetKey: string;
  disabled?: boolean;
  language: 'en' | 'zh';
}

type Purpose = EmailContactContext['purpose'];
type ReplyStatus = 'unknown' | 'no_reply' | 'received' | 'declined' | 'do_not_contact';
type Fields = {
  purpose: Purpose;
  referrerName: string;
  referralNote: string;
  previousMessage: string;
  sentOn: string;
  replyStatus: ReplyStatus;
  replyText: string;
  availability: string;
};
type Confirmations = { referral: boolean; sent: boolean; availability: boolean };
type PanelError = 'required' | 'confirmation' | 'invalid' | 'blocked' | 'apply';
type Supplied = { value: EmailContactContext; key: string; valid: boolean };
type State = {
  sourceKey: string;
  fields: Fields;
  confirmed: Confirmations;
  dirty: boolean;
  appliedKey: string | null;
  error: PanelError | null;
};
const unconfirmed = (): Confirmations => ({ referral: false, sent: false, availability: false });

function supplied(value: EmailContactContext | undefined): Supplied {
  try {
    const normalized = normalizeEmailContactContext(value);
    return { value: normalized, key: serializeEmailContactContext(normalized), valid: true };
  } catch {
    return { value: defaultEmailContactContext(), key: 'invalid', valid: false };
  }
}

function fromSupplied(source: Supplied): State {
  const value = source.value;
  return {
    sourceKey: source.key,
    fields: {
      purpose: value.purpose,
      referrerName: value.referral?.referrer_name ?? '',
      referralNote: value.referral?.referral_note ?? '',
      previousMessage: value.follow_up?.previous_message ?? '',
      sentOn: value.follow_up?.sent_on ?? '',
      replyStatus: value.follow_up?.reply_status ?? 'unknown',
      replyText: value.follow_up?.reply_text ?? '',
      availability: value.availability?.text ?? '',
    },
    confirmed: {
      referral: value.referral?.confirmed === true,
      sent: value.follow_up?.sent_confirmed === true,
      availability: value.availability?.confirmed === true,
    },
    dirty: !source.valid,
    appliedKey: source.valid ? source.key : null,
    error: source.valid ? null : 'invalid',
  };
}

function prepare(fields: Fields, confirmed: Confirmations):
  { value: EmailContactContext; key: string; error: null } | { error: PanelError } {
  if (fields.purpose === 'follow_up' && ['declined', 'do_not_contact'].includes(fields.replyStatus)) return { error: 'blocked' };
  if (fields.purpose === 'referral' && (!fields.referrerName.trim() || !fields.referralNote.trim())) return { error: 'required' };
  if (fields.purpose === 'follow_up' && (!fields.previousMessage.trim() || (fields.replyStatus === 'received' && !fields.replyText.trim()))) return { error: 'required' };
  if ((fields.purpose === 'referral' && !confirmed.referral)
    || (fields.purpose === 'follow_up' && !confirmed.sent)
    || (fields.availability.trim() && !confirmed.availability)) return { error: 'confirmation' };
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
  };
  try {
    const value = normalizeEmailContactContext(candidate);
    return { value, key: serializeEmailContactContext(value), error: null };
  } catch {
    return { error: 'invalid' };
  }
}

/** Context confirmation is local preparation only. This component cannot send,
 * generate, save a profile, or record a contacted/reminder event. */
export default function EmailContactContextPanel(props: EmailContactContextPanelProps) {
  return <ContextSession key={props.resetKey} {...props} />;
}

function ContextSession({ context, onDraftChange, onApply, disabled = false, language }: EmailContactContextPanelProps) {
  const copy = (en: string, zh: string) => language === 'zh' ? zh : en;
  const id = useId();
  const source = supplied(context);
  const [state, setState] = useState(() => fromSupplied(source));
  const [expanded, setExpanded] = useState(() => source.value.purpose !== 'first_contact');
  // Adopt an external accepted context only when it cannot erase unfinished
  // answers. A real owner/target reset uses the keyed session above.
  if (state.sourceKey !== source.key) {
    setState(!state.dirty || state.appliedKey === source.key
      ? fromSupplied(source)
      : { ...state, sourceKey: source.key, appliedKey: null });
  }
  const fields = state.fields;
  const prepared = prepare(fields, state.confirmed);
  const blocked = prepared.error === 'blocked';
  const applied = !state.dirty && state.appliedKey !== null && prepared.error === null && state.appliedKey === prepared.key;
  const error = state.error ?? (blocked ? 'blocked' : null);
  const errors: Record<PanelError, string> = {
    required: copy('Fill in the required details, or choose First contact. Your answers are kept.', '请补齐必要信息，或选择“首次联系”。已填内容会保留。'),
    confirmation: copy('Confirm the details you want to use. Optional availability can be cleared or skipped.', '请确认要使用的信息。可清空或跳过选填的可投入时间。'),
    invalid: copy('Some details are invalid or too long. Check the date and character counts. Your full text is kept.', '部分信息格式不正确或过长，请检查日期和字数。完整输入仍保留。'),
    blocked: copy('Do not prepare a follow-up after a refusal or a request not to contact them. Your current email and answers are kept.', '对方已拒绝或要求不再联系时，不准备跟进邮件。当前邮件和填写内容仍保留。'),
    apply: copy('The background could not be applied. Your answers are kept; please try again.', '背景信息未能应用，填写内容仍保留，请重试。'),
  };
  const update = <K extends keyof Fields>(key: K, value: Fields[K]) => {
    if (disabled) return;
    onDraftChange();
    setState(previous => ({ ...previous, fields: { ...previous.fields, [key]: value },
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
    const result = prepare(fields, state.confirmed);
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
  return <details className={styles.panel} open={expanded} onToggle={event => setExpanded(event.currentTarget.open)}
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
