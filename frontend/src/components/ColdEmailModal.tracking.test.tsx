/**
 * Verified-send tracking contract for the cold-email modal.
 *
 * Copying the draft or opening a mail client is NOT evidence the email was
 * sent — neither may create an 'applied' interaction (an outreach "send"
 * event that feeds the responsiveness aggregates). Only the explicit
 * "I sent it" confirmation records the contact. No evidence = no tracking
 * event.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('@/i18n/client', () => {
  const stableT = (key: string, vars?: Record<string, string | number>) => {
    if (!vars) return key;
    const parts = Object.entries(vars).map(([, v]) => String(v));
    return parts.length > 0 ? `${key}:${parts.join('|')}` : key;
  };
  return {
    useT: () => ({ t: stableT, locale: 'en' as const, setLocale: () => {} }),
  };
});

const mockGetVariants = vi.fn();
vi.mock('@/lib/api', () => ({
  getEmailVariants: (...args: unknown[]) => mockGetVariants(...args),
  generateColdEmail: vi.fn(),
  generateColdEmailStream: vi.fn().mockRejectedValue(new Error('no stream in tests')),
  refineEmail: vi.fn(),
  extractResumeBullets: async () => ({ bullets: [], method: 'heuristic' }),
}));

vi.mock('@/lib/auth-modal-context', () => ({
  useAuthModal: () => ({
    open: false,
    phase: 'auto',
    reason: null,
    openModal: vi.fn(),
    closeModal: () => {},
    setPhase: () => {},
  }),
}));

const trackInteractionMock = vi.fn().mockResolvedValue(undefined);
const getInteractionDetailMock = vi.fn().mockResolvedValue(null);
const updateInteractionDetailsMock = vi.fn().mockResolvedValue(undefined);
const confirmContactMock = vi.fn().mockResolvedValue({ type: 'applied' });
vi.mock('@/lib/supabase', () => ({
  confirmInteractionContact: (...args: unknown[]) => confirmContactMock(...args),
  trackInteraction: (...args: unknown[]) => trackInteractionMock(...args),
  getInteractionDetail: (...args: unknown[]) => getInteractionDetailMock(...args),
  updateInteractionDetails: (...args: unknown[]) => updateInteractionDetailsMock(...args),
  onAuthChange: () => () => {},
}));

import ColdEmailModal from './ColdEmailModal';
import type { ProfileData, EmailVariant } from '@/lib/types';

const profile: ProfileData = {
  name: 'Alex Chen',
  institution: 'UIUC',
  college: 'Grainger',
  major: 'CS',
  grade: 'Sophomore',
  is_international: false,
  research_interests: 'machine learning',
  skills: [],
  coursework: ['CS 225'],
};

const variant: EmailVariant = {
  id: 'v1',
  label: 'Template A',
  subject: 'Interested in research with you',
  body: 'Dear Professor,\n\nI am interested.\n\nBest,\nAlex',
  recipient_email: 'prof@illinois.edu',
  mailto_link: 'mailto:prof@illinois.edu',
};

beforeEach(() => {
  trackInteractionMock.mockClear();
  getInteractionDetailMock.mockClear().mockResolvedValue(null);
  updateInteractionDetailsMock.mockClear();
  confirmContactMock.mockClear().mockResolvedValue({ type: 'applied' });
  mockGetVariants.mockReset().mockResolvedValue({ variants: [variant] });
  Element.prototype.scrollIntoView = vi.fn();
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
    writable: true,
  });
  vi.stubGlobal('open', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function renderModal() {
  render(
    <ColdEmailModal
      isOpen
      onClose={vi.fn()}
      opportunityId="opp-1"
      opportunityTitle="REU"
      profile={profile}
    />,
  );
  await screen.findByText('coldEmail.copy');
}

describe('ColdEmailModal — verified send tracking', () => {
  it('copying the draft does not create an applied interaction', async () => {
    await renderModal();
    fireEvent.click(screen.getByText('coldEmail.copy'));
    // The confirm strip appears instead of silent tracking.
    expect(await screen.findByText('coldEmail.sentQuestion')).toBeInTheDocument();
    expect(confirmContactMock).not.toHaveBeenCalled();
    expect(trackInteractionMock).not.toHaveBeenCalled();
    expect(updateInteractionDetailsMock).not.toHaveBeenCalled();
  });

  it('opening a mail client does not create an applied interaction', async () => {
    await renderModal();
    fireEvent.click(screen.getByText('coldEmail.openInEmail'));
    expect(await screen.findByText('coldEmail.sentQuestion')).toBeInTheDocument();
    expect(confirmContactMock).not.toHaveBeenCalled();
    expect(trackInteractionMock).not.toHaveBeenCalled();
  });

  it('the explicit "I sent it" confirmation records the contact atomically', async () => {
    await renderModal();
    fireEvent.click(screen.getByText('coldEmail.copy'));
    fireEvent.click(await screen.findByTestId('cold-email-confirm-sent'));

    await waitFor(() => {
      // One call. The second argument is the owner capability captured when
      // the person confirmed — a tracker write that cannot say which identity
      // and which storage generation it belongs to has no business landing.
      expect(confirmContactMock).toHaveBeenCalledWith(
        'opp-1',
        expect.objectContaining({ epoch: expect.any(Number), generation: expect.any(Number) }),
      );
    });
    expect(confirmContactMock).toHaveBeenCalledTimes(1);
    // The three-round-trip flow this replaced is gone, not merely bypassed:
    // its read was the TOCTOU window that let a concurrent status change be
    // interleaved and downgraded back to 'applied'.
    expect(getInteractionDetailMock).not.toHaveBeenCalled();
    expect(trackInteractionMock).not.toHaveBeenCalled();
    expect(updateInteractionDetailsMock).not.toHaveBeenCalled();
    // Confirmation reveals the follow-up reminder chips.
    expect(await screen.findByText('coldEmail.remindPrompt')).toBeInTheDocument();
  });
});
