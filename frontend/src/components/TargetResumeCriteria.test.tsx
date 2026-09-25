import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TargetResumeContextV2 } from '@/lib/target-resume';
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
