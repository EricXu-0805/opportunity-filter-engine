import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

vi.mock('@/i18n/client', () => {
  /* The real useT memoizes `t` via useCallback so it is stable across
     renders. ColdEmailModal's fetchVariants useCallback depends on `t`;
     returning a new function on every useT() call would re-fire the
     mount effect on every render and loop the test forever. */
  const stableT = (key: string, vars?: Record<string, string | number>) => {
    if (!vars) return key;
    const parts = Object.entries(vars).map(([, v]) => String(v));
    return parts.length > 0 ? `${key}:${parts.join('|')}` : key;
  };
  const stableSetLocale = () => {};
  return {
    useT: () => ({ t: stableT, locale: 'en' as const, setLocale: stableSetLocale }),
  };
});

const mockGetVariants = vi.fn();
const mockGenerateColdEmail = vi.fn();
const mockRefineEmail = vi.fn();
vi.mock('@/lib/api', () => ({
  getEmailVariants: (...args: unknown[]) => mockGetVariants(...args),
  generateColdEmail: (...args: unknown[]) => mockGenerateColdEmail(...args),
  refineEmail: (...args: unknown[]) => mockRefineEmail(...args),
}));

import ColdEmailModal from './ColdEmailModal';
import type { ProfileData, EmailVariant, LabType } from '@/lib/types';

function makeProfile(overrides: Partial<ProfileData> = {}): ProfileData {
  return {
    institution: 'UIUC',
    college: 'Grainger',
    major: 'CS',
    grade: 'Sophomore',
    is_international: false,
    research_interests: 'machine learning',
    skills: [],
    coursework: ['CS 225', 'CS 374'],
    ...overrides,
  };
}

function makeVariant(overrides: Partial<EmailVariant> = {}): EmailVariant {
  return {
    id: 'v1',
    label: 'Template A',
    subject: 'Interested in research with you',
    body: 'Dear Professor,\n\nI am very interested in your work.\nI would love the chance to contribute.\nI am a fast learner.\n\nBest regards,\nAlex',
    recipient_email: 'prof@illinois.edu',
    mailto_link: 'mailto:prof@illinois.edu',
    ...overrides,
  };
}

const writeTextMock = vi.fn().mockResolvedValue(undefined);
const windowOpenMock = vi.fn();

beforeEach(() => {
  mockGetVariants.mockReset();
  mockGenerateColdEmail.mockReset();
  mockRefineEmail.mockReset();
  writeTextMock.mockReset().mockResolvedValue(undefined);
  windowOpenMock.mockReset();

  /* jsdom does not implement scrollIntoView; the modal calls it on a chatEnd
     ref every time chatMessages updates, so we stub it to a no-op spy. */
  Element.prototype.scrollIntoView = vi.fn();

  /* navigator.clipboard is not present in jsdom by default. The copy button
     calls navigator.clipboard.writeText, so we assign a stub here and assert
     against it. */
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: writeTextMock },
    configurable: true,
    writable: true,
  });

  vi.stubGlobal('open', windowOpenMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ColdEmailModal', () => {
  describe('lifecycle', () => {
    it('renders nothing when isOpen=false', () => {
      const { container } = render(
        <ColdEmailModal
          isOpen={false}
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp-1"
          opportunityTitle="REU at UIUC"
        />,
      );
      expect(container.firstChild).toBeNull();
      expect(mockGetVariants).not.toHaveBeenCalled();
    });

    it('fetches variants on open with profile + opportunityId', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      const profile = makeProfile();
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={profile}
          opportunityId="opp-42"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(mockGetVariants).toHaveBeenCalledTimes(1));
      expect(mockGetVariants).toHaveBeenCalledWith(profile, 'opp-42');
    });

    it('shows a loading spinner before variants resolve', () => {
      mockGetVariants.mockReturnValue(new Promise(() => {}));
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp-1"
          opportunityTitle="REU"
        />,
      );
      expect(screen.getByText('coldEmail.generating')).toBeInTheDocument();
    });
  });

  describe('variant rendering', () => {
    it('populates subject + body + recipient from the first variant', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant({ subject: 'SUBJ', body: 'BODY', recipient_email: 'r@x.edu' })],
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue('SUBJ')).toBeInTheDocument());
      expect(screen.getByDisplayValue('BODY')).toBeInTheDocument();
      expect(screen.getByDisplayValue('r@x.edu')).toBeInTheDocument();
    });

    it('renders one tab per variant + an AI pill', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [
          makeVariant({ id: 'a', label: 'Formal' }),
          makeVariant({ id: 'b', label: 'Casual' }),
          makeVariant({ id: 'c', label: 'Quirky' }),
        ],
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByText('Formal')).toBeInTheDocument());
      expect(screen.getByText('Casual')).toBeInTheDocument();
      expect(screen.getByText('Quirky')).toBeInTheDocument();
      expect(screen.getByText('coldEmail.aiVariantLabel')).toBeInTheDocument();
    });

    it('switches subject + body when a different variant tab is clicked', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [
          makeVariant({ id: 'a', label: 'Formal', subject: 'SUBJ-A', body: 'BODY-A' }),
          makeVariant({ id: 'b', label: 'Casual', subject: 'SUBJ-B', body: 'BODY-B' }),
        ],
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue('SUBJ-A')).toBeInTheDocument());
      fireEvent.click(screen.getByText('Casual'));
      expect(screen.getByDisplayValue('SUBJ-B')).toBeInTheDocument();
      expect(screen.getByDisplayValue('BODY-B')).toBeInTheDocument();
    });
  });

  describe('close triggers', () => {
    it('calls onClose when the close button is clicked', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      const onClose = vi.fn();
      render(
        <ColdEmailModal
          isOpen
          onClose={onClose}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument());
      fireEvent.click(screen.getByLabelText('coldEmail.closeAria'));
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('calls onClose when the backdrop is clicked', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      const onClose = vi.fn();
      const { container } = render(
        <ColdEmailModal
          isOpen
          onClose={onClose}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument());
      const backdrop = container.querySelector('div[aria-hidden="true"].bg-gray-900\\/60');
      expect(backdrop).not.toBeNull();
      fireEvent.click(backdrop!);
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('calls onClose when Escape is pressed', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      const onClose = vi.fn();
      render(
        <ColdEmailModal
          isOpen
          onClose={onClose}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument());
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('exposes role=dialog with aria-modal and a labelled title', () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      const dialog = screen.getByRole('dialog');
      expect(dialog).toHaveAttribute('aria-modal', 'true');
      expect(dialog).toHaveAttribute('aria-labelledby', 'email-modal-title');
      expect(document.getElementById('email-modal-title')).not.toBeNull();
    });
  });

  describe('copy + mailto', () => {
    it('copies "Subject: …\\n\\nbody" to the clipboard on click', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant({ subject: 'Hello', body: 'Body text' })],
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue('Hello')).toBeInTheDocument());
      fireEvent.click(screen.getByText('coldEmail.copy'));
      await waitFor(() => expect(writeTextMock).toHaveBeenCalledTimes(1));
      expect(writeTextMock).toHaveBeenCalledWith('Subject: Hello\n\nBody text');
    });

    it('renders Gmail + Outlook deep-link buttons that open in a new window', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant({ subject: 'Hi', body: 'Hey', recipient_email: 'p@x.edu' })],
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue('Hi')).toBeInTheDocument());
      fireEvent.click(screen.getByText('coldEmail.gmail'));
      expect(windowOpenMock).toHaveBeenCalledTimes(1);
      const url = windowOpenMock.mock.calls[0][0] as string;
      expect(url).toContain('mail.google.com');
      expect(url).toContain('to=p@x.edu');
    });
  });

  describe('AI pill', () => {
    it('calls generateColdEmail with engine="ai" when the AI pill is clicked', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      mockGenerateColdEmail.mockResolvedValue({
        subject: 'AI Subject',
        body: 'AI Body',
        recipient_email: 'p@x.edu',
        mailto_link: 'mailto:p@x.edu',
        method: 'ai',
      });
      const profile = makeProfile();
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={profile}
          opportunityId="opp-7"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument());
      fireEvent.click(screen.getByText('coldEmail.aiVariantLabel'));
      await waitFor(() => expect(mockGenerateColdEmail).toHaveBeenCalledTimes(1));
      expect(mockGenerateColdEmail).toHaveBeenCalledWith(profile, 'opp-7', { engine: 'ai' });
    });

    it('R72-A: shows the fabrication fallback hint when the AI draft is rejected', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      mockGenerateColdEmail.mockResolvedValue({
        subject: 'Template Subject',
        body: 'Template Body',
        recipient_email: 'p@x.edu',
        mailto_link: 'mailto:p@x.edu',
        method: 'template',
        fallback_reason: 'fabrication',
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp-fab"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument());
      fireEvent.click(screen.getByText('coldEmail.aiVariantLabel'));
      await waitFor(() =>
        expect(screen.getByText('coldEmail.aiFallbackFabrication')).toBeInTheDocument(),
      );
    });

    it('clicking the AI pill again switches to the cached AI variant without re-fetching', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      mockGenerateColdEmail.mockResolvedValue({
        subject: 'AI Subject',
        body: 'AI Body',
        recipient_email: 'p@x.edu',
        mailto_link: 'mailto:p@x.edu',
        method: 'ai',
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument());
      const pill = screen.getByText('coldEmail.aiVariantLabel');
      fireEvent.click(pill);
      await waitFor(() => expect(screen.getByDisplayValue('AI Subject')).toBeInTheDocument());
      fireEvent.click(screen.getByText('Template A'));
      fireEvent.click(pill);
      expect(mockGenerateColdEmail).toHaveBeenCalledTimes(1);
      expect(screen.getByDisplayValue('AI Subject')).toBeInTheDocument();
    });

    it('FE-5: shows a durable "template, not AI" badge when the AI pill falls back', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      mockGenerateColdEmail.mockResolvedValue({
        subject: 'T', body: 'Template Body', recipient_email: 'p@x.edu',
        mailto_link: 'mailto:p@x.edu', method: 'template', fallback_reason: 'not_configured',
      });
      render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp" opportunityTitle="REU" />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument());
      fireEvent.click(screen.getByText('coldEmail.aiVariantLabel'));
      await waitFor(() =>
        expect(screen.getByText('coldEmail.templateFallbackBadge')).toBeInTheDocument(),
      );
    });

    it('FE-5: shows no template badge when the AI draft is genuine', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      mockGenerateColdEmail.mockResolvedValue({
        subject: 'AI', body: 'AI Body', recipient_email: 'p@x.edu',
        mailto_link: 'mailto:p@x.edu', method: 'ai',
      });
      render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp" opportunityTitle="REU" />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument());
      fireEvent.click(screen.getByText('coldEmail.aiVariantLabel'));
      await waitFor(() => expect(screen.getByDisplayValue('AI Body')).toBeInTheDocument());
      expect(screen.queryByText('coldEmail.templateFallbackBadge')).toBeNull();
    });
  });

  describe('send buttons (FE-2)', () => {
    it('disables the deep-link send buttons when no recipient is resolved', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant({ recipient_email: '' })] });
      render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp" opportunityTitle="REU" />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument());
      expect(screen.getByText('coldEmail.openInEmail').closest('button')).toBeDisabled();
      expect(screen.getByText('coldEmail.gmail').closest('button')).toBeDisabled();
      // The copy button stays usable — pasting elsewhere is still helpful.
      expect(screen.getByText('coldEmail.copy').closest('button')).not.toBeDisabled();
    });

    it('enables the send buttons once a recipient is present', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant({ recipient_email: 'prof@illinois.edu' })] });
      render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp" opportunityTitle="REU" />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument());
      expect(screen.getByText('coldEmail.openInEmail').closest('button')).not.toBeDisabled();
    });
  });

  describe('error handling', () => {
    it('shows the error state + try-again button when the variants fetch fails', async () => {
      mockGetVariants.mockRejectedValue(new Error('boom'));
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByText('coldEmail.tryAgain')).toBeInTheDocument());
      expect(screen.getByText('boom')).toBeInTheDocument();
    });

    it('try-again button retriggers the fetch', async () => {
      mockGetVariants
        .mockRejectedValueOnce(new Error('first failure'))
        .mockResolvedValueOnce({ variants: [makeVariant({ subject: 'OK' })] });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByText('coldEmail.tryAgain')).toBeInTheDocument());
      fireEvent.click(screen.getByText('coldEmail.tryAgain'));
      await waitFor(() => expect(screen.getByDisplayValue('OK')).toBeInTheDocument());
      expect(mockGetVariants).toHaveBeenCalledTimes(2);
    });
  });

  describe('quick actions (local body transforms)', () => {
    it('"formal" replaces "I would love" with "I would greatly appreciate"', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant({ body: 'I would love to chat.\n\nBest regards,\nAlex' })],
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/I would love/)).toBeInTheDocument());
      fireEvent.click(screen.getByText('coldEmail.quickActions.formal'));
      await waitFor(() =>
        expect(screen.getByDisplayValue(/I would greatly appreciate to chat/)).toBeInTheDocument(),
      );
    });

    it('"shorter" drops "fast learner" / "always eager" lines', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [
          makeVariant({
            body:
              'Line one.\nI am a fast learner and want to help.\nLine three.\nI am always eager to learn.\nLine five.',
          }),
        ],
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Line one/)).toBeInTheDocument());
      fireEvent.click(screen.getByText('coldEmail.quickActions.shorter'));
      const textarea = screen.getByDisplayValue(/Line one/) as HTMLTextAreaElement;
      expect(textarea.value).not.toMatch(/fast learner/);
      expect(textarea.value).not.toMatch(/always eager/);
      expect(textarea.value).toMatch(/Line one/);
      expect(textarea.value).toMatch(/Line five/);
    });

    it('"coursework" inserts the profile\'s coursework when present', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant({ body: 'Intro.\n\nBest regards,\nAlex' })],
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile({ coursework: ['CS 225', 'CS 374'] })}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Intro/)).toBeInTheDocument());
      fireEvent.click(screen.getByText('coldEmail.quickActions.coursework'));
      await waitFor(() => expect(screen.getByDisplayValue(/CS 225/)).toBeInTheDocument());
      expect(screen.getByDisplayValue(/CS 374/)).toBeInTheDocument();
    });

    it('"coursework" with an empty coursework list does not insert anything', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant({ body: 'Just an intro.\n\nBest,\nAlex' })],
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile({ coursework: [] })}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Just an intro/)).toBeInTheDocument());
      const before = (screen.getByDisplayValue(/Just an intro/) as HTMLTextAreaElement).value;
      fireEvent.click(screen.getByText('coldEmail.quickActions.coursework'));
      const after = (screen.getByDisplayValue(/Just an intro/) as HTMLTextAreaElement).value;
      expect(after).toBe(before);
    });
  });

  describe('refine chat', () => {
    it('submitting the chat input calls refineEmail with body + instruction', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant({ body: 'Original body.' })],
      });
      mockRefineEmail.mockResolvedValue({ body: 'Refined body.', method: 'llm' });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue('Original body.')).toBeInTheDocument());
      const input = screen.getByPlaceholderText('coldEmail.refinePlaceholder');
      fireEvent.change(input, { target: { value: 'Make it warmer' } });
      // Submit via form to trigger the onSubmit handler (jsdom does not auto-fire
      // form submit from a button click on type="submit" inside a form).
      const form = input.closest('form');
      expect(form).not.toBeNull();
      await act(async () => {
        fireEvent.submit(form!);
      });
      await waitFor(() => expect(mockRefineEmail).toHaveBeenCalledTimes(1));
      expect(mockRefineEmail).toHaveBeenCalledWith(
        'Original body.',
        'Make it warmer',
        makeProfile(),
        'opp',
      );
      await waitFor(() => expect(screen.getByDisplayValue('Refined body.')).toBeInTheDocument());
    });

    it('R72-A: shows the fabrication hint when a refine edit is rejected', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant({ body: 'Original body.' })],
      });
      mockRefineEmail.mockResolvedValue({
        body: 'Original body.',
        method: 'local',
        fallback_reason: 'fabrication',
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue('Original body.')).toBeInTheDocument());
      const input = screen.getByPlaceholderText('coldEmail.refinePlaceholder');
      fireEvent.change(input, { target: { value: 'say I know Rust' } });
      const form = input.closest('form');
      await act(async () => {
        fireEvent.submit(form!);
      });
      await waitFor(() =>
        expect(screen.getByText('coldEmail.refineFabrication')).toBeInTheDocument(),
      );
    });
  });

  describe('R32: lab-type badge + tips panel', () => {
    it('renders LabTypeBadge when the response has a top-level lab_type', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant()],
        lab_type: 'wet' as LabType,
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByText('coldEmail.labType.wet')).toBeInTheDocument());
    });

    it('falls back to the first variant.lab_type when the top-level field is absent', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant({ lab_type: 'dry' as LabType })],
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByText('coldEmail.labType.dry')).toBeInTheDocument());
    });

    it('renders EmailTipsPanel headings whenever labType is set', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant()],
        lab_type: 'humanities' as LabType,
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() =>
        expect(screen.getByText('coldEmail.tips.skillsHeading')).toBeInTheDocument(),
      );
      expect(screen.getByText('coldEmail.tips.mistakesHeading')).toBeInTheDocument();
    });

    it('omits the badge and tips panel when lab_type is null/absent', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument());
      expect(screen.queryByText('coldEmail.labType.wet')).toBeNull();
      expect(screen.queryByText('coldEmail.labType.dry')).toBeNull();
      expect(screen.queryByText('coldEmail.labType.humanities')).toBeNull();
      expect(screen.queryByText('coldEmail.tips.skillsHeading')).toBeNull();
    });
  });
});
