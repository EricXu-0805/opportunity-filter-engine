import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import golden from '../../../tests/fixtures/target-resume-context-v3-golden.json';
import type { TargetResumeContextV3, TargetResumeContextV2 } from '@/lib/target-resume';
import TargetResumeCriteria from './TargetResumeCriteria';

const target: TargetResumeContextV2 = {
  opportunity_id: 'saved', title: 'Lab', organization: 'University', source_url: '', description: '', requirements: [],
  context_version: 2, criteria: {
    eligibility: { skills_required: ['Python'], majors: ['Physics'], citizenship_required: null },
    timing: { deadline: '2027-01-31', deadline_is_estimate: true, is_rolling: true }, application: {}, setting: {}, availability: {},
    attribution: { skills_attribution: 'inferred', majors_attribution: null },
  },
};
describe('saved opportunity uncertainty labels', () => {
  it.each(['en', 'zh'])('keeps uncertainty beside the affected field in %s, without treating absent flags as confirmation', locale => {
    render(<TargetResumeCriteria target={target} locale={locale} />);
    expect(screen.getByText(locale === 'en' ? 'Required skills (inferred)' : '要求的技能（推断）')).toBeVisible();
    expect(screen.getByText(locale === 'en' ? 'Deadline (estimated)' : '截止日期（预计）')).toBeVisible();
    expect(screen.getByText('Python')).toBeVisible();
    expect(screen.getByText(locale === 'en' ? 'No inference flag recorded' : '未记录推断标记')).toBeVisible();
    expect(screen.queryByText(/Majors \(confirmed\)|专业（已确认）/)).toBeNull();
    expect(screen.getByText(locale === 'en' ? 'A rolling flag is recorded without a deadline note. Check the source page.'
      : '只有滚动申请标记，没有日期说明；请以原始页面为准。')).toBeVisible();
  });
});

describe('saved deadline note label', () => {
  const withNote = (attribution: TargetResumeContextV2['criteria']['attribution']): TargetResumeContextV2 => ({
    ...target, criteria: { ...target.criteria, timing: { deadline_note: 'Applications due March 1' }, attribution } });
  it.each(['en', 'zh'])('marks a note the program page does not state as inferred in %s', locale => {
    render(<TargetResumeCriteria target={withNote({ deadline_note_attribution: 'inferred' })} locale={locale} />);
    expect(screen.getByText(locale === 'en' ? 'Deadline note (inferred)' : '截止日期说明（推断）')).toBeVisible();
  });
  it.each(['en', 'zh'])('gives a note saved without the flag a neutral label, not the page\'s wording, in %s', locale => {
    render(<TargetResumeCriteria target={withNote({})} locale={locale} />);
    expect(screen.getByText(locale === 'en' ? 'Deadline note' : '截止日期说明')).toBeVisible();
    expect(screen.queryByText(/原始说明|\(inferred\)|（推断）/)).toBeNull();
  });
});

describe('saved research source labels', () => {
  it.each(['en', 'zh'])('shows attributed complete title/abstract and original link in %s', locale => {
    const value = structuredClone(golden.draft.target_snapshot) as TargetResumeContextV3;
    render(<TargetResumeCriteria target={value} locale={locale} />);
    expect(screen.getByTestId('saved-target-research')).toBeVisible();
    expect(screen.getByRole('link', { name: '机器人😀研究' })).toHaveAttribute('href', 'https://doi.org/10.1234/robot');
    expect(screen.getByText(locale === 'en' ? 'Abstract' : '摘要')).toBeVisible();
    expect(screen.getByText(/We study Python sensors/)).toHaveTextContent('研究😀证据完整保留。');
    expect(screen.getByText(locale === 'en' ? /checked author attribution/ : /核对作者归属/)).toBeVisible();
  });
  it('keeps stale source readable with an explicit AI exclusion', () => {
    const value = structuredClone(golden.draft.target_snapshot) as TargetResumeContextV3;
    value.research.status = 'stale'; render(<TargetResumeCriteria target={value} locale="en" />);
    expect(screen.getByText(/AI does not use these papers/)).toBeVisible();
    expect(screen.getByRole('link', { name: '机器人😀研究' })).toBeVisible();
  });
});

describe('saved location and compensation labels', () => {
  const withSetting = (attribution: TargetResumeContextV2['criteria']['attribution']): TargetResumeContextV2 => ({
    ...target, criteria: { ...target.criteria, setting: { location: 'Champaign, IL', compensation_details: '$500' }, attribution } });
  it.each(['en', 'zh'])('marks inferred compensation and location in %s', locale => {
    render(<TargetResumeCriteria target={withSetting({ location_attribution: 'inferred', compensation_attribution: 'inferred' })} locale={locale} />);
    expect(screen.getByText(locale === 'en' ? 'Location (inferred)' : '地点（推断）')).toBeVisible();
    expect(screen.getByText(locale === 'en' ? 'Compensation details (inferred)' : '报酬说明（推断）')).toBeVisible();
  });
  it.each(['en', 'zh'])('says a host school\'s city is the school\'s, not where the work is, in %s', locale => {
    render(<TargetResumeCriteria target={withSetting({ location_attribution: 'institution' })} locale={locale} />);
    expect(screen.getByText(locale === 'en' ? 'Location (host school’s city)' : '地点（所在学校的城市）')).toBeVisible();
    expect(screen.getByText(locale === 'en' ? 'Host school’s city' : '所在学校的城市')).toBeVisible();
    expect(screen.getByText(locale === 'en' ? 'Compensation details' : '报酬说明')).toBeVisible();
  });
});
