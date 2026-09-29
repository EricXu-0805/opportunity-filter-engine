import { describe, it, expect } from 'vitest';
import { isEmailTargetConditions, readEmailTargetConditions, isEmailConditionIssues, type EmailTargetConditions } from './email-target-conditions';
export const conditions: EmailTargetConditions = { version: 1, record_kind: 'listing', template_request: null, conditions: [
  { field: 'eligibility.min_gpa', category: 'eligibility', status: 'stated', value: 0, usage: 'usable', reason: 'source_stated', sources: [
    { quote: 'Minimum GPA: 0. Required documents: CV.', source_url: 'https://example.edu/program', checked_at: '2026-09-28T09:00:00Z' },
  ] },
] };
describe('target-condition receipt contract', () => {
  it('preserves numeric zero, boolean false, Unicode and complete long text', () => {
    expect(isEmailTargetConditions(conditions)).toBe(true);
    for (const value of [false, '🧪'.repeat(20000), ['Python', '最后技能'], null]) {
      const receipt = structuredClone(conditions); receipt.conditions[0].value = value;
      expect(readEmailTargetConditions({ target_conditions: receipt })).toEqual(receipt);
    }
  });
  it('treats an old missing receipt as unavailable and rejects an invalid present one', () => {
    expect(readEmailTargetConditions({})).toBeNull(); expect(() => readEmailTargetConditions({ target_conditions: null })).toThrow();
  });
  it.each(['inferred', 'policy', 'unknown', 'stale', 'conflicting', 'unverified'])('does not promote %s to usable', status => {
    const receipt = structuredClone(conditions); Object.assign(receipt.conditions[0], { status });
    expect(isEmailTargetConditions(receipt)).toBe(false);
    receipt.conditions[0].usage = 'ask_only'; expect(isEmailTargetConditions(receipt)).toBe(true);
  });
  it.each(['field', 'duplicate', 'category', 'source', 'timestamp', 'size', 'emoji', 'infinity'])('rejects malformed %s instead of truncating', fault => {
    const receipt = structuredClone(conditions); const row = receipt.conditions[0];
    if (fault === 'field') Object.assign(row, { field: 'private_token' });
    if (fault === 'duplicate') receipt.conditions.push(row);
    if (fault === 'category') row.category = 'materials';
    if (fault === 'source') row.sources[0].source_url = 'javascript:alert(1)';
    if (fault === 'timestamp') row.sources[0].checked_at = '2026-09-28';
    if (fault === 'size') row.sources[0].quote = 'x'.repeat(4001);
    if (fault === 'emoji') row.value = '🧪'.repeat(20001);
    if (fault === 'infinity') row.value = Infinity;
    expect(isEmailTargetConditions(receipt)).toBe(false);
  });
  it('accepts a privacy-excluded condition without manufacturing sources', () => {
    const receipt = structuredClone(conditions); Object.assign(receipt.conditions[0], { status: 'unknown', usage: 'excluded', reason: 'source_not_public', value: null, sources: [] });
    expect(isEmailTargetConditions(receipt)).toBe(true);
  });
  it('rejects unknown or repeated issue codes', () => {
    expect(isEmailConditionIssues(['unsupported_attachment_claim'])).toBe(true);
    expect(isEmailConditionIssues(['private response text'])).toBe(false);
    expect(isEmailConditionIssues(['empty_draft', 'empty_draft'])).toBe(false);
  });
  it.each(['record_kind', 'status', 'usage', 'reason'])('rejects array-coerced %s enums', field => {
    const receipt = structuredClone(conditions);
    if (field === 'record_kind') Object.assign(receipt, { record_kind: ['listing'] });
    else {
      const row = receipt.conditions[0];
      Object.assign(row, { [field]: [row[field as 'status' | 'usage' | 'reason']] });
      if (field === 'usage') row.sources = [];
    }
    expect(isEmailTargetConditions(receipt)).toBe(false);
    expect(() => readEmailTargetConditions({ target_conditions: receipt })).toThrow();
  });

});
