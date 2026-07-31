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
const mockGenerateColdEmailStream = vi.fn();
const mockRefineEmail = vi.fn();
vi.mock('@/lib/api', () => ({
  getEmailVariants: (...args: unknown[]) => mockGetVariants(...args),
  generateColdEmail: (...args: unknown[]) => mockGenerateColdEmail(...args),
  generateColdEmailStream: (...args: unknown[]) => mockGenerateColdEmailStream(...args),
  refineEmail: (...args: unknown[]) => mockRefineEmail(...args),
  extractResumeBullets: async () => ({ bullets: [], method: 'heuristic' }),
}));

// W10b: spy the auth modal opener so the sign-in-to-reveal affordance is
// assertable; every other test simply ignores the stub (same shape as the
// context's INERT fallback).
const openAuthModalMock = vi.fn();
vi.mock('@/lib/auth-modal-context', () => ({
  useAuthModal: () => ({
    open: false,
    phase: 'auto',
    reason: null,
    openModal: openAuthModalMock,
    closeModal: () => {},
    setPhase: () => {},
  }),
}));

import ColdEmailModal from './ColdEmailModal';
import type { ProfileData, EmailVariant, LabType } from '@/lib/types';

function makeProfile(overrides: Partial<ProfileData> = {}): ProfileData {
  return {
    // The cold-email flow requires a sender name (backend 422s without one);
    // every test not specifically about that gate uses a named profile.
    name: 'Alex Chen',
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
  // The modal is stream-first with a blocking-route fallback; existing AI
  // tests exercise the fallback path by default (stream "unavailable").
  mockGenerateColdEmailStream.mockReset().mockRejectedValue(new Error('no stream in tests'));
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
  describe('student-name gate', () => {
    it.each([undefined, '', '   '])(
      'blocks generation and points to the profile form when name is %j',
      async (name) => {
        render(
          <ColdEmailModal
            isOpen
            onClose={vi.fn()}
            profile={makeProfile({ name })}
            opportunityId="opp-1"
            opportunityTitle="REU"
          />,
        );
        await waitFor(() => {
          expect(screen.getByTestId('cold-email-name-required')).toBeInTheDocument();
        });
        expect(screen.getByText('coldEmail.nameRequiredTitle')).toBeInTheDocument();
        expect(screen.getByText('coldEmail.nameRequiredBody')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'coldEmail.nameRequiredCta' }))
          .toHaveAttribute('href', '/');
        // Nothing was generated — no variants fetch, no AI pipeline.
        expect(mockGetVariants).not.toHaveBeenCalled();
        expect(mockGenerateColdEmail).not.toHaveBeenCalled();
        expect(mockGenerateColdEmailStream).not.toHaveBeenCalled();
        // No generic error/retry UI for this state.
        expect(screen.queryByText('coldEmail.tryAgain')).not.toBeInTheDocument();
      },
    );

    it('maps a backend student_name_required 422 to the same guidance instead of a generic failure', async () => {
      mockGetVariants.mockRejectedValue(new Error(
        'API 422: {"detail":[{"type":"student_name_required","loc":["body","profile"]}]}',
      ));
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp-1"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => {
        expect(screen.getByTestId('cold-email-name-required')).toBeInTheDocument();
      });
      expect(screen.getByRole('link', { name: 'coldEmail.nameRequiredCta' }))
        .toHaveAttribute('href', '/');
      expect(screen.queryByText(/API 422/)).not.toBeInTheDocument();
    });
  });

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
      expect(url).toContain('to=p%40x.edu');
    });

    it('URL-encodes a user-edited recipient in the Gmail + Outlook deep links', async () => {
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
      const edited = 'p@x.edu?cc=evil@x.com&bcc=e2@x.com';
      fireEvent.change(screen.getByDisplayValue('p@x.edu'), { target: { value: edited } });
      fireEvent.click(screen.getByText('coldEmail.gmail'));
      fireEvent.click(screen.getByText('coldEmail.outlook'));
      const [gmailUrl, outlookUrl] = windowOpenMock.mock.calls.map((c) => c[0] as string);
      for (const url of [gmailUrl, outlookUrl]) {
        expect(url).toContain(`to=${encodeURIComponent(edited)}`);
        // raw ?/&/@ must not leak extra query params into the compose URL
        expect(url).not.toContain('&bcc=');
        expect(url).not.toContain('cc=evil@x.com');
      }
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
      // Stream-first: the (default-rejecting) stream mock was tried before the
      // blocking fallback landed the draft.
      expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1);
      // No recommended_style in this variants mock → seeds the default tone.
      expect(mockGenerateColdEmail).toHaveBeenCalledWith(profile, 'opp-7', { engine: 'ai', style: 'professional' });
    });

    it('uses the stream result when streaming succeeds (no blocking call)', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      mockGenerateColdEmailStream.mockReset().mockImplementation(
        async (
          _profile: unknown,
          _oppId: unknown,
          _opts: unknown,
          onStage?: (s: string) => void,
        ) => {
          onStage?.('drafting');
          onStage?.('revising');
          return {
            subject: 'Streamed Subject',
            body: 'Streamed AI Body',
            recipient_email: 'p@x.edu',
            mailto_link: 'mailto:p@x.edu',
            method: 'ai',
          };
        },
      );
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp-7"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument());
      fireEvent.click(screen.getByText('coldEmail.aiVariantLabel'));
      await waitFor(() =>
        expect(screen.getByDisplayValue('Streamed AI Body')).toBeInTheDocument(),
      );
      expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1);
      expect(mockGenerateColdEmail).not.toHaveBeenCalled();
    });

    it('regenerates the AI draft in the chosen tone when a tone pill is clicked', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()], recommended_style: 'warm' });
      mockGenerateColdEmail.mockResolvedValue({
        subject: 'AI Subject',
        body: 'AI Body',
        recipient_email: 'p@x.edu',
        mailto_link: 'mailto:p@x.edu',
        method: 'ai',
        style: 'lively',
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
      fireEvent.click(screen.getByText('coldEmail.tone.lively'));
      await waitFor(() => expect(mockGenerateColdEmail).toHaveBeenCalledTimes(1));
      expect(mockGenerateColdEmail).toHaveBeenCalledWith(profile, 'opp-7', { engine: 'ai', style: 'lively' });
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

  describe('AI default engine (auto-fire on open)', () => {
    const AI_RESP = {
      subject: 'Auto AI Subject',
      body: 'Auto AI Body',
      recipient_email: 'p@x.edu',
      mailto_link: 'mailto:p@x.edu',
      method: 'ai',
    };

    it('runs the pipeline once on open and switches to the AI draft, no click needed', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      mockGenerateColdEmailStream.mockReset().mockResolvedValue(AI_RESP);
      render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp-auto" opportunityTitle="REU" />,
      );
      await waitFor(() => expect(screen.getByDisplayValue('Auto AI Body')).toBeInTheDocument());
      expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1);
      expect(mockGenerateColdEmail).not.toHaveBeenCalled();
    });

    it('stays silently on the template when the automatic run falls back', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      mockGenerateColdEmail.mockResolvedValue({
        subject: 'T', body: 'Template Body', recipient_email: 'p@x.edu',
        mailto_link: 'mailto:p@x.edu', method: 'template', fallback_reason: 'not_configured',
      });
      render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp-silent" opportunityTitle="REU" />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument());
      // the automatic attempt did run (stream rejected → blocking fallback)…
      await waitFor(() => expect(mockGenerateColdEmail).toHaveBeenCalledTimes(1));
      // …but the user never asked, so nothing is announced or switched.
      expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument();
      expect(screen.queryByText('coldEmail.templateFallbackBadge')).toBeNull();
      expect(screen.queryByText('coldEmail.aiFallbackNotConfigured')).toBeNull();
    });

    it('never clobbers a body the user edited while the pipeline was running', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      let release!: (v: typeof AI_RESP) => void;
      mockGenerateColdEmailStream.mockReset().mockImplementation(
        () => new Promise((res) => { release = res; }),
      );
      render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp-edit" opportunityTitle="REU" />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument());
      await waitFor(() => expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1));
      const bodyArea = screen.getByDisplayValue(/Interested/).closest('div')!.parentElement!
        .querySelector('textarea[id="email-body"], textarea')!;
      fireEvent.change(bodyArea, { target: { value: 'my hand-tuned draft' } });
      await act(async () => { release(AI_RESP); });
      // Draft is available on the AI pill but the user's edit stays put.
      expect(screen.getByDisplayValue('my hand-tuned draft')).toBeInTheDocument();
      fireEvent.click(screen.getByText('coldEmail.aiVariantLabel'));
      await waitFor(() => expect(screen.getByDisplayValue('Auto AI Body')).toBeInTheDocument());
    });

    it('reopening the same opportunity serves the cached draft without re-billing', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      mockGenerateColdEmailStream.mockReset().mockResolvedValue(AI_RESP);
      const profile = makeProfile();
      const { rerender } = render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={profile} opportunityId="opp-cache" opportunityTitle="REU" />,
      );
      await waitFor(() => expect(screen.getByDisplayValue('Auto AI Body')).toBeInTheDocument());
      rerender(
        <ColdEmailModal isOpen={false} onClose={vi.fn()} profile={profile} opportunityId="opp-cache" opportunityTitle="REU" />,
      );
      rerender(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={profile} opportunityId="opp-cache" opportunityTitle="REU" />,
      );
      await waitFor(() => expect(screen.getByDisplayValue('Auto AI Body')).toBeInTheDocument());
      expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1);
    });

    it('cached AI writing never restores a recipient after auth loses reveal', async () => {
      mockGetVariants
        .mockResolvedValueOnce({
          variants: [makeVariant({ recipient_email: 'p@x.edu' })],
          recipient_status: 'revealed',
        })
        .mockResolvedValueOnce({
          variants: [makeVariant({ recipient_email: '' })],
          recipient_status: 'unavailable',
        });
      mockGenerateColdEmailStream.mockReset().mockResolvedValue(AI_RESP);
      const profile = makeProfile();
      const { rerender } = render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={profile} opportunityId="opp-auth-cache" opportunityTitle="REU" />,
      );
      await waitFor(() => expect(screen.getByDisplayValue('Auto AI Body')).toBeInTheDocument());
      expect(screen.getByPlaceholderText('coldEmail.toPlaceholder')).toHaveValue('p@x.edu');

      rerender(
        <ColdEmailModal isOpen={false} onClose={vi.fn()} profile={profile} opportunityId="opp-auth-cache" opportunityTitle="REU" />,
      );
      rerender(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={profile} opportunityId="opp-auth-cache" opportunityTitle="REU" />,
      );

      await waitFor(() =>
        expect(screen.getByPlaceholderText('coldEmail.toPlaceholder')).toHaveValue(''),
      );
      expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1);
      expect(screen.getByText('coldEmail.openInEmail').closest('button')).toBeDisabled();
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

  describe('quick actions', () => {
    it('"formal" routes through the backend refine with a canned instruction', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant({ body: 'I would love to chat.\n\nBest regards,\nAlex' })],
      });
      mockRefineEmail.mockResolvedValue({
        body: 'I would greatly appreciate to chat.\n\nRespectfully,\nAlex',
        method: 'llm',
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
      await waitFor(() => expect(mockRefineEmail).toHaveBeenCalledTimes(1));
      expect(mockRefineEmail).toHaveBeenCalledWith(
        'I would love to chat.\n\nBest regards,\nAlex',
        'Make it more formal and professional',
        makeProfile(),
        'opp',
        expect.any(Object),
      );
      await waitFor(() =>
        expect(screen.getByDisplayValue(/I would greatly appreciate to chat/)).toBeInTheDocument(),
      );
    });

    it('"shorter" routes through the backend refine (deterministic fallback shown)', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [
          makeVariant({
            body:
              'Line one.\nI am a fast learner and want to help.\nLine three.',
          }),
        ],
      });
      mockRefineEmail.mockResolvedValue({
        body: 'Line one.\nLine three.',
        method: 'local',
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
      await waitFor(() => expect(mockRefineEmail).toHaveBeenCalledTimes(1));
      expect(mockRefineEmail.mock.calls[0][1]).toBe('Make it shorter and more concise');
      await waitFor(() => {
        const textarea = screen.getByDisplayValue(/Line one/) as HTMLTextAreaElement;
        expect(textarea.value).not.toMatch(/fast learner/);
      });
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

    it('FE-4: "coursework" inserts BEFORE a non-"Best" closing (e.g. Sincerely)', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant({ body: 'Intro paragraph.\n\nSincerely,\nAlex' })],
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile({ coursework: ['CS 225'] })}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Intro paragraph/)).toBeInTheDocument());
      fireEvent.click(screen.getByText('coldEmail.quickActions.coursework'));
      const value = await waitFor(() => {
        const ta = screen.getByDisplayValue(/CS 225/) as HTMLTextAreaElement;
        return ta.value;
      });
      // The coursework sentence must sit ABOVE the signature, not dangle below it.
      expect(value.indexOf('CS 225')).toBeLessThan(value.indexOf('Sincerely'));
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
        expect.any(Object), // options (resumeBullets when extracted)
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

describe('no-email directory self-lookup link', () => {
  it('links the official campus directory when the school has one and no email resolved', async () => {
    mockGetVariants.mockResolvedValue({
      variants: [makeVariant({ recipient_email: '' })],
    });
    render(
      <ColdEmailModal
        isOpen
        onClose={vi.fn()}
        profile={makeProfile()}
        opportunityId="opp-uw"
        opportunityTitle="UW Lab"
        opportunitySchool="uw"
      />,
    );
    await waitFor(() =>
      expect(screen.getByText('coldEmail.emailUnavailableTitle')).toBeInTheDocument(),
    );
    const link = screen.getByText('coldEmail.emailLookupDirectory:UW Directory');
    expect(link).toHaveAttribute('href', 'https://directory.uw.edu/');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('renders no directory link for schools without a self-lookup directory', async () => {
    mockGetVariants.mockResolvedValue({
      variants: [makeVariant({ recipient_email: '' })],
    });
    render(
      <ColdEmailModal
        isOpen
        onClose={vi.fn()}
        profile={makeProfile()}
        opportunityId="opp-uiuc"
        opportunityTitle="UIUC Lab"
        opportunitySchool="uiuc"
      />,
    );
    await waitFor(() =>
      expect(screen.getByText('coldEmail.emailUnavailableTitle')).toBeInTheDocument(),
    );
    expect(screen.queryByText(/emailLookupDirectory/)).toBeNull();
  });
});

describe('W10b recipient states (contact bar)', () => {
  it('locked reveal: shows the sign-in affordance, not the "not found" lie', async () => {
    mockGetVariants.mockResolvedValue({
      variants: [makeVariant({ recipient_email: '' })],
      recipient_status: 'sign_in_required',
    });
    render(
      <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp" opportunityTitle="REU" />,
    );
    expect(await screen.findByTestId('recipient-sign-in')).toBeInTheDocument();
    expect(screen.queryByText('coldEmail.emailUnavailableTitle')).toBeNull();
    // Drafting still works — the draft is the value.
    expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument();
    // Send affordances stay disabled until an address exists.
    expect(screen.getByText('coldEmail.openInEmail').closest('button')).toBeDisabled();
    fireEvent.click(screen.getByText('coldEmail.signInToRevealCta'));
    expect(openAuthModalMock).toHaveBeenCalledWith({ reason: 'contact-reveal' });
  });

  it('no verified address: keeps the honest unavailable state (no sign-in bait)', async () => {
    mockGetVariants.mockResolvedValue({
      variants: [makeVariant({ recipient_email: '' })],
      recipient_status: 'unavailable',
    });
    render(
      <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp" opportunityTitle="REU" />,
    );
    await waitFor(() =>
      expect(screen.getByText('coldEmail.emailUnavailableTitle')).toBeInTheDocument(),
    );
    expect(screen.queryByTestId('recipient-sign-in')).toBeNull();
  });

  it('revealed: prefills the To field exactly as before', async () => {
    mockGetVariants.mockResolvedValue({
      variants: [makeVariant({ recipient_email: 'prof@illinois.edu' })],
      recipient_status: 'revealed',
    });
    render(
      <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp" opportunityTitle="REU" />,
    );
    await waitFor(() => expect(screen.getByDisplayValue('prof@illinois.edu')).toBeInTheDocument());
    expect(screen.queryByTestId('recipient-sign-in')).toBeNull();
    expect(screen.getByText('coldEmail.openInEmail').closest('button')).not.toBeDisabled();
  });

  it('switching variants never wipes a hand-typed address', async () => {
    mockGetVariants.mockResolvedValue({
      variants: [
        makeVariant({ id: 'a', label: 'Formal', recipient_email: '' }),
        makeVariant({ id: 'b', label: 'Casual', recipient_email: '' }),
      ],
      recipient_status: 'sign_in_required',
    });
    render(
      <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp" opportunityTitle="REU" />,
    );
    await waitFor(() => expect(screen.getByText('Casual')).toBeInTheDocument());
    const toInput = screen.getByPlaceholderText('coldEmail.toPlaceholder');
    fireEvent.change(toInput, { target: { value: 'typed@example.edu' } });
    fireEvent.click(screen.getByText('Casual'));
    expect(screen.getByDisplayValue('typed@example.edu')).toBeInTheDocument();
  });
});
