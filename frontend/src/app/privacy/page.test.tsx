import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { MATERIAL_MAX_BYTES } from '@/lib/material-core';
import { MAX_RESUME_TEXT_CHARACTERS } from '@/lib/resume-input';
import PrivacyPage from './page';

// The course list's release switch, as this branch ships it unless a test
// turns it off.
const release = vi.hoisted(() => ({ courseStatus: true }));
vi.mock('@/lib/release-scope', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/release-scope')>();
  return { ...actual, RELEASE_SCOPE: { ...actual.RELEASE_SCOPE, get courseStatus() { return release.courseStatus; } } };
});

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
  // one. A status a résumé label gives is only a suggestion on the form: never
  // stored or sent. Removing the résumé keeps only the courses the student
  // marked or added; an older app's removal hides the rest until the next
  // change here deletes them.
  it('says what is stored of each course, that a résumé status is only a suggestion, and what removing the résumé keeps', () => {
    const { container } = render(<PrivacyPage />);
    const text = container.textContent ?? '';
    expect(text).toContain('courses (for each one its name, whether it came from your résumé or you added it, and the status you set: completed, in progress, planned or not marked)');
    expect(text).toContain('Of each course found on the résumé we store its name; the line it was found on is not stored, and the form shows it from the stored résumé text.');
    expect(text).toContain('Where a line of the résumé, or a column on it, starts with a label that gives a status, such as “Current courses:” or “Planned courses:”, the form suggests that status (in progress or planned) for the courses listed after it, for you to confirm or change.');
    expect(text).toContain('A suggestion is read from the résumé text each time and is never stored or sent: until you confirm it or choose a status, the course is not marked, in matching and in generated text alike.');
    expect(text).toContain('together with the courses it found that you have not marked yourself; courses you marked or added yourself stay.');
    expect(text).toContain('If an older version of the app removes or replaces the résumé, the courses that résumé found and you had not marked are no longer shown or used, and are deleted from your profile the next time you change your courses or your résumé here.');
    expect(text).not.toContain('is shown and used as in progress or planned');
    expect(text).not.toContain('store the résumé line');
  });

  // With the course list switched off, nothing deletes a course the résumé
  // found or stores a status here, so the policy says what it said before
  // the course list (review p2-b, M1).
  it('says what it said before the course list while the switch is off', async () => {
    release.courseStatus = false;
    vi.resetModules();
    try {
      const { default: OffPage } = await import('./page');
      const { container } = render(<OffPage />);
      const text = container.textContent ?? '';
      expect(text).toContain('Effective date: October 12, 2026');
      expect(text).toContain('research interests, skills and proficiency levels, coursework, experience level.');
      expect(text).toContain('to pre-fill skills, coursework, and interests.');
      expect(text).toContain(`characters of extracted résumé text as part of your profile. The original PDF file is not stored on our servers. Removing the résumé from your profile clears that text and the coursework it extracted from your current profile, and future matching and generation stop using them. It does not change copies saved elsewhere`);
      expect(text).toContain('skills, coursework, research interests, your own résumé bullet points');
      for (const course of ['not marked yourself', 'the next time you change your courses', 'Of each course found', 'suggests that status', 'courses and their statuses']) {
        expect(text).not.toContain(course);
      }
    } finally {
      release.courseStatus = true;
      vi.resetModules();
    }
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
