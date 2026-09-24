import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen, waitFor, fireEvent } from '@testing-library/react';
import type { ProfileData, ResumeParseResponse } from '@/lib/types';

vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key }) }));
vi.mock('@/lib/pdf-parser', () => ({ parseResumePDF: vi.fn() }));

import { DocumentsCard } from './DocumentsCard';
import { parseResumePDF } from '@/lib/pdf-parser';

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


describe('DocumentsCard — wait for the current profile snapshot', () => {
  beforeEach(() => vi.mocked(parseResumePDF).mockReset());

  it('does not mount file or removal controls while the profile is not ready', () => {
    const onResumeParsed = vi.fn();
    const onResumeRemoved = vi.fn();
    const view = render(<DocumentsCard profile={profile} ready={false}
      onResumeParsed={onResumeParsed} onResumeRemoved={onResumeRemoved} t={t} />);
    expect(screen.getByRole('status')).toHaveTextContent('home.actions.profileLoading');
    expect(document.querySelector('input[type="file"]')).toBeNull();
    expect(screen.queryByLabelText('resume.removeAria')).toBeNull();
    fireEvent.drop(view.container, { dataTransfer: { files: [new File(['pdf'], 'resume.pdf', { type: 'application/pdf' })] } });
    expect(parseResumePDF).not.toHaveBeenCalled();
    expect(onResumeParsed).not.toHaveBeenCalled();
    expect(onResumeRemoved).not.toHaveBeenCalled();
  });

  it('enables controls only after readiness and shows the loaded cloud resume', async () => {
    const props = { profile, onResumeParsed: vi.fn(), onResumeRemoved: vi.fn(), t };
    const view = render(<DocumentsCard {...props} ready={false} />);
    view.rerender(<DocumentsCard {...props} ready />);
    await screen.findByLabelText('resume.removeAria');
    expect(screen.getByText('resume.savedFallback')).toBeInTheDocument();
    expect(screen.queryByText('home.actions.profileLoading')).toBeNull();
    expect(props.onResumeRemoved).not.toHaveBeenCalled();
  });

  it('retires an in-flight parse when readiness is lost, before a new owner snapshot is loaded', async () => {
    let finish!: (value: ResumeParseResponse) => void;
    vi.mocked(parseResumePDF).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const props = { profile, onResumeParsed: vi.fn(), onResumeRemoved: vi.fn(), t };
    const view = render(<DocumentsCard {...props} ready />);
    await screen.findByLabelText('resume.removeAria');
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(['pdf'], 'old-owner.pdf', { type: 'application/pdf' })] } });
    await waitFor(() => expect(parseResumePDF).toHaveBeenCalledTimes(1));
    view.rerender(<DocumentsCard {...props} ready={false} />);
    expect(document.querySelector('input[type="file"]')).toBeNull();
    await act(async () => { finish({ success: true, raw_text: 'Old owner text' } as ResumeParseResponse); });
    expect(props.onResumeParsed).not.toHaveBeenCalled();
    view.rerender(<DocumentsCard {...props} profile={{ ...profile, resume_text: 'New owner cloud source' }} ready />);
    await screen.findByText('resume.savedFallback');
    expect(screen.queryByText('old-owner.pdf')).toBeNull();
    expect(props.onResumeRemoved).not.toHaveBeenCalled();
  });

  it('preserves the real uploader badge when the parent explicitly refuses removal', async () => {
    const onResumeRemoved = vi.fn(() => false);
    render(<DocumentsCard profile={profile} onResumeParsed={vi.fn()} onResumeRemoved={onResumeRemoved} t={t} />);
    await screen.findByLabelText('resume.removeAria');
    fireEvent.click(screen.getByLabelText('resume.removeAria'));
    expect(onResumeRemoved).toHaveBeenCalledTimes(1);
    expect(screen.getByText('resume.savedFallback')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('resume.errProfileChanged');
  });
});
