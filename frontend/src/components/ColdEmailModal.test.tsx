import { emailValidationReceipt } from './ColdEmailModal.test-fixtures';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act, within } from '@testing-library/react';
import { ColdEmailStreamError } from '@/lib/cold-email-stream';

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
const mockExtractResumeBullets = vi.fn();
// Independent compose tests cover address revalidation; these suites retain their history/encoding assertions.
vi.mock('@/lib/email-compose', () => ({ verifyComposeRecipient: vi.fn().mockResolvedValue(undefined) }));
vi.mock('@/lib/api', () => ({
  validateEmailDraft: emailValidationReceipt,
  getEmailVariants: (...args: unknown[]) => emailReceipt(mockGetVariants(...args), args[1] as string, (args[3] as { expectedTargetVersion?: string } | undefined)?.expectedTargetVersion),
  generateColdEmail: (...args: unknown[]) => emailReceipt(mockGenerateColdEmail(...args), args[1] as string, (args[2] as { expectedTargetVersion?: string } | undefined)?.expectedTargetVersion),
  generateColdEmailStream: (...args: unknown[]) => emailReceipt(mockGenerateColdEmailStream(...args), args[1] as string, (args[2] as { expectedTargetVersion?: string } | undefined)?.expectedTargetVersion),
  refineEmail: (...args: unknown[]) => emailReceipt(mockRefineEmail(...args), args[3] as string, (args[4] as { expectedTargetVersion?: string } | undefined)?.expectedTargetVersion),
  extractResumeBullets: (...args: unknown[]) => mockExtractResumeBullets(...args),
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

vi.mock('@/lib/supabase', () => ({
  onAuthChange: () => () => {},
  confirmContactEvent: vi.fn(),
  updateInteractionDetails: vi.fn(),
}));

import RawColdEmailModal from './ColdEmailModal';
import { emailTarget, emailReceipt, EMAIL_TARGET_VERSION } from './ColdEmailModal.test-fixtures';
function ColdEmailModal(props: Parameters<typeof RawColdEmailModal>[0]) {
  return <RawColdEmailModal target={emailTarget(props.opportunityId)} {...props} />;
}
import { advanceOwnerEpoch, syncLocalIdentityOwner } from '@/lib/identity-owner';
import type { ProfileData, EmailVariant, LabType } from '@/lib/types';
import { en, zh } from '@/i18n/dictionaries';

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

beforeEach(async () => {
  advanceOwnerEpoch('cold-email-test-owner');
  await syncLocalIdentityOwner('cold-email-test-owner');
  mockGetVariants.mockReset();
  mockGenerateColdEmail.mockReset().mockResolvedValue({ ...makeVariant(), method: 'template' });
  // These legacy AI fixtures exercise a known old backend: its SSE endpoint
  // returns 404 before generation begins. Only that explicit unsupported
  // result permits the blocking compatibility request; network/timeout
  // failures remain covered separately and must never replay.
  mockGenerateColdEmailStream.mockReset().mockRejectedValue(new ColdEmailStreamError('unsupported', 404));
  mockRefineEmail.mockReset();
  mockExtractResumeBullets.mockReset().mockResolvedValue({
    bullets: [],
    method: 'heuristic',
  });
  writeTextMock.mockReset().mockResolvedValue(undefined);
  windowOpenMock.mockReset().mockImplementation(() => ({ closed: false, opener: null, location: { href: 'about:blank' }, close: vi.fn() }));

  /* A chat update must never scroll a field or any ancestor into view. */
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
      expect(mockGetVariants).toHaveBeenCalledWith(profile, 'opp-42', undefined, { expectedTargetVersion: EMAIL_TARGET_VERSION, contactContext: { version: 1, purpose: 'first_contact' } });
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
      expect(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' })).toBeInTheDocument();
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
      await waitFor(() => expect(screen.getByDisplayValue('SUBJ-B')).toBeInTheDocument());
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
      await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
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
      await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
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
      await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
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
      await waitFor(() => expect(windowOpenMock.mock.results[0].value.location.href).toContain('mail.google.com'));
      expect(windowOpenMock.mock.calls[0][0]).toBe('about:blank');
      const url = windowOpenMock.mock.results[0].value.location.href as string;
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
      const edited = 'p+lab&tag@x.edu';
      fireEvent.change(screen.getByDisplayValue('p@x.edu'), { target: { value: edited } });
      fireEvent.click(screen.getByText('coldEmail.gmail'));
      await waitFor(() => expect(windowOpenMock.mock.results[0].value.location.href).toContain('mail.google.com'));
      fireEvent.click(screen.getByText('coldEmail.outlook'));
      await waitFor(() => expect(windowOpenMock.mock.results[1].value.location.href).toContain('outlook.office365.com'));
      const [gmailUrl, outlookUrl] = windowOpenMock.mock.results.map((result) => result.value.location.href as string);
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
      await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' })).toBeEnabled());
      fireEvent.click(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' }));
      await waitFor(() => expect(mockGenerateColdEmail).toHaveBeenCalledTimes(1));
      // Stream-first: the known unsupported (404) endpoint was checked before
      // the blocking compatibility route landed the draft.
      expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1);
      // No recommended_style in this variants mock → seeds the default tone.
      expect(mockGenerateColdEmail).toHaveBeenCalledWith(profile, 'opp-7', { engine: 'ai', style: 'professional', expectedTargetVersion: EMAIL_TARGET_VERSION, contactContext: { version: 1, purpose: 'first_contact' } });
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
      await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' })).toBeEnabled());
      fireEvent.click(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' }));
      // Wait for the result rather than race the temporary stage label.
      await waitFor(() =>
        expect(screen.getByDisplayValue('Streamed AI Body')).toBeInTheDocument(),
      );
      expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1);
      expect(mockGenerateColdEmail).not.toHaveBeenCalled();
    });

    it('after an AI draft exists, a tone pill only picks the voice and Generate rewrites in it', async () => {
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
      await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' })).toBeEnabled());
      fireEvent.click(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' }));
      await screen.findByDisplayValue('AI Body');
      expect(mockGenerateColdEmail).toHaveBeenLastCalledWith(profile, 'opp-7', { engine: 'ai', style: 'warm', expectedTargetVersion: EMAIL_TARGET_VERSION, contactContext: { version: 1, purpose: 'first_contact' } });
      await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.aiVariantLabel' })).toBeEnabled());
      fireEvent.click(screen.getByText('coldEmail.tone.lively'));
      await act(async () => {});
      expect(mockGenerateColdEmail).toHaveBeenCalledTimes(1);
      fireEvent.click(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' }));
      await waitFor(() => expect(mockGenerateColdEmail).toHaveBeenCalledTimes(2));
      expect(mockGenerateColdEmail).toHaveBeenLastCalledWith(profile, 'opp-7', { engine: 'ai', style: 'lively', expectedTargetVersion: EMAIL_TARGET_VERSION, contactContext: { version: 1, purpose: 'first_contact' } });
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
      await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' })).toBeEnabled());
      fireEvent.click(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' }));
      await waitFor(() =>
        expect(screen.getByText('coldEmail.aiFallbackFabrication')).toBeInTheDocument(),
      );
    });

    it('explains when target evidence is insufficient without claiming AI ran', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      mockGenerateColdEmail.mockResolvedValue({
        subject: 'Template Subject',
        body: 'Template Body',
        recipient_email: 'p@x.edu',
        mailto_link: 'mailto:p@x.edu',
        method: 'template',
        fallback_reason: 'insufficient_evidence',
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp-no-target"
          opportunityTitle="Faculty profile"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Interested/)).toBeInTheDocument());
      await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' })).toBeEnabled());
      fireEvent.click(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' }));
      await waitFor(() =>
        expect(screen.getByText('coldEmail.aiFallbackInsufficientEvidence')).toBeInTheDocument(),
      );
      expect(screen.queryByText('coldEmail.aiFallbackFabrication')).toBeNull();
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
      await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' })).toBeEnabled());
      fireEvent.click(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' }));
      await waitFor(() => expect(screen.getByDisplayValue('AI Subject')).toBeInTheDocument());
      await waitFor(() => expect(screen.getByRole('button', { name: 'Template A' })).toBeEnabled());
      fireEvent.click(screen.getByRole('button', { name: 'Template A' }));
      await waitFor(() => expect(screen.getByLabelText('coldEmail.body')).toHaveValue(makeVariant().body));
      const pill = screen.getByRole('button', { name: 'coldEmail.aiVariantLabel' });
      await waitFor(() => expect(pill).toBeEnabled());
      fireEvent.click(pill);
      expect(mockGenerateColdEmail).toHaveBeenCalledTimes(1);
      await waitFor(() => expect(screen.getByDisplayValue('AI Subject')).toBeInTheDocument());
    });

    it('FE-5: shows a durable "template, not AI" badge when the AI pill falls back', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()] });
      const fallback = {
        subject: 'T', body: 'Template Body', recipient_email: 'p@x.edu',
        mailto_link: 'mailto:p@x.edu', method: 'template', fallback_reason: 'not_configured',
      };
      mockGenerateColdEmail.mockResolvedValue(fallback);
      render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp" opportunityTitle="REU" />,
      );
      await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' })).toBeEnabled());
      expect(screen.getByRole('textbox', { name: 'coldEmail.body' })).toHaveValue(makeVariant().body);
      expect(screen.queryByText('coldEmail.templateFallbackBadge')).toBeNull();
      expect(mockGenerateColdEmail).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' }));
      await waitFor(() => expect(mockGenerateColdEmail).toHaveBeenCalledTimes(1));
      await screen.findByDisplayValue('Template Body');
      expect(await screen.findByText('coldEmail.templateFallbackBadge')).toBeInTheDocument();
      // A fallback is not an AI draft: the control still offers to generate one.
      expect(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' })).toBeInTheDocument();
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
      await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' })).toBeEnabled());
      fireEvent.click(screen.getByRole('button', { name: 'coldEmail.generateAiDraft' }));
      await waitFor(() => expect(screen.getByDisplayValue('AI Body')).toBeInTheDocument());
      expect(screen.queryByText('coldEmail.templateFallbackBadge')).toBeNull();
    });
  });

  // M75 (owner decision Q47): opening the editor must not spend a model call.
  // The template is the draft until the student clicks Generate.
  describe('AI draft only on an explicit Generate click', () => {
    const AI_RESP = {
      subject: 'Clicked AI Subject',
      body: 'Clicked AI Body',
      recipient_email: 'p@x.edu',
      mailto_link: 'mailto:p@x.edu',
      method: 'ai',
      pipeline_version: 'pipeline-current',
    };
    // Flushes the effects and queued tasks the open path schedules, so a
    // zero-call assertion is not just an early read.
    const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    const generate = () => screen.getByRole('button', { name: 'coldEmail.generateAiDraft' });

    it('opening the editor makes no generate call; one Generate click makes exactly one', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()], pipeline_version: 'pipeline-current' });
      mockGenerateColdEmailStream.mockReset().mockResolvedValue(AI_RESP);
      render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp-opt-in" opportunityTitle="REU" />,
      );
      await screen.findByDisplayValue(/Interested/);
      await settle();
      expect(mockGenerateColdEmailStream).not.toHaveBeenCalled();
      expect(mockGenerateColdEmail).not.toHaveBeenCalled();
      expect(screen.getByLabelText('coldEmail.body')).toHaveValue(makeVariant().body);
      await waitFor(() => expect(generate()).toBeEnabled());
      fireEvent.click(generate());
      await screen.findByDisplayValue('Clicked AI Body');
      await settle();
      expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1);
      expect(mockGenerateColdEmail).not.toHaveBeenCalled();
    });

    it('choosing a tone calls nothing; Generate then writes in the chosen tone', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()], recommended_style: 'warm', pipeline_version: 'pipeline-current' });
      mockGenerateColdEmailStream.mockReset().mockResolvedValue(AI_RESP);
      render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp-tone" opportunityTitle="REU" />,
      );
      await screen.findByDisplayValue(/Interested/);
      const lively = screen.getByRole('button', { name: 'coldEmail.tone.lively' });
      await waitFor(() => expect(lively).toBeEnabled());
      fireEvent.click(lively);
      await settle();
      expect(mockGenerateColdEmailStream).not.toHaveBeenCalled();
      expect(mockGenerateColdEmail).not.toHaveBeenCalled();
      expect(screen.getByLabelText('coldEmail.body')).toHaveValue(makeVariant().body);
      expect(lively).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByRole('button', { name: /^coldEmail\.tone\.warm/ })).toHaveAttribute('aria-pressed', 'false');
      fireEvent.click(generate());
      await screen.findByDisplayValue('Clicked AI Body');
      expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1);
      expect(mockGenerateColdEmailStream.mock.calls[0][2]).toMatchObject({ engine: 'ai', style: 'lively' });
    });

    it('rebuilding from changed materials refreshes the template only; Generate stays the one model call', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()], pipeline_version: 'pipeline-current' });
      mockGenerateColdEmailStream.mockReset().mockResolvedValue(AI_RESP);
      const { rerender } = render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp-rebuild" opportunityTitle="REU" />,
      );
      await screen.findByDisplayValue(/Interested/);
      mockGetVariants.mockResolvedValue({ variants: [makeVariant({ body: 'Rebuilt template body' })], pipeline_version: 'pipeline-current' });
      rerender(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile({ research_interests: 'robotics' })} opportunityId="opp-rebuild" opportunityTitle="REU" />,
      );
      const rebuild = await screen.findByRole('button', { name: 'coldEmail.regenerateFromProfile' });
      await waitFor(() => expect(rebuild).toBeEnabled());
      fireEvent.click(rebuild);
      await screen.findByDisplayValue('Rebuilt template body');
      await settle();
      expect(mockGetVariants).toHaveBeenCalledTimes(2);
      expect(mockGenerateColdEmailStream).not.toHaveBeenCalled();
      expect(mockGenerateColdEmail).not.toHaveBeenCalled();
      await waitFor(() => expect(generate()).toBeEnabled());
      fireEvent.click(generate());
      await screen.findByDisplayValue('Clicked AI Body');
      expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1);
      expect(mockGenerateColdEmailStream.mock.calls[0][0]).toMatchObject({ research_interests: 'robotics' });
    });

    it('a no-target AI attempt never calls resume extraction', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant()],
        grounding: 'no_target_data',
      });
      mockGenerateColdEmailStream.mockReset().mockResolvedValue({
        subject: 'Template subject',
        body: 'Template body',
        recipient_email: '',
        mailto_link: 'mailto:',
        method: 'template',
        fallback_reason: 'insufficient_evidence',
        grounding: 'no_target_data',
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile({ resume_text: 'Built a CFD solver in Python.' })}
          opportunityId="opp-no-target-manual"
          opportunityTitle="Faculty profile"
        />,
      );
      await waitFor(() => expect(generate()).toBeEnabled());
      fireEvent.click(generate());
      await waitFor(() => expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1));
      expect(mockExtractResumeBullets).toHaveBeenCalledTimes(0);
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
      await waitFor(() => expect(generate()).toBeEnabled());
      fireEvent.click(generate());
      await waitFor(() => expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1));
      const bodyArea = screen.getByLabelText('coldEmail.body');
      fireEvent.change(bodyArea, { target: { value: 'my hand-tuned draft' } });
      await act(async () => { release(AI_RESP); });
      // Draft is available on the AI pill but the user's edit stays put.
      expect(screen.getByDisplayValue('my hand-tuned draft')).toBeInTheDocument();
      const pill = screen.getByRole('button', { name: 'coldEmail.aiVariantLabel' });
      await waitFor(() => expect(pill).toBeEnabled());
      fireEvent.click(pill);
      await waitFor(() => expect(screen.getByDisplayValue('Clicked AI Body')).toBeInTheDocument());
      expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1);
    });

    it('returning to a generated tone reuses its draft without re-billing, and reopening calls nothing', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()], pipeline_version: 'pipeline-current' });
      mockGenerateColdEmailStream.mockReset()
        .mockResolvedValueOnce(AI_RESP)
        .mockResolvedValueOnce({ ...AI_RESP, body: 'Warm AI Body' });
      const profile = makeProfile();
      const { rerender } = render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={profile} opportunityId="opp-cache" opportunityTitle="REU" />,
      );
      const aiPill = () => screen.getByRole('button', { name: 'coldEmail.aiVariantLabel' });
      await waitFor(() => expect(generate()).toBeEnabled());
      fireEvent.click(generate());
      await screen.findByDisplayValue('Clicked AI Body');
      await waitFor(() => expect(aiPill()).toBeEnabled());
      fireEvent.click(screen.getByRole('button', { name: 'coldEmail.tone.warm' }));
      fireEvent.click(generate());
      await screen.findByDisplayValue('Warm AI Body');
      await waitFor(() => expect(aiPill()).toBeEnabled());
      fireEvent.click(screen.getByRole('button', { name: 'coldEmail.tone.professional' }));
      fireEvent.click(generate());
      await screen.findByDisplayValue('Clicked AI Body');
      await waitFor(() => expect(aiPill()).toBeEnabled());
      expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(2);
      rerender(
        <ColdEmailModal isOpen={false} onClose={vi.fn()} profile={profile} opportunityId="opp-cache" opportunityTitle="REU" />,
      );
      rerender(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={profile} opportunityId="opp-cache" opportunityTitle="REU" />,
      );
      await screen.findByDisplayValue('Clicked AI Body');
      await settle();
      expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(2);
    });

    it('a reopened AI draft never restores a recipient after auth loses reveal', async () => {
      mockGetVariants
        .mockResolvedValueOnce({
          variants: [makeVariant({ recipient_email: 'p@x.edu' })],
          recipient_status: 'revealed',
          pipeline_version: 'pipeline-current',
        })
        .mockResolvedValueOnce({
          variants: [makeVariant({ recipient_email: '' })],
          recipient_status: 'unavailable',
          pipeline_version: 'pipeline-current',
        });
      mockGenerateColdEmailStream.mockReset().mockResolvedValue(AI_RESP);
      const profile = makeProfile();
      const { rerender } = render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={profile} opportunityId="opp-auth-cache" opportunityTitle="REU" />,
      );
      await waitFor(() => expect(generate()).toBeEnabled());
      fireEvent.click(generate());
      await screen.findByDisplayValue('Clicked AI Body');
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
      await settle();
      expect(screen.getByDisplayValue('Clicked AI Body')).toBeInTheDocument();
      expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1);
      expect(screen.getByText('coldEmail.openInEmail').closest('button')).toBeDisabled();
    });

    it('keeps the paid draft: quick actions and typed requests wait until Generate finishes', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()], pipeline_version: 'pipeline-current' });
      let release!: (v: typeof AI_RESP) => void;
      mockGenerateColdEmailStream.mockReset().mockImplementation(() => new Promise((res) => { release = res; }));
      mockRefineEmail.mockResolvedValue({ body: 'Refined body', method: 'llm' });
      render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp-busy" opportunityTitle="REU" />,
      );
      await waitFor(() => expect(generate()).toBeEnabled());
      fireEvent.click(generate());
      await waitFor(() => expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1));
      const request = screen.getByRole('textbox', { name: 'coldEmail.requestLabel' });
      fireEvent.change(request, { target: { value: 'Make it shorter' } });
      for (const key of ['formal', 'shorter', 'enthusiastic', 'coursework']) {
        expect(screen.getByRole('button', { name: `coldEmail.quickActions.${key}` })).toBeDisabled();
      }
      expect(screen.getByRole('button', { name: 'coldEmail.submitRequest' })).toBeDisabled();
      // A submit that bypasses the disabled button must not start a refine either.
      fireEvent.submit(request.closest('form')!);
      await settle();
      expect(mockRefineEmail).not.toHaveBeenCalled();
      await act(async () => { release(AI_RESP); });
      await screen.findByDisplayValue('Clicked AI Body');
      expect(screen.getByText('coldEmail.aiGenerated')).toBeInTheDocument();
      await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.quickActions.shorter' })).toBeEnabled());
      expect(screen.getByRole('button', { name: 'coldEmail.submitRequest' })).toBeEnabled();
      expect(mockGenerateColdEmailStream).toHaveBeenCalledTimes(1);
      expect(mockRefineEmail).not.toHaveBeenCalled();
    });

    it('the busy control says it is generating until a pipeline stage arrives', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()], pipeline_version: 'pipeline-current' });
      let onStage!: (stage: string) => void;
      let release!: (v: typeof AI_RESP) => void;
      mockGenerateColdEmailStream.mockReset().mockImplementation((_profile: unknown, _id: unknown, _opts: unknown, stage: (s: string) => void) => {
        onStage = stage;
        return new Promise((res) => { release = res; });
      });
      render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp-busy-label" opportunityTitle="REU" />,
      );
      await waitFor(() => expect(generate()).toBeEnabled());
      fireEvent.click(generate());
      expect(await screen.findByRole('button', { name: 'coldEmail.aiGenerating' })).toBeDisabled();
      expect(screen.queryByRole('button', { name: 'coldEmail.generateAiDraft' })).toBeNull();
      act(() => onStage('drafting'));
      expect(screen.getByRole('button', { name: 'coldEmail.stageDrafting' })).toBeDisabled();
      await act(async () => { release(AI_RESP); });
      await screen.findByDisplayValue('Clicked AI Body');
      expect(screen.getByRole('button', { name: 'coldEmail.aiVariantLabel' })).toBeInTheDocument();
    });

    it('the busy control says it is generating on the compatibility route too', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()], pipeline_version: 'pipeline-current' });
      // beforeEach: the stream route answers 404, so the click falls back to the blocking route.
      let release!: (v: typeof AI_RESP) => void;
      mockGenerateColdEmail.mockReset().mockImplementation(() => new Promise((res) => { release = res; }));
      render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp-busy-compat" opportunityTitle="REU" />,
      );
      await waitFor(() => expect(generate()).toBeEnabled());
      fireEvent.click(generate());
      await waitFor(() => expect(mockGenerateColdEmail).toHaveBeenCalledTimes(1));
      expect(screen.getByRole('button', { name: 'coldEmail.aiGenerating' })).toBeDisabled();
      expect(screen.queryByRole('button', { name: 'coldEmail.generateAiDraft' })).toBeNull();
      await act(async () => { release(AI_RESP); });
      await screen.findByDisplayValue('Clicked AI Body');
    });

    it('says next to the tone chips that the tone applies to the next AI draft', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant()], recommended_style: 'warm' });
      render(
        <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp-tone-hint" opportunityTitle="REU" />,
      );
      await screen.findByDisplayValue(/Interested/);
      expect(screen.getByText('coldEmail.tone.hint')).toBeVisible();
      for (const style of ['professional', 'warm', 'friendly', 'lively']) {
        expect(screen.getByRole('button', { name: new RegExp(`^coldEmail\\.tone\\.${style}`) })).toHaveAccessibleDescription('coldEmail.tone.hint');
      }
      expect(en.coldEmail.tone.hint).toBeTruthy();
      expect(zh.coldEmail.tone.hint).toBeTruthy();
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
        { expectedTargetVersion: EMAIL_TARGET_VERSION, contactContext: { version: 1, purpose: 'first_contact' }, subject: 'Interested in research with you' },
      );
      expect(await screen.findByRole('region', { name: 'Pending edit suggestion' })).toHaveTextContent('I would greatly appreciate to chat.');
      expect(screen.getByLabelText('coldEmail.body')).toHaveValue('I would love to chat.\n\nBest regards,\nAlex');
      fireEvent.click(screen.getByRole('button', { name: 'Accept suggestion' }));
      await waitFor(() => expect(screen.getByLabelText('coldEmail.body')).toHaveValue('I would greatly appreciate to chat.\n\nRespectfully,\nAlex'));
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
      expect(await screen.findByRole('region', { name: 'Pending edit suggestion' })).toHaveTextContent('Line three.');
      expect(screen.getByLabelText('coldEmail.body')).toHaveValue('Line one.\nI am a fast learner and want to help.\nLine three.');
      expect(screen.getByText('Basic edit suggestion ready. Compare it, then accept or reject.')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Accept suggestion' }));
      await waitFor(() => expect(screen.getByLabelText('coldEmail.body')).toHaveValue('Line one.\nLine three.'));
    });

    it('"coursework" inserts the profile\'s coursework when present', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant({ body: 'Intro.\n\nBest regards,\nAlex' })],
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile({ coursework: ['CS 225', 'CS 374', 'CS 101', 'CS 102', 'LATE COURSE 5'] })}
          opportunityId="opp"
          opportunityTitle="REU"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue(/Intro/)).toBeInTheDocument());
      fireEvent.click(screen.getByText('coldEmail.quickActions.coursework'));
      expect(await screen.findByRole('region', { name: 'Pending edit suggestion' })).toHaveTextContent('CS 225');
      expect(screen.getByLabelText('coldEmail.body')).toHaveValue('Intro.\n\nBest regards,\nAlex');
      fireEvent.click(screen.getByRole('button', { name: 'Accept suggestion' }));
      await waitFor(() => expect(screen.getByDisplayValue(/CS 225/)).toBeInTheDocument());
      expect(screen.getByDisplayValue(/CS 374/)).toBeInTheDocument();
      expect(screen.getByDisplayValue(/LATE COURSE 5/)).toBeInTheDocument();
    });

    it('keeps the draft when complete coursework exceeds the email body limit', async () => {
      mockGetVariants.mockResolvedValue({ variants: [makeVariant({ body: 'Original draft.\n\nBest regards,\nAlex' })] });
      render(<ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile({ coursework: Array.from({length:110},(_,i)=>String(i)+'x'.repeat(990)) })} opportunityId="opp" opportunityTitle="REU" />);
      await screen.findByDisplayValue(/Original draft/);
      fireEvent.click(screen.getByText('coldEmail.quickActions.coursework'));
      expect(await screen.findByText('profileInput.courseworkTooLarge')).toBeInTheDocument();
      expect(screen.getByLabelText('coldEmail.body')).toHaveValue('Original draft.\n\nBest regards,\nAlex');
      expect(screen.queryByRole('region', {name:'Pending edit suggestion'})).toBeNull();
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
      expect(await screen.findByRole('region', { name: 'Pending edit suggestion' })).toHaveTextContent('CS 225');
      expect(screen.getByLabelText('coldEmail.body')).toHaveValue('Intro paragraph.\n\nSincerely,\nAlex');
      fireEvent.click(screen.getByRole('button', { name: 'Accept suggestion' }));
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
        { expectedTargetVersion: EMAIL_TARGET_VERSION, contactContext: { version: 1, purpose: 'first_contact' }, subject: 'Interested in research with you' },
      );
      expect(await screen.findByRole('region', { name: 'Pending edit suggestion' })).toHaveTextContent('Refined body.');
      expect(screen.getByLabelText('coldEmail.body')).toHaveValue('Original body.');
      expect(input).toHaveValue('Make it warmer');
      fireEvent.click(screen.getByRole('button', { name: 'Accept suggestion' }));
      await waitFor(() => expect(screen.getByDisplayValue('Refined body.')).toBeInTheDocument());
      expect(input).toHaveValue('');
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
      expect(screen.getByLabelText('coldEmail.body')).toHaveValue('Original body.');
      expect(input).toHaveValue('say I know Rust');
      expect(screen.queryByRole('region', { name: 'Pending edit suggestion' })).toBeNull();
    });

    it('offers the safe version of a rejected edit as a suggestion, not as an applied edit', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant({ body: 'I would love to join.' })],
      });
      mockRefineEmail.mockResolvedValue({
        body: 'I would greatly appreciate to join.',
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
      await waitFor(() => expect(screen.getByDisplayValue('I would love to join.')).toBeInTheDocument());
      const input = screen.getByPlaceholderText('coldEmail.refinePlaceholder');
      fireEvent.change(input, { target: { value: 'Make it formal and say I know Rust' } });
      await act(async () => {
        fireEvent.submit(input.closest('form')!);
      });
      expect(await screen.findByRole('region', { name: 'Pending edit suggestion' })).toHaveTextContent('I would greatly appreciate to join.');
      expect(screen.getByText('coldEmail.refineFabricationSuggestion')).toBeInTheDocument();
      expect(screen.queryByText('coldEmail.refineFabrication')).toBeNull();
      expect(screen.getByLabelText('coldEmail.body')).toHaveValue('I would love to join.');
    });

    it('reports an evidence-gated safe-template replacement instead of a basic tone edit', async () => {
      mockGetVariants.mockResolvedValue({
        variants: [makeVariant({ body: 'Original body.' })],
      });
      mockRefineEmail.mockResolvedValue({
        body: 'Safe general inquiry template.',
        method: 'local',
        fallback_reason: 'insufficient_evidence',
      });
      render(
        <ColdEmailModal
          isOpen
          onClose={vi.fn()}
          profile={makeProfile()}
          opportunityId="opp-no-target-refine"
          opportunityTitle="Faculty profile"
        />,
      );
      await waitFor(() => expect(screen.getByDisplayValue('Original body.')).toBeInTheDocument());
      const input = screen.getByPlaceholderText('coldEmail.refinePlaceholder');
      fireEvent.change(input, { target: { value: 'Make it warmer' } });
      const form = input.closest('form');
      await act(async () => {
        fireEvent.submit(form!);
      });

      expect(await screen.findByRole('region', { name: 'Pending edit suggestion' })).toHaveTextContent('Safe general inquiry template.');
      expect(screen.getByLabelText('coldEmail.body')).toHaveValue('Original body.');
      expect(input).toHaveValue('Make it warmer');
      fireEvent.click(screen.getByRole('button', { name: 'Accept suggestion' }));
      await waitFor(() => expect(screen.getByDisplayValue('Safe general inquiry template.')).toBeInTheDocument());
      expect(input).toHaveValue('');
      expect(screen.getByText('coldEmail.aiFallbackInsufficientEvidence')).toBeInTheDocument();
      expect(screen.queryByText('coldEmail.doneFallback')).not.toBeInTheDocument();
      expect(screen.queryByText('coldEmail.doneLlm')).not.toBeInTheDocument();
    });

    it('ships the evidence-gated no-AI outcome in both locales', () => {
      expect(en.coldEmail.aiFallbackInsufficientEvidence).toContain('safe inquiry template');
      expect(en.coldEmail.aiFallbackInsufficientEvidence).toContain('AI did not run');
      expect(zh.coldEmail.aiFallbackInsufficientEvidence).toContain('安全询问模板');
      expect(zh.coldEmail.aiFallbackInsufficientEvidence).toContain('未运行 AI');
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


describe('ColdEmailModal editing workspace', () => {
  it('names the guidelines and request areas and scrolls only chat history on new messages', async () => {
    mockGetVariants.mockResolvedValue({ variants: [makeVariant()], lab_type: 'dry' });
    mockGenerateColdEmail.mockRejectedValue(new Error('AI unavailable in test'));
    render(
      <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="layout-opp" opportunityTitle="Research" />,
    );
    const guidelines = await screen.findByRole('region', { name: 'coldEmail.guidelinesTitle' });
    expect(guidelines).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('region', { name: 'coldEmail.aiRequestsTitle' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'coldEmail.requestLabel' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'coldEmail.submitRequest' })).toBeDisabled();

    const history = screen.getByRole('log', { name: 'coldEmail.aiRequestsTitle' });
    const workspace = screen.getByTestId('cold-email-workspace');
    const editor = screen.getByTestId('cold-email-editor-fields');
    Object.defineProperty(history, 'scrollHeight', { configurable: true, value: 720 });
    workspace.scrollTop = 130;
    editor.scrollTop = 90;
    guidelines.scrollTop = 40;
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.quickActions.coursework' }));
    await waitFor(() => expect(history.scrollTop).toBe(720));
    expect(workspace.scrollTop).toBe(130);
    expect(editor.scrollTop).toBe(90);
    expect(guidelines.scrollTop).toBe(40);
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
  });

  it('pins only Copy and Open in Email below the two-column size; the other actions scroll with the draft', async () => {
    // M29: on a phone, a short window or at 200% zoom the primary actions stay
    // in view. Everything else in the footer moves into the scrolling
    // workspace, and returns to the footer row once the window is wide again.
    const listeners = new Set<() => void>();
    let wide = false;
    vi.stubGlobal('matchMedia', (query: string) => ({
      media: query,
      get matches() { return wide && query === '(min-width: 1024px) and (min-height: 720px)'; },
      addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
    }));
    mockGetVariants.mockResolvedValue({ variants: [makeVariant()], lab_type: 'dry' });
    render(
      <ColdEmailModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="layout-opp" opportunityTitle="Research" />,
    );
    const button = (label: string) => screen.getByText(label).closest('button')!;
    const secondary = () => [screen.getByTestId('copy-draft-only'), screen.getByTestId('record-sent-email'),
      button('coldEmail.gmail'), button('coldEmail.outlook')];
    const footer = await screen.findByTestId('cold-email-footer');
    expect(within(footer).getAllByRole('button')).toEqual([button('coldEmail.copy'), button('coldEmail.openInEmail')]);
    for (const action of secondary()) expect(screen.getByTestId('cold-email-workspace')).toContainElement(action);

    wide = true;
    act(() => listeners.forEach((listener) => listener()));
    const row = screen.getByTestId('cold-email-footer');
    for (const action of [button('coldEmail.copy'), button('coldEmail.openInEmail'), ...secondary()]) {
      expect(row).toContainElement(action);
    }
    expect(screen.getByTestId('cold-email-workspace')).not.toContainElement(button('coldEmail.gmail'));
  });
});
