import type { Locale } from '@/i18n/translate';

/**
 * One match reason line's template key and params (M107), served by the
 * backend index-aligned with reasons_fit / reasons_gap. null where no
 * template wrote the line (a model's sentence, an older backend's unknown
 * line). The params are the English line's own substrings.
 */
export interface MatchReasonKey {
  key: string;
  params?: Record<string, string> | null;
}

type Params = Record<string, string>;
type Render = (p: Params) => string | null;

// Names and quoted source text stay as the source wrote them, in 「」.
const quote = (text: string): string => `「${text}」`;
// The backend joins list items with ", "; each item is a name or a label.
const quoteList = (text: string): string => text.split(', ').map(quote).join('、');

const YEARS: Record<string, string> = {
  freshman: '大一',
  sophomore: '大二',
  junior: '大三',
  senior: '大四',
  masters: '硕士生',
  phd: '博士生',
  graduate: '研究生',
  undergraduate: '本科生',
};
const year = (text: string): string => YEARS[text.trim().toLowerCase()] ?? quote(text);
const years = (text: string): string => text.split(', ').map(year).join('、');

const TYPES: Record<string, string> = {
  research: '研究',
  'summer program': '暑期项目',
  internship: '实习',
  fellowship: '奖学金项目',
};
const type = (text: string): string | null => (text ? TYPES[text.toLowerCase()] ?? quote(text) : null);

// A matched skill may carry the student's level, which is our label.
const LEVEL_SUFFIXES: [string, string][] = [[' (expert)', '（精通）'], [' (experienced)', '（熟练）']];
const skills = (text: string): string => text.split(', ').map((item) => {
  for (const [suffix, zh] of LEVEL_SUFFIXES) {
    if (item.endsWith(suffix) && item.length > suffix.length) return quote(item.slice(0, -suffix.length)) + zh;
  }
  return quote(item);
}).join('、');

const SKILL_LEVELS: Record<string, string> = {
  strong: '技术栈高度契合',
  overlap: '技术栈有重合',
  partial: '部分技能匹配',
};

const NOT_ON_PAGE = ' —— 项目页面未确认';

const fixed = (text: string): Render => () => text;

// Same wording strength as the English line: "may", "suggests", "our
// listing", "our reading" and "not confirmed" each keep their hedge.
const ZH_REASONS: Record<string, Render> = {
  // Class year
  year_may_fit: (p) => `你的年级（${year(p.year)}）可能符合这个项目`,
  year_accepts: (p) => `接受${year(p.year)}学生`,
  year_missing: fixed('补充你的年级，才能确认年级是否符合'),
  year_undergrad_only: fixed('面向本科生 —— 不是研究生层次的机会'),
  year_listing_undergrad: fixed(`我们列表里的信息显示这个项目面向本科生${NOT_ON_PAGE}`),
  year_targets: (p) => `通常面向${years(p.years)}`,
  year_listing_targets: (p) => `我们列表里的信息显示面向${years(p.years)}学生${NOT_ON_PAGE}`,
  // Major
  major_department_aligns: fixed('这位教师所在的院系与你的专业一致'),
  major_department_related: fixed('这位教师所在的院系与你的专业相关'),
  major_field_may_fit: fixed('你的专业可能适合这个领域'),
  major_field_may_relate: fixed('你的专业可能与这个领域相关'),
  major_all_listing: fixed(`我们列表里写着对所有专业开放${NOT_ON_PAGE}`),
  major_all: fixed('对所有专业开放'),
  major_may_fit: (p) => `你的专业${quote(p.major)}可能适合这个项目`,
  major_may_relate: (p) => `你的专业${quote(p.major)}可能与这个项目相关`,
  major_direct: (p) => `你的专业${quote(p.major)}完全对口`,
  major_close: (p) => `你的专业${quote(p.major)}与要求密切相关`,
  major_prefers: (p) => `偏好：${quoteList(p.majors)}`,
  major_listing: (p) => `我们列表里的信息显示偏向${quoteList(p.majors)}专业${NOT_ON_PAGE}`,
  // International students and citizenship
  intl_listing_no_sponsorship: (p) =>
    `列表标注：${quote(p.label)}（我们的说明：实习可能仍可使用 CPT/OPT，请向雇主确认）`,
  citizenship_listing: fixed(`我们列表里写着需要美国公民或永久居民身份${NOT_ON_PAGE}`),
  citizenship_read: fixed(`可能需要美国公民或永久居民身份，这是我们对页面的理解${NOT_ON_PAGE}`),
  citizenship_listing_and_read: fixed(
    `可能需要美国公民或永久居民身份，依据我们的列表和我们对页面的理解${NOT_ON_PAGE}`,
  ),
  citizenship_no_sponsorship: fixed('雇主不提供签证担保'),
  citizenship_required: fixed('需要美国公民或永久居民身份'),
  intl_unclear_internship: fixed('国际学生资格不明确 —— 很多实习可以使用 CPT/OPT，请向雇主确认'),
  intl_unstated_faculty: fixed('未注明是否接受国际学生 —— 联系教师时请确认'),
  intl_unclear: fixed('国际学生资格不明确 —— 申请前请核实'),
  intl_open_listing: fixed(`我们列表里写着接受国际学生${NOT_ON_PAGE}`),
  intl_open_read: fixed(`接受国际学生，这是我们对页面的理解${NOT_ON_PAGE}`),
  intl_open: fixed('接受国际学生'),
  // Skills and type
  skills_fit_required: (p) => {
    const label = SKILL_LEVELS[p.level];
    return label ? `${label}：${skills(p.skills)} —— 要求的 ${p.required} 项技能中你有 ${p.matched} 项` : null;
  },
  skills_fit: (p) => (SKILL_LEVELS[p.level] ? `${SKILL_LEVELS[p.level]}：${skills(p.skills)}` : null),
  skills_missing: (p) => `缺少的技能：${skills(p.skills)}`,
  skills_mentioned: (p) => `描述里提到的技能：${skills(p.skills)}`,
  skills_preferred: (p) => `加分技能有重合：${skills(p.skills)}`,
  type_match: (p) => {
    const label = type(p.type);
    return label ? `符合你想找的类型：${label}` : null;
  },
  type_mismatch: (p) => {
    const label = type(p.type);
    return label ? `这是${label}机会 —— 不是你的首选类型` : null;
  },
  // Readiness
  resume_required: fixed('需要简历 —— 申请前先准备好'),
  experience_faculty: fixed('你的经历足以支撑一次用心的教师联系'),
  experience_competitive: fixed('你的经验水平有竞争力'),
  experience_limited_faculty: fixed('你的经历信息有限 —— 可以问问需要哪些准备'),
  experience_limited: fixed('先前经验有限 —— 这个职位可能竞争激烈'),
  outreach_comfortable: fixed('你愿意直接联系对方'),
  effort_low: fixed('申请工作量小 —— 很快就能申请'),
  effort_high: fixed('申请工作量大 —— 预留时间准备材料'),
  // Upside
  paid: fixed('有报酬'),
  stipend: fixed('提供津贴'),
  first_time_welcome: fixed('明确欢迎第一次做研究的学生'),
  at_your_university: fixed('在你的学校'),
  brand_faculty_university: fixed('来自一所重要研究型大学的教师主页'),
  brand_university: fixed('重要研究型大学 —— 对简历很有帮助'),
  brand_faculty_institution: fixed('来自一家知名研究机构的教师主页'),
  brand_institution: fixed('知名机构 —— 对简历很有帮助'),
  publication_pathway: fixed('可能有发表论文或长期参与的机会'),
  interests_match: (p) => `符合你的兴趣：${quoteList(p.terms)}`,
  interest_lab_work: (p) =>
    `你感兴趣的${quoteList(p.interest)}与${quote(p.lab)}在${quoteList(p.work)}方面的工作高度吻合`,
  interest_their_work: (p) => `你感兴趣的${quoteList(p.interest)}与他们在${quoteList(p.work)}方面的工作高度吻合`,
  lab_also_works: (p) => `${quote(p.lab)}也从事${quoteList(p.work)}方面的工作`,
  they_also_work: (p) => `他们也从事${quoteList(p.work)}方面的工作`,
  interests_lab_focus: (p) => `你的研究兴趣与${quote(p.lab)}的研究方向一致`,
  // Dates, level and the record itself
  topic_mismatch: fixed('研究方向看起来与你填写的兴趣不同'),
  deadline_passed: fixed('截止日期已过 —— 请核实是否仍在接受申请'),
  deadline_soon: (p) => (/^\d+$/.test(p.days) ? `${p.days} 天后截止 —— 尽快申请` : null),
  start_passed: fixed('项目开始日期已过 —— 请查看是否有新一期'),
  grad_level_reach: fixed('面向研究生/博士生 —— 对本科生来说难度较大'),
  summer_in_season: fixed('暑期研究 —— 正当季，通常正在接受申请'),
  faculty_unconfirmed: fixed('教师是否招人、资格要求都未确认 —— 联系时请核实'),
  lab_focus: (p) => `该实验室的研究方向：${quote(p.summary)}`,
  // The record's own names and topics: nothing of ours to translate.
  research_summary: (p) => p.text,
  // Lines for a record the results left out (explain route)
  excluded_inactive: fixed('已不再开放 —— 已从你的结果中移除'),
  excluded_listing_closed: fixed('该招募已关闭，不再招人 —— 仅作参考保留，不在你的结果中'),
  excluded_reference_only: fixed('作为参考资料发布，不是开放中的招募 —— 不在你的结果中'),
  excluded_other_school_campus: fixed('仅限另一所学校的本校学生 —— 不在你的结果中'),
  excluded_cross_school_hidden: fixed('属于另一所学校 —— 开启跨校结果后才会包含'),
  excluded_faculty_not_accepting: fixed('来源主页注明这位教师目前不接收本科生 —— 已从你的结果中排除'),
  excluded_seeking_type_mismatch: fixed('不在你选择的机会类型内 —— 不在你的结果中'),
  excluded_below_threshold: fixed('低于你设定的最低匹配分 —— 未在你的结果中显示'),
  excluded_other: fixed('不在你当前的结果中'),
  excluded_restriction: (p) => {
    const inner = p.restriction?.startsWith('citizenship_') ? ZH_REASONS[p.restriction] : undefined;
    const text = inner?.({});
    return text ? `已从你的结果中排除：${text}` : null;
  },
};

/** Every key the zh table renders (for tests and audits). */
export const ZH_REASON_KEYS: readonly string[] = Object.keys(ZH_REASONS);

function zhReason(entry: unknown): string | null {
  if (!entry || typeof entry !== 'object') return null;
  const { key, params } = entry as MatchReasonKey;
  if (typeof key !== 'string' || !Object.prototype.hasOwnProperty.call(ZH_REASONS, key)) return null;
  const safe: Params = {};
  if (params && typeof params === 'object') {
    for (const [name, value] of Object.entries(params)) {
      if (typeof value === 'string') safe[name] = value;
    }
  }
  // A template whose param is missing reads the English line instead.
  const missing = new Proxy(safe, {
    get: (target, name) => {
      if (typeof name === 'string' && !(name in target)) throw new RangeError(name);
      return target[name as string];
    },
  });
  try {
    const text = ZH_REASONS[key](missing);
    return text ? text : null;
  } catch {
    return null;
  }
}

/**
 * The reason lines to show in `locale`. English shows the served lines as
 * they are. Chinese renders each keyed line from the table above and keeps
 * the English line wherever the key is null, unknown, incomplete, or the
 * keys do not line up with the lines (an older backend sends none).
 */
export function localizeMatchReasons(locale: Locale, reasons: string[], keys: unknown): string[] {
  if (locale !== 'zh' || !Array.isArray(keys) || keys.length !== reasons.length) return reasons;
  return reasons.map((reason, i) => zhReason(keys[i]) ?? reason);
}
