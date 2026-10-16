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

  // Checklist M13: a course is stored with a status only once the student sets
  // one; its résumé line and any status read from the résumé are not stored,
  // and removing the résumé keeps only the courses the student marked or added.
  it('says what is stored of each course, what is read from the résumé instead, and what removing the résumé keeps', () => {
    const { container } = render(<PrivacyPage />);
    const text = container.textContent ?? '';
    expect(text).toContain('courses (for each one its name, whether it came from your résumé or you added it, and the status you set: completed, in progress, planned or not marked)');
    expect(text).toContain('Of each course found on the résumé we store its name; the line it was found on is not stored, and the form shows it from the stored résumé text.');
    expect(text).toContain('A course listed under a résumé label that gives a status, such as “Current courses:” or “Planned courses:”, is shown and used as in progress or planned while that résumé is on your profile, until you confirm or change it; that status is read from the résumé text each time and is not stored.');
    expect(text).toContain('together with the courses it found that you have not marked yourself, so no status read from it remains; courses you marked or added yourself stay');
    expect(text).not.toContain('the coursework it extracted');
    expect(text).not.toContain('store the résumé line');
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

  // Review of the first wording: a guest merged into an account can keep 41
  // versions until the next save, every target résumé version embeds the
  // whole résumé text, and an import's records live on its own records page.
  it('describes target résumé copies, the version cap after sign-in and import records truthfully', () => {
    const { container } = render(<PrivacyPage />);
    const text = container.textContent ?? '';
    const limit = MAX_RESUME_TEXT_CHARACTERS.toLocaleString('en-US');
    expect(text).not.toContain('up to its 20 most recent saved versions');
    expect(text).toContain('We normally keep the 20 most recent versions of each target résumé');
    expect(text).toContain("the guest session's versions are kept as well until the next save of that résumé trims the list back to 20");
    expect(text).toContain(`each saved version hold a full copy of your profile's résumé text (up to ${limit} characters)`);
    expect(text).toContain('every target résumé you saved and each of its saved versions holds a full copy of the résumé text');
    expect(text).toContain('None of these copies can be deleted in the app');
    expect(text).toContain('on its records page: "View records" under "Imports in your account"');
    expect(text).toContain('not the application and email records (with their PDFs) you made for it;');
    expect(text).not.toContain('or target résumés you made for it');
    expect(text).toContain('keep their content until you delete them in the app; an empty entry with its dates then stays until your account is deleted');
    expect(text).toContain('the target résumés and résumé bullet-editor drafts you save');
    expect(text).toContain('target résumés and bullet-editor drafts; imports you save');
    expect(text).toContain('Application and email records, target résumés and bullet-editor drafts are kept until your account is deleted');
  });
});
