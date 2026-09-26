import { hasTargetResumeCriteria, type TargetResumeContext } from '@/lib/target-resume';

type Labels = Record<string, readonly [string, string]>;
const groups: Labels = {
  eligibility: ['Eligibility', '申请资格'], timing: ['Dates and duration', '时间与期限'],
  application: ['Application', '申请方式与材料'], setting: ['Opportunity details', '机会信息'],
  availability: ['Availability at creation', '建稿时的机会状态'], attribution: ['Inference flags', '推断标记'],
};
const fields: Labels = {
  preferred_year: ['Year of study', '年级'], min_gpa_decimal: ['Minimum GPA', '最低 GPA'], majors: ['Majors', '专业'],
  skills_required: ['Required skills', '要求的技能'], skills_preferred: ['Preferred skills', '加分技能'],
  citizenship_required: ['Citizenship requirement', '公民身份要求'], international_friendly: ['International eligibility', '国际学生资格'],
  work_auth_notes: ['Work authorization', '工作许可说明'], first_time_researchers: ['First-time researchers', '初次参与科研'],
  deadline: ['Deadline', '截止日期'], deadline_is_estimate: ['Estimated deadline', '是否为预计截止日期'],
  is_rolling: ['Rolling application flag', '滚动申请标记'], deadline_note: ['Deadline note', '截止日期原始说明'],
  start_date: ['Start date', '开始日期'], posted_date: ['Posted date', '发布日期'], duration: ['Duration', '持续时间'],
  contact_method: ['Application method', '申请方式'], application_effort: ['Estimated application effort', '预计申请工作量'],
  requires_resume: ['Résumé required', '是否需要简历'], requires_cover_letter: ['Cover letter required', '是否需要求职信'],
  requires_transcript: ['Transcript required', '是否需要成绩单'], requires_recommendation: ['Recommendation required', '是否需要推荐信'],
  application_url: ['Application link', '申请链接'], location: ['Location', '地点'], remote_option: ['Remote option', '远程安排'],
  on_campus: ['On campus', '是否在校内'], opportunity_type: ['Opportunity type', '机会类型'], paid: ['Pay status', '报酬情况'],
  compensation_details: ['Compensation details', '报酬说明'], department: ['Department', '院系'], lab_or_program: ['Lab or program', '实验室或项目'],
  pi_name: ['Professor', '教授'], target_truth: ['Availability information', '机会状态说明'], record_kind: ['Record type', '记录类型'], source_type: ['Source type', '来源类型'],
  faculty_availability_status: ['Faculty availability', '教授接收状态'], listing_state: ['Listing state', '机会开放状态'],
  reference_only: ['Reference only', '是否仅供参考'], actionable: ['Available for an application action', '是否可继续申请操作'],
  accepting_state: ['Accepting students', '接收学生状态'], reason_code: ['Availability note', '状态说明'],
  skills_attribution: ['Skills', '技能'], majors_attribution: ['Majors', '专业'], preferred_year_attribution: ['Year of study', '年级'],
  international_attribution: ['International eligibility', '国际学生资格'], citizenship_attribution: ['Citizenship', '公民身份'],
  paid_attribution: ['Pay status', '报酬情况'],
};
const values: Labels = {
  unknown: ['Unknown', '未知'], yes: ['Yes', '是'], no: ['No', '否'], inferred: ['Inferred', '推断'],
  open: ['Open', '开放'], closed: ['Closed', '已关闭'], accepting: ['Accepting', '接收中'], not_accepting: ['Not accepting', '不接收'],
  listing_closed: ['Listing closed', '机会已关闭'], reference_only: ['For reference only', '仅供参考'],
  faculty_not_accepting: ['Faculty not accepting students', '教授不接收学生'], inactive: ['Inactive', '未开放'],
  record_kind_unverified: ['Record type unverified', '记录类型未核实'],
};

/** Only the saved, validated public snapshot is shown here, never live data. */
export default function TargetResumeCriteria({ target, locale }: { target: TargetResumeContext; locale: string }) {
  if (!hasTargetResumeCriteria(target)) return null;
  const language = locale === 'zh' ? 1 : 0;
  const inferredFields: Record<string, keyof typeof target.criteria.attribution> = {
    skills_required: 'skills_attribution', majors: 'majors_attribution',
    preferred_year: 'preferred_year_attribution', international_friendly: 'international_attribution',
    citizenship_required: 'citizenship_attribution', paid: 'paid_attribution',
  };
  const label = (key: string) => {
    const base = fields[key]?.[language] ?? key.replaceAll('_', ' ');
    const inferred = inferredFields[key] && target.criteria.attribution[inferredFields[key]] === 'inferred';
    const estimated = key === 'deadline' && target.criteria.timing.deadline_is_estimate;
    return base + (inferred ? [' (inferred)', '（推断）'][language] : estimated ? [' (estimated)', '（预计）'][language] : '');
  };
  const text = (value: unknown, attribution: boolean): string => {
    if (value === null || value === undefined || value === '') return attribution
      ? ['No inference flag recorded', '未记录推断标记'][language] : ['Not provided', '未提供'][language];
    if (Array.isArray(value)) return value.length ? value.join(' · ') : ['None listed', '未列出'][language];
    if (typeof value === 'boolean') return (value ? values.yes : values.no)[language];
    return typeof value === 'string' ? values[value]?.[language] ?? value : '';
  };
  return <div className="mt-3 space-y-3" data-testid="saved-target-criteria">
    <p className="text-xs text-gray-600">{language
      ? '建稿时保存的公开资料。推断值和预计日期仍需核实，缺少标记不代表已确认。'
      : 'Public details saved with this draft. Inferred values and estimated dates still need checking; an absent flag does not mean confirmed.'}</p>
    {target.context_version === 3 && <section data-testid="saved-target-research" className="min-w-0 rounded-lg bg-gray-50 p-3">
      <h3 className="text-sm font-medium">{language ? '建稿时的研究资料' : 'Research saved with this draft'}</h3>
      <p className="mt-1 text-xs text-gray-600">{target.research.status === 'available'
        ? (language ? '论文标题与摘要已核对作者归属，用于判断研究相关性；不代表教授正在招人，也不是你的成果。' : 'Paper titles and abstracts with checked author attribution, for research relevance; they do not establish recruiting or your accomplishments.')
        : target.research.status === 'stale' ? (language ? '资料已过期，保留供查看；AI 不使用这些旧论文。' : 'This snapshot is stale and kept for display. AI does not use these papers.')
        : (language ? '没有可用的已核实研究资料。' : 'No verified research snapshot is available.')}</p>
      {target.research.snapshot && <>
        <p className="mt-1 break-words text-xs text-gray-600">{language ? '核对时间' : 'Checked'}: {target.research.snapshot.checked_at}</p>
        <ul className="mt-2 space-y-2 text-sm">{target.research.snapshot.works.map(work => <li key={work.work_id} className="min-w-0">
          <a href={work.source_url} target="_blank" rel="noreferrer" className="break-words text-indigo-700 underline">{work.title}</a> ({work.year})
          {work.abstract_status === 'present' ? <details className="mt-1"><summary>{language ? '摘要' : 'Abstract'}</summary><p className="whitespace-pre-wrap break-words">{work.abstract}</p></details>
            : <p className="text-xs text-gray-600">{language ? '未提供可用摘要' : 'No usable abstract provided'}</p>}
        </li>)}</ul>
      </>}
    </section>}
    {Object.entries(target.criteria).map(([group, data]) => {
      const rows = Object.entries(data).flatMap<[string, unknown]>(([key, value]) => key === 'target_truth' && value && typeof value === 'object'
        ? Object.entries(value) : [[key, value]]);
      return <section key={group} className="min-w-0 rounded-lg bg-gray-50 p-3" aria-label={groups[group][language]}>
        <h3 className="text-sm font-medium">{groups[group][language]}</h3>
        {rows.length ? <dl className="mt-2 space-y-2 text-sm">{rows.map(([key, value]) => <div key={key} className="min-w-0 sm:grid sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-3">
          <dt className="text-gray-600">{label(key)}</dt><dd className="whitespace-pre-wrap break-words">{text(value, group === 'attribution')}</dd>
        </div>)}</dl> : <p className="mt-2 text-sm text-gray-600">{language ? '未提供' : 'Not provided'}</p>}
        {group === 'timing' && target.criteria.timing.is_rolling && !target.criteria.timing.deadline_note && <p className="mt-2 text-xs text-amber-800">{language
          ? '只有滚动申请标记，没有日期说明；请以原始页面为准。'
          : 'A rolling flag is recorded without a deadline note. Check the source page.'}</p>}
      </section>;
    })}
  </div>;
}
