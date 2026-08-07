import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import type { ProfileData } from '@/lib/types';

vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key }) }));
vi.mock('@/lib/pdf-parser', () => ({ parseResumePDF: vi.fn() }));

import { DocumentsCard } from './DocumentsCard';

const profile = { resume_text: 'the text of my resume', skills: [] } as unknown as ProfileData;
const t = ((key: string) => key) as never;

describe('DocumentsCard — the remove button reaches the profile', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('clicking Remove on the real uploader calls the parent\'s removal handler', async () => {
    const onResumeRemoved = vi.fn();
    render(
      <DocumentsCard
        profile={profile}
        onResumeParsed={vi.fn()}
        onResumeRemoved={onResumeRemoved}
        t={t}
      />,
    );
    // next/dynamic({ssr:false}) resolves the real uploader asynchronously.
    await waitFor(() => expect(screen.getByLabelText('resume.removeAria')).toBeTruthy());

    fireEvent.click(screen.getByLabelText('resume.removeAria'));

    expect(onResumeRemoved).toHaveBeenCalledTimes(1);
  });

  it('links to the privacy policy from the note about what removal does', async () => {
    render(
      <DocumentsCard
        profile={profile}
        onResumeParsed={vi.fn()}
        onResumeRemoved={vi.fn()}
        t={t}
      />,
    );
    await waitFor(() => expect(screen.getByText('resume.privacyLink')).toBeTruthy());
    expect(screen.getByText('resume.privacyLink').getAttribute('href')).toBe('/privacy');
  });
});
