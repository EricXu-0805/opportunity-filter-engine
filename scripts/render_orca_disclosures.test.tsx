import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { cleanup, render } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import EmailTargetConditionsPanel from './EmailTargetConditionsPanel';
import type { EmailTargetConditions } from '@/lib/email-target-conditions';

// Only the locale input and synthetic public receipt vary. The tested frontend
// owns the entire disclosure, from its DOM through the collapsed contents.
let locale: 'en' | 'zh' = 'en';
vi.mock('@/i18n/client', () => ({ useT: () => ({ locale }) }));

const receipt: EmailTargetConditions = { version: 1, record_kind: 'listing', template_request: null, conditions: [
  { field: 'eligibility.min_gpa', category: 'eligibility', status: 'stated', value: 3, usage: 'usable', reason: 'source_stated', sources: [{ quote: '3.0 GPA', source_url: 'https://example.org/program', checked_at: '2026-11-26T00:00:00Z' }] },
  { field: 'deadline', category: 'deadline', status: 'stale', value: '2025-12-01', usage: 'ask_only', reason: 'source_stale', sources: [] },
] };

it('exports four initially collapsed disclosure panels from this application commit', () => {
  for (const lang of ['en', 'zh'] as const) {
    locale = lang;
    for (const data of [null, receipt]) {
      const { container } = render(<EmailTargetConditionsPanel receipt={data} current />);
      const panel = container.querySelector('section');
      expect(panel?.querySelector('details')).not.toHaveAttribute('open');
      if (!panel) throw new Error('Disclosure panel missing');
      const variant = data ? 'sourced' : 'unreviewed';
      writeFileSync(join(process.env.OFE_RENDERED_PANEL_DIR!, lang + '-' + variant + '.html'), panel.outerHTML);
      cleanup();
    }
  }
});
