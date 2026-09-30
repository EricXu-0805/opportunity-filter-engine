import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import EmailTargetConditionsPanel from './EmailTargetConditionsPanel';
import type { EmailTargetConditions } from '@/lib/email-target-conditions';
let locale: 'en' | 'zh' = 'en';
vi.mock('@/i18n/client', () => ({ useT: () => ({ locale }) }));
const receipt: EmailTargetConditions = { version: 1, record_kind: 'listing', template_request: null, conditions: [
  { field: 'eligibility.min_gpa', category: 'eligibility', status: 'stated', value: 3.0, usage: 'usable', reason: 'source_stated', sources: [{ quote: 'Applicants need a GPA of at least 3.0; a CV is required.', source_url: 'https://example.edu/apply', checked_at: '2026-09-28T10:30:00Z' }] },
  { field: 'deadline', category: 'deadline', status: 'stale', value: '2025-12-01', usage: 'ask_only', reason: 'source_stale', sources: [] },
] };
beforeEach(() => { locale = 'en'; });
const expand = () => fireEvent.click(screen.getByText(/Target conditions for this draft|本次参考的目标条件/));
describe('email target conditions', () => {
  it('shows complete evidence on demand without claiming eligibility or attachments', () => {
    render(<EmailTargetConditionsPanel receipt={receipt} current />); expand();
    expect(screen.getByText(/not proof that you qualify/)).toBeVisible();
    expect(screen.getByText('Deadline · Source needs a fresh check')).toBeVisible();
    fireEvent.click(screen.getByText('View evidence and sources'));
    expect(screen.getByText(receipt.conditions[0].sources[0].quote)).toBeVisible();
    expect(screen.getByRole('link', { name: 'View source' })).toHaveAttribute('href', 'https://example.edu/apply');
    expect(screen.getByText('Source checked: 2026-09-28')).toBeVisible();
  });
  it('hides a previous receipt when current source checks are missing', () => {
    render(<EmailTargetConditionsPanel receipt={receipt} current={false} />); expand();
    expect(screen.queryByText('2025-12-01')).toBeNull(); expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByText(/has not been checked/)).toBeVisible();
  });
  it('does not invent a checklist for a faculty record with no conditions', () => {
    locale = 'zh'; render(<EmailTargetConditionsPanel receipt={{ version: 1, record_kind: 'faculty_contact', conditions: [], template_request: null }} current />); expand();
    expect(screen.getByText(/不代表没有要求/)).toBeVisible(); expect(screen.queryByRole('list')).toBeNull();
  });
  it('keeps a long source and literal markup as text', () => {
    const long = structuredClone(receipt); long.conditions[0].sources[0].quote = '<script>bad()</script> ' + '完整材料 '.repeat(700) + '最后一句';
    render(<EmailTargetConditionsPanel receipt={long} current />); expand(); fireEvent.click(screen.getByText('View evidence and sources'));
    expect(screen.getByText(long.conditions[0].sources[0].quote)).toBeVisible(); expect(document.querySelector('script')).toBeNull();
  });
  it.each(['en', 'zh'] as const)('localizes known materials and years in %s, preserving free source text', selectedLocale => {
    locale = selectedLocale;
    const localized = structuredClone(receipt); const base = localized.conditions[0];
    localized.conditions = [
      { ...base, field: 'application.requires_resume', category: 'materials', value: 'yes' },
      { ...base, field: 'application.requires_transcript', category: 'materials', value: 'no' },
      { ...base, field: 'application.requires_recommendation', category: 'materials', status: 'unknown', usage: 'ask_only', reason: 'no_source_evidence', value: 'unknown', sources: [] },
      { ...base, field: 'eligibility.preferred_year', value: ['freshman', 'senior', 'Special visiting year'] },
      { ...base, field: 'eligibility.citizenship_required', value: 'yes' },
    ];
    localized.conditions[0].sources = [{ ...base.sources[0], heading: 'Required documents', quote: 'yes; freshman applicants' }];
    render(<EmailTargetConditionsPanel receipt={localized} current />); expand();
    expect(screen.getByText(locale === 'zh' ? '需要' : 'Required', { exact: true })).toBeVisible();
    expect(screen.getByText(locale === 'zh' ? '不需要' : 'Not required', { exact: true })).toBeVisible();
    expect(screen.getByText(locale === 'zh' ? '尚不明确' : 'Not established', { exact: true })).toBeVisible();
    expect(screen.getByText(locale === 'zh' ? '大一 · 大四 · Special visiting year' : 'Freshman · Senior · Special visiting year')).toBeVisible();
    expect(screen.getByText('yes', { exact: true })).toBeVisible();
    fireEvent.click(screen.getAllByText(/View evidence and sources|查看依据与来源/)[0]);
    expect(screen.getByText('Required documents')).toBeVisible(); expect(screen.getByText('yes; freshman applicants')).toBeVisible();
  });

});
