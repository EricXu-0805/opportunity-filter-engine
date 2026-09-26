/** Contact rules are produced from server-owned source snapshots, not drafts. */
export type ContactRuleKind = 'no_email' | 'form_only' | 'subject' | 'materials' | 'contact_person' | 'email_allowed';
export interface ContactInstructionRule {
  kind: ContactRuleKind; quote: string; source_url: string; checked_at: string;
  subject?: string; subject_template?: string; materials?: string[];
}
export interface ContactInstructions {
  version: 1; status: 'unknown' | 'known' | 'conflicting';
  email_policy: 'unknown' | 'allowed' | 'not_accepted' | 'form_only' | 'conflicting';
  rules: ContactInstructionRule[];
  review_required?: true; reason?: 'too_many_requirements';
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const nonblank = (v: unknown, max: number): v is string => typeof v === 'string' && !!v.trim() && v.length <= max;
const kinds: ContactRuleKind[] = ['no_email', 'form_only', 'subject', 'materials', 'contact_person', 'email_allowed'];
export function contactSourceUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
export function isContactInstructions(value: unknown): value is ContactInstructions {
  if (!object(value) || value.version !== 1
    || !['unknown', 'known', 'conflicting'].includes(String(value.status))
    || !['unknown', 'allowed', 'not_accepted', 'form_only', 'conflicting'].includes(String(value.email_policy))
    || !Array.isArray(value.rules) || value.rules.length > 40) return false;
  if (('review_required' in value || 'reason' in value)
    && !(value.review_required === true && value.reason === 'too_many_requirements')) return false;
  if (value.status === 'unknown' && (value.rules.length || value.email_policy !== 'unknown')) return false;
  if (value.status === 'known' && !value.rules.length) return false;
  if ((value.status === 'conflicting') !== (value.email_policy === 'conflicting')) return false;
  return value.rules.every(rule => object(rule) && kinds.includes(rule.kind as ContactRuleKind)
    && nonblank(rule.quote, 6000) && contactSourceUrl(rule.source_url) !== null
    && typeof rule.checked_at === 'string' && Number.isFinite(Date.parse(rule.checked_at))
    && (!('subject' in rule) || (rule.kind === 'subject' && nonblank(rule.subject, 500) && !/[\r\n]/.test(rule.subject)))
    && (!('subject_template' in rule) || (rule.kind === 'subject' && !('subject' in rule) && nonblank(rule.subject_template, 500) && !/[\r\n]/.test(rule.subject_template)))
    && (!('materials' in rule) || (rule.kind === 'materials' && Array.isArray(rule.materials)
      && rule.materials.length <= 20 && rule.materials.every(item => nonblank(item, 200)))));
}
export function readContactInstructions(target: unknown): ContactInstructions | null {
  if (!object(target)) return null;
  if (!('contact_instructions' in target)) return { version: 1, status: 'unknown', email_policy: 'unknown', rules: [] };
  return isContactInstructions(target.contact_instructions) ? target.contact_instructions : null;
}
export type ContactEmailBlock = 'unavailable' | 'not_accepted' | 'form_only' | 'conflicting' | 'subject' | 'subject_format' | 'too_many_requirements';
export function requiredContactSubject(target: unknown): string | null {
  const policy = readContactInstructions(target);
  if (policy?.status !== 'known') return null;
  const subjects = [...new Set(policy.rules.flatMap(rule => rule.kind === 'subject' && rule.subject ? [rule.subject] : []))];
  return subjects.length === 1 ? subjects[0] : null;
}
export function needsContactSubjectReview(target: unknown): boolean {
  return readContactInstructions(target)?.rules.some(rule => rule.kind === 'subject' && !rule.subject) ?? false;
}
export function contactEmailBlock(target: unknown, subject?: string, options: { subjectFormatConfirmed?: boolean } = {}): ContactEmailBlock | null {
  const policy = readContactInstructions(target);
  if (!policy) return 'unavailable';
  if (policy.review_required) return 'too_many_requirements';
  if (policy.email_policy === 'not_accepted' || policy.email_policy === 'form_only' || policy.email_policy === 'conflicting') return policy.email_policy;
  const required = requiredContactSubject(target);
  if (required && subject !== undefined && subject !== required) return 'subject';
  if (subject !== undefined && needsContactSubjectReview(target)) {
    const copiedTemplate = policy.rules.some(rule => rule.subject_template === subject);
    const placeholder = /[\[<{](?:your\s+)?(?:last|first|full|family|name|surname)[^\]>}]*[\]>}]/i.test(subject);
    if (!subject.trim() || copiedTemplate || placeholder || !options.subjectFormatConfirmed) return 'subject_format';
  }
  return null;
}
export const contactInstructionCopy = {
  en: {
    too_many_requirements: 'This source has more requirements than can be checked here. Review the official page before continuing.',
    title: 'Contact instructions', unknown: 'No applicable contact instructions were confirmed. Check the official page before contacting.',
    unavailable: 'Contact instructions could not be loaded. Refresh this opportunity and try again.',
    not_accepted: 'The source says not to email. Follow the official contact instructions.',
    form_only: 'The source requires contact through its form. Continue on the official page.',
    conflicting: 'The sources give conflicting contact instructions. Check the official page first.',
    subject: 'Use the subject required by the source before opening your email app.',
    subject_format: 'Fill in the subject using the source format, then confirm that you checked it.',
    confirmFormat: 'I filled in the required subject and checked it against the source.',
    requiredSubject: 'Required subject', useSubject: 'Use this subject', materials: 'Materials to prepare',
    materialNote: 'Preparing a draft does not attach files or submit an application.',
    source: 'Source', checked: 'Checked', old: 'This source was checked over 60 days ago. Verify that it still applies.',
    no_email: 'Email not accepted', email_allowed: 'Email instructions', contact_person: 'Contact person',
  },
  zh: {
    too_many_requirements: '这份来源的要求较多，当前无法完整核对。请先查看官网。',
    title: '联系要求', unknown: '尚未确认适用的联系要求。联系前请核对官网。',
    unavailable: '联系要求未能加载，请刷新机会信息后重试。',
    not_accepted: '来源明确不接受邮件，请按官网说明继续。',
    form_only: '来源要求通过表单联系，请前往官网继续。',
    conflicting: '不同来源的联系要求有冲突，请先核对官网。',
    subject: '请先使用来源要求的邮件主题，再打开邮箱。',
    subject_format: '请按来源格式填写主题，再确认已核对。',
    confirmFormat: '我已按来源格式填写主题，并核对无误。',
    requiredSubject: '要求的邮件主题', useSubject: '使用此主题', materials: '需要准备的材料',
    materialNote: '生成草稿不代表已附上文件或提交申请。',
    source: '来源', checked: '核对时间', old: '这份来源已超过 60 天未核对，请确认要求仍然适用。',
    no_email: '不接受邮件', email_allowed: '邮件联系说明', contact_person: '联系对象',
  },
} as const;

export function contactMaterialLabel(material: string, locale: 'en' | 'zh'): string {
  const names: Record<string, [string, string]> = {
    resume_cv: ['Resume / CV', '简历 / CV'], transcript: ['Transcript', '成绩单'],
    unofficial_transcript: ['Unofficial transcript', '非正式成绩单'], cover_letter: ['Cover letter', '求职信'],
    statement_of_interest: ['Statement of interest', '兴趣说明'], application_form: ['Completed application form', '填写好的申请表'],
    single_pdf: ['Combine the required materials into one PDF', '将要求的材料合并成一份 PDF'],
  };
  return names[material]?.[locale === 'zh' ? 1 : 0] ?? material;
}
