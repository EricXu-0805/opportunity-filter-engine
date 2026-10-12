import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { MATERIAL_MAX_BYTES } from '@/lib/material-core';
import { MAX_RESUME_TEXT_CHARACTERS } from '@/lib/resume-input';
import PrivacyPage from './page';

describe('Privacy page', () => {
  // The page said "up to ~8,000 characters" of résumé text for weeks after
  // #975 raised the stored limit to 60,000, and it never mentioned the PDF
  // archive that went live on 2026-09-30.
  it('states the résumé text limit the code enforces', () => {
    const { container } = render(<PrivacyPage />);
    const text = container.textContent ?? '';
    expect(text).toContain(`up to ${MAX_RESUME_TEXT_CHARACTERS.toLocaleString('en-US')} characters of extracted résumé text`);
    expect(text).not.toContain('8,000');
  });

  it('discloses the application and email PDF archive, its limit and how to remove it', () => {
    const { container } = render(<PrivacyPage />);
    const text = container.textContent ?? '';
    expect(text).toContain('PDFs you submitted or attached');
    expect(text).toContain(`up to ${MATERIAL_MAX_BYTES / 1_000_000} MB`);
    expect(text).toContain('until you delete the file or your account is deleted');
    expect(text).toContain('Target résumés');
    expect(text).toContain('Imports saved to your account');
  });
});
