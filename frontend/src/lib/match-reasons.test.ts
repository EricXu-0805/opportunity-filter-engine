import { describe, expect, it } from 'vitest';
import fixture from './__fixtures__/match-reason-keys.json';
import { localizeMatchReasons, ZH_REASON_KEYS } from './match-reasons';

interface Case { kind: string; english: string; key: string; params: Record<string, string> }
// The backend keys each of these lines so (tests/test_reason_keys_m107.py).
const CASES = fixture.cases as Case[];

const zh = (c: Case): string => localizeMatchReasons('zh', [c.english], [{ key: c.key, params: c.params }])[0];
const byKey = (key: string): Case => CASES.find((c) => c.key === key)!;

describe('match reasons on the zh interface (M107)', () => {
  it('has a zh line for every key the backend serves, and none it does not', () => {
    expect(new Set(ZH_REASON_KEYS)).toEqual(new Set(CASES.map((c) => c.key)));
  });

  it.each(CASES.map((c) => [c.key, c] as const))('renders %s in Chinese', (_key, c) => {
    const line = zh(c);
    expect(line).toBeTruthy();
    expect(line).not.toMatch(/undefined|null|\{\w+\}/);
    if (c.key === 'research_summary') {
      // The record's own names and topics: nothing of ours to translate.
      expect(line).toBe(c.english);
    } else {
      expect(line).not.toBe(c.english);
      expect(line).toMatch(/[一-鿿]/);
    }
  });

  it('keeps quoted source text and names exactly as given, in 「」', () => {
    expect(zh(byKey('intl_listing_no_sponsorship'))).toBe(
      '列表标注：「Does Not Offer Sponsorship」（我们的说明：实习可能仍适用 CPT/OPT，请向雇主确认）',
    );
    expect(zh(byKey('major_direct'))).toBe('你的专业「Biology」完全对口');
    expect(zh(byKey('major_prefers'))).toBe('偏好专业：「Biology」、「Chemistry」');
    expect(zh(byKey('interest_lab_work'))).toBe(
      '你感兴趣的「genomics」与「Prof. Ada Lovelace」在「genomics」、「proteomics」方面的工作高度吻合',
    );
    expect(zh(byKey('skills_fit_required'))).toBe(
      '技术栈高度契合：「Python」（精通）、「SQL」（熟练） —— 要求的 3 项技能中你有 2 项',
    );
    expect(zh(byKey('skills_missing'))).toBe('缺少的技能：「MATLAB」、「Stata」');
    expect(zh(byKey('lab_focus'))).toBe('该实验室的研究方向：「Genomics Lab — sequencing」');
  });

  it('keeps every hedge the English line has (M88 wording)', () => {
    // "Our listing ... — not confirmed on the program page" stays ours and unconfirmed.
    for (const c of CASES.filter((x) => x.english.includes('not confirmed on the program page'))) {
      expect(zh(c)).toContain('项目页面未确认');
    }
    for (const c of CASES.filter((x) => x.english.startsWith('Our listing'))) {
      expect(zh(c)).toContain('我们列表里');
    }
    for (const c of CASES.filter((x) => x.english.includes('by our reading of the page'))) {
      expect(zh(c)).toContain('我们对页面的理解');
    }
    // "may" / "suggests" / "Potential" never become a plain statement.
    for (const key of [
      'year_may_fit', 'major_field_may_fit', 'major_field_may_relate', 'major_may_fit', 'major_may_relate',
      'citizenship_read', 'citizenship_listing_and_read', 'publication_pathway', 'experience_limited',
    ]) {
      expect(zh(byKey(key))).toContain('可能');
    }
    for (const c of CASES.filter((x) => x.english.startsWith('Our listing suggests'))) {
      expect(zh(c)).toContain('我们列表里的信息提示');
    }
    expect(zh(byKey('year_may_fit'))).toBe('你的年级（大三）可能符合这个项目');
    expect(zh(byKey('citizenship_read'))).toBe(
      '可能需要美国公民或永久居民身份，这是我们对页面的理解 —— 项目页面未确认',
    );
  });

  it('names class years and opportunity types as students and kinds of opportunity', () => {
    const lines = (key: string): string[] => CASES.filter((c) => c.key === key).map(zh);
    expect(lines('year_accepts')).toEqual(['接受大三学生', '接受博士生']);
    expect(lines('year_listing_targets')).toEqual([
      '我们列表里的信息提示面向大三、大四学生 —— 项目页面未确认',
      '我们列表里的信息提示面向大四学生、研究生 —— 项目页面未确认',
    ]);
    // A label that already names students (硕士生, 博士生) takes no second 学生.
    for (const c of CASES) expect(zh(c)).not.toContain('生学生');
    const typeLine = (type: string): string =>
      localizeMatchReasons('zh', ['x'], [{ key: 'type_mismatch', params: { type } }])[0];
    expect(zh(byKey('type_mismatch'))).toBe('这是实习 —— 不是你的首选类型');
    expect(typeLine('research')).toBe('这是研究机会 —— 不是你的首选类型');
    expect(typeLine('fellowship')).toBe('这是资助项目 —— 不是你的首选类型');
    expect(zh(byKey('type_match'))).toBe('符合你想找的类型：暑期项目');
  });

  it('says what the experience can support, no more firmly than "can"', () => {
    expect(zh(byKey('experience_faculty'))).toBe('你的经历可以支撑你认真地联系这位教师');
  });

  it('wraps an exclusion around its restriction with the same hedge', () => {
    const read = CASES.find((c) => c.key === 'excluded_restriction' && c.params.restriction === 'citizenship_read')!;
    expect(zh(read)).toBe('已从你的结果中排除：可能需要美国公民或永久居民身份，这是我们对页面的理解 —— 项目页面未确认');
  });

  it('falls back to the English line, never blank', () => {
    const lines = ['Paid opportunity', 'A model wrote this', 'Something new', 'Accepts junior students', 'X'];
    const keys = [
      { key: 'paid', params: {} },
      null,
      { key: 'a_key_this_client_does_not_know', params: {} },
      { key: 'year_accepts', params: {} },
      { key: 'type_match', params: { type: '' } },
    ];
    expect(localizeMatchReasons('zh', lines, keys)).toEqual([
      '有报酬', 'A model wrote this', 'Something new', 'Accepts junior students', 'X',
    ]);
    // An older backend sends no keys, or keys that do not line up.
    expect(localizeMatchReasons('zh', lines, undefined)).toBe(lines);
    expect(localizeMatchReasons('zh', lines, keys.slice(1))).toBe(lines);
    expect(localizeMatchReasons('zh', lines, 'junk')).toBe(lines);
    expect(localizeMatchReasons('zh', ['Paid opportunity'], [{ key: 'paid', params: { x: 1 } }])).toEqual(['有报酬']);
    expect(localizeMatchReasons('zh', ['Accepts junior students'], [{ key: 'year_accepts', params: null }]))
      .toEqual(['Accepts junior students']);
  });

  it('shows the served English lines unchanged on the en interface', () => {
    const lines = CASES.map((c) => c.english);
    const keys = CASES.map((c) => ({ key: c.key, params: c.params }));
    expect(localizeMatchReasons('en', lines, keys)).toBe(lines);
  });
});
