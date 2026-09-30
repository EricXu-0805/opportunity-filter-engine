import { contactSourceUrl } from './contact-instructions';

export const TARGET_CONDITION_FIELDS = [
  'eligibility.preferred_year', 'eligibility.min_gpa', 'eligibility.majors', 'eligibility.skills_required',
  'eligibility.skills_preferred', 'eligibility.citizenship_required', 'eligibility.international_friendly',
  'eligibility.work_auth_notes', 'eligibility.eligibility_text_raw', 'deadline', 'is_rolling',
  'application.requires_resume', 'application.requires_cover_letter', 'application.requires_transcript',
  'application.requires_recommendation',
] as const;
export type TargetConditionField = typeof TARGET_CONDITION_FIELDS[number];
export interface EmailTargetCondition {
  field: TargetConditionField;
  category: 'eligibility' | 'deadline' | 'materials';
  status: 'stated' | 'inferred' | 'policy' | 'unverified' | 'unknown' | 'stale' | 'conflicting';
  value: string | number | boolean | string[] | null;
  usage: 'usable' | 'ask_only' | 'excluded';
  reason: 'source_stated' | 'inferred_field' | 'program_policy' | 'unverified_legacy_value' | 'no_source_evidence'
    | 'source_stale' | 'source_conflict' | 'normalized_source_conflict' | 'source_binding_mismatch'
    | 'source_unavailable' | 'unsupported_source_wording' | 'source_overflow' | 'source_not_public';
  sources: Array<{ heading?: string; quote: string; source_url: string; checked_at: string }>;
}
export interface EmailTargetConditions {
  version: 1;
  record_kind: 'listing' | 'faculty_contact' | 'unverified';
  conditions: EmailTargetCondition[];
  template_request: string | null;
}
export const EMAIL_CONDITION_ISSUES = ['unsupported_eligibility_claim', 'unsupported_deadline_claim',
  'unsupported_material_claim', 'unsupported_attachment_claim', 'empty_draft'] as const;
export type EmailConditionIssue = typeof EMAIL_CONDITION_ISSUES[number];
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown, max: number): v is string => typeof v === 'string' && Array.from(v).length <= max && !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(v);
const reasons = ['source_stated', 'inferred_field', 'program_policy', 'unverified_legacy_value', 'no_source_evidence',
  'source_stale', 'source_conflict', 'normalized_source_conflict', 'source_binding_mismatch', 'source_unavailable',
  'unsupported_source_wording', 'source_overflow', 'source_not_public'];
export function isEmailTargetConditions(value: unknown): value is EmailTargetConditions {
  if (!object(value) || value.version !== 1 || typeof value.record_kind !== 'string' || !['listing', 'faculty_contact', 'unverified'].includes(value.record_kind)
    || !Array.isArray(value.conditions) || value.conditions.length > 15
    || !(value.template_request === null || text(value.template_request, 500))) return false;
  const seen = new Set<string>();
  return value.conditions.every(c => {
    if (!object(c) || !TARGET_CONDITION_FIELDS.includes(c.field as TargetConditionField) || seen.has(String(c.field))) return false;
    seen.add(String(c.field));
    const category = String(c.field).startsWith('eligibility.') ? 'eligibility' : String(c.field).startsWith('application.') ? 'materials' : 'deadline';
    if (c.category !== category || typeof c.status !== 'string' || !['stated', 'inferred', 'policy', 'unverified', 'unknown', 'stale', 'conflicting'].includes(c.status)
      || typeof c.usage !== 'string' || !['usable', 'ask_only', 'excluded'].includes(c.usage) || typeof c.reason !== 'string' || !reasons.includes(c.reason)) return false;
    if (!(c.value === null || typeof c.value === 'boolean' || typeof c.value === 'number' && Number.isFinite(c.value)
      || text(c.value, 20000) || Array.isArray(c.value) && c.value.length <= 512 && c.value.every(v => text(v, 1000)))) return false;
    if (!Array.isArray(c.sources) || c.sources.length > 40 || !c.sources.every(s => object(s)
      && (s.heading === undefined || text(s.heading, 1000)) && text(s.quote, 4000) && !!s.quote.trim() && text(s.source_url, 2000) && contactSourceUrl(s.source_url) !== null
      && text(s.checked_at, 80) && /(?:Z|[+-]\d{2}:?\d{2})$/i.test(s.checked_at) && Number.isFinite(Date.parse(s.checked_at)))) return false;
    // A usable row must have explicit current source support. Other statuses
    // are displayed for review, never promoted by the client.
    return c.usage !== 'usable' || c.status === 'stated' && c.reason === 'source_stated' && c.sources.length > 0;
  });
}
export function readEmailTargetConditions(response: unknown): EmailTargetConditions | null {
  if (!object(response) || response.target_conditions === undefined) return null;
  if (!isEmailTargetConditions(response.target_conditions)) throw Object.assign(new Error('Invalid email condition receipt'), { code: 'INVALID_EMAIL_TARGET_CONDITIONS' });
  return response.target_conditions;
}
export function emailConditionIssueText(issue: EmailConditionIssue, locale: 'en' | 'zh'): string {
  const messages: Record<EmailConditionIssue, [string, string]> = {
    unsupported_eligibility_claim: ['Review claims that you meet the eligibility requirements. The current information does not support them.', '请核对“我已符合资格”的表述，现有资料无法支持。'],
    unsupported_deadline_claim: ['Review the deadline stated in your draft against the source.', '请对照来源核对邮件中的截止日期。'],
    unsupported_material_claim: ['Review the materials described as required against the source.', '请对照来源核对邮件中称为必需的申请材料。'],
    unsupported_attachment_claim: ['The draft claims files are attached. No attachment has been confirmed here.', '邮件写了已附上文件，但这里尚未确认附件。'],
    empty_draft: ['Add a subject and message before continuing.', '请先填写主题和正文。'],
  };
  return messages[issue][locale === 'zh' ? 1 : 0];
}
export function targetConditionLabel(field: TargetConditionField, locale: 'en' | 'zh'): string {
  const labels: Record<TargetConditionField, [string, string]> = {
    'eligibility.preferred_year': ['Year of study', '年级'], 'eligibility.min_gpa': ['Minimum GPA', '最低 GPA'],
    'eligibility.majors': ['Majors', '专业'], 'eligibility.skills_required': ['Required skills', '必需技能'],
    'eligibility.skills_preferred': ['Preferred skills', '优先考虑的技能'], 'eligibility.citizenship_required': ['Citizenship requirement', '国籍要求'],
    'eligibility.international_friendly': ['International students', '国际生'], 'eligibility.work_auth_notes': ['Work authorization', '工作许可'],
    'eligibility.eligibility_text_raw': ['Eligibility', '申请资格'], deadline: ['Deadline', '截止日期'], is_rolling: ['Rolling applications', '滚动申请'],
    'application.requires_resume': ['Resume / CV', '简历 / CV'], 'application.requires_cover_letter': ['Cover letter', '求职信'],
    'application.requires_transcript': ['Transcript', '成绩单'], 'application.requires_recommendation': ['Recommendation', '推荐材料'],
  };
  return labels[field][locale === 'zh' ? 1 : 0];
}
export function targetConditionStatus(condition: EmailTargetCondition, locale: 'en' | 'zh'): string {
  const status: Record<EmailTargetCondition['status'], [string, string]> = {
    stated: ['Stated in the source', '来源明确说明'], inferred: ['Inferred; needs confirmation', '推测，需核对'],
    policy: ['Policy; confirm it applies here', '政策信息，需确认是否适用'], unverified: ['Not verified', '尚未核对'],
    unknown: ['Not established', '尚不明确'], stale: ['Source needs a fresh check', '来源需重新核对'], conflicting: ['Sources disagree', '来源有冲突'],
  };
  return status[condition.status][locale === 'zh' ? 1 : 0];
}

export function isEmailConditionIssues(value: unknown): value is EmailConditionIssue[] {
  return Array.isArray(value) && value.length <= EMAIL_CONDITION_ISSUES.length && new Set(value).size === value.length
    && value.every(issue => EMAIL_CONDITION_ISSUES.includes(issue));
}

export function targetConditionReason(condition: EmailTargetCondition, locale: 'en' | 'zh'): string | null {
  const reasons: Partial<Record<EmailTargetCondition['reason'], [string, string]>> = {
    source_not_public: ['This source cannot currently support the draft. Check the original page.', '这项条件的来源暂无法用于写作，请查看原网页核对。'],
    source_overflow: ['This condition has more information than can be checked here. Review the full source.', '这项条件的内容超出本次核对范围，请查看完整来源。'],
    source_binding_mismatch: ['The source no longer matches this record. Check the current requirement.', '来源与当前记录不一致，请重新核对要求。'],
    source_unavailable: ['The supporting source is unavailable. Confirm the requirement before using it.', '暂时无法核对支持这项条件的来源，使用前请确认。'],
    unsupported_source_wording: ['The source wording does not establish this condition.', '现有来源的表述不足以确认这项条件。'],
    normalized_source_conflict: ['The recorded condition conflicts with its source.', '记录的条件与来源不一致。'],
  };
  return reasons[condition.reason]?.[locale === 'zh' ? 1 : 0] ?? null;
}

/** Translate only known structured values. Free text and source quotations stay verbatim. */
export function targetConditionValue(condition: EmailTargetCondition, locale: 'en' | 'zh'): string {
  const value = condition.value; const zh = locale === 'zh';
  const material: Record<string, [string, string]> = { yes: ['Required', '需要'], no: ['Not required', '不需要'], unknown: ['Not established', '尚不明确'] };
  const years: Record<string, [string, string]> = { freshman: ['Freshman', '大一'], sophomore: ['Sophomore', '大二'], junior: ['Junior', '大三'], senior: ['Senior', '大四'], masters: ['Masters', '硕士'], phd: ['PhD', '博士'] };
  const format = (item: string): string => {
    const labels = condition.category === 'materials' ? material[item.toLowerCase()]
      : condition.field === 'eligibility.preferred_year' ? years[item.toLowerCase()] : undefined;
    return labels?.[zh ? 1 : 0] ?? item;
  };
  if (Array.isArray(value)) return value.map(format).join(' · ');
  if (typeof value === 'string') return format(value);
  if (typeof value === 'boolean') return value ? zh ? '是' : 'Yes' : zh ? '否' : 'No';
  return value === null ? '' : String(value);
}
