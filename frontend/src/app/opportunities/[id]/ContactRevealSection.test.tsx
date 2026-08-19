import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';

const mockGetOpportunityById = vi.fn();
vi.mock('@/lib/api', () => ({
  getOpportunityById: (...args: unknown[]) => mockGetOpportunityById(...args),
}));

const mockGetAuthState = vi.fn();
const mockOnAuthChange = vi.fn();
vi.mock('@/lib/supabase', () => ({
  getAuthState: (...args: unknown[]) => mockGetAuthState(...args),
  onAuthChange: (...args: unknown[]) => mockOnAuthChange(...args),
}));

const openModalMock = vi.fn();
vi.mock('@/lib/auth-modal-context', () => ({
  useAuthModal: () => ({
    open: false,
    phase: 'auto',
    reason: null,
    openModal: openModalMock,
    closeModal: () => {},
    setPhase: () => {},
  }),
}));

import { ContactRevealSection } from './ContactRevealSection';
import type { Opportunity } from '@/lib/types';
import { en, zh } from '@/i18n/dictionaries';

const t = (key: string) => key;

function makeOpp(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: 'opp-1',
    title: 'ML Research',
    organization: 'Test U',
    opportunity_type: 'research',
    paid: 'unknown',
    location: 'Campus',
    on_campus: true,
    description_clean: '',
    keywords: [],
    eligibility: {
      international_friendly: 'yes',
      preferred_year: [],
      majors: [],
      skills_required: [],
      citizenship_required: false,
    },
    application: {
      application_effort: '',
      requires_resume: '',
      contact_method: 'email',
    },
    metadata: { is_active: true, confidence_score: 1 },
    ...overrides,
  };
}

const anonState = { session: null, user: null, isAnonymous: false, email: null };
const guestState = {
  session: { access_token: 'anon-tok' } as never,
  user: {} as never,
  isAnonymous: true,
  email: null,
};
const signedInState = {
  session: { access_token: 'tok' } as never,
  user: {} as never,
  isAnonymous: false,
  email: 'student@example.com',
};

beforeEach(() => {
  mockGetOpportunityById.mockReset();
  openModalMock.mockReset();
  mockGetAuthState.mockReset().mockResolvedValue(anonState);
  mockOnAuthChange.mockReset().mockReturnValue(() => {});
});

describe('locked state (sign_in_required)', () => {
  it('uses recipient-neutral contact copy for non-faculty records', async () => {
    render(
      <ContactRevealSection
        opp={makeOpp({
          source_type: 'campus_program',
          contact_email_status: 'sign_in_required',
        })}
        t={t}
      />,
    );
    expect(await screen.findByText('detail.contactSignInPrompt')).toBeInTheDocument();
    expect(en.detail.contactSignInPrompt.toLowerCase()).not.toContain('faculty');
    expect(en.detail.contactVerifyHint.toLowerCase()).not.toContain('faculty');
    expect(zh.detail.contactSignInPrompt).not.toMatch(/教授|教师/);
    expect(zh.detail.contactVerifyHint).not.toMatch(/教授|教师/);
  });

  it('renders the sign-in affordance for anonymous visitors, no fetch', async () => {
    render(<ContactRevealSection opp={makeOpp({ contact_email_status: 'sign_in_required' })} t={t} />);
    expect(await screen.findByTestId('contact-sign-in')).toBeInTheDocument();
    fireEvent.click(screen.getByText('detail.contactSignInCta'));
    expect(openModalMock).toHaveBeenCalledWith({ reason: 'contact-reveal' });
    expect(mockGetOpportunityById).not.toHaveBeenCalled();
  });

  it('guest (anonymous Supabase session) stays locked too', async () => {
    mockGetAuthState.mockResolvedValue(guestState);
    render(<ContactRevealSection opp={makeOpp({ contact_email_status: 'sign_in_required' })} t={t} />);
    expect(await screen.findByTestId('contact-sign-in')).toBeInTheDocument();
    expect(mockGetOpportunityById).not.toHaveBeenCalled();
  });

  it('signed-in visitor upgrades client-side and sees the address', async () => {
    mockGetAuthState.mockResolvedValue(signedInState);
    mockGetOpportunityById.mockResolvedValue({
      id: 'opp-1',
      contact_email: 'prof@example.edu',
      contact_email_status: 'revealed',
    });
    render(<ContactRevealSection opp={makeOpp({ contact_email_status: 'sign_in_required' })} t={t} />);
    const link = await screen.findByTestId('contact-email-link');
    expect(link).toHaveTextContent('prof@example.edu');
    expect(link).toHaveAttribute('href', 'mailto:prof%40example.edu');
    expect(mockGetOpportunityById).toHaveBeenCalledWith('opp-1');
  });

  it('a still-locked refetch keeps the affordance (degrade, no error)', async () => {
    mockGetAuthState.mockResolvedValue(signedInState);
    mockGetOpportunityById.mockResolvedValue({
      id: 'opp-1',
      contact_email_status: 'sign_in_required',
    });
    render(<ContactRevealSection opp={makeOpp({ contact_email_status: 'sign_in_required' })} t={t} />);
    await waitFor(() => expect(mockGetOpportunityById).toHaveBeenCalled());
    expect(screen.getByTestId('contact-sign-in')).toBeInTheDocument();
  });

  it('reveals live when the user signs in from the affordance', async () => {
    let notify: ((s: unknown) => void) | null = null;
    mockOnAuthChange.mockImplementation((cb: (s: unknown) => void) => {
      notify = cb;
      return () => {};
    });
    mockGetOpportunityById.mockResolvedValue({
      id: 'opp-1',
      contact_email: 'prof@example.edu',
      contact_email_status: 'revealed',
    });
    render(<ContactRevealSection opp={makeOpp({ contact_email_status: 'sign_in_required' })} t={t} />);
    expect(await screen.findByTestId('contact-sign-in')).toBeInTheDocument();
    act(() => { notify!(signedInState); });
    expect(await screen.findByTestId('contact-email-link')).toBeInTheDocument();
  });
});

describe('other states', () => {
  it.each(['sign_in_required', 'revealed'] as const)(
    'hides a not-accepting faculty contact even when address state is %s',
    async (contactStatus) => {
    mockGetAuthState.mockResolvedValue(signedInState);
    const { container } = render(
      <ContactRevealSection
        opp={makeOpp({
          source_type: 'faculty_research',
          faculty_availability_status: 'not_accepting_undergraduates',
          contact_email_status: contactStatus,
          contact_email: 'prof@example.edu',
        })}
        t={t}
      />,
    );

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId('contact-email-link')).toBeNull();
    expect(screen.queryByTestId('contact-sign-in')).toBeNull();
    await waitFor(() => expect(mockGetOpportunityById).not.toHaveBeenCalled());
    expect(openModalMock).not.toHaveBeenCalled();
    },
  );

  it('does not turn research inactivity into a contact prohibition', () => {
    render(
      <ContactRevealSection
        opp={makeOpp({
          source_type: 'faculty_research',
          faculty_availability_status: 'research_inactive',
          contact_email_status: 'revealed',
          contact_email: 'prof@example.edu',
        })}
        t={t}
      />,
    );
    expect(screen.getByTestId('contact-email-link')).toHaveTextContent('prof@example.edu');
  });

  it('renders nothing when no verified address exists', () => {
    const { container } = render(
      <ContactRevealSection opp={makeOpp({ contact_email_status: 'unavailable' })} t={t} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for payloads without the status flag (older cache)', () => {
    const { container } = render(<ContactRevealSection opp={makeOpp()} t={t} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders the address immediately when the payload already revealed it', () => {
    render(
      <ContactRevealSection
        opp={makeOpp({ contact_email_status: 'revealed', contact_email: 'prof@example.edu' })}
        t={t}
      />,
    );
    expect(screen.getByTestId('contact-email-link')).toHaveTextContent('prof@example.edu');
    expect(mockGetOpportunityById).not.toHaveBeenCalled();
  });
});
